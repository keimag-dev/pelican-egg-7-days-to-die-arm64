"""7DTD ARM64 runtime. Copyright (c) 2026 keimag-dev. MIT licensed."""
import os
from pathlib import Path
import tempfile
import re
import socket
import time
import xml.etree.ElementTree as ET

SENSITIVE = re.compile(r'password|passwd|token|secret|auth|ticket|session[_ -]?key|steam[_ :.-]*id|eos[_ :.-]*id|platformid|(?<![0-9])[0-9]{17}(?![0-9])|[a-f0-9]{32}', re.I)


def redact(text, secrets=()):
    """Never emit preferences/identity/token lines; also remove known literal secrets."""
    if SENSITIVE.search(text):
        return '[sensitive game output redacted]'
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text


def console_command(command, port=8081, timeout=3.0, idle=0.5):
    """One bounded loopback exchange, collecting the response before disconnecting.

    7DTD has no command transaction ID/end marker: completion is EOF, an idle
    interval after response bytes, the byte budget, or the absolute deadline.
    Long-running commands may have later output on the main game log instead.
    """
    if not command or len(command) > 4096 or any(ord(c) < 32 for c in command):
        raise ValueError('Console accepts one printable command per line')
    deadline = time.monotonic() + timeout
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as sock:
        # Drain the welcome banner separately; do not mistake it for a response.
        sock.settimeout(min(0.15, timeout))
        try:
            sock.recv(8192)
        except socket.timeout:
            pass
        sock.sendall(command.encode('utf-8') + b'\r\n')
        chunks = []
        size = 0
        while size < 65536:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(min(idle if chunks else remaining, remaining))
            try:
                block = sock.recv(min(8192, 65536 - size))
            except socket.timeout:
                break
            if not block:
                break
            chunks.append(block)
            size += len(block)
    return b''.join(chunks).decode('utf-8', errors='replace')

import queue
import signal
import subprocess
import sys
import threading


def supervise(command, input_stream=None, output=None, port=8081, grace=90,
              stop_event=None, check_binding=True, secrets=()):
    """Indefinite child supervisor; only an explicit stop starts a grace timer."""
    input_stream = sys.stdin if input_stream is None else input_stream
    output = sys.stdout if output is None else output
    stop_event = threading.Event() if stop_event is None else stop_event
    lock = threading.Lock()
    commands = queue.Queue(maxsize=64)
    ready = threading.Event()
    def emit(text):
        with lock:
            print(redact(text, secrets), file=output, flush=True)
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, start_new_session=(os.name == 'posix'))
    def read_output():
        assert child.stdout is not None
        dropping = False
        while True:
            block = child.stdout.readline(8193)
            if not block:
                break
            if len(block) > 8192 or dropping:
                dropping = not block.endswith(b'\n')
                continue
            text = block.decode('utf-8', errors='replace').rstrip('\r\n')
            if re.search(r'(?:^|\bINF\s+(?:\[Steamworks\.NET\]\s+)?)GameServer\.Init successful(?:\s|$)', text):
                ready.set()
                # A static status line contains no game-provided data. Passwords
                # such as "a" must not mutilate the Panel readiness marker.
                with lock:
                    print('[bridge] GameServer.Init successful', file=output, flush=True)
            emit(text)
    def read_stdin():
        while child.poll() is None:
            line = input_stream.readline(4098)
            if not line:
                return  # Wings/pipe EOF is not a game shutdown request.
            if len(line) > 4097:
                while line and not line.endswith('\n'):
                    line = input_stream.readline(4098)
                emit('[bridge] rejected overlong command')
                continue
            command_line = line.rstrip('\r\n')
            if command_line.strip().lower() == 'shutdown':
                stop_event.set()
            elif command_line:
                try:
                    commands.put_nowait(command_line)
                except queue.Full:
                    emit('[bridge] command queue full; command rejected')
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    threading.Thread(target=read_stdin, daemon=True).start()
    old_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, lambda *_: stop_event.set())
    deadline = None
    sent_stop = False
    retry_at = 0.0
    forced = False
    unsafe = False
    try:
        while child.poll() is None:
            now = time.monotonic()
            if check_binding:
                try:
                    check_console_binding(port)
                except ValueError:
                    emit('[bridge] unsafe non-loopback console listener; terminating immediately')
                    unsafe = True
                    # No save grace for security violations. Kill the whole group
                    # directly: waiting for the leader after SIGTERM can leave a
                    # SIGTERM-ignoring descendant holding the unsafe listener.
                    try:
                        if os.name == 'posix':
                            os.killpg(child.pid, signal.SIGKILL)
                        else:
                            child.kill()
                    except ProcessLookupError:
                        pass
                    break
            if stop_event.is_set():
                if deadline is None:
                    deadline = now + grace
                    emit('[bridge] graceful shutdown requested')
                if now >= deadline:
                    forced = True
                    emit('[bridge] shutdown grace expired; terminating child')
                    if os.name == 'posix':
                        os.killpg(child.pid, signal.SIGTERM)
                    else:
                        child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        if os.name == 'posix':
                            os.killpg(child.pid, signal.SIGKILL)
                        else:
                            child.kill()
                    break
                if not sent_stop and now >= retry_at:
                    try:
                        response = console_command('shutdown', port, timeout=min(3, max(.05, deadline - now)))
                        if response:
                            emit(response.rstrip())
                        sent_stop = True
                    except (OSError, ValueError):
                        retry_at = time.monotonic() + 0.25
            else:
                try:
                    line = commands.get_nowait()
                except queue.Empty:
                    line = None
                if line:
                    if not ready.is_set():
                        emit('[bridge] game not ready; command rejected (not queued)')
                    else:
                        try:
                            response = console_command(line, port)
                            emit(response.rstrip() if response else '[bridge] sent; no response before console deadline')
                        except (OSError, ValueError):
                            emit('[bridge] console command failed; no execution guarantee')
            time.sleep(.05)
        status = child.wait()
        reader.join(timeout=2)
        return 1 if forced or unsafe else (status if status >= 0 else 128 - status)
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if child.poll() is None:
            child.kill()
            child.wait()
        if child.stdout:
            child.stdout.close()


def check_console_binding(port=8081, proc_net=Path('/proc/net')):
    """Verify actual Linux listening sockets; empty password alone is not proof."""
    found = False
    for filename, loopback in (('tcp', '0100007F'), ('tcp6', '00000000000000000000000001000000')):
        path = proc_net / filename
        if not path.exists() and filename == 'tcp6':
            continue
        for line in path.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) < 4 or fields[3] != '0A':
                continue
            address, hexport = fields[1].split(':')
            if int(hexport, 16) == port:
                if address != loopback:
                    raise ValueError('Console listener is not loopback-only')
                found = True
    return found


def game_command(root):
    root = Path(root)
    return ['box64', str(root / 'game' / '7DaysToDieServer.x86_64'),
            '-quit', '-batchmode', '-nographics', '-dedicated',
            '-configfile=' + str(root / 'serverconfig.xml'), '-logfile', '/dev/stdout']


MANAGED = {
    'SERVER_NAME': 'ServerName',
    'SERVER_DESCRIPTION': 'ServerDescription',
    'SERVER_PASSWORD': 'ServerPassword',
    'SERVER_PORT': 'ServerPort',
    'SERVER_VISIBILITY': 'ServerVisibility',
    'MAX_PLAYERS': 'ServerMaxPlayerCount',
    'GAME_WORLD': 'GameWorld',
    'GAME_NAME': 'GameName',
    'WORLD_SEED': 'WorldGenSeed',
    'WORLD_SIZE': 'WorldGenSize',
}
SAFETY = {
    'TelnetEnabled': 'true', 'TelnetPort': '8081', 'TelnetPassword': '',
    'WebDashboardEnabled': 'false', 'ControlPanelEnabled': 'false',
    'TerminalWindowEnabled': 'false', 'EACEnabled': 'false',
    'ServerAllowCrossplay': 'false', 'UserDataFolder': '/home/container/UserData',
}


def configure(path, env):
    """Atomically merge only owned settings; preserve unknown XML and SandboxCode.

    user mode opts out of general fields, never the loopback-console invariants.
    """
    import re
    mode = env.get('USER_XML_MODE', 'managed')
    if mode not in ('managed', 'user'):
        raise ValueError('USER_XML_MODE must be managed or user')
    values = {field: env[key] for key, field in MANAGED.items() if key in env and mode == 'managed'}
    for name, value in values.items():
        if len(value) > 2048 or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid text for ' + name)
    for key, low, high in (('ServerPort', 1024, 65532), ('ServerVisibility', 0, 2), ('ServerMaxPlayerCount', 1, 64)):
        if key in values and (not re.fullmatch(r'[0-9]+', values[key]) or not low <= int(values[key]) <= high):
            raise ValueError('Invalid ' + key)
    if 'WorldGenSize' in values and values['WorldGenSize'] not in ('4096', '6144', '8192', '10240'):
        raise ValueError('Invalid WorldGenSize')
    for key in ('GameName', 'GameWorld'):
        if key in values and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]{0,63}', values[key]):
            raise ValueError('Invalid ' + key)
    sandbox = env.get('SANDBOX_CODE', '')
    if mode == 'managed' and sandbox:
        if not re.fullmatch(r'[A-Z]{3,4095}', sandbox) or len(sandbox) % 3:
            raise ValueError('SANDBOX_CODE must be uppercase three-character entries')
        values['SandboxCode'] = sandbox
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Unsafe XML path or size')
    data = path.read_bytes()
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper() or b'\x00' in data:
        raise ValueError('DTD/entities and non-UTF8 XML are not supported')
    try:
        tree = ET.ElementTree(ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))))
    except ET.ParseError as exc:
        raise ValueError('Invalid server XML; original is unchanged') from exc
    root = tree.getroot()
    if root.tag != 'ServerSettings':
        raise ValueError('Expected ServerSettings XML root')
    props = {p.get('name'): p for p in root.findall('property')}
    if len(props) != len(root.findall('property')):
        raise ValueError('Duplicate XML property names')
    values.update(SAFETY)
    for name, value in values.items():
        node = props.get(name)
        if node is None:
            node = ET.SubElement(root, 'property', name=name)
        node.set('value', value)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            tree.write(f, encoding='utf-8', xml_declaration=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(root=None, env=None):
    import platform
    root = Path(__file__).resolve().parent.parent if root is None else Path(root)
    env = os.environ if env is None else env
    grace = env.get('SHUTDOWN_GRACE', '90')
    if not re.fullmatch(r'[0-9]{1,3}', grace) or not 10 <= int(grace) <= 600:
        raise ValueError('SHUTDOWN_GRACE must be 10..600 seconds')
    if sys.platform != 'linux' or platform.machine().lower() not in ('aarch64', 'arm64'):
        raise ValueError('Runtime requires Linux ARM64 and Box64')
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    config = root / 'serverconfig.xml'
    configure(config, env)
    settings = {p.get('name'): p.get('value', '') for p in ET.parse(config).getroot().findall('property')}
    secrets = tuple(value for name, value in settings.items() if 'password' in name.lower() and value)
    os.chdir(root / 'game')
    return supervise(game_command(root), grace=int(grace), secrets=secrets)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        # Do not print XML data, environment values, command arguments or secrets.
        print('[bridge] startup failed: ' + type(exc).__name__ + '; check config/install and README', file=sys.stderr)
        raise SystemExit(1)

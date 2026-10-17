#!/bin/bash
# Copyright (c) 2026 keimag-dev. MIT. Disposable root installer only.
set -euo pipefail
umask 022
ulimit -c 0
if [ "$(uname -m)" != "aarch64" ]; then
    printf '%s\n' 'This Egg needs a native Linux ARM64 installer.' >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends python3 ca-certificates
fi
if [ -L /mnt/server/.pelican ]; then
    printf '%s\n' 'Refusing symlink helper directory.' >&2
    exit 1
fi
mkdir -p /mnt/server/.pelican
for helper in installer.py runtime.py; do
    target="/mnt/server/.pelican/$helper"
    if [ -L "$target" ] || { [ -e "$target" ] && [ ! -f "$target" ]; }; then
        printf '%s\n' 'Refusing non-regular helper destination.' >&2
        exit 1
    fi
done
cd /
# Bootstrap source stays outside the user-writable server volume.
work=$(mktemp -d /tmp/pelican-bootstrap.XXXXXX)
trap 'rm -rf -- "$work"' EXIT
cat > "$work/installer.py" <<'__PELICAN_INSTALLER_PY__'
"""Anonymous native ARM64 installer. Copyright (c) 2026 keimag-dev. MIT."""
import re


def validate(env):
    branch = env.get('STEAM_BRANCH', 'public')
    manifest = env.get('STEAM_MANIFEST', '')
    version = env.get('DEPOTDOWNLOADER_VERSION', '3.4.0')
    checksum = env.get('DEPOTDOWNLOADER_SHA256', '')
    timeout = env.get('INSTALL_TIMEOUT', '3600')
    if branch not in ('public', 'latest_experimental'):
        raise ValueError('STEAM_BRANCH must be public or latest_experimental')
    if manifest and (not re.fullmatch(r'[0-9]{1,20}', manifest) or not 0 < int(manifest) < 2**64):
        raise ValueError('STEAM_MANIFEST must be a positive uint64 decimal ID')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('DEPOTDOWNLOADER_VERSION must be an explicit x.y.z version')
    if checksum and not re.fullmatch(r'[a-fA-F0-9]{64}', checksum):
        raise ValueError('DEPOTDOWNLOADER_SHA256 must be a 64-digit SHA256')
    if not re.fullmatch(r'[0-9]{1,6}', timeout) or not 60 <= int(timeout) <= 86400:
        raise ValueError('INSTALL_TIMEOUT must be 60..86400 seconds (installer only)')
    return branch, manifest, version, checksum.lower(), int(timeout)


import os
from pathlib import Path
import shutil
import stat


def release_asset(release, version):
    """Only trust the exact ARM64 asset on the requested official release."""
    if release.get('tag_name') != 'DepotDownloader_' + version or release.get('draft'):
        raise ValueError('Release tag mismatch or draft')
    matches = [a for a in release.get('assets', []) if a.get('name') == 'DepotDownloader-linux-arm64.zip']
    if len(matches) != 1:
        raise ValueError('Expected exactly one Linux ARM64 release asset')
    asset = matches[0]
    expected = f'https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_{version}/DepotDownloader-linux-arm64.zip'
    if asset.get('browser_download_url') != expected or not 0 < asset.get('size', 0) <= 128 * 1024 * 1024:
        raise ValueError('Unexpected official asset URL or size')
    digest = asset.get('digest')
    if digest and not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
        raise ValueError('Unsupported upstream artifact digest')
    return asset


def extract_tool(archive, destination):
    from pathlib import PurePosixPath
    entries = archive.infolist()
    if len(entries) > 1000 or sum(i.file_size for i in entries) > 256 * 1024 * 1024:
        raise ValueError('Tool archive exceeds extraction budget')
    names = set()
    for info in entries:
        name = info.filename
        path = PurePosixPath(name)
        if (not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts
                or stat.S_ISLNK(info.external_attr >> 16) or name in names):
            raise ValueError('Unsafe archive entry')
        names.add(name)
    archive.extractall(destination)
    tool = destination / 'DepotDownloader'
    if not tool.is_file() or tool.is_symlink():
        raise ValueError('Missing native DepotDownloader executable')
    tool.chmod(0o755)
    return tool


def finalize_install(root):
    """Only downloaded game files update; persistent XML/UserData are never reset."""
    root = Path(root)
    binary = root / 'game' / '7DaysToDieServer.x86_64'
    if binary.is_symlink():
        raise ValueError('Game executable cannot be a symlink')
    with binary.open('rb') as f:
        header = f.read(20)
    if header[:4] != b'\x7fELF' or header[18:20] != b'\x3e\x00':
        raise ValueError('Expected x86-64 Linux game executable')
    binary.chmod(0o755)
    persistent = root / 'serverconfig.xml'
    if persistent.is_symlink():
        raise ValueError('Persistent config cannot be a symlink')
    if not persistent.exists():
        stock = root / 'game' / 'serverconfig.xml'
        if stock.is_symlink():
            raise ValueError('Stock config cannot be a symlink')
        temporary = None
        try:
            # Open the source first; errors never create a partial persistent file.
            with stock.open('rb') as src, tempfile.NamedTemporaryFile(dir=root, prefix='.serverconfig-', delete=False) as out:
                temporary = Path(out.name)
                shutil.copyfileobj(src, out)
                out.flush()
                os.fsync(out.fileno())
            import xml.etree.ElementTree as ET
            data = temporary.read_bytes()
            if len(data) > 4 * 1024 * 1024 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper() or b'\x00' in data:
                raise ValueError('Unsafe stock config XML or size')
            try:
                settings = ET.fromstring(data)
            except ET.ParseError as exc:
                raise ValueError('Invalid stock config XML') from exc
            if settings.tag != 'ServerSettings':
                raise ValueError('Stock config has an unexpected XML root')
            names = [node.get('name') for node in settings.findall('property')]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate stock XML property names')
            temporary.chmod(0o600)
            try:
                # Atomic create-only publish; a concurrently added user config wins.
                os.link(temporary, persistent)
            except FileExistsError:
                pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def download_command(tool, game_dir, env):
    branch, manifest, _, _, _ = validate(env)
    command = [str(tool), '-app', '294420', '-depot', '294422', '-os', 'linux', '-osarch', '64',
               '-branch', branch, '-dir', str(game_dir), '-validate', '-max-downloads', '4']
    if manifest:
        command += ['-manifest', manifest]
    return command


import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone


def install(root, env):
    branch, manifest, version, expected_hash, timeout = validate(env)
    if sys.platform != 'linux' or platform.machine().lower() not in ('aarch64', 'arm64'):
        raise ValueError('Installer requires native Linux ARM64')
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # NOT RLIMIT_FSIZE (.NET memfd).
    root = Path(root)
    metadata_dir = root / '.pelican'
    game_dir = root / 'game'
    for path in (root, metadata_dir, game_dir):
        if path.is_symlink():
            raise ValueError('Install directories cannot be symlinks')
        path.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 2 * 1024**3:
        raise ValueError('Less than 2 GiB physical disk free; game needs substantially more')
    url = f'https://api.github.com/repos/SteamRE/DepotDownloader/releases/tags/DepotDownloader_{version}'
    headers = {'User-Agent': 'pelican-community-eggs-7dtd-arm64', 'Accept': 'application/vnd.github+json'}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError('Release metadata exceeds budget')
    asset = release_asset(json.loads(payload), version)
    with tempfile.TemporaryDirectory(prefix='install-', dir=metadata_dir) as temporary:
        directory = Path(temporary)
        archive_path = directory / 'depotdownloader.zip'
        sha = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(urllib.request.Request(asset['browser_download_url'], headers={'User-Agent': headers['User-Agent']}), timeout=30) as response, archive_path.open('xb') as out:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > asset['size']:
                    raise ValueError('Downloaded tool exceeds declared size')
                sha.update(block)
                out.write(block)
        actual_hash = sha.hexdigest()
        if total != asset['size']:
            raise ValueError('Truncated tool archive')
        upstream_hash = (asset.get('digest') or '').removeprefix('sha256:').lower()
        if (expected_hash and actual_hash != expected_hash) or (upstream_hash and actual_hash != upstream_hash):
            raise ValueError('DepotDownloader SHA256 mismatch')
        with zipfile.ZipFile(archive_path) as archive:
            tool = extract_tool(archive, directory)
        native_env = os.environ.copy()
        native_env['DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'] = '1'
        subprocess.run(download_command(tool, game_dir, env), check=True, timeout=timeout, env=native_env)
        finalize_install(root)
        provenance = {
            'installed_at': datetime.now(timezone.utc).isoformat(),
            'app_id': 294420, 'depot_id': 294422, 'branch': branch,
            'requested_manifest': manifest or None,
            'depotdownloader_version': version, 'artifact_url': asset['browser_download_url'],
            'artifact_sha256': actual_hash, 'upstream_digest': asset.get('digest'),
            'operator_digest_verified': bool(expected_hash),
            'note': 'Resolved depot manifest is recorded by DepotDownloader in game/.DepotDownloader; no version fallback.',
        }
        saved = directory / 'installation.json'
        saved.write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
        os.replace(saved, metadata_dir / 'installation.json')
    print('Anonymous Linux depot installed; persistent config and UserData preserved.', flush=True)


if __name__ == '__main__':
    try:
        install(Path('/mnt/server'), os.environ)
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print('Installation failed: ' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
__PELICAN_INSTALLER_PY__
cat > "$work/runtime.py" <<'__PELICAN_RUNTIME_PY__'
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
            '-configfile=' + str(root / 'serverconfig.xml'),
            '-UserDataFolder=' + str(root / 'UserData'), '-logfile', '/dev/stdout']


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
    'WebDashboardEnabled': 'false',
    'TerminalWindowEnabled': 'false', 'EACEnabled': 'false',
    'ServerAllowCrossplay': 'false',
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
    # Older schemas may expose this dashboard; do not invent it on V3.3.
    if 'ControlPanelEnabled' in props:
        values['ControlPanelEnabled'] = 'false'
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
__PELICAN_RUNTIME_PY__
chmod 644 "$work/installer.py" "$work/runtime.py"
cp -- "$work/installer.py" "$work/published-installer.py"
mv -fT -- "$work/published-installer.py" /mnt/server/.pelican/installer.py
mv -fT -- "$work/runtime.py" /mnt/server/.pelican/runtime.py
# Isolate imports/environment too; only this private staged source runs as root.
python3 -I "$work/installer.py"

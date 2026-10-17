"""Real unsafe-listener regressions; POSIX group semantics require Linux."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHILD = r'''
import json, os, signal, socket, subprocess, sys, time
from pathlib import Path
status, port, mode = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
if mode == 'tree':
    subprocess.Popen([sys.executable, '-u', __file__, str(status), str(port), 'listener'])
    while True: time.sleep(1)
if os.name == 'posix': signal.signal(signal.SIGTERM, signal.SIG_IGN)
with socket.socket() as sock:
    sock.bind(('0.0.0.0', port)); sock.settimeout(.1)
    status.write_text(json.dumps({'pid': os.getpid(), 'leader': os.getppid() if mode == 'listener' else os.getpid(), 'address': sock.getsockname()[0]}))
    sock.listen()
    print('unsafe listener ready', flush=True)
    while True:
        try:
            conn, _ = sock.accept()
        except socket.timeout:
            continue
        with conn:
            conn.settimeout(.1)
            try: conn.recv(4096)
            except OSError: pass
            # Deliberately ignore shutdown, just as an incompatible game might.
'''
RUNNER = r'''
import io, json, os, socket, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import runtime
child, status, port, mode = sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
if os.name != 'posix':
    # Windows has no /proc/net. Validate a real child-reported getsockname and
    # live TCP connection instead; never claim this verifies the Linux probe.
    def probe(port):
        if not status.exists(): return False
        try: data = json.loads(status.read_text())
        except (ValueError, OSError): return False
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1): pass
        except OSError:
            return False
        if data['address'] != '127.0.0.1': raise ValueError('actual wildcard listener')
        return True
    runtime.check_console_binding = probe
started = time.monotonic()
result = runtime.supervise([sys.executable, '-u', child, str(status), str(port), mode],
                           input_stream=io.StringIO(''), output=io.StringIO(), port=port)
print(json.dumps({'status': result, 'elapsed': time.monotonic() - started}))
'''


class SecuritySocketTests(unittest.TestCase):
    def exercise_listener(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child, status = root / 'child.py', root / 'status.json'
            child.write_text(CHILD, encoding='utf-8')
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            try:
                # No grace override: a regression must fail in six seconds, not
                # hang for the normal default 90-second shutdown deadline.
                run = subprocess.run([sys.executable, '-u', '-c', RUNNER, str(ROOT), str(child), str(status), str(port), mode],
                                     capture_output=True, text=True, timeout=6)
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads(run.stdout)
                self.assertEqual(result['status'], 1)
                self.assertLess(result['elapsed'], 3)
                self.assertTrue(status.exists(), 'The child must really open its unsafe listener')
                with socket.socket() as probe:
                    probe.settimeout(.2)
                    self.assertNotEqual(probe.connect_ex(('127.0.0.1', port)), 0,
                                        'Unsafe listener must not survive supervisor return')
            finally:
                if status.exists():
                    state = json.loads(status.read_text())
                    if os.name == 'posix':
                        try: os.killpg(state['leader'], signal.SIGKILL)
                        except ProcessLookupError: pass
                    else:
                        # PID originates only from this test's own child.
                        try: os.kill(state['pid'], signal.SIGTERM)
                        except OSError: pass

    def test_real_wildcard_socket_is_closed_without_default_save_grace(self):
        self.exercise_listener('single')

    @unittest.skipUnless(sys.platform == 'linux', 'Requires Linux /proc/net and POSIX process groups')
    def test_sigterm_ignoring_descendant_listener_dies_with_process_group(self):
        self.exercise_listener('tree')


if __name__ == '__main__':
    unittest.main()

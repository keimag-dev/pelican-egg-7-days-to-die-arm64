import importlib.util
import io
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'runtime.py')
assert spec and spec.loader
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

class LifecycleTests(unittest.TestCase):
    def test_child_exit_is_propagated_and_eof_is_not_shutdown(self):
        self.assertTrue(hasattr(runtime, 'supervise'), 'production supervisor is missing')
        out = io.StringIO()
        started = time.monotonic()
        result = runtime.supervise([sys.executable, '-u', '-c', 'import time; print("GameServer.Init successful"); time.sleep(0.25); raise SystemExit(7)'], input_stream=io.StringIO(''), output=out, check_binding=False)
        self.assertEqual(result, 7)
        self.assertGreaterEqual(time.monotonic() - started, 0.2)
        self.assertIn('GameServer.Init successful', out.getvalue())

    def test_actual_child_socket_shutdown_acknowledgement(self):
        self.assertTrue(hasattr(runtime, 'supervise'), 'production supervisor is missing')
        out = io.StringIO()
        result = runtime.supervise([sys.executable, '-u', str(ROOT / 'tests' / 'fake_game.py')], input_stream=io.StringIO('shutdown\n'), output=out, port=18081, grace=5, check_binding=False)
        self.assertEqual(result, 0)
        self.assertIn('SaveAndCleanupWorld', out.getvalue())
        self.assertIn('shutdown acknowledged', out.getvalue())

    def test_stop_event_kills_uncooperative_child_after_grace(self):
        self.assertTrue(hasattr(runtime, 'supervise'), 'production supervisor is missing')
        stop = threading.Event()
        timer = threading.Timer(0.15, stop.set)
        timer.start()
        started = time.monotonic()
        out = io.StringIO()
        result = runtime.supervise([sys.executable, '-u', '-c', 'import time; print("running"); time.sleep(60)'], input_stream=io.StringIO(''), output=out, port=1, grace=0.2, stop_event=stop, check_binding=False)
        timer.join()
        self.assertNotEqual(result, 0)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn('grace expired', out.getvalue())

    def test_unsafe_console_binding_does_not_wait_for_normal_save_grace(self):
        from unittest.mock import patch
        out = io.StringIO()
        started = time.monotonic()
        with patch.object(runtime, 'check_console_binding', side_effect=ValueError('unsafe fixture binding')):
            result = runtime.supervise([sys.executable, '-u', '-c', 'import time; time.sleep(60)'],
                                       input_stream=io.StringIO(''), output=out, port=1, grace=2)
        self.assertEqual(result, 1)
        self.assertLess(time.monotonic() - started, 1.5, 'Unsafe exposure must not retain normal save grace')
        self.assertIn('unsafe', out.getvalue())

    def test_security_failure_targets_entire_group_even_if_leader_can_exit(self):
        # Windows cannot exercise POSIX killpg. This adapter delivers real native
        # termination to the child while verifying the production group signal;
        # the Linux-only socket/tree regression below verifies kernel semantics.
        import os
        import signal
        from types import SimpleNamespace
        from unittest.mock import patch
        signals = []
        def kill_group(pid, sig):
            signals.append(sig)
            os.kill(pid, signal.SIGTERM)
        group_os = SimpleNamespace(name='posix', killpg=kill_group)
        group_signal = SimpleNamespace(SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM,
                                       SIGKILL=9, signal=signal.signal)
        with patch.object(runtime, 'os', group_os), patch.object(runtime, 'signal', group_signal), \
             patch.object(runtime, 'check_console_binding', side_effect=ValueError('unsafe')):
            result = runtime.supervise([sys.executable, '-u', '-c', 'import time; time.sleep(60)'],
                                       input_stream=io.StringIO(''), output=io.StringIO())
        self.assertEqual(result, 1)
        self.assertEqual(signals, [9], 'Security failures must kill the whole group, not just wait for its leader')

    def test_binding_probe_rejects_wildcard_and_nonloopback(self):
        self.assertTrue(hasattr(runtime, 'check_console_binding'), 'actual listener safety probe missing')
        header = 'sl local_address rem_address st tx_queue\n'
        with tempfile.TemporaryDirectory() as d:
            proc = pathlib.Path(d)
            (proc / 'tcp6').write_text(header)
            (proc / 'tcp').write_text(header + '0: 0100007F:1F91 00000000:0000 0A 0:0\n')
            self.assertTrue(runtime.check_console_binding(8081, proc))
            (proc / 'tcp').write_text(header)
            self.assertFalse(runtime.check_console_binding(8081, proc))
            for address in ('00000000', '0100000A'):
                (proc / 'tcp').write_text(header + f'0: {address}:1F91 00000000:0000 0A 0:0\n')
                with self.assertRaises(ValueError):
                    runtime.check_console_binding(8081, proc)

    def test_game_launch_contract_preserves_fps_default(self):
        self.assertTrue(hasattr(runtime, 'game_command'), 'game launch contract missing')
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            command = runtime.game_command(root)
            self.assertEqual(command[0], 'box64')
            self.assertIn('-configfile=' + str(root / 'serverconfig.xml'), command)
            self.assertIn('-logfile', command)
            self.assertIn('/dev/stdout', command)
            self.assertFalse(any('targetfps' in value.lower() for value in command))

    def test_real_sigterm_handler_requests_graceful_socket_shutdown(self):
        self.assertTrue(hasattr(runtime, 'supervise'), 'production supervisor is missing')
        import signal
        timer = threading.Timer(0.3, lambda: signal.raise_signal(signal.SIGTERM))
        timer.start()
        out = io.StringIO()
        try:
            result = runtime.supervise([sys.executable, '-u', str(ROOT / 'tests' / 'fake_game.py')], input_stream=io.StringIO(''), output=out, port=18081, grace=5, check_binding=False)
        finally:
            timer.cancel()
            timer.join()
        self.assertEqual(result, 0)
        self.assertIn('SaveAndCleanupWorld', out.getvalue())
        self.assertIn('shutdown acknowledged', out.getvalue())

    def test_runtime_entrypoint_rejects_invalid_grace(self):
        self.assertTrue(hasattr(runtime, 'main'), 'runtime entrypoint missing')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                runtime.main(pathlib.Path(d), {'SHUTDOWN_GRACE': '0'})

    def test_stdin_roundtrip_after_readiness(self):
        class Input:
            def __init__(self):
                self.lines = iter(('gettime\n', 'shutdown\n', ''))
            def readline(self, size):
                time.sleep(0.3)
                return next(self.lines, '')
        out = io.StringIO()
        result = runtime.supervise([sys.executable, '-u', str(ROOT / 'tests' / 'fake_game.py')], input_stream=Input(), output=out, port=18081, grace=5, check_binding=False)
        self.assertEqual(result, 0)
        self.assertIn('fixture response', out.getvalue())

    def test_oversized_output_does_not_stop_the_child(self):
        out = io.StringIO()
        command = [sys.executable, '-u', '-c', 'print("x"*100000); print("still alive"); print("AuthSteam=do-not-leak")']
        result = runtime.supervise(command, input_stream=io.StringIO(''), output=out, check_binding=False)
        self.assertEqual(result, 0)
        self.assertIn('still alive', out.getvalue())
        self.assertNotIn('do-not-leak', out.getvalue())
        self.assertLess(len(out.getvalue()), 1000)

    def test_readiness_survives_short_password_substrings(self):
        out = io.StringIO()
        result = runtime.supervise([sys.executable, '-u', '-c', 'print("GameServer.Init successful")'], input_stream=io.StringIO(''), output=out, check_binding=False, secrets=('a',))
        self.assertEqual(result, 0)
        self.assertIn('GameServer.Init successful', out.getvalue())

    def test_actual_shipped_readiness_prefix_is_recognized(self):
        out = io.StringIO()
        code = 'print("2026-10-16T04:14:48 238.202 INF [Steamworks.NET] GameServer.Init successful")'
        result = runtime.supervise([sys.executable, '-u', '-c', code], input_stream=io.StringIO(''), output=out, check_binding=False, secrets=('a',))
        self.assertEqual(result, 0)
        self.assertIn('[bridge] GameServer.Init successful', out.getvalue())

if __name__ == '__main__':
    unittest.main()

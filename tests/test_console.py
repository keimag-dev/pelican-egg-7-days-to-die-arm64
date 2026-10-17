import importlib.util
import pathlib
import socket
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime', ROOT / 'runtime.py')
assert spec and spec.loader
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

class ConsoleTests(unittest.TestCase):
    def test_real_socket_reads_response_before_close(self):
        self.assertTrue(hasattr(runtime, 'console_command'), 'console bridge is not implemented')
        observed = []
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            def server():
                with listener.accept()[0] as conn:
                    conn.sendall(b'7DTD console\r\n')
                    line = b''
                    while not line.endswith(b'\n'):
                        line += conn.recv(1024)
                    observed.append(line)
                    time.sleep(0.06)
                    conn.sendall(b'Game time: Day 1 08:00\r\n')
            worker = threading.Thread(target=server)
            worker.start()
            response = runtime.console_command('gettime', port=port, timeout=1, idle=0.15)
            worker.join(2)
        self.assertEqual(observed, [b'gettime\r\n'])
        self.assertIn('Game time: Day 1', response)
        self.assertFalse(worker.is_alive())

    def test_commands_and_log_secrets_are_not_forwarded_unsafely(self):
        self.assertTrue(hasattr(runtime, 'redact'), 'log redaction missing')
        for text in ('GamePref.ServerPassword = leaked', 'Auth_Steam=76561198000000000', 'EOS_ab12cd34ef56ab12cd34ef56ab12cd34', 'token=secret', 'Steam_76561198000000000'):
            self.assertNotEqual(runtime.redact(text), text)
        self.assertEqual(runtime.redact('GameServer.Init successful'), 'GameServer.Init successful')
        self.assertNotIn('topsecret', runtime.redact('hello topsecret', secrets=('topsecret',)))
        for command in ('gettime\nshutdown', 'x\rhelp', 'x\x00', 'x' * 4097):
            with self.assertRaises(ValueError):
                runtime.console_command(command, port=1)

    def test_auth_variants_are_redacted(self):
        for text in ('AuthSteam=credential', 'AuthEOS=credential', 'Auth_Steam=credential', 'Auth_EOS=credential'):
            with self.subTest(text=text):
                self.assertNotEqual(runtime.redact(text), text)

if __name__ == '__main__':
    unittest.main()

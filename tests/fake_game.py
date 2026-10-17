"""A real local subprocess/socket fixture, not the game or a claimed game result."""
import socket
import sys

with socket.socket() as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 18081))
    listener.listen(4)
    print('2026-10-16T04:14:48 238.202 INF [Steamworks.NET] GameServer.Init successful', flush=True)
    while True:
        with listener.accept()[0] as conn:
            conn.sendall(b'Console ready\r\n')
            data = b''
            while not data.endswith(b'\n'):
                block = conn.recv(4096)
                if not block:
                    break
                data += block
            if data.strip() == b'shutdown':
                conn.sendall(b'shutdown acknowledged\r\n')
                print('SaveAndCleanupWorld', flush=True)
                sys.exit(0)
            conn.sendall(b'fixture response\r\n')

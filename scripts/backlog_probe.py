"""Controlled local TCP listener saturation experiment; no application processes."""
import json
import socket
from concurrent.futures import ThreadPoolExecutor


def probe(backlog):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(backlog)
        address = listener.getsockname()
        clients = []

        def connect(_):
            client = socket.socket()
            client.settimeout(1)
            try:
                client.connect(address)
                clients.append(client)
                return 'connected'
            except OSError as exc:
                client.close()
                return type(exc).__name__

        with ThreadPoolExecutor(max_workers=32) as pool:
            outcomes = list(pool.map(connect, range(32)))
        for client in clients:
            client.close()
        return {key: outcomes.count(key) for key in set(outcomes)}


if __name__ == '__main__':
    print(json.dumps({'backlog_5': probe(5), 'backlog_128': probe(128)}, indent=2))

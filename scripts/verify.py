import json
from contextlib import closing
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def request(url, data=None, token='local-verification-token'):
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, payload, {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=3) as response:
        return response.read().decode()


def wait_ready(url, process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('service exited before readiness')
        try:
            request(url)
            return
        except (OSError, urllib.error.URLError):
            time.sleep(.05)
    raise RuntimeError('service readiness timeout')


def main():
    processes = []
    logs = []
    evidence = ROOT / 'evidence' / 'verification.json'
    evidence.parent.mkdir(exist_ok=True)
    scratch = tempfile.TemporaryDirectory(prefix='sales-pipeline-')
    try:
        if True:
            tmp = scratch.name
            gateway = port()
            env = dict(os.environ, SERVICE_TOKEN='local-verification-token', AUTH_MODE='local', SQLITE_PATH=str(Path(tmp) / 'orders.db'), OBJECT_DIR=tmp, BACKEND='local')
            for stage in ('transform', 'load', 'query', 'fused'):
                stage_port = port()
                env.update(PORT=str(stage_port), STAGE=stage)
                logs.append((ROOT / 'evidence' / f'{stage}.log').open('w'))
                processes.append(subprocess.Popen([sys.executable, 'service.py'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=logs[-1]))
                wait_ready(f'http://127.0.0.1:{stage_port}/health', processes[-1])
                env[stage.upper() + '_URL'] = f'http://127.0.0.1:{stage_port}'
            env.update(PORT=str(gateway))
            logs.append((ROOT / 'evidence' / 'gateway.log').open('w'))
            processes.append(subprocess.Popen(['node', 'gateway.mjs'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=logs[-1]))
            wait_ready(f'http://127.0.0.1:{gateway}/health', processes[-1])
            data = {'csv': (ROOT / 'sample.csv').read_text(), 'filters': {'country': 'France'}}
            split = json.loads(request(f'http://127.0.0.1:{gateway}/split', data))
            fused = json.loads(request(f'http://127.0.0.1:{gateway}/fused', data))
            assert split == fused and split['count'] == 2 and split['revenue'] == '25.00' and split['profit'] == '9.00'
            with closing(sqlite3.connect(env['SQLITE_PATH'])) as db:
                rows = db.execute('SELECT count(*) FROM orders').fetchone()[0]
            assert rows == 2
            try:
                request(f'http://127.0.0.1:{gateway}/split', data, 'wrong')
                raise AssertionError('unauthorized request succeeded')
            except urllib.error.HTTPError as error:
                assert error.code == 401
            grouped = json.loads(request(f'http://127.0.0.1:{gateway}/split', {**data, 'group_by': ['priority']}))
            assert [item['priority'] for item in grouped] == ['High', 'Low']
            for url, invalid in [(env['TRANSFORM_URL'] + '/transform', {'csv': 'bad header'}), (env['LOAD_URL'] + '/load', {'rows': [{'id': '1'}]}), (env['QUERY_URL'] + '/query', {'filters': {'bad': 'x'}})]:
                try:
                    request(url, invalid)
                    raise AssertionError('invalid request succeeded')
                except urllib.error.HTTPError as error:
                    assert error.code == 400
            processes[2].terminate()
            processes[2].wait(timeout=5)
            start = time.monotonic()
            try:
                request(f'http://127.0.0.1:{gateway}/split', data)
                raise AssertionError('unavailable query stage succeeded')
            except urllib.error.HTTPError as error:
                assert error.code == 502 and time.monotonic() - start < 3
            query_port = env['QUERY_URL'].rsplit(':', 1)[1]
            query_env = dict(env, STAGE='query', PORT=query_port)
            processes[2] = subprocess.Popen([sys.executable, 'service.py'], cwd=ROOT, env=query_env, stdout=subprocess.DEVNULL, stderr=logs[2])
            wait_ready(env['QUERY_URL'] + '/health', processes[2])
            assert json.loads(request(env['QUERY_URL'] + '/query', {'filters': {'country': 'France'}})) == split
            recovered = json.loads(request(f'http://127.0.0.1:{gateway}/split', data))
            assert recovered == split
            db_path = Path(env['SQLITE_PATH'])
            backup_path = db_path.with_suffix('.saved')
            db_path.rename(backup_path)
            try:
                try:
                    request(env['QUERY_URL'] + '/query', {'filters': {}})
                    raise AssertionError('unavailable database succeeded')
                except urllib.error.HTTPError as error:
                    assert error.code == 500
            finally:
                if db_path.exists():
                    db_path.unlink()
                backup_path.rename(db_path)
            assert json.loads(request(env['QUERY_URL'] + '/query', {'filters': {'country': 'France'}})) == split
            subprocess.run(['node', 'scripts/bench.mjs', f'http://127.0.0.1:{gateway}'], cwd=ROOT, env=env, check=True)
            with closing(sqlite3.connect(env['SQLITE_PATH'])) as db:
                assert db.execute('SELECT count(*) FROM orders').fetchone()[0] == 1002
            evidence.write_text(json.dumps({'action': 'split, fused, grouped, unavailable-stage and restart', 'split': split, 'fused': fused, 'grouped': grouped, 'database_rows_before_campaign': rows, 'database_rows_after_campaign': 1002, 'unauthorized_status': 401, 'invalid_stage_status': 400, 'unavailable_stage_status': 502, 'unavailable_backend_status': 500, 'restart_recovered': recovered}, indent=2))
    finally:
        for p in reversed(processes):
            p.terminate()
            p.wait(timeout=5)
        for log in logs:
            log.close()
        scratch.cleanup()
    assert evidence.exists()
    print(evidence.read_text())


if __name__ == '__main__':
    main()

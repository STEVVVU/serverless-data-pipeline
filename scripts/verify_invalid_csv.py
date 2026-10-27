"""Drive malformed CSV values through an isolated real transform HTTP service."""
import json
import os
import subprocess
import urllib.error
from pathlib import Path

from verify import ROOT, port, request, wait_ready


def main():
    stage_port = port()
    env = dict(os.environ, AUTH_MODE='local', SERVICE_TOKEN='local-verification-token', STAGE='transform', PORT=str(stage_port))
    process = subprocess.Popen(['python', 'service.py'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = []
    try:
        url = f'http://127.0.0.1:{stage_port}'
        wait_ready(url + '/health', process)
        for value in (17, None, [], {}):
            try:
                request(url + '/transform', {'csv': value})
                raise AssertionError('invalid CSV accepted')
            except urllib.error.HTTPError as error:
                assert error.code == 400
                results.append({'csv': value, 'status': error.code, 'body': json.loads(error.read())})
    finally:
        process.terminate()
        process.wait(timeout=5)
    evidence = ROOT / 'evidence' / 'invalid-csv-regression.json'
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text(json.dumps({'results': results}, indent=2))
    print(evidence.read_text())
    assert Path(evidence).exists()


if __name__ == '__main__':
    main()

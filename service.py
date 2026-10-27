import hmac
import json
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pipeline import MAX_BYTES, fetch_object, load, query, transform


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.reply(200, {'status': 'ready'}) if self.path == '/health' else self.reply(404, {'error': 'not found'})

    def do_POST(self):
        header = self.headers.get('Authorization', '')
        try:
            if os.environ.get('AUTH_MODE') == 'local':
                token = os.environ['SERVICE_TOKEN']
                authorized = bool(token) and hmac.compare_digest(header, 'Bearer ' + token)
            elif os.environ.get('AUTH_MODE') == 'google':
                from google.auth.transport.requests import Request
                from google.oauth2.id_token import verify_oauth2_token
                claims = verify_oauth2_token(header.removeprefix('Bearer '), Request(), os.environ['AUDIENCE'])
                authorized = header.startswith('Bearer ') and claims.get('email_verified') and claims.get('email') in os.environ['ALLOWED_CALLERS'].split(',')
            else:
                authorized = False
        except Exception:
            authorized = False
        if not authorized:
            return self.reply(401, {'error': 'unauthorized'})
        try:
            length = int(self.headers.get('Content-Length', '-1'))
            if length < 0 or length > MAX_BYTES * 2:
                raise ValueError('invalid body length')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('expected object')
            if self.path != '/' + os.environ.get('STAGE', ''):
                return self.reply(404, {'error': 'not found'})
            if self.path == '/transform':
                result = transform(fetch_object(data['object']) if 'object' in data else data['csv'])
            elif self.path == '/load':
                rows = data['rows']
                result = load(rows)
            elif self.path == '/query':
                result = query(data.get('filters', {}), data.get('group_by'))
            elif self.path == '/fused':
                rows = transform(fetch_object(data['object']) if 'object' in data else data['csv'])
                load(rows)
                result = query(data.get('filters', {}), data.get('group_by'))
            else:
                return self.reply(404, {'error': 'not found'})
            self.reply(200, result)
        except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError):
            self.reply(400, {'error': 'invalid input'})
        except Exception as exc:
            print('backend failure:', type(exc).__name__, file=sys.stderr, flush=True)
            self.reply(500, {'error': 'backend failure'})


class Server(ThreadingHTTPServer):
    request_queue_size = socket.SOMAXCONN


if __name__ == '__main__':
    mode = os.environ.get('AUTH_MODE')
    if mode not in ('local', 'google') or os.environ.get('STAGE') not in ('transform', 'load', 'query', 'fused'):
        raise SystemExit('AUTH_MODE and STAGE are required')
    if mode == 'local' and not os.environ.get('SERVICE_TOKEN'):
        raise SystemExit('SERVICE_TOKEN is required')
    if mode == 'google' and (not os.environ.get('AUDIENCE') or not os.environ.get('ALLOWED_CALLERS') or os.environ.get('BACKEND') != 'firestore'):
        raise SystemExit('Google mode requires AUDIENCE, ALLOWED_CALLERS, and BACKEND=firestore')
    Server(('127.0.0.1' if mode == 'local' else '0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler).serve_forever()

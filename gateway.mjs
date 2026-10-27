import http from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { GoogleAuth, OAuth2Client } from 'google-auth-library';

const token = process.env.SERVICE_TOKEN;
const mode = process.env.AUTH_MODE;
if (!['local', 'google'].includes(mode) || (mode === 'local' && !token)) throw new Error('AUTH_MODE and local token are required');
if (mode === 'google' && (!process.env.AUDIENCE || !process.env.ALLOWED_CALLERS)) throw new Error('AUDIENCE and ALLOWED_CALLERS are required');
const auth = new GoogleAuth();
const verifier = new OAuth2Client();
async function call(path, data) {
  const target = process.env[path.slice(1).toUpperCase() + '_URL'];
  if (!target) throw new Error('missing stage URL');
  if (mode === 'local' && !/^http:\/\/127\.0\.0\.1:\d+$/.test(target)) throw new Error('local stages must be loopback');
  if (mode === 'google' && new URL(target).protocol !== 'https:') throw new Error('Google stage URLs must use HTTPS');
  const client = mode === 'google' ? await auth.getIdTokenClient(target) : null;
  const headers = client ? await client.getRequestHeaders(target) : new Headers({authorization: `Bearer ${token}`});
  headers.set('content-type', 'application/json');
  let response;
  try {
    response = await fetch(target + path, {method: 'POST', headers, body: JSON.stringify(data), signal: AbortSignal.timeout(15000)});
  } catch (error) {
    console.error('stage connection failure:', path, error?.cause?.code || error?.name);
    throw error;
  }
  if (!response.ok) throw new Error(`stage returned ${response.status}`);
  return response.json();
}
http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') { res.writeHead(200); res.end('ready'); return; }
  let authorized = false;
  try {
    if (mode === 'local') {
      const supplied = Buffer.from(req.headers.authorization || '');
      const expected = Buffer.from(`Bearer ${token}`);
      authorized = supplied.length === expected.length && timingSafeEqual(supplied, expected);
    } else if (req.headers.authorization?.startsWith('Bearer ')) {
      const ticket = await verifier.verifyIdToken({idToken: req.headers.authorization.slice(7), audience: process.env.AUDIENCE});
      const claims = ticket.getPayload();
      authorized = claims?.email_verified === true && (process.env.ALLOWED_CALLERS || '').split(',').includes(claims.email);
    }
  } catch { authorized = false; }
  if (!authorized) { res.writeHead(401); res.end(); return; }
  if (req.method !== 'POST' || !['/split', '/fused'].includes(req.url)) { res.writeHead(404); res.end(); return; }
  try {
    const chunks = [];
    let size = 0;
    for await (const chunk of req) { size += chunk.length; if (size > 4000000) throw new Error('too large'); chunks.push(chunk); }
    const data = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    let result;
    if (req.url === '/fused') result = await call('/fused', data);
    else {
      const rows = await call('/transform', data);
      await call('/load', {rows});
      result = await call('/query', {filters: data.filters || {}, group_by: data.group_by});
    }
    res.writeHead(200, {'content-type': 'application/json'}); res.end(JSON.stringify(result));
  } catch (error) { console.error('pipeline failure:', error?.message, error?.cause?.code || ''); res.writeHead(502); res.end(JSON.stringify({error: 'pipeline failed'})); }
}).listen(Number(process.env.PORT || 8080), mode === 'local' ? '127.0.0.1' : '0.0.0.0');

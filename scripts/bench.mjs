import autocannon from 'autocannon';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import os from 'node:os';
import { execFileSync } from 'node:child_process';

const base = process.argv[2];
const csv = readFileSync('sample.csv', 'utf8').split(/\r?\n/)[0] + '\n' + Array.from({length: 1000}, (_, i) => `Benchmark,France,Office Supplies,Online,H,1/1/2024,${10000 + i},1/3/2024,2,10.00,6.00,20.00,12.00,8.00`).join('\n') + '\n';
const body = JSON.stringify({csv, filters: {region: 'Benchmark'}});
const headers = {'content-type': 'application/json', authorization: 'Bearer local-verification-token'};
const expected = {count: 1000, units: 2000, min_units: 2, max_units: 2, average_units: '2', revenue: '20000.00', profit: '8000.00', average_days: '2', average_margin: '0.4'};
const receipts = [];
const diagnostic = process.env.DIAGNOSTIC === '1';
const warmup = await fetch(`${base}/fused`, {method: 'POST', headers, body});
if (!warmup.ok || JSON.stringify(await warmup.json()) !== JSON.stringify(expected)) throw new Error('warmup failed');
for (const connections of (diagnostic ? [8] : [1, 8])) for (let i = 0; i < (diagnostic ? 1 : 5); i++) {
  for (const mode of (i % 2 ? ['fused', 'split'] : ['split', 'fused'])) {
    const outcomes = [];
    const result = await autocannon({url: `${base}/${mode}`, connections, amount: 50, timeout: 60, requests: [{method: 'POST', headers, body, onResponse: (status, responseBody) => {
      try { const match = JSON.stringify(JSON.parse(responseBody)) === JSON.stringify(expected); outcomes.push({status, match, ...(!match && {body: responseBody.slice(0, 500)})}); }
      catch { outcomes.push({status, match: false, body: responseBody.slice(0, 500)}); }
    }}]});
    const response = await fetch(`${base}/${mode}`, {method: 'POST', headers, body});
    const oracle = await response.json();
    const groupedResponse = await fetch(`${base}/${mode}`, {method: 'POST', headers, body: JSON.stringify({csv, filters: {region: 'Benchmark'}, group_by: ['priority']})});
    const grouped = await groupedResponse.json();
    const committed = Number(execFileSync('python', ['-c', 'import os,sqlite3; c=sqlite3.connect(os.environ["SQLITE_PATH"]); print(c.execute("select count(*) from orders").fetchone()[0]); c.close()'], {encoding: 'utf8'}));
    const pass = response.status === 200 && JSON.stringify(oracle) === JSON.stringify(expected) && groupedResponse.status === 200 && JSON.stringify(grouped) === JSON.stringify([{priority: 'High', ...expected}]) && committed === 1002 && outcomes.length === 50 && outcomes.every(x => x.status === 200 && x.match) && result.errors === 0 && result.non2xx === 0 && result.requests.total === 50;
    receipts.push({mode, connections, pass, oracle, grouped, committed, outcomes, status: response.status, requests: result.requests.total, errors: result.errors, non2xx: result.non2xx, latency_ms: result.latency, elapsed_seconds: result.duration});
  }
}
const sourceHash = createHash('sha256').update(['pipeline.py', 'service.py', 'gateway.mjs', 'sample.csv', 'scripts/bench.mjs', 'package-lock.json', 'requirements.lock'].map(x => readFileSync(x)).join('')).digest('hex');
const python = execFileSync('python', ['--version'], {encoding: 'utf8'}).trim();
writeFileSync(diagnostic ? 'evidence/concurrency-diagnostic.json' : 'evidence/campaign.json', JSON.stringify({tool: 'autocannon 8.0.0', workload: diagnostic ? '50 requests per run, concurrency 8, one pair' : '50 requests per run, concurrency 1 and 8, identical 1000-distinct-row CSV; preloaded static idempotent writes; five interleaved pairs per concurrency', dataset_sha256: createHash('sha256').update(csv).digest('hex'), platform: os.platform(), release: os.release(), arch: os.arch(), cpu: os.cpus()[0].model, node: process.version, python, source_sha256: sourceHash, receipts}, null, 2));
if (receipts.some(x => !x.pass)) process.exitCode = 1;

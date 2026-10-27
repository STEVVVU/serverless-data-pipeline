---
name: verify-serverless-data-pipeline
description: Drive the sales pipeline HTTP services locally and capture evidence.
---

# Verification

## Launch
Run `npm ci` then `python scripts/verify.py` from the project root. It owns five isolated processes and temporary data; local mode uses loopback only.

## Doctor
The driver waits for each service health endpoint before sending requests and fails if startup fails.

## Drive
The driver sends the sample sales CSV through split and fused HTTP paths, repeats it, queries groups, tests malformed inputs, stops and restarts the query process, and runs five interleaved benchmark pairs at each of two concurrency levels.

For the focused invalid-CSV HTTP regression without running the benchmark, run `python scripts/verify_invalid_csv.py`; its receipt is `evidence/invalid-csv-regression.json`.

## Evidence
The driver writes request, response and database assertions to `evidence/verification.json`, and detailed benchmark runs to `evidence/campaign.json`, outside temporary state. Both paths are ignored generated evidence. `evidence/benchmark.json` is the preserved earlier smoke receipt.

## Cleanup
The driver terminates only its own subprocesses and removes its temporary directory; evidence survives.

## Helpers
`python scripts/verify.py` is the maintained HTTP driver. Live GCP and Cloud Run remain separate checks.

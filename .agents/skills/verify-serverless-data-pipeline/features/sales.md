# Sales journey

## Sub-features
CSV transformation, idempotent load, and grouped query.

## How to get to it (user POV)
Send sales CSV to the pipeline endpoint.

## Driving it with HTTP
Run `python scripts/verify.py` and inspect its receipt.

## Gotchas
Local filesystem and SQLite do not prove cloud IAM, persistence, or network behavior.

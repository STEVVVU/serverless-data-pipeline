# Serverless data pipeline

Node gateway.mjs calls separate Python transform, load, query and fused service processes. pipeline.py owns shared transformations and storage adapters, service.py owns HTTP/auth boundaries. Use .venv and requirements.lock plus requirements-dev.txt; use npm ci in this directory, never in the parent directory.

Run `.venv/Scripts/python -m unittest discover -s tests`, `.venv/Scripts/python -m ruff check --select F .`, `.venv/Scripts/python -m mypy --check-untyped-defs --ignore-missing-imports pipeline.py service.py`, `node --check gateway.mjs`, and `.venv/Scripts/python scripts/verify.py`. The maintained lifecycle skill is .agents/skills/verify-serverless-data-pipeline/SKILL.md.

Local mode must bind loopback and use synthetic shared credentials. Google mode verifies audience and caller identity; SDK clients use application credentials. Do not commit secrets or claim local duplicate-write benchmarks measure cloud/fresh-insert throughput. Preserve failed campaigns, source hashes and diagnostic receipts. Stop only driver-owned processes. No cloud resources or deployment without authorization.

# CLAUDE.md — Claude Code Guide for `loomledger`

Welcome to **loomledger**. Follow this quick reference whenever operating in this repository.

## Context & Memory Files

1. **Always read [`MEMORY.md`](MEMORY.md) first** for current phase status, locked decisions (`D1`–`D12`), and the active Phase 1–5 task queue.
2. **Read [`AGENTS.md`](AGENTS.md)** for universal coding rules and architectural invariants.
3. **Read [`SKILLS.md`](SKILLS.md)** for step-by-step implementation playbooks.

## Essential Commands

* **Run tests (fast, offline):** `PYTHONPATH=src python3 -m unittest discover -s tests -v` (or `uv run pytest -v`)
* **Lint code:** `uv run ruff check src tests`
* **Start Postgres 17:** `docker compose up -d`

## Critical Guardrails for Claude

* **Never install or import `litellm`.** All provider calls go through thin `httpx` adapters in `src/loomledger/models/adapters/`.
* **Inherit models from `CompatModel` (`src/loomledger/_compat.py`)** and use `.to_dict()` / `.from_obj()` so validation works across Pydantic versions.
* **Preserve RFC 8785 & Ed25519 integrity:** Any change to `AuditReceipt` fields in `src/loomledger/audit/receipts.py` must keep `canonical_body_for_hashing()` deterministic and keep `run_seq` strictly sequential across both `ALLOW` and `DENY` events.
* **Test everything offline:** Use `FakeModel` or `respx` fixtures for all model and runtime tests—never make live network calls in `tests/`.
* **Update [`MEMORY.md`](MEMORY.md)** at the end of every feature or phase implementation.

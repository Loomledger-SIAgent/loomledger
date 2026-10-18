# AGENTS.md — Universal Instructions for AI Coding Agents

> **Applies to:** OpenAI Codex, Claude Code (`CLAUDE.md`), GitHub Copilot (`.github/copilot-instructions.md`), Cursor, Windsurf, OpenCode, and Gemini.

## 1. Required Reading Order Before Writing Code

1. Read **[`MEMORY.md`](MEMORY.md)** to understand current phase status, locked decisions (`D1`–`D12`), and non-negotiable architectural invariants.
2. Read **[`SKILLS.md`](SKILLS.md)** for the specific task playbook matching your assignment (e.g., adding an adapter, writing middleware, extending audit receipts, or adding tests).
3. If you need deeper context on the specification, consult the companion docs repository at **[Loomledger-SIAgent/loomledger-docs](https://github.com/Loomledger-SIAgent/loomledger-docs)** (`v2/docs/01` through `09`).

## 2. Build, Lint & Test Commands

* **Run all tests (uv / pytest):**
  ```bash
  uv run pytest -v
  ```
* **Run all tests (stdlib fallback — zero extra runner packages required):**
  ```bash
  PYTHONPATH=src python3 -m unittest discover -s tests -v
  ```
* **Lint & format check:**
  ```bash
  uv run ruff check src tests
  ```
* **Start local PostgreSQL 17 ledger:**
  ```bash
  docker compose up -d
  ```

Every pull request or completed agent turn MUST leave all existing and new tests passing with zero network calls required during unit tests.

## 3. Code Style & Engineering Rules

* **Use `CompatModel` from `loomledger._compat`:** Inherit all Pydantic data models from `CompatModel` and use `@field_Validator` and `@model_Validator` from `loomledger._compat` so the codebase runs seamlessly on both Pydantic v2 (`>=2.9`) and older system Python environments (`1.10+`).
* **Strict Monetary & Usage Types:** Always use `decimal.Decimal` for USD prices and costs (`cost_usd`, `max_cost_usd`). Never use `float` for money. Keep unknown token counts as `None`, never `0`.
* **Zero LiteLLM Dependency (`D9`):** Never add `litellm` to `pyproject.toml` (due to the March 2026 PyPI credential-stealing compromise). Write thin, auditable adapters using `httpx.AsyncClient` and Pydantic validation.
* **Terminology (`D2` / `03-architecture.md`):**
  * Everything in a workflow graph is a **`Node`** (`NodeSpec`).
  * Reserve **`agent`** (`NodeKind.AGENT`) strictly for an LLM node running a multi-step tool loop (`limits.max_steps >= 2`).
  * Single-shot LLM calls without a tool loop use **`llm`** (`NodeKind.LLM`).
  * System One / OpenRouter Decisions API models (like `typesafe/jev-1.14`) use **`decide`** (`NodeKind.DECIDE`).
* **Security & Secrets:**
  * Never accept or log raw API keys. Specs must use `secret://<provider>/<name>` URIs.
  * Never place prompt text, completion text, or tool output inside `AuditReceipt` fields or OpenTelemetry span attributes. Hash them via `PayloadBlobStore.put()` (`sha256:<hex>`) and store only `input_hash`, `output_hash`, and `raw_provider_hash` on the receipt.

## 4. End-of-Task Protocol

Before finishing any coding task:
1. Run the full test suite (`uv run pytest -v` or `PYTHONPATH=src python3 -m unittest discover -s tests -v`) and verify 100% pass rate.
2. Update **`MEMORY.md`** (move completed items from the backlog to the Completed Work Log and note any new modules added).

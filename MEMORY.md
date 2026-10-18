# MEMORY.md — Project State & Architectural Ledger for LLMs

> **Purpose:** This file serves as the persistent cross-session memory for any LLM or coding agent working on **loomledger**. Read this file first before planning or writing code, and update it whenever a milestone or architectural decision changes.

## 1. Repository Topology

* **Core Implementation Repository:** [Loomledger-SIAgent/loomledger](https://github.com/Loomledger-SIAgent/loomledger) (this repository — Phase 0+ runtime monorepo).
* **Design & Specification Repository:** [Loomledger-SIAgent/loomledger-docs](https://github.com/Loomledger-SIAgent/loomledger-docs)
  * `v1/docs/`: Initial exploratory baseline (9 October 2026).
  * `v2/docs/`: Confirmed architecture specification (`01` through `09-audit-and-tracing.md`, updated 17 October 2026).

## 2. Locked Architectural Decisions (`D1`–`D12`)

| ID | Locked Decision | Enforcement in Code |
| :--- | :--- | :--- |
| **D1** | Project name is `loomledger` | Package namespace `src/loomledger/` |
| **D2** | First-class LLM and non-LLM nodes (`agent`, `llm`, `decide`, `embed`, `tool`) | `NodeKind` enum in `specs/schemas.py`; `Request`/`Response` unions in `models/contracts.py` |
| **D3** | YAML/JSON spec is the single source of truth; UI is a view | `GraphSpec` and `NodeSpec` in `specs/schemas.py` |
| **D4** | Typed ports on every node; neutral typed payloads between nodes | `PortSchemaSpec` (defaults to strict schema; `TextPayload` is explicit opt-out) |
| **D5** | Build audit and tracing core (Phase 2) before UI (Phase 4) | Phase 0 includes `audit/crypto.py`, `audit/receipts.py`, and `migrations/001_audit_ledger.sql` |
| **D6** | Own thin graph executor (no LangGraph or Pydantic Graph runtime dependency) | Custom validator in `specs/validator.py`; executor scheduled for Phase 3 |
| **D7** | Meta-agent orchestrator produces drafts for human review only | Scheduled for Phase 5 (`src/loomledger/meta/`) |
| **D8** | Python 3.11/3.12+ (`FastAPI`, `Pydantic v2`, `asyncio`, `httpx`) + PostgreSQL 17 + React Flow | Configured in `pyproject.toml` and `docker-compose.yml` (Java alternative permanently dropped) |
| **D9** | Own thin `httpx` + Pydantic model adapters; **NEVER depend on LiteLLM** | LiteLLM PyPI `1.82.7`/`1.82.8` was compromised in March 2026; keep zero LiteLLM dependencies |
| **D10** | Cryptographic audit log is separate from sampled OpenTelemetry traces | `audit_events` + `payload_blobs` are the source of truth; OTel GenAI `v1.42.0` exported alongside |
| **D11** | Durable execution deferred post-MVP; target [DBOS (`dbos-transact-py`)](https://www.dbos.dev/blog/postgres-is-all-you-need-for-durable-execution) on Postgres | Keep step state serializable and idempotent |
| **D12** | PostgreSQL 17 for specs, runs, `audit_events`, and `payload_blobs` | `migrations/001_audit_ledger.sql` |

## 3. Non-Negotiable Invariants (Never Violate)

1. **No Moving Model Aliases:** Saved specs and `ModelId` instances MUST reject `latest`, `jev-latest`, `~typesafe/jev-latest`, `auto`, or `:latest`. Every model call must pin an exact version (e.g., `1.14`) and record `catalog_version`.
2. **No Raw Secrets in Specs or Logs:** `ModelSpec.secret_ref` MUST start with `secret://` (e.g., `secret://providers/openrouter`). Never allow `sk-...` or raw tokens in specs, `audit_events`, `payload_blobs`, or OTel span attributes.
3. **Unknown Usage Is `None`, Never `0`:** In `Usage`, if a provider does not report token counts or cost, leave the field as `None` rather than coercing to `0`. Use `Decimal` (never `float`) for `cost_usd`.
4. **RFC 8785 (JCS) + Dual Monotonic Counters + Ed25519:** Every audit event is canonicalized with `canonicalize_jcs()` before SHA-256 hashing (`event_hash`) and Ed25519 signing (`signature` + `key_id`). Both permitted (`ALLOW`) and blocked (`DENY`) actions increment `run_seq` so deleting a denied action leaves a provable sequence gap.
5. **Privacy by Payload Separation:** Never embed raw prompts, completions, or tool outputs directly inside `audit_events` or OpenTelemetry span attributes. Store redacted content in `payload_blobs` keyed by `sha256:<hex>` and put only `input_hash` / `output_hash` in `audit_events` so GDPR/retention purges (`PayloadBlobStore.purge()`) never break historical hash chains.
6. **System One / Decision Model Rules ([TypeSafe Jev 1.14](https://openrouter.ai/typesafe/jev-1.14)):**
   * `box` questions require `box` in `Capabilities.decision_primitives` and `vision=True` (supported by `typesafe/jev-1.14`, rejected with HTTP 400 by `jev-1.13.0` and non-TypeSafe decision models).
   * Always warn if a `box` question is not paired with a `noul` presence check in the same request (`box` always returns 4 edges even when the target is absent).
   * Warn or tag `long_context_mode=True` when `state` exceeds `32,000` bytes of text or includes images.

## 4. Completed Work Log

### Phase 0 (Completed 17–18 October 2026)
* [x] Created `pyproject.toml`, `docker-compose.yml` (PostgreSQL 17), and `migrations/001_audit_ledger.sql` with `trg_audit_events_immutable`.
* [x] Implemented `src/loomledger/_compat.py` so models and validators run cleanly on both Pydantic v2 (`>=2.9`) and Pydantic v1.10+.
* [x] Implemented `src/loomledger/models/contracts.py` (`ModelId`, `Usage`, `Capabilities`, `GenerateRequest`/`Response`, `DecideRequest`/`Response` with `noul`/`choice`/`score`/`box`, `EmbedRequest`/`Response`, `Envelope`, `ModelNode`).
* [x] Implemented `src/loomledger/catalog/models.yaml` (`v2026.10.17.1`) and `src/loomledger/catalog/loader.py`.
* [x] Implemented `src/loomledger/specs/schemas.py` and `src/loomledger/specs/validator.py`.
* [x] Implemented `src/loomledger/audit/crypto.py` and `src/loomledger/audit/receipts.py`.
* [x] Verified 12/12 unit tests passing in `tests/`.

## 5. Next Up: Phase 1 Backlog (Single-Node Runtime & Model Layer)

When asked to implement **Phase 1**, build the following modules in order:

1. **`src/loomledger/models/registry.py`:** Resolve a `ModelSpec` + `ModelCatalog` entry into a configured `ModelNode` adapter instance and resolve `secret://` URIs via a pluggable `SecretProvider` (env var provider for local dev, mock provider for tests).
2. **`src/loomledger/models/adapters/fake.py`:** Scripted deterministic `FakeModel` implementing `ModelNode` for `generate`, `decide`, and `embed` requests so all runtime tests execute offline.
3. **`src/loomledger/models/adapters/decisions.py`:** `httpx` adapter supporting both TypeSafe's `/v1/systemone` endpoint and OpenRouter's `/api/alpha/decisions` endpoint (`typesafe/jev-1.14` and 21 other decision models), setting `long_context_mode=True` when payload >32KB or contains `image_url`.
4. **`src/loomledger/models/adapters/openai_compat.py` & `anthropic.py`:** Thin `httpx` adapters normalizing tool calls, structured output ladders (`native` → `tool` → `json_mode` → bounded retry), and `Usage`.
5. **`src/loomledger/models/middleware/`:** Implement the 6-stage pipeline in strict order: `budget.py` → `redact.py` → `retry.py` → `fallback.py` → `cost.py` → `audit.py`.
6. **`src/loomledger/runtime/agent_loop.py`:** Bare single-node `agent` tool loop enforcing `LimitsSpec.max_steps`, `allowed_tools`, and `allow / ask / deny` tool permissions.

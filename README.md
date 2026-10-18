# loomledger — Core Runtime & Audit Ledger (Phase 0 Implementation)

> **Governed, model-agnostic multi-agent and decision-model runtime with RFC 8785 hash-chained, Ed25519-signed audit trails.**

**Implementation Repository:** [Loomledger-SIAgent/loomledger](https://github.com/Loomledger-SIAgent/loomledger)  
**Architecture & Design Docs Repository:** [Loomledger-SIAgent/loomledger-docs](https://github.com/Loomledger-SIAgent/loomledger-docs) (`v2/docs/`)  
**Current Implementation Status:** **Phase 0 Complete** (Foundations, Spec Schemas, Static Validator & Cryptographic Audit Primitives — 12/12 offline tests passing)  
**Next Milestone:** **Phase 1** (Model Adapters, 6-Stage Middleware Chain & Single-Node Agent Tool Loop)

## What Is Implemented in Phase 0

This repository ([Loomledger-SIAgent/loomledger](https://github.com/Loomledger-SIAgent/loomledger)) contains the core Python runtime and cryptographic audit engine for **loomledger**. Phase 0 establishes the non-negotiable foundations that every downstream phase (adapters, Postgres store, DAG executor, FastAPI server, and React Flow canvas) builds upon:

| Module / Path | Responsibility | Key Classes & Functions |
| :--- | :--- | :--- |
| **`migrations/001_audit_ledger.sql`** | PostgreSQL 17 append-only ledger & blob store DDL | `audit_events` table, `prevent_audit_events_mutation()` (`BEFORE UPDATE OR DELETE` trigger), `payload_blobs` table |
| **`src/loomledger/models/contracts.py`** | Unified model protocol & typed request/response contracts | `ModelId`, `Usage`, `Capabilities`, `Envelope`, `ModelNode`, `GenerateRequest`/`Response`, `DecideRequest`/`Response` (`noul`, `choice`, `score`, `box`), `EmbedRequest`/`Response` |
| **`src/loomledger/catalog/`** | Versioned capability & token pricing catalog (`v2026.10.17.1`) | `models.yaml`, `ModelCatalog`, `CatalogEntry`, `ModelPrice`, `compute_cost_usd()` |
| **`src/loomledger/specs/schemas.py`** | YAML/JSON node, agent, and workflow graph specifications | `NodeSpec` (`agent`, `llm`, `decide`, `embed`, `tool`), `ModelSpec`, `LimitsSpec`, `PortSchemaSpec`, `EdgeSpec`, `GraphSpec` |
| **`src/loomledger/specs/validator.py`** | Pre-execution static graph & capability checker | `SpecValidator`, `ValidationReport` (port type matching, DAG cycle detection, capability verification, [TypeSafe Jev 1.14](https://openrouter.ai/typesafe/jev-1.14) `box`/`noul` pairing & 32KB fast-mode warnings) |
| **`src/loomledger/audit/crypto.py`** | Deterministic serialization, hashing & Ed25519 signing | `canonicalize_jcs()` ([RFC 8785](https://agenticrail.nz/blog/cryptographic-ai-audit-trail/)), `hash_payload()`, `SigningKeyPair`, `PayloadBlobStore` |
| **`src/loomledger/audit/receipts.py`** | Hash-chained receipts & offline chain verification | `AuditReceipt`, `AuditChainBuilder`, `verify_run_chain()`, `ChainVerificationResult` |

## Repository Structure

```text
loomledger/
├── README.md                          # Phase 0 implementation guide & quickstart
├── MEMORY.md                          # Persistent project state, decisions & Phase 1 queue for LLMs
├── AGENTS.md                          # Universal coding agent instructions & architectural invariants
├── CLAUDE.md                          # Claude Code agent entry point & workflow commands
├── SKILLS.md                          # Step-by-step agent playbooks for extending loomledger
├── .github/
│   └── copilot-instructions.md        # GitHub Copilot instructions referencing AGENTS.md & SKILLS.md
├── pyproject.toml                     # Python package config, dependencies, ruff & pytest settings
├── docker-compose.yml                 # PostgreSQL 17 with auto-mounted migrations/
├── migrations/
│   └── 001_audit_ledger.sql           # Append-only audit_events & payload_blobs schema
├── src/
│   └── loomledger/
│       ├── __init__.py
│       ├── _compat.py                 # Pydantic v1/v2 compatibility layer
│       ├── catalog/
│       │   ├── __init__.py
│       │   ├── loader.py
│       │   └── models.yaml
│       ├── models/
│       │   ├── __init__.py
│       │   └── contracts.py
│       ├── specs/
│       │   ├── __init__.py
│       │   ├── schemas.py
│       │   └── validator.py
│       └── audit/
│           ├── __init__.py
│           ├── crypto.py
│           └── receipts.py
└── tests/
    ├── test_catalog_and_contracts.py
    ├── test_spec_validator.py
    └── test_crypto_receipts.py
```

## Quickstart & Running Tests

### 1. Run the Offline Test Suite (Zero External Dependencies or API Keys)

With `uv` (recommended):

```bash
uv sync --extra dev
uv run pytest -v
```

Or directly with standard `unittest` (requires only `pydantic`, `pyyaml`, and `cryptography`):

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### 2. Start the Local PostgreSQL 17 Audit Ledger

```bash
docker compose up -d
```

This starts `postgres:17-alpine` and automatically executes `migrations/001_audit_ledger.sql` to create `audit_events` (protected by the `trg_audit_events_immutable` trigger) and `payload_blobs`.

## Usage Examples (Phase 0 APIs)

### Validate a Multi-Model Workflow Graph Against the Catalog

```python
from loomledger.catalog import ModelCatalog
from loomledger.specs import GraphSpec, SpecValidator

catalog = ModelCatalog.load_default()
validator = SpecValidator(catalog)

graph = GraphSpec.from_yaml_file("workflow.yaml")
report = validator.validate_graph(graph)
if not report.valid:
    raise RuntimeError(f"Spec validation failed: {report.errors}")
```

### Build and Verify an RFC 8785 + Ed25519 Audit Chain Offline

```python
from loomledger.audit import (
    AuditChainBuilder,
    PayloadBlobStore,
    SigningKeyPair,
    verify_run_chain,
)

key = SigningKeyPair.generate("k1_2026-10_ed25519")
blobs = PayloadBlobStore()

input_hash = blobs.put({"claim_text": "Rear bumper scratch"}, created_at_ms=1760700000000)

chain = AuditChainBuilder(
    run_id="run-001",
    catalog_version="2026.10.17.1",
    trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
    signing_key=key,
)
chain.append(ts_ms=1760700000000, event_kind="run_start", decision="ALLOW", span_id="00f067aa0ba902b7")
chain.append(
    ts_ms=1760700000120,
    event_kind="model_call",
    node_id="claim-classifier",
    decision="ALLOW",
    model_id="openrouter_decisions/typesafe/jev-1.14@1.14",
    span_id="11f067aa0ba902b8",
    parent_span_id="00f067aa0ba902b7",
    input_hash=input_hash,
    confidence=0.94,
)

result = verify_run_chain(chain.receipts, public_keys={key.key_id: key.public_key})
assert result.valid is True
```

## AI Coding Agents & LLM Contributors

This repository is pre-configured for autonomous coding agents and LLM assistants:

* **[`MEMORY.md`](MEMORY.md):** Persistent project memory, architectural decisions (`D1`–`D12`), completed Phase 0 inventory, and the prioritized Phase 1 task backlog.
* **[`AGENTS.md`](AGENTS.md):** Universal rules, coding conventions, security constraints, and verification commands for all agents.
* **[`SKILLS.md`](SKILLS.md):** Modular step-by-step playbooks for implementing adapters, decision nodes, middleware, audit stores, and deterministic tests.
* **[`CLAUDE.md`](CLAUDE.md) & [`.github/copilot-instructions.md`](.github/copilot-instructions.md):** Tool-specific entry points for Claude Code and GitHub Copilot.

## License

Apache-2.0

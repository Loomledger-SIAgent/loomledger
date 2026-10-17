# loomledger

> **Build governed, model-agnostic multi-agent and decision-model workflows with cryptographically verifiable audit trails and per-node cost attribution.**

**Repository:** [github.com/npraveen092/loomledger](https://www.google.com/search?q=https%3A%2F%2Fgithub.com%2Fnpraveen092%2Floomledger)

**Current Specification:** [v2/](https://www.google.com/search?q=v2%2FREADME.md) (Updated 17 October 2026) · **Initial Baseline:** [v1/](https://www.google.com/search?q=v1%2FREADME.md) (9 October 2026)

**Status:** Phase 0 (Architecture & Specification Complete — Ready for Implementation)

## Why loomledger Exists

Visual agent builders such as Dify, Langflow, Flowise, n8n, and OpenAI's Agent Builder already cover general-purpose drag-and-drop canvas workflows. **loomledger** does not compete on generic widget breadth; instead, it is engineered for **governed, cost-aware, multi-model workflows** where regulated and cost-sensitive teams can always prove:

1. **Which exact pinned model** made a decision or generated an output (`agent`, `llm`, `decide`, `embed`, or `tool` node).

2. **What exact input state and schema** entered and exited the node, validated via strict Pydantic v2 contracts rather than raw chat histories.

3. **What the invocation cost** in input, output, cached, and reasoning tokens against a versioned price catalog (`models.yaml`).

4. **Whether the audit log was altered**, proven offline through [RFC 8785 (JSON Canonicalization Scheme) SHA-256 hash chaining, monotonic sequence numbers covering both ALLOW and DENY events, and Ed25519 cryptographic signatures](https://www.google.com/search?q=https%3A%2F%2Fagenticrail.nz%2Fblog%2Fcryptographic-ai-audit-trail%2F).

## Core Architectural Pillars

### 1. The Spec Is the Source of Truth

Every node and workflow graph is defined as a versioned YAML/JSON specification (`NodeSpec`, `AgentSpec`, `GraphSpec`). The React Flow visual canvas reads and writes these exact specification files—if the UI and spec ever disagree, the spec wins.

### 2. First-Class LLM and Non-LLM Decision Nodes

Rather than forcing every step through an expensive generative chat loop, **loomledger** treats non-LLM decision models as first-class graph citizens alongside LLMs:

| Node Kind (`kind`) | Purpose | Example Models / Runtimes | Enforced Output Contract | 
| ----- | ----- | ----- | ----- | 
| **`agent`** | Multi-step LLM node running a permissioned tool loop (`max_steps > 1`) | Claude, GPT, local Qwen (via Ollama / LM Studio) | Schema-validated Pydantic payload (`output_schema`) + full tool-call audit trail | 
| **`llm`** | Single-shot generative inference (no tool loop) | Any OpenAI-compatible or Anthropic model | Schema-validated JSON by default (`TextPayload` explicit opt-out) | 
| **`decide`** | Fast, calibrated probabilistic judgments (`noul`, `choice`, `score`, `box`) | [TypeSafe Jev 1.14](https://www.google.com/search?q=https%3A%2F%2Fopenrouter.ai%2Ftypesafe%2Fjev-1.14) (`typesafe/jev-1.14`) & 22 models on the [OpenRouter Decisions API](https://www.google.com/search?q=https%3A%2F%2Fopenrouter.ai%2Fdocs%2Fguides%2Fcommunity%2Fjev) | Selected option, calibrated probability distribution, bounding box, and `confidence` | 
| **`embed`** | Vector embedding generation | Local or API-hosted embedding models | Typed vector payload | 
| **`tool`** | Deterministic code or sandboxed [Model Context Protocol (MCP)](https://www.google.com/search?q=https%3A%2F%2Fmodelcontextprotocol.io%2Fdocs%2F2026-07-28%2Ftutorials%2Fsecurity%2Fsecurity_best_practices) tool execution | Python functions, containerized shell/file/MCP servers | Schema-validated tool output | 

### 3. Six-Stage Model Middleware Pipeline

Every node invocation passes through a thin, auditable in-house adapter (`httpx` + Pydantic v2, with zero LiteLLM dependency) wrapped in a strict six-stage middleware chain:

1. **Budget & Policy Gate:** Enforces per-run token/USD ceilings, allowed models, and payload size thresholds (such as [Jev 1.14's 32KB fast mode vs. 262K long-context mode](https://www.google.com/search?q=https%3A%2F%2Fopenrouter.ai%2Fdocs%2Fguides%2Fcommunity%2Fjev)).

2. **Pre-Hash Redaction:** Scrubs PII and secrets before payloads are hashed or persisted.

3. **Timeout & Bounded Retry:** Applies exponential backoff with jitter on retryable errors (`429`, `5xx`, network timeouts).

4. **Capability-Checked Fallback:** Routes to a fallback model only if it satisfies the same `Capabilities` and output schema, logging the fallback reason as its own audit event.

5. **Versioned Cost Attribution:** Computes exact USD cost from the pinned `catalog/models.yaml` version.

6. **Audit & Telemetry Emission:** Commits the signed receipt to PostgreSQL and exports [OpenTelemetry GenAI (v1.42.0)](https://www.google.com/search?q=https%3A%2F%2Fwww.dash0.com%2Fknowledge%2Fopentelemetry-genai-semantic-conventions-explained) spans and metrics.

### 4. Cryptographic Audit Trail & Privacy-Safe Payload Separation

Standard database logs can be silently edited or truncated by anyone with database credentials ([Activepieces, 2026](https://www.google.com/search?q=https%3A%2F%2Fwww.activepieces.com%2Fblog%2Fwhat-a-hash-chained-audit-trail-actually-means)). **loomledger** separates immutable event metadata from sensitive content:

* **`audit_events` Table (Append-Only):** Records `run_seq` (monotonic per run, numbering both permitted `ALLOW` and blocked `DENY` steps so deleted records leave a provable gap), `prev_event_hash`, `event_hash` over RFC 8785 canonical JSON, `key_id`, and an `Ed25519` signature.

* **`payload_blobs` Table (Content-Addressed by `sha256`):** Stores redacted prompts, completions, and raw provider envelopes keyed by SHA-256 digest. If a privacy retention policy later purges a sensitive blob, every historical `event_hash` and `Ed25519` signature in `audit_events` remains 100% valid.

* **External WORM Anchoring:** Periodically anchors signed chain heads to [Amazon S3 Object Lock](https://www.google.com/search?q=https%3A%2F%2Fdocs.aws.amazon.com%2FAmazonS3%2Flatest%2Fuserguide%2Fobject-lock.html) or [Sigstore Rekor](https://www.google.com/search?q=https%3A%2F%2Fdocs.sigstore.dev%2Flogging%2Foverview%2F).

### 5. Two-Way Orchestration & Two-Layer Safety Gates

Users can wire typed nodes manually or ask the **meta-agent orchestrator** to inspect node specs and draft a candidate `GraphSpec` that passes the same static port type-checker before human review. Destructive tool calls are protected by two-layer gating: a fast `decide` reversibility check (e.g., `typesafe/jev-1.14` `noul` question) paired with a mandatory human approval gate when confidence falls below threshold.

## Repository Evolution: `v1/` vs. `v2/`

This repository preserves both the initial exploratory design ([v1/](https://www.google.com/search?q=v1%2FREADME.md)) and the researched, locked-in specification ([v2/](https://www.google.com/search?q=v2%2FREADME.md)):

| Area | `v1/` — Initial Exploration (9 Oct 2026) | `v2/` — Confirmed Specification (17 Oct 2026) | 
| ----- | ----- | ----- | 
| **Backend & Storage Stack** | Proposed Python (FastAPI) vs. Java (Quarkus / LangChain4j) alternative | **Locked in Python 3.12+ (`FastAPI`, `Pydantic v2`, `asyncio`, `httpx`) + PostgreSQL 17**; Java alternative removed | 
| **Decision Model Layer** | Single custom adapter for `jev-1.13.0` (32K context, 3 primitives: `noul`, `choice`, `score`) | Generalized **`decisions.py` adapter** supporting [TypeSafe System One](https://www.google.com/search?q=https%3A%2F%2Fdocs.typesafe.ai%2Fconcepts%2Fsystem-one) (`/v1/systemone`) and the 22-model [OpenRouter Decisions API](https://www.google.com/search?q=https%3A%2F%2Fopenrouter.ai%2Fdocs%2Fguides%2Fcommunity%2Fjev) (`/api/alpha/decisions`), updated for **`typesafe/jev-1.14`** (262K context, image inputs, and the 4th `box` primitive) | 
| **Audit & Tracing Design** | High-level baseline; exact event schema and privacy policy left as open questions | Added **`09-audit-and-tracing.md`** with full PostgreSQL DDL, RFC 8785 JCS canonicalization, `Ed25519` signing (`key_id`), `payload_blobs` separation, and [OTel GenAI v1.42.0](https://www.google.com/search?q=https%3A%2F%2Fwww.dash0.com%2Fknowledge%2Fopentelemetry-genai-semantic-conventions-explained) mapping | 
| **Output Schema Strictness** | Open question whether typed output should be enforced by default | **Typed `output_schema` enforced by default** across all nodes, with explicit `TextPayload(text: str)` opt-out | 
| **Open Questions (`07`)** | 9 unresolved architectural questions and 10 unconfirmed proposals | All **12 decisions (`D1`–`D12`) confirmed** and all **9 open questions resolved** with concrete engineering specs | 
| **Framework & Security Research** | Early notes on Pydantic AI, DBOS, and tool sandboxing | Updated for [Pydantic AI's pydantic_graph & RuntimeCapability](https://www.google.com/search?q=https%3A%2F%2Fpydantic.dev%2Fdocs%2Fai%2Fcapabilities%2Fdurable_execution%2Foverview%2F), [DBOS on Postgres](https://www.google.com/search?q=https%3A%2F%2Fwww.dbos.dev%2Fblog%2Fpostgres-is-all-you-need-for-durable-execution), and [June–July 2026 MCP sandboxing guidelines](https://www.google.com/search?q=https%3A%2F%2Fmodelcontextprotocol.io%2Fdocs%2F2026-07-28%2Ftutorials%2Fsecurity%2Fsecurity_best_practices) | 

## Documentation Index

| Document | `v2/` (Current Spec) | `v1/` (Initial Baseline) | What It Covers | 
| ----- | ----- | ----- | ----- | 
| **Overview** | [v2/README.md](https://www.google.com/search?q=v2%2FREADME.md) | [v1/README.md](https://www.google.com/search?q=v1%2FREADME.md) | High-level summary, doc table, and phase overview | 
| **01 Vision & Positioning** | [v2/docs/01-vision-and-positioning.md](https://www.google.com/search?q=v2%2Fdocs%2F01-vision-and-positioning.md) | [v1/docs/01-vision-and-positioning.md](https://www.google.com/search?q=v1%2Fdocs%2F01-vision-and-positioning.md) | Core thesis, honest market assessment, differentiators, and MVP success criteria | 
| **02 Requirements** | [v2/docs/02-requirements.md](https://www.google.com/search?q=v2%2Fdocs%2F02-requirements.md) | [v1/docs/02-requirements.md](https://www.google.com/search?q=v1%2Fdocs%2F02-requirements.md) | Functional (`FR1`–`FR9`) and non-functional requirements, multi-model constraints, and non-goals | 
| **03 Architecture** | [v2/docs/03-architecture.md](https://www.google.com/search?q=v2%2Fdocs%2F03-architecture.md) | [v1/docs/03-architecture.md](https://www.google.com/search?q=v1%2Fdocs%2F03-architecture.md) | `Node` vs. `Agent` terminology, typed ports, spec sketches, confirmed stack, and security model | 
| **04 Implementation Plan** | [v2/docs/04-implementation-plan.md](https://www.google.com/search?q=v2%2Fdocs%2F04-implementation-plan.md) | [v1/docs/04-implementation-plan.md](https://www.google.com/search?q=v1%2Fdocs%2F04-implementation-plan.md) | Six-phase execution plan (Phases 0–5), engineering principles, and risk mitigations | 
| **05 Learning Roadmap** | [v2/docs/05-learning-roadmap.md](https://www.google.com/search?q=v2%2Fdocs%2F05-learning-roadmap.md) | [v1/docs/05-learning-roadmap.md](https://www.google.com/search?q=v1%2Fdocs%2F05-learning-roadmap.md) | Structured path through Python async/Pydantic v2, bare agent loops, decision routing, MCP, and evals | 
| **06 Research Notes** | [v2/docs/06-research-notes.md](https://www.google.com/search?q=v2%2Fdocs%2F06-research-notes.md) | [v1/docs/06-research-notes.md](https://www.google.com/search?q=v1%2Fdocs%2F06-research-notes.md) | Verified notes on Jev 1.14, OpenRouter Decisions API, Apple Silicon local models, LiteLLM incident, OTel GenAI, and DBOS | 
| **07 Decisions & Questions** | [v2/docs/07-decisions-and-open-questions.md](https://www.google.com/search?q=v2%2Fdocs%2F07-decisions-and-open-questions.md) | [v1/docs/07-decisions-and-open-questions.md](https://www.google.com/search?q=v1%2Fdocs%2F07-decisions-and-open-questions.md) | Decision log (`D1`–`D12`) and resolved architectural questions | 
| **08 Model Layer** | [v2/docs/08-model-layer.md](https://www.google.com/search?q=v2%2Fdocs%2F08-model-layer.md) | [v1/docs/08-model-layer.md](https://www.google.com/search?q=v1%2Fdocs%2F08-model-layer.md) | `ModelNode` protocol, `Generate`/`Decide`/`Embed` contracts, middleware order, and `decisions.py` adapter | 
| **09 Audit & Tracing** | [v2/docs/09-audit-and-tracing.md](https://www.google.com/search?q=v2%2Fdocs%2F09-audit-and-tracing.md) | *Added in `v2/`* | PostgreSQL `audit_events` & `payload_blobs` DDL, RFC 8785 + Ed25519 receipts, WORM anchoring, and OTel GenAI mapping | 

## Confirmed Technology Stack (`v2/`)

* **Language & Runtime:** Python 3.12+ (`asyncio`, strict type annotations)

* **API & Validation:** `FastAPI`, `Pydantic v2`

* **Model Adapters:** Thin custom `httpx` adapters (`openai_compat.py`, `anthropic.py`, `decisions.py`, `fake.py`) with a versioned YAML capability and pricing catalog (`catalog/models.yaml`)

* **Cryptography & Audit Integrity:** `cryptography` (Ed25519 signing with `key_id` rotation), RFC 8785 canonical JSON serialization, SHA-256 content-addressed blobs, and pluggable WORM chain-head anchoring ([Amazon S3 Object Lock](https://www.google.com/search?q=https%3A%2F%2Fdocs.aws.amazon.com%2FAmazonS3%2Flatest%2Fuserguide%2Fobject-lock.html) / [Sigstore Rekor](https://www.google.com/search?q=https%3A%2F%2Fdocs.sigstore.dev%2Flogging%2Foverview%2F))

* **Database:** PostgreSQL 17 (`specs`, `runs`, `audit_events` with `UPDATE`/`DELETE` prevention triggers, and `payload_blobs`)

* **Observability:** [OpenTelemetry GenAI (v1.42.0)](https://www.google.com/search?q=https%3A%2F%2Fwww.dash0.com%2Fknowledge%2Fopentelemetry-genai-semantic-conventions-explained) spans (`invoke_workflow`, `invoke_agent`, `chat`, `decide`, `execute_tool`) and loop-detection metrics isolated in `loomledger/audit/otel_mapping.py`

* **Tool Sandboxing:** Rootless containers / OS sandboxes (Bubblewrap) with per-node capability allowlists for shell, file, and MCP tools

* **Frontend (Phase 4):** React + TypeScript + React Flow

* **Supply Chain & Tooling:** `uv` (hash-pinned lockfile), `ruff`, `pytest`, `respx`

* **Post-MVP Durable Execution:** [DBOS (dbos-transact-py)](https://www.google.com/search?q=https%3A%2F%2Fwww.dbos.dev%2Fblog%2Fpostgres-is-all-you-need-for-durable-execution) checkpointing directly to PostgreSQL

## Implementation Roadmap

1. **Phase 0 — Foundations & Cryptographic Primitives (Days 1–3):** Initialize `uv` workspace, PostgreSQL 17 `docker-compose.yml`, RFC 8785 + SHA-256 + Ed25519 receipt primitives (`loomledger/audit/crypto.py`), and Pydantic v2 schemas for `Envelope`, `Capabilities`, `NodeSpec`, `AgentSpec`, and `GraphSpec`.

2. **Phase 1 — Model Layer & Single-Node Runtime (Weeks 1–2):** Implement `ModelNode` contracts, `catalog/models.yaml`, the four MVP adapters (`fake`, `openai_compat`, `anthropic`, `decisions` for `typesafe/jev-1.14`), the 6-stage middleware pipeline, and the permissioned `agent` tool loop with offline contract tests.

3. **Phase 2 — Audit & Tracing Core (Weeks 2–3):** Build the append-only PostgreSQL `audit_events` and `payload_blobs` store, PII redaction middleware, `ReplayAdapter`, `otel_mapping.py` exporter, and CLI commands (`loomledger run`, `loomledger trace`, `loomledger verify`, `loomledger replay`).

4. **Phase 3 — Multi-Node Graph Execution & Safety Gates (Week 4):** Add the typed DAG/conditional graph executor, confidence-gated `decide` routing, per-run token/USD budgets, and two-layer human approval gates.

5. **Phase 4 — FastAPI Service & React Flow Canvas (Weeks 5–6):** Expose REST/SSE endpoints and build the React Flow canvas with live port type-checking, trace timeline inspection, and per-node cost attribution views.

6. **Phase 5 — Meta-Agent Orchestrator (Weeks 7–8):** Build the meta-agent that reads `NodeSpec` definitions and drafts a type-validated `GraphSpec` for human review, benchmarked against hand-built graphs.

## License

Proposed under the **Apache-2.0 License** (see [v2/docs/07-decisions-and-open-questions.md](https://www.google.com/search?q=v2%2Fdocs%2F07-decisions-and-open-questions.md)).
# SKILLS.md — Project Playbooks for Coding Agents

> **Purpose:** Modular, step-by-step playbooks for agents working on **loomledger**. Load the relevant skill section below before implementing a feature in that subsystem.

## Skill 1: Adding or Updating a Model Adapter (`src/loomledger/models/adapters/`)

When implementing a model adapter in Phase 1+:

1. **Implement the `ModelNode` Protocol (`src/loomledger/models/contracts.py`):**
   * Expose `id: ModelId` (pinned version required) and `capabilities: Capabilities` loaded from `src/loomledger/catalog/models.yaml`.
   * Implement `async def invoke(self, req: Request, ctx: CallContext) -> Response`.
2. **Pre-Flight Capability Check:**
   * Verify `req.kind` is in `self.capabilities.kinds`.
   * For `GenerateRequest`, if `req.tools` is non-empty, verify `self.capabilities.tools is True`.
3. **Structured Output Ladder (`GenerateRequest`):**
   * Respect `self.capabilities.structured_output`:
     * `"native"`: use provider's native JSON Schema response format.
     * `"tool"`: bind the output schema as a synthetic tool call and extract tool arguments.
     * `"json_mode"`: request JSON mode and validate the parsed response against the Pydantic schema.
   * On validation failure, perform bounded retries feeding the Pydantic validation error back into the retry prompt, and log each attempt.
4. **Normalize Usage & Raw Provider Hash:**
   * Populate `Usage(input_tokens=..., output_tokens=..., cached_tokens=..., reasoning_tokens=...)` leaving missing metrics as `None`.
   * Compute `raw_provider_hash = hash_payload(raw_response_dict)` and store the redacted raw envelope in `PayloadBlobStore`.

## Skill 2: Working with System One & Decisions API Nodes (`decisions.py`)

When building or extending support for decision models ([TypeSafe Jev 1.14](https://openrouter.ai/typesafe/jev-1.14) and the [OpenRouter Decisions API](https://openrouter.ai/docs/guides/community/jev)):

1. **Support Both API Surfaces:**
   * **TypeSafe System One API:** `POST https://api.typesafe.ai/v1/systemone` or `POST https://openrouter.ai/api/v1/systemone` with `{state, model, questions}`.
   * **OpenRouter Decisions API:** `POST https://openrouter.ai/api/alpha/decisions` supporting `typesafe/jev-1.14` plus 21+ models across OpenAI (`openai/gpt-6-luna-decisions`), Microsoft (`microsoft/microsoft-decision-1`), Perplexity, and Cloudflare.
2. **Enforce Primitive Rules (`noul`, `choice`, `score`, `box`):**
   * `noul`: returns a single probability (`0.0` to `1.0`).
   * `choice`: requires 2–255 options in `criteria`; encourage an explicit `other` option because probabilities are relative to supplied labels.
   * `score`: requires 2–10 ordered rubric levels in `criteria`.
   * `box`: supported ONLY when `"box"` is in `capabilities.decision_primitives` and `capabilities.vision is True` (e.g., `typesafe/jev-1.14`). Because `box` always returns 4 coordinates (`top`, `bottom`, `left`, `right`) even if the object is absent, always pair `box` with a `noul` presence question in the same request.
3. **Detect Long-Context Mode:**
   * If serialized `state` exceeds `32,000` bytes of text or contains an `image_url` block, set `DecideResponse.long_context_mode = True` and attach `loomledger.decide.long_context_mode = True` to trace metadata.
4. **LLM Fallback Shape Compatibility:**
   * When a `decide` node falls back to a generative `llm` node (e.g., `ollama/qwen3.6-27b`), the fallback adapter wrapper MUST enforce a strict Pydantic schema that returns a valid `DecideResponse` (`answers` with probabilities and `confidence`) so downstream conditional edges work unchanged.

## Skill 3: Implementing the 6-Stage Middleware Chain (`src/loomledger/models/middleware/`)

Maintain this exact execution order around every `ModelNode.invoke()` call:

1. **`budget.py` (Budget & Policy Gate):** Check remaining run token and USD budgets (`CallContext.budget_remaining_tokens`, `budget_remaining_usd`) and payload size against `max_context`. If exceeded, emit an `AuditReceipt` with `event_kind="policy_gate"` and `decision="DENY"` before raising `BudgetExceededError`.
2. **`redact.py` (Pre-Hash Redaction):** Apply regex/PII/secret scrubbing to inputs before hashing into `PayloadBlobStore` and before sending to external providers.
3. **`retry.py` (Timeout & Retry):** Enforce `LimitsSpec.timeout_ms` and retry only transient errors (`HTTP 429`, `5xx`, network timeouts) with exponential backoff + jitter.
4. **`fallback.py` (Capability-Checked Fallback):** If primary retries are exhausted and `ModelSpec.fallback` is defined, emit an `AuditReceipt` (`event_kind="fallback"`, `decision="ALLOW"`, `meta_json={"reason": ...}`) and invoke the fallback model.
5. **`cost.py` (Versioned Cost Calculation):** Compute `usage.cost_usd` via `ModelCatalog.compute_cost_usd()` using the pinned `catalog_version`.
6. **`audit.py` (Cryptographic Receipt & OTel Span):** Store redacted input/output blobs in `PayloadBlobStore`, append the signed `AuditReceipt` to `AuditChainBuilder` / Postgres, and emit the OpenTelemetry GenAI span via `otel_mapping.py`.

## Skill 4: Extending the Cryptographic Audit Ledger & OpenTelemetry Mapping (`src/loomledger/audit/`)

1. **Canonical Serialization (`crypto.py`):**
   * Never use raw `json.dumps()` for hashing or signing. Always call `canonicalize_jcs(obj)` so keys are sorted lexicographically at every nesting level with no whitespace ([RFC 8785](https://agenticrail.nz/blog/cryptographic-ai-audit-trail/)).
2. **Sequence Integrity (`receipts.py`):**
   * Every step—including blocked tool calls (`decision="DENY"`), failed schema validations, and human approval escalations (`decision="ESCALATE"`)—must be appended to the run's receipt chain with a strictly incrementing `run_seq`.
3. **OpenTelemetry GenAI `v1.42.0` Isolation (`otel_mapping.py`):**
   * Keep all `gen_ai.*` attribute strings inside `src/loomledger/audit/otel_mapping.py` because `semantic-conventions-genai` is still in `Development` status ([Dash0 Guide](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained)).
   * Map runs to `invoke_workflow`, `agent` nodes to `invoke_agent`, model calls to `chat` / `decide` / `embeddings`, and tools/MCP calls to `execute_tool`.
   * Track `gen_ai.invoke_agent.inference_calls` vs. `gen_ai.invoke_agent.tool_calls` to detect deliberative agent loops.
   * Never attach prompt or completion strings to span attributes.

## Skill 5: Writing Offline Deterministic Tests (`tests/`)

1. **Dual Runner Compatibility:** Write test suites using `unittest.TestCase` (which `pytest` also discovers and runs natively) so tests execute in any environment via either `uv run pytest` or `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
2. **Zero Live Network Calls:** Mock HTTP adapters with `respx` or use `FakeModel` (`fake/scripted@1.0.0`).
3. **Tamper-Evidence Assertions:** Whenever touching `audit/` or `specs/`, include negative tests verifying that `verify_run_chain()` catches mutated fields, deleted `DENY` steps (`run_seq` gaps), unknown `key_id`s, and tail truncation, while confirming `PayloadBlobStore.purge()` leaves chain verification intact.

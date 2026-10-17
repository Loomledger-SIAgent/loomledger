-- Phase 0: Append-only cryptographic audit ledger and content-addressed payload store
-- Matches v2/docs/09-audit-and-tracing.md specification

CREATE TABLE IF NOT EXISTS audit_events (
    ledger_seq        BIGSERIAL PRIMARY KEY,
    event_id          UUID NOT NULL UNIQUE,
    run_id            UUID NOT NULL,
    run_seq           INTEGER NOT NULL CHECK (run_seq >= 1),
    ts_ms             BIGINT NOT NULL CHECK (ts_ms > 0),
    event_kind        TEXT NOT NULL CHECK (
        event_kind IN (
            'run_start',
            'node_invoke',
            'model_call',
            'tool_call',
            'policy_gate',
            'approval_gate',
            'fallback',
            'run_end'
        )
    ),
    node_id           TEXT,
    decision          TEXT NOT NULL CHECK (
        decision IN ('ALLOW', 'DENY', 'ESCALATE', 'ERROR')
    ),
    model_id          TEXT,
    catalog_version   TEXT NOT NULL,
    trace_id          TEXT NOT NULL,
    span_id           TEXT NOT NULL,
    parent_span_id    TEXT,
    input_hash        TEXT,
    output_hash       TEXT,
    raw_provider_hash TEXT,
    usage_json        JSONB,
    confidence        NUMERIC(5, 4) CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    meta_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    prev_event_hash   TEXT NOT NULL,
    event_hash        TEXT NOT NULL,
    key_id            TEXT NOT NULL,
    signature         TEXT NOT NULL,
    UNIQUE (run_id, run_seq)
);

CREATE INDEX IF NOT EXISTS idx_audit_events_run_id_seq ON audit_events (run_id, run_seq);
CREATE INDEX IF NOT EXISTS idx_audit_events_trace_id ON audit_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_node_id ON audit_events (node_id);

CREATE OR REPLACE FUNCTION prevent_audit_events_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: % operations are prohibited', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events;
CREATE TRIGGER trg_audit_events_immutable
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION prevent_audit_events_mutation();

CREATE TABLE IF NOT EXISTS payload_blobs (
    blob_hash         TEXT PRIMARY KEY,
    created_at_ms     BIGINT NOT NULL CHECK (created_at_ms > 0),
    redaction_policy  TEXT NOT NULL,
    content_json      JSONB,
    purged_at_ms      BIGINT
);

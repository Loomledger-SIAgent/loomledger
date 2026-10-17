"""Append-only hash-chained and Ed25519-signed audit receipts and offline verifier."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence
import uuid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field

from loomledger._compat import CompatModel
from loomledger.audit.crypto import SigningKeyPair, canonicalize_jcs, sha256_hex

GENESIS_HASH = "GENESIS"

EventKind = Literal[
    "run_start",
    "node_invoke",
    "model_call",
    "tool_call",
    "policy_gate",
    "approval_gate",
    "fallback",
    "run_end",
]
DecisionKind = Literal["ALLOW", "DENY", "ESCALATE", "ERROR"]


class AuditReceipt(CompatModel):
    """Cryptographic receipt representing a single row in the audit_events table."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    run_seq: int = Field(..., ge=1)
    ts_ms: int = Field(..., gt=0)
    event_kind: EventKind
    node_id: Optional[str] = None
    decision: DecisionKind
    model_id: Optional[str] = None
    catalog_version: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    raw_provider_hash: Optional[str] = None
    usage_json: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    meta_json: Dict[str, Any] = Field(default_factory=dict)
    prev_event_hash: str
    event_hash: str
    key_id: str
    signature: str
    version: str = "loomledger_receipt_v2"

    def canonical_body_for_hashing(self) -> Dict[str, Any]:
        """Return all signed fields (excluding event_hash and signature) for RFC 8785 hashing."""
        data = self.to_dict()
        data.pop("event_hash", None)
        data.pop("signature", None)
        return data

    def compute_expected_hash(self) -> str:
        return f"sha256:{sha256_hex(canonicalize_jcs(self.canonical_body_for_hashing()))}"


class ChainVerificationResult(CompatModel):
    valid: bool
    checked_count: int
    broken_at_run_seq: Optional[int] = None
    reason: Optional[str] = None


class AuditChainBuilder:
    """Builds sequential, hash-chained, Ed25519-signed receipts for a single workflow run."""

    def __init__(
        self,
        run_id: str,
        catalog_version: str,
        trace_id: str,
        signing_key: SigningKeyPair,
    ) -> None:
        self.run_id = run_id
        self.catalog_version = catalog_version
        self.trace_id = trace_id
        self.signing_key = signing_key
        self._receipts: List[AuditReceipt] = []

    @property
    def receipts(self) -> List[AuditReceipt]:
        return list(self._receipts)

    def rotate_key(self, new_signing_key: SigningKeyPair) -> None:
        """Rotate the active Ed25519 signing key mid-stream while preserving chain continuity."""
        self.signing_key = new_signing_key

    def append(
        self,
        *,
        ts_ms: int,
        event_kind: EventKind,
        decision: DecisionKind,
        span_id: str,
        node_id: Optional[str] = None,
        model_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        input_hash: Optional[str] = None,
        output_hash: Optional[str] = None,
        raw_provider_hash: Optional[str] = None,
        usage_json: Optional[Dict[str, Any]] = None,
        confidence: Optional[float] = None,
        meta_json: Optional[Dict[str, Any]] = None,
    ) -> AuditReceipt:
        run_seq = len(self._receipts) + 1
        prev_hash = GENESIS_HASH if run_seq == 1 else self._receipts[-1].event_hash

        draft = AuditReceipt(
            run_id=self.run_id,
            run_seq=run_seq,
            ts_ms=ts_ms,
            event_kind=event_kind,
            node_id=node_id,
            decision=decision,
            model_id=model_id,
            catalog_version=self.catalog_version,
            trace_id=self.trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            input_hash=input_hash,
            output_hash=output_hash,
            raw_provider_hash=raw_provider_hash,
            usage_json=usage_json,
            confidence=confidence,
            meta_json=meta_json or {},
            prev_event_hash=prev_hash,
            event_hash="pending",
            key_id=self.signing_key.key_id,
            signature="pending",
        )
        computed_hash = draft.compute_expected_hash()
        draft.event_hash = computed_hash
        draft.signature = self.signing_key.sign_bytes(computed_hash.encode("utf-8"))
        self._receipts.append(draft)
        return draft


def verify_run_chain(
    receipts: Sequence[AuditReceipt],
    public_keys: Dict[str, Ed25519PublicKey],
    expected_final_seq: Optional[int] = None,
    anchored_head_hash: Optional[str] = None,
) -> ChainVerificationResult:
    """Verify an ordered list of AuditReceipts offline against published Ed25519 public keys."""
    if not receipts:
        return ChainVerificationResult(valid=True, checked_count=0)

    expected_prev_hash = GENESIS_HASH
    run_id = receipts[0].run_id

    for idx, receipt in enumerate(receipts, start=1):
        if receipt.run_id != run_id:
            return ChainVerificationResult(
                valid=False,
                checked_count=idx - 1,
                broken_at_run_seq=receipt.run_seq,
                reason=f"Mismatched run_id '{receipt.run_id}' (expected '{run_id}').",
            )
        if receipt.run_seq != idx:
            return ChainVerificationResult(
                valid=False,
                checked_count=idx - 1,
                broken_at_run_seq=idx,
                reason=f"Sequence gap detected: expected run_seq={idx}, found run_seq={receipt.run_seq}.",
            )
        if receipt.prev_event_hash != expected_prev_hash:
            return ChainVerificationResult(
                valid=False,
                checked_count=idx - 1,
                broken_at_run_seq=idx,
                reason=(
                    f"Broken hash chain at run_seq={idx}: prev_event_hash='{receipt.prev_event_hash}' "
                    f"does not match prior event_hash='{expected_prev_hash}'."
                ),
            )
        recomputed_hash = receipt.compute_expected_hash()
        if receipt.event_hash != recomputed_hash:
            return ChainVerificationResult(
                valid=False,
                checked_count=idx - 1,
                broken_at_run_seq=idx,
                reason=f"Payload tampered at run_seq={idx}: recomputed hash '{recomputed_hash}' != '{receipt.event_hash}'.",
            )
        pub_key = public_keys.get(receipt.key_id)
        if pub_key is None:
            return ChainVerificationResult(
                valid=False,
                checked_count=idx - 1,
                broken_at_run_seq=idx,
                reason=f"Unknown signing key_id '{receipt.key_id}' at run_seq={idx}.",
            )
        if not SigningKeyPair.verify_bytes(pub_key, receipt.event_hash.encode("utf-8"), receipt.signature):
            return ChainVerificationResult(
                valid=False,
                checked_count=idx - 1,
                broken_at_run_seq=idx,
                reason=f"Invalid Ed25519 signature at run_seq={idx} under key_id '{receipt.key_id}'.",
            )
        expected_prev_hash = receipt.event_hash

    if expected_final_seq is not None and len(receipts) != expected_final_seq:
        return ChainVerificationResult(
            valid=False,
            checked_count=len(receipts),
            broken_at_run_seq=len(receipts),
            reason=(
                f"Tail truncation detected: chain has {len(receipts)} receipts, "
                f"but anchored final_run_seq is {expected_final_seq}."
            ),
        )

    if anchored_head_hash is not None and receipts[-1].event_hash != anchored_head_hash:
        return ChainVerificationResult(
            valid=False,
            checked_count=len(receipts),
            broken_at_run_seq=len(receipts),
            reason=(
                f"Chain head mismatch against WORM anchor: head '{receipts[-1].event_hash}' "
                f"!= anchored '{anchored_head_hash}'."
            ),
        )

    return ChainVerificationResult(valid=True, checked_count=len(receipts))

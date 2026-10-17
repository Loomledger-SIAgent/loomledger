"""Cryptographic audit primitives: RFC 8785 (JCS) canonical JSON, SHA-256 blobs, and Ed25519 signing."""

from __future__ import annotations

import base64
from decimal import Decimal
import hashlib
import json
import math
from typing import Any, Dict, Optional
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import Field

from loomledger._compat import CompatModel


def _jcs_serialize_value(val: Any) -> str:
    """Serialize a Python value into RFC 8785 (JSON Canonicalization Scheme) string form."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, Decimal):
        # Preserve exact normalized decimal representation as string or number per schema
        normalized = val.normalize()
        return json.dumps(str(normalized), ensure_ascii=False)
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            raise ValueError("RFC 8785 does not permit NaN or Infinity in canonical JSON.")
        if val == 0.0:
            return "0"
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, str):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, (list, tuple)):
        return "[" + ",".join(_jcs_serialize_value(item) for item in val) + "]"
    if isinstance(val, dict):
        # Sort keys lexicographically by UTF-16 / Unicode code point order
        sorted_items = sorted(val.items(), key=lambda kv: str(kv[0]))
        parts = [
            f"{json.dumps(str(k), ensure_ascii=False)}:{_jcs_serialize_value(v)}"
            for k, v in sorted_items
        ]
        return "{" + ",".join(parts) + "}"
    if hasattr(val, "to_dict"):
        return _jcs_serialize_value(val.to_dict())
    raise TypeError(f"Unsupported type for RFC 8785 canonicalization: {type(val)!r}")


def canonicalize_jcs(obj: Any) -> bytes:
    """Return deterministic UTF-8 bytes formatted according to RFC 8785 (JCS)."""
    return _jcs_serialize_value(obj).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_payload(obj: Any) -> str:
    """Return a content-addressed SHA-256 digest ('sha256:<hex>') over the RFC 8785 canonical payload."""
    return f"sha256:{sha256_hex(canonicalize_jcs(obj))}"


class SigningKeyPair:
    """Ed25519 signing and verification keypair tagged with an explicit key_id for rotation."""

    def __init__(self, key_id: str, private_key: Ed25519PrivateKey) -> None:
        if not key_id or not key_id.strip():
            raise ValueError("key_id must be a non-empty string.")
        self.key_id = key_id
        self._private_key = private_key
        self._public_key = private_key.public_key()

    @classmethod
    def generate(cls, key_id: str) -> "SigningKeyPair":
        return cls(key_id=key_id, private_key=Ed25519PrivateKey.generate())

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._public_key

    def public_key_bytes(self) -> bytes:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def sign_bytes(self, data: bytes) -> str:
        sig = self._private_key.sign(data)
        return base64.b64encode(sig).decode("ascii")

    @staticmethod
    def verify_bytes(public_key: Ed25519PublicKey, data: bytes, signature_b64: str) -> bool:
        try:
            sig = base64.b64decode(signature_b64.encode("ascii"), validate=True)
            public_key.verify(sig, data)
            return True
        except (InvalidSignature, ValueError):
            return False


class PayloadBlob(CompatModel):
    """Content-addressed payload record matching the payload_blobs PostgreSQL table."""

    blob_hash: str
    created_at_ms: int = Field(..., gt=0)
    redaction_policy: str = "default_v1"
    content_json: Optional[Dict[str, Any]] = None
    purged_at_ms: Optional[int] = None


class PayloadBlobStore:
    """Content-addressed blob store demonstrating privacy-safe erasure without breaking audit hashes."""

    def __init__(self) -> None:
        self._blobs: Dict[str, PayloadBlob] = {}

    def put(
        self,
        payload: Dict[str, Any],
        created_at_ms: int,
        redaction_policy: str = "default_v1",
    ) -> str:
        digest = hash_payload(payload)
        if digest not in self._blobs:
            self._blobs[digest] = PayloadBlob(
                blob_hash=digest,
                created_at_ms=created_at_ms,
                redaction_policy=redaction_policy,
                content_json=payload,
            )
        return digest

    def get(self, blob_hash: str) -> Optional[PayloadBlob]:
        return self._blobs.get(blob_hash)

    def purge(self, blob_hash: str, purged_at_ms: int) -> bool:
        """Purge sensitive content under retention/GDPR while keeping the blob tombstone."""
        blob = self._blobs.get(blob_hash)
        if blob is None:
            return False
        blob.content_json = None
        blob.purged_at_ms = purged_at_ms
        return True

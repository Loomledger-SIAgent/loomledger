import copy
import unittest

from loomledger.audit import (
    AuditChainBuilder,
    PayloadBlobStore,
    SigningKeyPair,
    canonicalize_jcs,
    hash_payload,
    verify_run_chain,
)


class TestCryptoAndReceipts(unittest.TestCase):
    def test_rfc8785_jcs_canonicalization_is_key_order_independent(self) -> None:
        obj_a = {"b": 2, "a": {"z": True, "y": [3, 2, 1], "x": None}}
        obj_b = {"a": {"x": None, "y": [3, 2, 1], "z": True}, "b": 2}
        self.assertEqual(canonicalize_jcs(obj_a), canonicalize_jcs(obj_b))
        self.assertEqual(
            canonicalize_jcs(obj_a),
            b'{"a":{"x":null,"y":[3,2,1],"z":true},"b":2}',
        )
        self.assertEqual(hash_payload(obj_a), hash_payload(obj_b))

    def test_hash_chain_and_key_rotation_verification(self) -> None:
        key_v1 = SigningKeyPair.generate("k1_2026-10_ed25519")
        key_v2 = SigningKeyPair.generate("k2_2026-10_ed25519")
        public_keys = {
            key_v1.key_id: key_v1.public_key,
            key_v2.key_id: key_v2.public_key,
        }

        blobs = PayloadBlobStore()
        in_hash = blobs.put({"claim_id": "CLM-99", "ssn_redacted": "***-**-1234"}, created_at_ms=1000)
        out_hash = blobs.put({"choice": "high", "confidence": 0.94}, created_at_ms=1050)

        builder = AuditChainBuilder(
            run_id="run-1234",
            catalog_version="2026.10.17.1",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            signing_key=key_v1,
        )
        builder.append(
            ts_ms=1000,
            event_kind="run_start",
            decision="ALLOW",
            span_id="00f067aa0ba902b7",
        )
        builder.append(
            ts_ms=1050,
            event_kind="model_call",
            node_id="claim-classifier",
            decision="ALLOW",
            model_id="openrouter_decisions/typesafe/jev-1.14@1.14",
            span_id="11f067aa0ba902b8",
            parent_span_id="00f067aa0ba902b7",
            input_hash=in_hash,
            output_hash=out_hash,
            confidence=0.94,
        )
        # Rotate signing key mid-run before recording a denied destructive tool call
        builder.rotate_key(key_v2)
        builder.append(
            ts_ms=1100,
            event_kind="policy_gate",
            node_id="senior-adjuster-agent",
            decision="DENY",
            span_id="22f067aa0ba902b9",
            parent_span_id="00f067aa0ba902b7",
            meta_json={"tool": "delete_customer_table", "reason": "destructive_tool_blocked"},
        )
        head = builder.append(
            ts_ms=1150,
            event_kind="run_end",
            decision="ALLOW",
            span_id="00f067aa0ba902b7",
        )

        # 1. Clean chain verifies
        res = verify_run_chain(
            builder.receipts,
            public_keys=public_keys,
            expected_final_seq=4,
            anchored_head_hash=head.event_hash,
        )
        self.assertTrue(res.valid)
        self.assertEqual(res.checked_count, 4)

        # 2. Purging sensitive PII blob for GDPR/retention does NOT break the hash chain
        self.assertTrue(blobs.purge(in_hash, purged_at_ms=2000))
        self.assertIsNone(blobs.get(in_hash).content_json)
        res_after_purge = verify_run_chain(builder.receipts, public_keys=public_keys)
        self.assertTrue(res_after_purge.valid)

        # 3. Flipping DENY -> ALLOW is caught immediately
        tampered_decision = copy.deepcopy(builder.receipts)
        tampered_decision[2].decision = "ALLOW"
        res_tampered = verify_run_chain(tampered_decision, public_keys=public_keys)
        self.assertFalse(res_tampered.valid)
        self.assertEqual(res_tampered.broken_at_run_seq, 3)
        self.assertIn("Payload tampered", res_tampered.reason)

        # 4. Deleting a denied record leaves a missing run_seq gap
        deleted_deny = [r for r in builder.receipts if r.run_seq != 3]
        res_deleted = verify_run_chain(deleted_deny, public_keys=public_keys)
        self.assertFalse(res_deleted.valid)
        self.assertEqual(res_deleted.broken_at_run_seq, 3)
        self.assertIn("Sequence gap detected", res_deleted.reason)

        # 5. Dropping the tail record is caught by the WORM anchor check
        truncated_tail = builder.receipts[:-1]
        res_truncated = verify_run_chain(
            truncated_tail,
            public_keys=public_keys,
            expected_final_seq=4,
            anchored_head_hash=head.event_hash,
        )
        self.assertFalse(res_truncated.valid)
        self.assertIn("Tail truncation detected", res_truncated.reason)


if __name__ == "__main__":
    unittest.main()

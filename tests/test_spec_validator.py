import unittest

from loomledger.catalog import ModelCatalog
from loomledger.specs import GraphSpec, SpecValidator


VALID_WORKFLOW_YAML = """
id: claims-triage-workflow
version: "1.0.0"
description: "Triage incoming claims with Jev 1.14 and escalate high-risk cases to a Claude agent."
budget_max_tokens: 50000
budget_max_cost_usd: "0.50"
nodes:
  - id: claim-classifier
    kind: decide
    role: "Classify claim risk and check photo evidence"
    model:
      provider: openrouter_decisions
      name: typesafe/jev-1.14
      version: "1.14"
      secret_ref: "secret://providers/openrouter"
      fallback:
        provider: ollama
        name: qwen3.6-27b
        version: "27b-q4_K_M"
    questions:
      is_damaged:
        type: noul
        instructions: "Does the claim photo show vehicle damage?"
      damage_box:
        type: box
        instructions: "the damaged bumper area in the photo"
      risk_tier:
        type: choice
        instructions: "Classify the claim risk tier"
        criteria:
          low: "Standard minor repair"
          high: "Complex structural or fraud-flagged claim"
          other: "Insufficient evidence"
    inputs:
      schema_name: ClaimSubmission
      fields:
        claim_text: str
    outputs:
      schema_name: TriageDecision
      fields:
        risk_tier: str

  - id: senior-adjuster-agent
    kind: agent
    role: "Investigate escalated claims using policy lookup tools"
    model:
      provider: anthropic
      name: claude-3-7-sonnet
      version: "20250219"
      secret_ref: "secret://providers/anthropic"
    limits:
      max_tokens: 8000
      max_steps: 5
      allowed_tools: ["lookup_policy", "verify_coverage"]
      require_human_approval_for: ["issue_payout"]
    inputs:
      schema_name: TriageDecision
      fields:
        risk_tier: str
    outputs:
      schema_name: AdjusterReport
      fields:
        summary: str

edges:
  - source: claim-classifier
    target: senior-adjuster-agent
    condition:
      question_key: risk_tier
      expected_choice: high
      min_confidence: 0.80
"""


class TestSpecValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = ModelCatalog.load_default()
        self.validator = SpecValidator(self.catalog)

    def test_valid_workflow_passes_validation(self) -> None:
        graph = GraphSpec.from_yaml(VALID_WORKFLOW_YAML)
        report = self.validator.validate_graph(graph)
        self.assertTrue(report.valid, msg=f"Unexpected errors: {report.errors}")
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])

    def test_rejects_raw_api_key_in_secret_ref(self) -> None:
        bad_yaml = VALID_WORKFLOW_YAML.replace("secret://providers/openrouter", "sk-or-v1-raw-key-12345")
        with self.assertRaises(ValueError):
            GraphSpec.from_yaml(bad_yaml)

    def test_rejects_box_primitive_on_jev_1_13(self) -> None:
        # Jev 1.13 does not support 'box' (returns HTTP 400 in production)
        bad_yaml = (
            VALID_WORKFLOW_YAML.replace("provider: openrouter_decisions", "provider: typesafe")
            .replace("name: typesafe/jev-1.14", "name: jev")
            .replace('version: "1.14"', 'version: "1.13.0"')
        )
        graph = GraphSpec.from_yaml(bad_yaml)
        report = self.validator.validate_graph(graph)
        self.assertFalse(report.valid)
        self.assertTrue(any("primitive 'box'" in err for err in report.errors))

    def test_warns_when_box_used_without_noul_presence_question(self) -> None:
        graph = GraphSpec.from_yaml(VALID_WORKFLOW_YAML)
        # Remove the 'is_damaged' noul question so 'damage_box' is unpaired
        del graph.nodes[0].questions["is_damaged"]
        report = self.validator.validate_graph(graph)
        self.assertTrue(report.valid)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("without a paired 'noul' presence question", report.warnings[0])

    def test_warns_when_state_exceeds_32kb_fast_mode(self) -> None:
        graph = GraphSpec.from_yaml(VALID_WORKFLOW_YAML)
        graph.nodes[0].estimated_state_bytes = 45_000
        report = self.validator.validate_graph(graph)
        self.assertTrue(report.valid)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("long-context mode", report.warnings[0])

    def test_detects_port_schema_mismatch(self) -> None:
        bad_yaml = VALID_WORKFLOW_YAML.replace(
            "schema_name: TriageDecision\n      fields:\n        risk_tier: str\n    outputs:\n      schema_name: AdjusterReport",
            "schema_name: WrongInputSchema\n      fields:\n        risk_tier: str\n    outputs:\n      schema_name: AdjusterReport",
        )
        graph = GraphSpec.from_yaml(bad_yaml)
        report = self.validator.validate_graph(graph)
        self.assertFalse(report.valid)
        self.assertTrue(any("Port type mismatch" in err for err in report.errors))


if __name__ == "__main__":
    unittest.main()

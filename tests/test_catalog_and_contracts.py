from decimal import Decimal
import unittest

from loomledger.catalog import ModelCatalog
from loomledger.models import (
    BoundingBox,
    BoxAnswer,
    BoxQuestion,
    ChoiceQuestion,
    DecideRequest,
    DecideResponse,
    ModelId,
    NoulAnswer,
    NoulQuestion,
    ScoreQuestion,
    Usage,
)


class TestCatalogAndContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = ModelCatalog.load_default()

    def test_catalog_loads_jev_1_14_and_capabilities(self) -> None:
        jev = self.catalog.require("openrouter_decisions", "typesafe/jev-1.14", "1.14")
        self.assertIn("decide", jev.capabilities.kinds)
        self.assertEqual(
            jev.capabilities.decision_primitives,
            {"noul", "choice", "score", "box"},
        )
        self.assertTrue(jev.capabilities.vision)
        self.assertEqual(jev.capabilities.default_context, 8192)
        self.assertEqual(jev.capabilities.max_context, 262144)

    def test_cost_calculation_for_jev_and_claude(self) -> None:
        # Jev 1.14: $0.042 / 1M input, $0 / 1M output
        jev_usage = Usage(input_tokens=500_000, output_tokens=200)
        jev_cost = self.catalog.compute_cost_usd(
            "openrouter_decisions", "typesafe/jev-1.14", "1.14", jev_usage
        )
        self.assertEqual(jev_cost, Decimal("0.02100000"))

        # Claude 3.7 Sonnet with cached input tokens and reasoning tokens
        claude_usage = Usage(
            input_tokens=10_000,
            cached_tokens=4_000,
            output_tokens=1_000,
            reasoning_tokens=500,
        )
        claude_cost = self.catalog.compute_cost_usd(
            "anthropic", "claude-3-7-sonnet", "20250219", claude_usage
        )
        # 6,000 uncached * $3/1M ($0.018) + 4,000 cached * $0.30/1M ($0.0012) + 1,500 out * $15/1M ($0.0225) = $0.0417
        self.assertEqual(claude_cost, Decimal("0.04170000"))

    def test_rejects_moving_version_aliases(self) -> None:
        for bad_version in ("latest", "jev-latest", "~typesafe/jev-latest", "v1-latest"):
            with self.assertRaises(ValueError):
                ModelId(provider="typesafe", name="jev", version=bad_version)

    def test_decide_request_and_response_primitives(self) -> None:
        req = DecideRequest(
            state=["Listing photo:", {"type": "image_url", "image_url": "data:image/png;base64,AAA"}],
            questions={
                "has_bicycle": NoulQuestion(instructions="Is a bicycle visible in the photo?"),
                "category": ChoiceQuestion(
                    instructions="Which category fits?",
                    criteria={"bikes": "Complete bicycles", "parts": "Parts"},
                ),
                "wear": ScoreQuestion(
                    instructions="How worn is the frame?",
                    criteria=["Like new", "Light wear", "Heavy wear"],
                ),
                "target_box": BoxQuestion(instructions="the bicycle frame in the photo"),
            },
        )
        self.assertEqual(len(req.questions), 4)

        resp = DecideResponse(
            model_id=ModelId(provider="openrouter_decisions", name="typesafe/jev-1.14", version="1.14"),
            answers={
                "has_bicycle": NoulAnswer(noul=0.96, confidence=0.95),
                "target_box": BoxAnswer(
                    box=BoundingBox(top=0.12, bottom=0.88, left=0.15, right=0.91),
                    confidence=0.92,
                ),
            },
        )
        self.assertAlmostEqual(resp.answers["has_bicycle"].noul, 0.96)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path

from core.ai_provider import ProviderResult
from core.semantic_judge import (
    SemanticJudgeError,
    build_judge_messages,
    load_judge_bundle,
    parse_judge_output,
    run_semantic_judge,
)


ROOT = Path(__file__).resolve().parent.parent
BUNDLE_PATH = ROOT / "benchmarks" / "judges" / "deal_room_semantic_judges.v1.json"


class FakeProvider:
    def complete(self, messages, temperature=1):
        self.messages = messages
        self.temperature = temperature
        return ProviderResult(
            provider_id="local_bonsai",
            model="27b@q1_0",
            content=json.dumps({"label": "fail", "rationale": "The answer omits financing.", "evidence": ["debt.md#term-loan"]}),
            latency_ms=12,
            usage={"input_tokens": 20, "output_tokens": 10},
        )


class SemanticJudgeTests(unittest.TestCase):
    def test_bundle_and_prompt_hide_route_identity(self):
        bundle = load_judge_bundle(BUNDLE_PATH)
        messages, metadata = build_judge_messages(
            bundle,
            "material_omission",
            task="Identify financing risks.",
            evidence_packet="Term loan matures in 2028.",
            answer="No financing risks found.",
        )
        material = json.dumps(messages)
        self.assertNotIn("route_mode", material)
        self.assertNotIn("answer_model", material)
        self.assertFalse(metadata["trusted_for_release"])

    def test_parser_rejects_extra_keys_and_nonbinary_labels(self):
        with self.assertRaises(SemanticJudgeError):
            parse_judge_output('{"label":"maybe","rationale":"x","evidence":[],"score":0.7}')

    def test_candidate_runner_never_claims_release_trust(self):
        result = run_semantic_judge(
            FakeProvider(),
            load_judge_bundle(BUNDLE_PATH),
            "material_omission",
            task="Identify financing risks.",
            evidence_packet="Term loan matures in 2028.",
            answer="No financing risks found.",
        )
        self.assertEqual(result["label"], "fail")
        self.assertEqual(result["judge_model"], "27b@q1_0")
        self.assertFalse(result["trusted_for_release"])


if __name__ == "__main__":
    unittest.main()

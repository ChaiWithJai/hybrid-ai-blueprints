import json
import unittest
from pathlib import Path

from core.workspace_eval import evaluate_generation, evaluate_workflow, score_retrieval


ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "benchmarks/workspace_eval_v1.json").read_text(encoding="utf-8"))


class WorkspaceEvalTests(unittest.TestCase):
    def test_retrieval_negative_control_lowers_recall(self):
        case = CONFIG["rag_cases"][0]
        result = score_retrieval(case, ["[wrong.md#node:wrong]"])
        self.assertEqual(result["recall_at_k"], 0.0)
        self.assertFalse(result["passed"])

    def test_wrong_number_fails_faithfulness(self):
        case = CONFIG["generation_cases"][0]
        record = json.loads((ROOT / case["evidence_file"]).read_text(encoding="utf-8"))
        answer = next(
            item["observed"] for item in record["assertions"]
            if item["name"] == case["response_assertion"]
        ).replace("$900.0", "$990.0", 1)
        result = evaluate_generation(ROOT, ROOT / CONFIG["folder"], case, answer)
        self.assertFalse(result["faithfulness"]["passed"])

    def test_missing_component_fails_relevance(self):
        case = CONFIG["generation_cases"][0]
        record = json.loads((ROOT / case["evidence_file"]).read_text(encoding="utf-8"))
        answer = next(
            item["observed"] for item in record["assertions"]
            if item["name"] == case["response_assertion"]
        ).replace("Subordinated Mezzanine Debt", "Unidentified tranche", 1)
        result = evaluate_generation(ROOT, ROOT / CONFIG["folder"], case, answer)
        self.assertFalse(result["answer_relevance"]["passed"])

    def test_missing_workflow_checkpoint_localizes_first_failure(self):
        workflow = {
            "id": "negative_control",
            "description": "A deliberately missing transition.",
            "evidence_file": "evidence/browser-titan-debt-chat-v1.json",
            "transitions": [{"from": "retrieval", "to": "publication", "assertion": "does_not_exist"}],
        }
        result = evaluate_workflow(ROOT, workflow)
        self.assertFalse(result["passed"])
        self.assertEqual(result["first_failure"], "retrieval -> publication")


if __name__ == "__main__":
    unittest.main()

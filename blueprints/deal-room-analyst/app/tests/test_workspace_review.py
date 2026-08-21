import tempfile
import unittest
from pathlib import Path

from core.workspace_review import WorkspaceReviewStore, build_review_corpus


def _message(index, *, role="operator", content=None, acceptance_state=None):
    return {
        "id": f"record-{index:02d}",
        "pubkey": role,
        "created_at": index,
        "content": content or f"Room message {index}",
        "display_content": content or f"Room message {index}",
        "signature_verified": True,
        "prism_acceptance_state": acceptance_state,
    }


class WorkspaceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        messages = [
            _message(0, content="## First pass requested\nReview the deal."),
            _message(1, role="agent", content="Rejected", acceptance_state="quarantined_uncommitted"),
            _message(2, content="What is the disclosed debt?"),
            _message(3, role="agent", content="Accepted answer", acceptance_state="accepted"),
        ] + [_message(index) for index in range(4, 16)]
        corpus = build_review_corpus(messages, agent_key="agent", operator_key="operator")
        self.store = WorkspaceReviewStore(Path(self.temporary.name), "room_one", corpus)

    def tearDown(self):
        self.temporary.cleanup()

    def test_room_snapshot_is_canonical_and_contextual(self):
        snapshot = self.store.snapshot(phoenix={"live": False})
        self.assertEqual(snapshot["canonical_path"], "/rooms/room_one/evaluation")
        self.assertEqual(len(snapshot["samples"]), 10)
        self.assertTrue(all(sample["turns"] for sample in snapshot["samples"]))
        self.assertEqual(snapshot["session"]["reviewed_count"], 0)

    def test_record_upserts_do_not_erase_other_annotations(self):
        first, second = [sample["id"] for sample in self.store.samples()[:2]]
        self.store.upsert_annotation({
            "record_id": first,
            "label": "pass",
            "note": "",
            "reviewer": "reviewer one",
            "confirmed_modes": [],
        })
        self.store.upsert_annotation({
            "record_id": second,
            "label": "fail",
            "note": "Missing source boundary.",
            "reviewer": "reviewer two",
            "confirmed_modes": [],
        })
        annotations = self.store.annotations()
        self.assertEqual(set(annotations), {first, second})
        self.assertEqual(annotations[first]["label"], "pass")
        self.assertEqual(annotations[second]["label"], "fail")

    def test_depth_gate_and_observability_boundary(self):
        for index, sample in enumerate(self.store.samples()[:5]):
            self.store.upsert_annotation({
                "record_id": sample["id"],
                "label": "fail" if index == 1 else "pass",
                "note": "Fixture note" if index == 1 else "",
                "reviewer": "fixture reviewer",
                "confirmed_modes": [],
            })
        result = self.store.scan()
        snapshot = self.store.snapshot(phoenix={"live": True})
        observability = self.store.observability()
        self.assertGreaterEqual(result["added"], 0)
        self.assertEqual(snapshot["session"]["phase"], "depth")
        self.assertFalse(snapshot["session"]["saturation"]["claimed"])
        self.assertEqual(observability["room"], "room_one")
        self.assertEqual(len(snapshot["observability"]["records"]), 5)
        self.assertTrue(all(
            record["attributes"]["openinference.span.kind"] == "EVALUATOR"
            for record in snapshot["observability"]["records"]
        ))
        self.assertTrue(all(
            "input.value" not in record["attributes"]
            for record in snapshot["observability"]["records"]
        ))

    def test_room_ids_isolate_review_state(self):
        other = WorkspaceReviewStore(Path(self.temporary.name), "room_two", self.store.corpus)
        record_id = self.store.samples()[0]["id"]
        self.store.upsert_annotation({
            "record_id": record_id,
            "label": "pass",
            "note": "",
            "reviewer": "reviewer",
            "confirmed_modes": [],
        })
        self.assertEqual(len(self.store.annotations()), 1)
        self.assertEqual(other.annotations(), {})

    def test_breadth_sampling_adds_unsampled_room_traces(self):
        before = len(self.store.samples())
        result = self.store.add_breadth()
        self.assertEqual(len(result["added"]), 3)
        self.assertEqual(len(self.store.samples()), before + 3)


if __name__ == "__main__":
    unittest.main()

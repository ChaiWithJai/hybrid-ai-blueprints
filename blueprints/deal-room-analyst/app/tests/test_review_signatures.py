import json
import tempfile
import unittest
from pathlib import Path

from core.review_signatures import review_attestation_content
from scripts.render_review_attestation import render


class ReviewSignatureTests(unittest.TestCase):
    def test_renderer_matches_canonical_content_and_ignores_event_id(self):
        record = {
            "review_id": "review-one",
            "reviewer_id": "reviewer.one",
            "packet_sha256": "a" * 64,
            "reviewer_pubkey": "b" * 64,
            "buzz_event_id": "0" * 64,
            "drafts": [{"draft_id": "draft-one", "decision": "approve"}],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            rendered = render(path, "candidate_source_review")
        self.assertEqual(rendered, review_attestation_content("candidate_source_review", record))
        record["buzz_event_id"] = "f" * 64
        self.assertEqual(rendered, review_attestation_content("candidate_source_review", record))
        self.assertIn("PRISM_REVIEW_ATTESTATION_V1", rendered)
        self.assertIn("record_id=review-one", rendered)

    def test_renderer_rejects_an_unbound_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.json"
            path.write_text(json.dumps({"review_id": "review-one"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "actor ID"):
                render(path, "candidate_source_review")


if __name__ == "__main__":
    unittest.main()

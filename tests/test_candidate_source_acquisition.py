import json
import tempfile
import unittest
from pathlib import Path

from scripts.acquire_candidate_deal_source import (
    record_acquisition_in_registry,
    resolve_primary_document,
)


class CandidateSourceAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "cik": "0001463172",
            "accession": "0001140361-22-028748",
        }

    def test_resolves_exact_sec_primary_document(self):
        html = """
        <table><tr><td>1</td><td>DEFM14A</td>
        <td><a href="/Archives/edgar/data/1463172/000114036122028748/proxy.htm">proxy.htm</a></td>
        <td>DEFM14A</td></tr></table>
        """
        self.assertEqual(
            resolve_primary_document(html, self.candidate),
            "https://www.sec.gov/Archives/edgar/data/1463172/000114036122028748/proxy.htm",
        )

    def test_rejects_ambiguous_or_cross_accession_document(self):
        ambiguous = """
        <tr><td>DEFM14A</td><td><a href="/Archives/edgar/data/1463172/000114036122028748/a.htm">a</a>
        <a href="/Archives/edgar/data/1463172/000114036122028748/b.htm">b</a></td></tr>
        """
        with self.assertRaisesRegex(ValueError, "expected one"):
            resolve_primary_document(ambiguous, self.candidate)
        wrong = """
        <tr><td>DEFM14A</td><td><a href="/Archives/edgar/data/1463172/WRONG/proxy.htm">proxy</a></td></tr>
        """
        with self.assertRaisesRegex(ValueError, "does not match"):
            resolve_primary_document(wrong, self.candidate)

    def test_registry_update_is_hash_bound_and_cannot_claim_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry_path = root / "registry.json"
            evidence_path = root / "evidence" / "candidate-source-test.json"
            evidence_path.parent.mkdir()
            registry_path.write_text(json.dumps({
                "candidates": [{
                    "id": "test",
                    "state": "source_index_identified_not_acquired",
                }],
            }), encoding="utf-8")
            evidence_path.write_text(json.dumps({
                "candidate_id": "test",
                "benchmark_case_registered": False,
                "domain_review_status": "not_reviewed",
                "parser": {"passed": True},
            }), encoding="utf-8")
            digest = record_acquisition_in_registry(
                registry_path, evidence_path, "test", project_root=root,
            )
            updated = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["candidates"][0]["state"],
                "acquired_parser_verified_not_registered",
            )
            self.assertEqual(updated["candidates"][0]["evidence_sha256"], digest)

            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["domain_review_status"] = "approved"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot claim domain review"):
                record_acquisition_in_registry(
                    registry_path, evidence_path, "test", project_root=root,
                )


if __name__ == "__main__":
    unittest.main()

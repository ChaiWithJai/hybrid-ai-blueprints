import unittest

from scripts.acquire_candidate_companion_sources import validate_primary_url


class CandidateCompanionAcquisitionTests(unittest.TestCase):
    def companion(self):
        return {
            "candidate_id": "target_2024",
            "cik": "0000001234",
            "accession": "0000000001-24-000002",
            "primary_document": "quarter.htm",
            "primary_url": "https://www.sec.gov/Archives/edgar/data/1234/000000000124000002/quarter.htm",
        }

    def test_exact_sec_archive_path_is_accepted(self):
        self.assertIsNone(validate_primary_url(self.companion()))

    def test_cross_accession_host_and_query_are_rejected(self):
        for url in (
            "https://www.sec.gov/Archives/edgar/data/1234/other/quarter.htm",
            "https://example.com/Archives/edgar/data/1234/000000000124000002/quarter.htm",
            "https://www.sec.gov/Archives/edgar/data/1234/000000000124000002/quarter.htm?x=1",
        ):
            companion = self.companion()
            companion["primary_url"] = url
            with self.assertRaisesRegex(ValueError, "outside its exact SEC filing path"):
                validate_primary_url(companion)

    def test_path_traversal_document_is_rejected(self):
        companion = self.companion()
        companion["primary_document"] = "../quarter.htm"
        with self.assertRaisesRegex(ValueError, "primary document is invalid"):
            validate_primary_url(companion)


if __name__ == "__main__":
    unittest.main()

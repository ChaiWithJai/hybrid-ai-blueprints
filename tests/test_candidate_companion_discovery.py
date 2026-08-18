import unittest

from scripts.discover_candidate_companion_sources import filing_rows, select_companion


class CandidateCompanionDiscoveryTests(unittest.TestCase):
    def candidate(self):
        return {
            "id": "target_2024",
            "company": "Target, Inc.",
            "cik": "0000001234",
            "accession": "0000000001-24-000010",
            "filing_date": "2024-05-15",
        }

    def payload(self, rows):
        keys = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
        return {"filings": {"recent": {
            key: [row[key] for row in rows] for key in keys
        }}}

    def test_latest_financial_filing_before_proxy_is_selected(self):
        rows = [
            {"accessionNumber": "0000000001-24-000001", "filingDate": "2024-02-01", "reportDate": "2023-12-31", "form": "10-K", "primaryDocument": "annual.htm"},
            {"accessionNumber": "0000000001-24-000002", "filingDate": "2024-05-01", "reportDate": "2024-03-31", "form": "10-Q", "primaryDocument": "quarter.htm"},
            {"accessionNumber": "0000000001-24-000003", "filingDate": "2024-05-20", "reportDate": "2024-03-31", "form": "10-Q", "primaryDocument": "too_late.htm"},
            {"accessionNumber": "0000000001-24-000004", "filingDate": "2024-05-10", "reportDate": "", "form": "8-K", "primaryDocument": "current.htm"},
        ]
        selected = select_companion(self.candidate(), [self.payload(rows)])
        self.assertEqual(selected["form"], "10-Q")
        self.assertEqual(selected["accession"], "0000000001-24-000002")
        self.assertEqual(
            selected["primary_url"],
            "https://www.sec.gov/Archives/edgar/data/1234/000000000124000002/quarter.htm",
        )
        self.assertFalse(selected["benchmark_case_registered"])
        self.assertEqual(selected["domain_review_status"], "not_reviewed")

    def test_malformed_rows_and_post_proxy_filings_are_rejected(self):
        rows = [
            {"accessionNumber": "bad", "filingDate": "2024-05-01", "reportDate": "2024-03-31", "form": "10-Q", "primaryDocument": "quarter.htm"},
            {"accessionNumber": "0000000001-24-000003", "filingDate": "2024-05-20", "reportDate": "2024-03-31", "form": "10-Q", "primaryDocument": "too_late.htm"},
            {"accessionNumber": "0000000001-24-000005", "filingDate": "2024-05-01", "reportDate": "2024-03-31", "form": "10-Q", "primaryDocument": "../escape.htm"},
        ]
        self.assertIsNone(select_companion(self.candidate(), [self.payload(rows)]))

    def test_misaligned_sec_columns_fail_closed(self):
        payload = self.payload([])
        payload["filings"]["recent"]["form"] = ["10-K"]
        with self.assertRaisesRegex(ValueError, "different lengths"):
            filing_rows(payload)


if __name__ == "__main__":
    unittest.main()

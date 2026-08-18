import json
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.verify_public_deal_corpus import verify_pdf_renders


ROOT = Path(__file__).resolve().parents[1]


def write_minimal_pdf(path: Path) -> None:
    stream = b"0 0 0 rg 10 10 80 80 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(payload)


class PublicDealCorpusVerificationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm is required")
    def test_pdf_render_check_runs_a_renderer_without_claiming_visual_quality(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "one-page.pdf"
            write_minimal_pdf(source)
            source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            result = verify_pdf_renders(source, [1])
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["source_sha256"], source_sha256)
        self.assertGreater(result["pages"][0]["width_pixels"], 0)
        self.assertGreater(result["pages"][0]["height_pixels"], 0)
        self.assertIn("does not measure legibility", result["meaning"])

    def test_saved_corpus_evidence_does_not_claim_an_unrecorded_human_review(self):
        report = json.loads(
            (ROOT / "evidence" / "public-deal-corpus-verification-v2.json").read_text()
        )
        review = report["pdf_visual_review"]
        self.assertIsNone(review["passed"])
        self.assertEqual(review["state"], "not_recorded")
        self.assertIsNone(review["reviewer"])
        self.assertIsNone(review["receipt"])
        self.assertTrue(report["automated_pdf_render_check"]["passed"])

    def test_legacy_visual_claim_corrections_match_current_bytes(self):
        correction = json.loads(
            (ROOT / "evidence" / "public-pdf-visual-claim-remediation-v1.json").read_text()
        )
        active_path = ROOT / correction["correction"]["active_evidence"]
        self.assertEqual(
            hashlib.sha256(active_path.read_bytes()).hexdigest(),
            correction["correction"]["active_evidence_sha256"],
        )
        for item in correction["corrected_records"]:
            path = ROOT / item["path"]
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                item["corrected_sha256"],
            )
            report = json.loads(path.read_text())
            review = report["pdf_visual_review"]
            self.assertEqual(review["state"], "superseded_unsubstantiated_claim")
            self.assertIsNone(review["passed"])
            self.assertIsNone(review["reviewer"])
            self.assertIsNone(review["receipt"])
            self.assertNotIn("Human-visible PNG renders were checked", path.read_text())

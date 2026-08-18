import hashlib
import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_ROOT = ROOT / "docs" / "assets" / "screenshots"


class DocumentationAssetTests(unittest.TestCase):
    def test_demo_screenshot_manifest_is_complete_and_content_bound(self):
        manifest = json.loads((SCREENSHOT_ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["schema_version"], "1.0")
        self.assertEqual(manifest["fixture_class"], "synthetic_demo")
        self.assertEqual(
            {item["id"] for item in manifest["screenshots"]},
            {
                "deal_room_overview",
                "cited_source_evidence",
                "source_inventory",
                "team_activity",
                "evaluation_review_queue",
                "evaluation_lab",
            },
        )

        for item in manifest["screenshots"]:
            path = (SCREENSHOT_ROOT / item["path"]).resolve()
            path.relative_to(SCREENSHOT_ROOT.resolve())
            payload = path.read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])
            self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", payload[16:24])
            self.assertGreaterEqual(width, 1280)
            self.assertGreaterEqual(height, 720)

    def test_getting_started_guide_uses_every_manifest_screenshot(self):
        guide = (ROOT / "docs" / "demo" / "README.md").read_text()
        manifest = json.loads((SCREENSHOT_ROOT / "manifest.json").read_text())
        for item in manifest["screenshots"]:
            self.assertIn(item["path"], guide)

    def test_architecture_guide_contains_the_documented_views(self):
        guide = (ROOT / "docs" / "architecture" / "README.md").read_text()
        self.assertGreaterEqual(guide.count("```mermaid"), 5)
        for implementation_path in (
            "core/hybrid_router.py",
            "core/ai_provider.py",
            "core/cloud_consent.py",
            "core/arize_evals.py",
            "scripts/export_eval_review_to_phoenix.py",
        ):
            self.assertIn(implementation_path, guide)


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


# Catalog resources (docs/, tooling/) live at the repository root, which is four
# levels above this application after the issue #2 migration. ROOT stays the
# application root so app-relative paths are unaffected.


REPO_ROOT = Path(__file__).resolve().parents[4]
SCREENSHOT_ROOT = REPO_ROOT / "docs" / "assets" / "screenshots"
CARELINE_SCREENSHOT_ROOT = SCREENSHOT_ROOT / "careline"


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
        guide = (REPO_ROOT / "docs" / "demo" / "README.md").read_text()
        manifest = json.loads((SCREENSHOT_ROOT / "manifest.json").read_text())
        for item in manifest["screenshots"]:
            self.assertIn(item["path"], guide)

    def test_careline_screenshot_manifest_is_complete_and_content_bound(self):
        """The voice blueprint keeps its own manifest, per ADR 0003.

        Held to the same contract as the deal room's: declared ids, hash-bound
        files, real PNGs, and a stated claim boundary. Regenerate with
        blueprints/careline-voice-checkin/app/scripts/capture_screenshots.mjs.
        """
        manifest = json.loads((CARELINE_SCREENSHOT_ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["schema_version"], "1.0")
        self.assertEqual(manifest["blueprint"], "careline-voice-checkin")
        self.assertEqual(manifest["fixture_class"], "synthetic_demo")
        self.assertIn("synthetic", manifest["claim_boundary"])
        self.assertEqual(
            {item["id"] for item in manifest["screenshots"]},
            {"careline_console"},
        )

        for item in manifest["screenshots"]:
            path = (CARELINE_SCREENSHOT_ROOT / item["path"]).resolve()
            path.relative_to(CARELINE_SCREENSHOT_ROOT.resolve())
            payload = path.read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])
            self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
            width, height = struct.unpack(">II", payload[16:24])
            self.assertGreaterEqual(width, 1280)
            self.assertGreaterEqual(height, 720)

    def test_careline_screenshot_is_used_and_names_no_operator(self):
        """The picture must be referenced, and must not show one person's name.

        The self-voice label is an operator setting served from /api/config. A
        captured screenshot naming an operator would be wrong for everyone who
        clones the repository, so the capture script refuses it and this test
        guards the committed file's description.
        """
        manifest = json.loads((CARELINE_SCREENSHOT_ROOT / "manifest.json").read_text())
        readme = (REPO_ROOT / "README.md").read_text()
        blueprint = (
            REPO_ROOT / "blueprints" / "careline-voice-checkin" / "README.md"
        ).read_text()
        for item in manifest["screenshots"]:
            self.assertIn(item["path"], readme)
            self.assertIn(item["path"], blueprint)
            self.assertNotIn("your cloned voice)", item["state"])

    def test_architecture_guide_contains_the_documented_views(self):
        guide = (REPO_ROOT / "docs" / "architecture" / "README.md").read_text()
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

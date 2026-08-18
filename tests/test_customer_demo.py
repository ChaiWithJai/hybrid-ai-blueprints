import json
import tempfile
import unittest
from pathlib import Path

from core.customer_demo import (
    validate_content_graph,
    validate_customer_demo_browser_record,
    validate_customer_demo_scope,
)


ROOT = Path(__file__).resolve().parent.parent


class CustomerDemoTests(unittest.TestCase):
    def test_current_scope_contract_passes(self):
        result = validate_customer_demo_scope(ROOT)
        self.assertTrue(result["passed"], result["errors"])

    def test_content_graph_defends_every_segment_and_phrase(self):
        result = validate_content_graph(ROOT)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["segment_count"], 16)
        self.assertGreaterEqual(result["copy_count"], 50)

    def test_content_graph_fails_when_copy_loses_its_defense(self):
        with tempfile.TemporaryDirectory() as folder:
            copied_root = Path(folder)
            (copied_root / "web").mkdir()
            graph = json.loads((ROOT / "web" / "content-graph.json").read_text(encoding="utf-8"))
            copy_node = next(node for node in graph["nodes"] if node["kind"] == "copy")
            copy_node["defense"] = ""
            (copied_root / "web" / "content-graph.json").write_text(json.dumps(graph), encoding="utf-8")
            (copied_root / "web" / "index.html").write_text((ROOT / "web" / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
            (copied_root / "web" / "app.js").write_text((ROOT / "web" / "app.js").read_text(encoding="utf-8"), encoding="utf-8")
            result = validate_content_graph(copied_root)
        self.assertFalse(result["passed"])
        self.assertTrue(any("copy has no text or defense" in item for item in result["errors"]))

    def test_browser_record_fails_when_asset_version_is_stale(self):
        canonical_path = ROOT / "evidence" / "browser-customer-demo-v1.json"
        if not canonical_path.exists():
            self.skipTest("fresh customer demo browser record has not been created")
        record = json.loads(canonical_path.read_text(encoding="utf-8"))
        record["asset_version"] = "demo-first-v1"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "stale.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            result = validate_customer_demo_browser_record(ROOT, path)
        self.assertFalse(result["passed"])
        self.assertTrue(any("asset version" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()

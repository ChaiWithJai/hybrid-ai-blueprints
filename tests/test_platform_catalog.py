import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tooling" / "catalog" / "validate_catalog.py"
SPEC = importlib.util.spec_from_file_location("catalog_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
catalog_validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog_validator)

LINK_VALIDATOR_PATH = ROOT / "tooling" / "documentation" / "validate_links.py"
LINK_SPEC = importlib.util.spec_from_file_location("link_validator", LINK_VALIDATOR_PATH)
assert LINK_SPEC and LINK_SPEC.loader
link_validator = importlib.util.module_from_spec(LINK_SPEC)
LINK_SPEC.loader.exec_module(link_validator)


class PlatformCatalogTests(unittest.TestCase):
    def test_catalog_and_local_references_are_valid(self):
        result = catalog_validator.validate()
        self.assertEqual(result["project"], "hybrid-ai-blueprints")
        self.assertEqual(
            result["use_cases"], ["deal-room-underwriting", "wellness-check-in-calls"]
        )
        self.assertEqual(
            result["blueprints"], ["careline-voice-checkin", "deal-room-analyst"]
        )

    def test_local_documentation_links_resolve(self):
        self.assertEqual(link_validator.validate(), [])

    def test_root_readme_names_the_project_and_steward(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("# Hybrid AI Blueprints", readme)
        self.assertIn("PrismML sponsors and stewards the project", readme)

    def test_observability_document_states_the_governance_boundary(self):
        document = (
            ROOT / "docs" / "concepts" / "observability-and-evaluation.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Native Computing Foundation project", document)
        self.assertIn("do not establish Linux Foundation governance", document)
        self.assertIn("OpenInference", document)
        self.assertIn("Arize Phoenix", document)


if __name__ == "__main__":
    unittest.main()

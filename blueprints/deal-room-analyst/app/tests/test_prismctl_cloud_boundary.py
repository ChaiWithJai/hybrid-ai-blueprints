import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PrismctlCloudBoundaryTests(unittest.TestCase):
    def cloud_environment(self, ledger: Path) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update({
            "PRISM_CLOUD_AI_URL": "https://cloud.invalid/v1",
            "PRISM_CLOUD_AI_MODEL": "cloud-test-model",
            "PRISM_CLOUD_CONSENT_LEDGER": str(ledger),
        })
        return environment

    def run_prismctl(self, *arguments: str, ledger: Path):
        return subprocess.run(
            [sys.executable, str(ROOT / "prismctl"), *arguments],
            cwd=ROOT,
            env=self.cloud_environment(ledger),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_cloud_agent_requires_consent_file_before_agent_or_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "uses.json"
            completed = self.run_prismctl(
                "agent", "--runtime", "cloud", "--deal-room", "project_titan_lbo",
                "Analyze EBITDA",
                ledger=ledger,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("--cloud-consent is required", completed.stderr + completed.stdout)
            self.assertFalse(ledger.exists())

    def test_cloud_folder_path_requires_stable_room_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "uses.json"
            completed = self.run_prismctl(
                "agent", "--runtime", "cloud",
                "--deal-room", str(ROOT / "deal_rooms" / "sample_ma_acquisition"),
                "--cloud-consent", str(Path(folder) / "missing.json"),
                "Analyze EBITDA",
                ledger=ledger,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "requires --cloud-room-id",
                completed.stderr + completed.stdout,
            )
            self.assertFalse(ledger.exists())

    def test_cloud_benchmark_requires_per_case_consent_map(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "uses.json"
            completed = self.run_prismctl(
                "benchmark", "--runtime", "cloud",
                ledger=ledger,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("--cloud-consents is required", completed.stderr + completed.stdout)
            self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()

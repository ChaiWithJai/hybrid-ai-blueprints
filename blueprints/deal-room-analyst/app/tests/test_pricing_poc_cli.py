import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PricingPocCliTests(unittest.TestCase):
    @staticmethod
    def unsigned_record():
        return {
            "schema_version": 1,
            "poc_id": "poc-cli-boundary",
            "buyer": {
                "buyer_id": "buyer-cli-boundary",
                "workflow_owner_role": "private_equity_vice_president",
                "economic_buyer_role": "private_equity_partner",
                "budget_authority_confirmed": True,
                "buyer_pubkey": "a" * 64,
            },
        }

    def test_authorization_renderer_emits_exact_signing_statement(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "unsigned.json"
            path.write_text(json.dumps(self.unsigned_record()), encoding="utf-8")
            completed = subprocess.run(
                [
                    "python3",
                    "scripts/render_pricing_buyer_authorization.py",
                    str(path.relative_to(ROOT)),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        rendered = json.loads(completed.stdout)
        self.assertEqual(rendered["authorization_kind"], "pricing_buyer_authorization_v1")
        self.assertIn("PRISM_PRICING_BUYER_AUTHORIZATION_V1", rendered["content"])
        self.assertIn("buyer_pubkey=" + "a" * 64, rendered["content"])

    def test_publisher_fails_before_buzz_when_authority_is_unconfigured(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "unsigned.json"
            output = Path(directory) / "final.json"
            path.write_text(json.dumps(self.unsigned_record()), encoding="utf-8")
            environment = os.environ.copy()
            for name in (
                "PRISM_PRICING_AUTHORITY_PUBKEY",
                "PRISM_PRICING_AUTHORITY_CHANNEL",
                "BUZZ_PRIVATE_KEY",
            ):
                environment.pop(name, None)
            completed = subprocess.run(
                [
                    "python3",
                    "scripts/publish_pricing_poc.py",
                    "--record",
                    str(path.relative_to(ROOT)),
                    "--buzz-channel",
                    "pricing-poc-channel",
                    "--buyer-authorization-event",
                    "0" * 64,
                    "--output",
                    str(output.relative_to(ROOT)),
                    "--confirm-record-buyer-evidence",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            output_exists = output.exists()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("PRISM_PRICING_AUTHORITY_PUBKEY", completed.stderr)
        self.assertFalse(output_exists)

    def test_authority_publisher_fails_before_buzz_when_authority_is_unconfigured(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "unsigned.json"
            path.write_text(json.dumps(self.unsigned_record()), encoding="utf-8")
            environment = os.environ.copy()
            for name in (
                "PRISM_PRICING_AUTHORITY_PUBKEY",
                "PRISM_PRICING_AUTHORITY_CHANNEL",
                "BUZZ_PRIVATE_KEY",
            ):
                environment.pop(name, None)
            completed = subprocess.run(
                [
                    "python3",
                    "scripts/publish_pricing_buyer_authorization.py",
                    "--record",
                    str(path.relative_to(ROOT)),
                    "--buzz-channel",
                    "pricing-poc-channel",
                    "--confirm-authorize-buyer",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("PRISM_PRICING_AUTHORITY_PUBKEY", completed.stderr)

    def test_authority_publisher_rejects_self_authorized_buyer_before_buzz(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "unsigned.json"
            path.write_text(json.dumps(self.unsigned_record()), encoding="utf-8")
            environment = os.environ.copy()
            environment.update({
                "PRISM_PRICING_AUTHORITY_PUBKEY": "a" * 64,
                "PRISM_PRICING_AUTHORITY_CHANNEL": "pricing-poc-channel",
            })
            environment.pop("BUZZ_PRIVATE_KEY", None)
            completed = subprocess.run(
                [
                    "python3",
                    "scripts/publish_pricing_buyer_authorization.py",
                    "--record",
                    str(path.relative_to(ROOT)),
                    "--buzz-channel",
                    "pricing-poc-channel",
                    "--confirm-authorize-buyer",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("keys must be distinct", completed.stderr)
        self.assertNotIn("Buzz publish failed", completed.stderr)


if __name__ == "__main__":
    unittest.main()

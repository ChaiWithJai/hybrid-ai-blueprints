import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.ai_provider import OpenAICompatibleProvider, ProviderRegistry
from core.cloud_consent import (
    CloudConsentAuthority,
    consume_cloud_consent,
    validate_cloud_consent,
)
from core.coding_agent import DealRoomWorkflowAgent
from tests.cloud_consent_fixtures import authority, relay_events, signed_bundle


ROOT = Path(__file__).resolve().parents[1]


class CloudConsentTests(unittest.TestCase):
    def agent(self, ledger: Path):
        registry = ProviderRegistry()
        registry.cloud = OpenAICompatibleProvider(
            "cloud_ai", "cloud", "https://approved-cloud.example/v1", "cloud-model"
        )
        agent = DealRoomWorkflowAgent(
            str(ROOT / "deal_rooms/sample_ma_acquisition"),
            providers=registry,
            cloud_consent_authority=authority(),
            cloud_consent_ledger_path=ledger,
        )
        return agent, registry.cloud

    def report(self, agent, provider, bundle, *, prompt="Analyze EBITDA", include_context=False, now=1786852800):
        return validate_cloud_consent(
            authority=authority(), bundle=bundle, room_id="sample-room",
            source_snapshot_sha256=agent._source_snapshot_sha256(), prompt=prompt,
            provider_endpoint=str(provider.status().endpoint),
            provider_model=str(provider.status().model), include_context=include_context,
            restored_events=relay_events(bundle),
            now=now,
        )

    def test_unconfigured_authority_and_unsigned_boolean_fail_closed(self):
        report = validate_cloud_consent(
            authority=CloudConsentAuthority(None, None, None), bundle=None,
            room_id="room", source_snapshot_sha256="a" * 64, prompt="prompt",
            provider_endpoint="https://cloud.example", provider_model="model",
            include_context=False, now=1786852800,
        )
        self.assertFalse(report["valid"])
        self.assertIn("authorities are not configured", report["errors"][0])

    def test_dispatch_and_context_need_distinct_request_bound_signatures(self):
        with tempfile.TemporaryDirectory() as folder:
            agent, provider = self.agent(Path(folder) / "uses.json")
            prompt = "Analyze EBITDA"
            bundle = signed_bundle(
                agent=agent, prompt=prompt, room_id="sample-room", provider=provider,
                include_context=True, now=1786852800,
            )
            report = self.report(
                agent, provider, bundle, prompt=prompt, include_context=True,
            )
            self.assertTrue(report["valid"], report["errors"])
            self.assertEqual(len(report["event_ids"]), 2)
            self.assertEqual(len(set(report["event_ids"])), 2)

            no_context_signature = copy.deepcopy(bundle)
            no_context_signature.pop("deal_room_context_event")
            rejected = self.report(
                agent, provider, no_context_signature, prompt=prompt, include_context=True,
            )
            self.assertFalse(rejected["valid"])
            self.assertTrue(any("raw Buzz consent event" in item for item in rejected["errors"]))

    def test_prompt_snapshot_provider_and_expiry_tamper_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            agent, provider = self.agent(Path(folder) / "uses.json")
            bundle = signed_bundle(
                agent=agent, prompt="Analyze EBITDA", room_id="sample-room",
                provider=provider, include_context=False, now=1786852800,
            )
            mutations = (
                {"prompt": "Analyze debt"},
                {"source_snapshot_sha256": "0" * 64},
                {"provider_model": "other-model"},
                {"now": 1786854000},
            )
            for changed in mutations:
                with self.subTest(changed=changed):
                    arguments = dict(
                        authority=authority(), bundle=bundle, room_id="sample-room",
                        source_snapshot_sha256=agent._source_snapshot_sha256(),
                        prompt="Analyze EBITDA", provider_endpoint=str(provider.status().endpoint),
                        provider_model=str(provider.status().model), include_context=False,
                        restored_events=relay_events(bundle),
                        now=1786852800,
                    )
                    arguments.update(changed)
                    report = validate_cloud_consent(**arguments)
                    self.assertFalse(report["valid"])

    def test_consent_is_atomically_consumed_once(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "uses.json"
            agent, provider = self.agent(ledger)
            bundle = signed_bundle(
                agent=agent, prompt="Analyze EBITDA", room_id="sample-room",
                provider=provider, include_context=False, now=1786852800,
            )
            report = self.report(agent, provider, bundle)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(consume_cloud_consent, ledger, report, consumed_at=1786852801) for _ in range(2)]
            successes = 0
            failures = 0
            for future in futures:
                try:
                    future.result()
                    successes += 1
                except ValueError as exc:
                    self.assertIn("already consumed", str(exc))
                    failures += 1
            self.assertEqual((successes, failures), (1, 1))
            saved = json.loads(ledger.read_text())
            self.assertEqual(len(saved["uses"]), 1)
            self.assertNotIn("prompt", saved["uses"][0])
            self.assertTrue(saved["uses"][0]["relay_restored"])

    def test_signed_but_unpublished_or_changed_event_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            agent, provider = self.agent(Path(folder) / "uses.json")
            bundle = signed_bundle(
                agent=agent, prompt="Analyze EBITDA", room_id="sample-room",
                provider=provider, include_context=False, now=1786852800,
            )
            missing = validate_cloud_consent(
                authority=authority(), bundle=bundle, room_id="sample-room",
                source_snapshot_sha256=agent._source_snapshot_sha256(),
                prompt="Analyze EBITDA", provider_endpoint=str(provider.status().endpoint),
                provider_model=str(provider.status().model), include_context=False,
                restored_events={}, now=1786852800,
            )
            self.assertFalse(missing["valid"])
            self.assertFalse(missing["relay_restored"])
            self.assertTrue(any("not restored from Buzz" in item for item in missing["errors"]))

            changed_events = relay_events(bundle)
            changed_events[bundle["cloud_dispatch_event"]["id"]] = {
                **bundle["cloud_dispatch_event"], "content": "changed after signing",
            }
            changed = validate_cloud_consent(
                authority=authority(), bundle=bundle, room_id="sample-room",
                source_snapshot_sha256=agent._source_snapshot_sha256(),
                prompt="Analyze EBITDA", provider_endpoint=str(provider.status().endpoint),
                provider_model=str(provider.status().model), include_context=False,
                restored_events=changed_events, now=1786852800,
            )
            self.assertFalse(changed["valid"])
            self.assertTrue(any("differs from the submitted" in item for item in changed["errors"]))


if __name__ == "__main__":
    unittest.main()

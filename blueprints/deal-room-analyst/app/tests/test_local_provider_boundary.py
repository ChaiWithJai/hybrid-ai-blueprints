import os
import subprocess
import sys
import unittest
from unittest import mock

from core.ai_provider import (
    OpenAICompatibleProvider,
    ProviderError,
    ProviderRegistry,
    cloud_endpoint_is_safe,
    local_endpoint_is_loopback_literal,
)
from core.operator_preflight import _safe_loopback_origin


class LocalProviderBoundaryTests(unittest.TestCase):
    def test_registry_accepts_only_loopback_ip_literals_for_local_provider(self):
        accepted = (
            "http://127.0.0.1:1234",
            "http://127.42.0.9:8080/v1",
            "http://[::1]:1234",
        )
        for endpoint in accepted:
            with self.subTest(endpoint=endpoint), mock.patch.dict(
                os.environ,
                {"PRISM_LOCAL_AI_URL": endpoint, "PRISM_LOCAL_AI_MODEL": "test-model"},
            ):
                registry = ProviderRegistry()
                self.assertTrue(registry.local.configured)
                self.assertEqual(registry.local.status().network_scope, "loopback_ip_literal")

    def test_registry_rejects_remote_alias_and_ambiguous_local_urls(self):
        rejected = (
            "https://127.0.0.1:1234",
            "http://localhost:1234",
            "http://local.test:1234",
            "http://192.168.1.10:1234",
            "http://2130706433:1234",
            "http://0x7f000001:1234",
            "http://127.0.0.1@remote.example:1234",
            "http://user:secret@127.0.0.1:1234",
            "http://127.0.0.1:1234?target=remote.example",
            "http://127.0.0.1:1234#remote",
            "http://[::ffff:127.0.0.1]:1234",
        )
        for endpoint in rejected:
            with self.subTest(endpoint=endpoint), mock.patch.dict(
                os.environ,
                {"PRISM_LOCAL_AI_URL": endpoint, "PRISM_LOCAL_AI_MODEL": "test-model"},
            ):
                with self.assertRaisesRegex(ProviderError, "loopback IP literal"):
                    ProviderRegistry()
                self.assertFalse(local_endpoint_is_loopback_literal(endpoint))
                self.assertFalse(_safe_loopback_origin(endpoint))
                with self.assertRaisesRegex(ProviderError, "loopback IP literal"):
                    OpenAICompatibleProvider(
                        "local_bonsai", "local", endpoint, "test-model"
                    )

    def test_unconfigured_local_provider_remains_an_explicit_unavailable_state(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            status = ProviderRegistry().local.status()
        self.assertFalse(status.configured)
        self.assertIsNone(status.endpoint)
        self.assertIsNone(status.network_scope)

    def test_direct_server_import_fails_closed_for_remote_local_provider(self):
        environment = os.environ.copy()
        environment.update({
            "PRISM_LOCAL_AI_URL": "http://remote.example:1234",
            "PRISM_LOCAL_AI_MODEL": "misclassified-remote-model",
        })
        result = subprocess.run(
            [sys.executable, "-c", "import server"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("loopback IP literal", result.stderr)

    def test_cloud_provider_keeps_explicit_external_endpoint_boundary(self):
        with mock.patch.dict(os.environ, {
            "PRISM_CLOUD_AI_URL": "https://approved-cloud.example/v1",
            "PRISM_CLOUD_AI_MODEL": "approved-cloud-model",
        }, clear=True):
            registry = ProviderRegistry()
        self.assertFalse(registry.local.configured)
        self.assertTrue(registry.cloud.configured)
        self.assertEqual(registry.cloud.status().network_scope, "operator_configured")

    def test_cloud_provider_rejects_unsafe_endpoint_forms(self):
        rejected = (
            "http://cloud.example/v1",
            "https://user:secret@cloud.example/v1",
            "https://cloud.example/v1?api_key=secret",
            "https://cloud.example/v1#fragment",
        )
        for endpoint in rejected:
            with self.subTest(endpoint=endpoint):
                self.assertFalse(cloud_endpoint_is_safe(endpoint))
                with self.assertRaisesRegex(ProviderError, "must use HTTPS"):
                    OpenAICompatibleProvider("cloud_ai", "cloud", endpoint, "model")

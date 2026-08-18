import copy
import unittest

from core.network_observation import (
    classify_socket_name,
    parse_lsof_fields,
    validate_network_observation,
)
from scripts.record_network_observation import sanitized_process


LSOF = """p10
cPython
f3
n127.0.0.1:8787
TST=LISTEN
p19
cBionic
f5
n127.0.0.1:1234
TST=LISTEN
p20
cllama-server
f4
n127.0.0.1:62300->127.0.0.1:51000
TST=ESTABLISHED
"""


def fixture():
    return {
        "verification_kind": "process_socket_observation.v1",
        "passed": True,
        "processes": {
            "prism_server": {"pid": 10, "command": "python server.py --port 8787"},
            "bionic_app": {"pid": 19, "command": "/Applications/Bionic.app/Contents/MacOS/Bionic"},
            "bonsai_llama_server": {"pid": 20, "command": "llama-server --api-key [REDACTED]"},
        },
        "request": {
            "http_status": 200,
            "endpoint": "http://127.0.0.1:1234/api/v1/chat",
            "protocol": "lmstudio_native_chat",
            "model": "27b@q1_0",
            "model_instance_id": "27b@q1_0",
            "reasoning_requested": "off",
            "reasoning_output_tokens": 0,
            "response_matched_requested_text": True,
        },
        "samples": [{"lsof_output": LSOF} for _ in range(3)],
        "observation": {
            "non_loopback_hosts": [],
            "invalid_hosts": [],
            "wildcard_hosts": [],
        },
        "packet_capture_used": False,
        "zero_egress_proved": False,
        "air_gap_proved": False,
    }


class NetworkObservationTests(unittest.TestCase):
    def test_loopback_listener_and_connection_are_classified(self):
        records = parse_lsof_fields(LSOF)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(item["loopback_only"] for item in records))

    def test_non_loopback_remote_endpoint_is_detected(self):
        result = classify_socket_name("192.168.1.4:51000->34.120.1.2:443")
        self.assertEqual(result["non_loopback_hosts"], ["192.168.1.4", "34.120.1.2"])

    def test_wildcard_listener_is_not_treated_as_loopback(self):
        result = classify_socket_name("*:8787")
        self.assertFalse(result["loopback_only"])
        self.assertEqual(result["wildcard_hosts"], ["*"])

    def test_sampled_loopback_observation_passes_without_zero_egress_claim(self):
        result = validate_network_observation(fixture())
        self.assertTrue(result["passed"])
        self.assertFalse(result["zero_egress_proved"])

    def test_saved_record_requires_a_pass_label(self):
        record = fixture()
        del record["passed"]
        result = validate_network_observation(record)
        self.assertFalse(result["passed"])
        self.assertIn("network-observation pass label is required", result["errors"])

    def test_recorder_derives_pass_without_a_predeclared_label(self):
        record = fixture()
        del record["passed"]
        result = validate_network_observation(record, require_pass_label=False)
        self.assertTrue(result["passed"])

    def test_pass_derivation_rejects_a_predeclared_label(self):
        result = validate_network_observation(fixture(), require_pass_label=False)
        self.assertFalse(result["passed"])
        self.assertIn(
            "pass-label derivation input must not contain a declared pass label",
            result["errors"],
        )

    def test_pass_derivation_recomputes_external_socket_failure(self):
        record = fixture()
        del record["passed"]
        record["samples"][1]["lsof_output"] += (
            "p19\ncBionic\nf9\nn10.0.0.2:50000->1.1.1.1:443\n"
        )
        result = validate_network_observation(record, require_pass_label=False)
        self.assertFalse(result["passed"])
        self.assertIn("1.1.1.1", result["non_loopback_hosts"])

    def test_external_socket_or_zero_egress_label_fails(self):
        record = fixture()
        record["samples"][1]["lsof_output"] += "p19\ncBionic\nf9\nn10.0.0.2:50000->1.1.1.1:443\n"
        record["zero_egress_proved"] = True
        result = validate_network_observation(record)
        self.assertFalse(result["passed"])
        self.assertIn("1.1.1.1", result["non_loopback_hosts"])

    def test_declared_socket_summary_cannot_hide_observed_endpoint(self):
        record = fixture()
        record["samples"][0]["lsof_output"] += "p19\ncBionic\nf9\nn127.0.0.1:50000->8.8.8.8:443\n"
        result = validate_network_observation(record)
        self.assertFalse(result["passed"])
        self.assertTrue(any("declared" in error for error in result["errors"]))

    def test_every_named_process_must_have_an_observed_socket(self):
        record = fixture()
        record["processes"]["bionic_app"]["pid"] = 99
        result = validate_network_observation(record)
        self.assertFalse(result["passed"])
        self.assertTrue(any("no observed sockets" in error for error in result["errors"]))

    def test_process_metadata_redacts_api_key(self):
        row = {"pid": 2, "ppid": 1, "command": "llama-server --api-key secret --port 9"}
        result = sanitized_process(row)
        self.assertNotIn("secret", result["command"])
        self.assertIn("--api-key [REDACTED]", result["command"])

    def test_unredacted_process_secret_fails_closed(self):
        record = fixture()
        record["processes"]["bonsai_llama_server"]["command"] = (
            "llama-server --api-key secret"
        )
        result = validate_network_observation(record)
        self.assertFalse(result["passed"])
        self.assertTrue(any("unredacted" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()

import unittest
import tempfile
import json
import signal
import socket
from unittest import mock
from pathlib import Path
import server as server_module
from core.arize_evals import ArizeObservabilityTracer

from core.operator_preflight import PreflightCheck, evaluate_model_inventory, required_checks_pass
from scripts.buzz_agent import build_acp_environment
from scripts.run_v0 import (
    assert_loopback_port_available,
    resolve_agent_scope,
    running_acp_pids,
    stop_agent_tree,
    supervise,
    verify_agent_started,
    verify_agent_subscription,
    verify_server_started,
)
from server import run_server


class OperatorPreflightTests(unittest.TestCase):
    def test_buzz_compose_publishes_relay_on_ipv4_loopback_only(self):
        compose_path = Path(__file__).resolve().parents[1] / "infra" / "buzz" / "compose.yml"
        compose_text = compose_path.read_text(encoding="utf-8")
        self.assertIn(
            '- "127.0.0.1:${BUZZ_HTTP_PORT:-3030}:3000"',
            compose_text,
        )
        self.assertNotIn(
            '- "${BUZZ_HTTP_PORT:-3030}:3000"',
            compose_text,
        )

    def test_occupied_workspace_port_fails_closed_without_fallback(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            with self.assertRaisesRegex(RuntimeError, "already in use"):
                assert_loopback_port_available(port)
            with self.assertRaisesRegex(RuntimeError, "Refusing to select a different port"):
                run_server(port)
        finally:
            listener.close()
        # A closed listener may leave TCP state behind, but that must not block
        # Prism's allow_reuse_address restart behavior.
        assert_loopback_port_available(port)

    def test_failed_bind_does_not_open_or_migrate_trace_store(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        original = server_module.global_tracer
        try:
            with tempfile.TemporaryDirectory() as folder:
                trace_path = Path(folder) / "must-not-exist.jsonl"
                server_module.global_tracer = ArizeObservabilityTracer()
                with mock.patch.dict(
                    "os.environ", {"PRISM_TRACE_STORE": str(trace_path)}, clear=False,
                ):
                    with self.assertRaisesRegex(RuntimeError, "Refusing to select"):
                        server_module.run_server(port)
                self.assertIsNone(server_module.global_tracer.storage_path)
                self.assertFalse(trace_path.exists())
                self.assertFalse(
                    trace_path.with_name(f".{trace_path.name}.lock").exists()
                )
        finally:
            server_module.global_tracer = original
            listener.close()

    def test_server_readiness_requires_status_from_exact_child_pid(self):
        class Child:
            pid = 41234

            @staticmethod
            def poll():
                return None

            @staticmethod
            def terminate():
                return None

            @staticmethod
            def wait(timeout=None):
                return 0

        wrong = mock.MagicMock()
        wrong.__enter__.return_value = wrong
        wrong.__exit__.return_value = False
        wrong.read.return_value = json.dumps({
            "server_process_pid": 99999,
            "product_stage": "local_prototype",
            "buzz": {"workspace_ready": True},
        }).encode()
        with mock.patch("scripts.run_v0.urllib.request.urlopen", return_value=wrong), \
                mock.patch("scripts.run_v0.time.sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "expected child PID 41234"):
                verify_server_started(
                    Child(), 8787, timeout_seconds=0.001,
                    request_timeout_seconds=0.001,
                )

    def test_catalog_model_without_loaded_instance_fails_readiness(self):
        result = evaluate_model_inventory({
            "models": [{
                "key": "27b@q1_0",
                "loaded_instances": [],
                "capabilities": {"reasoning": {"allowed_options": ["off", "on"]}},
            }],
        }, "27b@q1_0")
        self.assertTrue(result["catalog_present"])
        self.assertFalse(result["loaded"])
        self.assertTrue(result["reasoning_off_supported"])

    def test_exact_loaded_instance_and_reasoning_off_are_distinct(self):
        result = evaluate_model_inventory({
            "models": [{
                "key": "27b@q1_0",
                "loaded_instances": [{"id": "other"}, {"id": "27b@q1_0"}],
                "capabilities": {"reasoning": {"allowed_options": ["off", "on"]}},
            }],
        }, "27b@q1_0")
        self.assertTrue(result["loaded"])
        self.assertTrue(result["reasoning_off_supported"])

    def test_optional_metadata_cannot_hide_a_required_failure(self):
        checks = [
            PreflightCheck("docker", True, False, "unavailable", None),
            PreflightCheck("benchmark_metadata", False, True, "complete", {}),
        ]
        self.assertFalse(required_checks_pass(checks))

    def test_optional_metadata_does_not_block_surface_readiness(self):
        checks = [
            PreflightCheck("docker", True, True, "ready", "29.6.2"),
            PreflightCheck("benchmark_metadata", False, False, "optional_missing", {}),
        ]
        self.assertTrue(required_checks_pass(checks))

    def test_early_agent_exit_prevents_ready_announcement(self):
        class ExitedAgent:
            @staticmethod
            def poll():
                return 7

        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "agent.log"
            log.write_text("model adapter failed\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as raised:
                verify_agent_started(ExitedAgent(), log, wait_seconds=0)
            self.assertIn("code 7", str(raised.exception))
            self.assertIn("model adapter failed", str(raised.exception))

    def test_agent_scope_requires_one_room_folder_and_channel_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "deal_rooms" / "project_test"
            source.mkdir(parents=True)
            runtime = root / ".runtime" / "buzz"
            runtime.mkdir(parents=True)
            channel = "4b668cff-fb84-4129-ae87-949e267fe657"
            (runtime / "rooms.json").write_text(json.dumps({
                "project_test": {"room_id": "project_test", "channel_id": channel},
            }))
            observed_source, observed_channel = resolve_agent_scope(root, "project_test")
            self.assertEqual(observed_source, source.resolve())
            self.assertEqual(observed_channel, channel)
            (runtime / "rooms.json").write_text(json.dumps({
                "project_test": {"room_id": "another-room", "channel_id": channel},
            }))
            with self.assertRaisesRegex(RuntimeError, "mismatched Buzz channel"):
                resolve_agent_scope(root, "project_test")

    def test_existing_repo_acp_process_is_detected_exactly(self):
        binary = Path("/repo/.runtime/buzz/bin/buzz-acp")
        process_table = mock.MagicMock(
            stdout=(
                "  101 /repo/.runtime/buzz/bin/buzz-acp\n"
                "  102 /other/buzz-acp\n"
                "  103 /repo/.runtime/buzz/bin/buzz-acp --different-launch\n"
            )
        )
        with mock.patch("scripts.run_v0.subprocess.run", return_value=process_table):
            self.assertEqual(running_acp_pids(binary), [101])

    def test_agent_shutdown_cleans_exact_child_binaries(self):
        binaries = [Path("/repo/buzz-acp"), Path("/repo/buzz-agent"), Path("/repo/buzz-dev-mcp")]
        observed = {
            "buzz-acp": [101],
            "buzz-agent": [102],
            "buzz-dev-mcp": [103],
        }
        with mock.patch(
            "scripts.run_v0.running_acp_pids",
            side_effect=lambda path: observed[path.name],
        ), mock.patch("scripts.run_v0.os.kill") as kill:
            stop_agent_tree(binaries, grace_seconds=0)
        for pid in (101, 102, 103):
            self.assertIn(mock.call(pid, signal.SIGTERM), kill.call_args_list)
            self.assertIn(mock.call(pid, signal.SIGKILL), kill.call_args_list)

    def test_acp_environment_is_single_room_owner_only_and_memoryless(self):
        channel = "4b668cff-fb84-4129-ae87-949e267fe657"
        identities = {
            "PRISM_BUZZ_AGENT_PRIVATE_KEY": "a" * 64,
            "PRISM_BUZZ_OWNER_PUBLIC_KEY": "b" * 64,
        }
        env = build_acp_environment(
            {"PATH": "/bin"}, identities, model="27b@q1_0",
            base_url="http://127.0.0.1:1234/v1", deal_room=Path("/deal/room"),
            channel=channel,
        )
        self.assertEqual(env["BUZZ_ACP_SUBSCRIBE"], "mentions")
        self.assertEqual(env["BUZZ_ACP_CHANNELS"], channel)
        self.assertEqual(env["BUZZ_ACP_RESPOND_TO"], "owner-only")
        self.assertEqual(env["BUZZ_ACP_ALLOWED_RESPOND_TO"], "owner-only")
        self.assertEqual(env["BUZZ_ACP_NO_MEMORY"], "true")
        self.assertEqual(env["RUST_LOG"], "buzz_acp=info")
        self.assertEqual(env["BUZZ_AGENT_NO_HINTS"], "1")
        self.assertEqual(env["PRISM_DEAL_ROOM_SOURCE"], "/deal/room")

    def test_agent_readiness_requires_exact_channel_subscription_marker(self):
        class RunningAgent:
            @staticmethod
            def poll():
                return None

        channel = "4b668cff-fb84-4129-ae87-949e267fe657"
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "agent.log"
            log.write_text(f"subscribed to channel {channel}\n", encoding="utf-8")
            verify_agent_subscription(
                RunningAgent(), log, channel, start_offset=0, timeout_seconds=0.1,
            )
            with self.assertRaisesRegex(RuntimeError, "did not confirm subscription"):
                verify_agent_subscription(
                    RunningAgent(), log, "8797b0be-9305-437f-84c6-8ed95385dd64",
                    start_offset=0, timeout_seconds=0,
                )

    def test_agent_exit_after_startup_stops_server(self):
        class Process:
            def __init__(self, poll_values):
                self.poll_values = iter(poll_values)
                self.terminated = False

            def poll(self):
                return next(self.poll_values)

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

            def kill(self):
                raise AssertionError("kill should not be needed")

        server = Process([None, None])
        agent = Process([None, 9])
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "agent.log"
            log.write_text("subscription failed\n")
            with mock.patch("scripts.run_v0.time.sleep", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "partial surface") as raised:
                    supervise(server, agent, log)
        self.assertTrue(server.terminated)
        self.assertIn("subscription failed", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

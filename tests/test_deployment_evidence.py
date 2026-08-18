import json
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from core.deployment_evidence import (
    parse_llama_processes,
    record_local_deployment,
    validate_deployment_record,
    verify_active_deployment_process,
)
import server as server_module
from server import _measured_local_deployment_for_file, measured_local_deployment_status


class DeploymentEvidenceTests(unittest.TestCase):
    @staticmethod
    def process_table(
        models: Path, *, fitted_context: str = "16384",
        bind_host: str = "127.0.0.1", bind_port: str = "58583",
    ) -> str:
        return (
            "123 /runtime/llama.cpp-test-2.28.2/llama-server "
            f"--model {models / 'weights.gguf'} "
            f"--mmproj {models / 'mmproj.gguf'} "
            f"--host {bind_host} --port {bind_port} "
            f"--fit-ctx {fitted_context} --parallel 4\n"
        )

    @classmethod
    def process_runner(cls, models: Path, *, fitted_context: str = "16384"):
        table = cls.process_table(models, fitted_context=fitted_context)

        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, table, "")

        return runner

    @staticmethod
    def deployment_record(weights: bytes, projection: bytes) -> dict:
        import hashlib
        return {
            "schema_version": 1,
            "verification_kind": "measured_local_model_deployment",
            "measurement_state": "current_host_artifacts_and_process_measured",
            "passed": True,
            "model": {"identifier": "27b@q1_0", "quantization": {"name": "Q1_0", "bits": 1}},
            "artifacts": [
                {"role": "model_weights", "logical_path": "weights.gguf", "size_bytes": len(weights),
                 "sha256": hashlib.sha256(weights).hexdigest()},
                {"role": "vision_projection", "logical_path": "mmproj.gguf", "size_bytes": len(projection),
                 "sha256": hashlib.sha256(projection).hexdigest()},
            ],
            "runtime": {
                "version": "2.28.2",
                "executable_bundle": "llama.cpp-test-2.28.2",
                "effective_config": {
                    "bind_host": "127.0.0.1", "bind_port": "58583",
                    "fitted_context_length": "16384", "parallel_slots": "4",
                    "key_cache_type": None, "value_cache_type": None,
                    "flash_attention": None, "load_mode": None,
                },
            },
            "hardware": {"machine_model": "MacTest", "chip_type": "Apple Test", "physical_memory": "48 GB"},
            "limitations": [
                "This is not clean-machine reproduction.",
                "These facts do not prove model quality.",
                "API keys are not stored.",
            ],
        }

    def test_process_parser_keeps_allowlisted_config_and_drops_api_key(self):
        model = Path("/models/bonsai.gguf")
        table = (
            "123 /runtime/llama.cpp-backend-2.28.2/llama-server "
            "--model /models/bonsai.gguf --api-key secret-value "
            "--host 127.0.0.1 --port 58583 --fit-ctx 16384 --parallel 4 "
            "--cache-type-k f16 --cache-type-v f16\n"
        )
        records = parse_llama_processes(table, model)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["runtime_version"], "2.28.2")
        self.assertEqual(records[0]["fitted_context_length"], "16384")
        self.assertEqual(records[0]["parallel_slots"], "4")
        self.assertEqual(records[0]["bind_host"], "127.0.0.1")
        self.assertEqual(records[0]["bind_port"], "58583")
        self.assertNotIn("secret-value", json.dumps(records))

    def test_recorder_hashes_exact_artifacts_and_never_saves_process_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder)
            weights = models / "publisher" / "Bonsai.gguf"
            projection = models / "publisher" / "Bonsai-mmproj.gguf"
            weights.parent.mkdir()
            weights.write_bytes(b"weights")
            projection.write_bytes(b"projection")
            inventory = [{
                "type": "llm", "format": "gguf", "identifier": "27b@q1_0",
                "displayName": "Bonsai 27B", "publisher": "publisher",
                "architecture": "qwen35", "path": "publisher/Bonsai.gguf",
                "sizeBytes": 999, "quantization": {"name": "Q1_0", "bits": 1},
            }]
            process = (
                f"123 /runtime/backend-2.28.2/llama-server --model {weights} "
                f"--api-key secret-value --mmproj {projection} --fit-ctx 16384 "
                "--parallel 4 --host 127.0.0.1 --port 58583 "
                "--cache-type-k f16 --cache-type-v f16\n"
            )
            hardware = {"SPHardwareDataType": [{
                "machine_model": "MacTest", "chip_type": "Apple Test",
                "physical_memory": "48 GB", "serial_number": "do-not-store",
            }]}

            def runner(command, **kwargs):
                if command[-2:] == ["ps", "--json"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps(inventory), "")
                if command[:2] == ["ps", "-axo"]:
                    return subprocess.CompletedProcess(command, 0, process, "")
                if command[:2] == ["system_profiler", "SPHardwareDataType"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps(hardware), "")
                raise AssertionError(command)

            with mock.patch("core.deployment_evidence.shutil.which", return_value="/bin/lms"):
                record = record_local_deployment(
                    "27b@q1_0", runner=runner, model_root=models,
                )
            self.assertEqual(validate_deployment_record(
                record, model_root=models, verify_files=True,
            ), [])
            serialized = json.dumps(record)
            self.assertNotIn("secret-value", serialized)
            self.assertNotIn("do-not-store", serialized)
            self.assertFalse(record["model"]["catalog_size_matches_artifact"])

    def test_file_bound_validator_rejects_artifact_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder)
            for name, content in (("weights.gguf", b"weights"), ("mmproj.gguf", b"projection")):
                (models / name).write_bytes(content)
            record = self.deployment_record(b"weights", b"projection")
            self.assertEqual(validate_deployment_record(
                record, model_root=models, verify_files=True,
            ), [])
            record_path = models / "deployment.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            _measured_local_deployment_for_file.cache_clear()
            warm = measured_local_deployment_status(
                record_path, model_root=models,
                process_runner=self.process_runner(models),
            )
            self.assertTrue(warm["verified"])
            self.assertTrue(warm["artifact_files_verified"])
            self.assertTrue(warm["active_runtime"]["verified"])
            self.assertEqual(
                warm["cache_basis"],
                "record_bytes_plus_artifact_device_inode_size_mtime_ctime",
            )
            (models / "weights.gguf").write_bytes(b"changed")
            cached_after_tamper = measured_local_deployment_status(
                record_path, model_root=models,
                process_runner=self.process_runner(models),
            )
            self.assertFalse(cached_after_tamper["verified"])
            self.assertTrue(any(
                "SHA-256 differs" in error for error in cached_after_tamper["errors"]
            ))
            errors = validate_deployment_record(record, model_root=models, verify_files=True)
            self.assertTrue(any("size differs" in error or "SHA-256 differs" in error for error in errors))

    def test_concurrent_cold_status_requests_hash_artifacts_once(self):
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder)
            (models / "weights.gguf").write_bytes(b"weights")
            (models / "mmproj.gguf").write_bytes(b"projection")
            record_path = models / "deployment.json"
            record_path.write_text(
                json.dumps(self.deployment_record(b"weights", b"projection")),
                encoding="utf-8",
            )
            _measured_local_deployment_for_file.cache_clear()
            calls = 0
            calls_lock = threading.Lock()
            original = validate_deployment_record

            def counted(*args, **kwargs):
                nonlocal calls
                with calls_lock:
                    calls += 1
                time.sleep(0.05)
                return original(*args, **kwargs)

            with mock.patch.object(server_module, "validate_deployment_record", side_effect=counted):
                with ThreadPoolExecutor(max_workers=10) as pool:
                    results = list(pool.map(
                        lambda _: measured_local_deployment_status(
                            record_path, model_root=models,
                            process_runner=self.process_runner(models),
                        ),
                        range(20),
                    ))
            self.assertEqual(calls, 1)
            self.assertTrue(all(result["verified"] for result in results))
            self.assertEqual(len({result["verified_at"] for result in results}), 1)

    def test_active_runtime_drift_fails_even_with_verified_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder)
            (models / "weights.gguf").write_bytes(b"weights")
            (models / "mmproj.gguf").write_bytes(b"projection")
            record = self.deployment_record(b"weights", b"projection")
            matching = verify_active_deployment_process(
                record, model_root=models, process_table=self.process_table(models),
            )
            self.assertTrue(matching["verified"])

            drifted = verify_active_deployment_process(
                record,
                model_root=models,
                process_table=self.process_table(models, fitted_context="8192"),
            )
            self.assertFalse(drifted["verified"])
            self.assertTrue(any(
                "fitted_context_length differs" in error for error in drifted["errors"]
            ))

            missing = verify_active_deployment_process(
                record, model_root=models, process_table="",
            )
            self.assertFalse(missing["verified"])
            self.assertIn("found 0", missing["errors"][0])

    def test_active_runtime_non_loopback_bind_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder)
            record = self.deployment_record(b"weights", b"projection")
            non_loopback = verify_active_deployment_process(
                record,
                model_root=models,
                process_table=self.process_table(models, bind_host="0.0.0.0"),
            )
            self.assertFalse(non_loopback["verified"])
            self.assertTrue(any(
                "bind_host differs" in error for error in non_loopback["errors"]
            ))

    def test_active_runtime_port_drift_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder)
            record = self.deployment_record(b"weights", b"projection")
            port_drift = verify_active_deployment_process(
                record,
                model_root=models,
                process_table=self.process_table(models, bind_port="58584"),
            )
            self.assertFalse(port_drift["verified"])
            self.assertTrue(any(
                "bind_port differs" in error for error in port_drift["errors"]
            ))


if __name__ == "__main__":
    unittest.main()

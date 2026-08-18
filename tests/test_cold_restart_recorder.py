import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import record_cold_restart_evidence as recorder


class ColdRestartRecorderTests(unittest.TestCase):
    def test_cold_restart_uses_immutable_browser_snapshot_path(self):
        browser_command = next(
            command for command in recorder._dependent_commands()
            if any(item.endswith("verify_browser_surface.mjs") for item in command)
        )
        self.assertNotIn("--output", browser_command)
        self.assertNotEqual(recorder.CURRENT_BROWSER_RECORD, recorder.COLD_BROWSER_RECORD)
        self.assertNotEqual(
            recorder.CURRENT_BROWSER_SCREENSHOT, recorder.COLD_BROWSER_SCREENSHOT,
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current_record = root / "current.json"
            current_screenshot = root / "current.png"
            cold_record = root / "cold.json"
            cold_screenshot = root / "cold.png"
            current_record.write_bytes(b"browser record")
            current_screenshot.write_bytes(b"browser screenshot")
            with (
                mock.patch.object(recorder, "CURRENT_BROWSER_RECORD", current_record),
                mock.patch.object(recorder, "CURRENT_BROWSER_SCREENSHOT", current_screenshot),
                mock.patch.object(recorder, "COLD_BROWSER_RECORD", cold_record),
                mock.patch.object(recorder, "COLD_BROWSER_SCREENSHOT", cold_screenshot),
            ):
                recorder._snapshot_browser_evidence()
            self.assertEqual(cold_record.read_bytes(), b"browser record")
            self.assertEqual(cold_screenshot.read_bytes(), b"browser screenshot")

    def test_exact_process_selection_ignores_other_apps_and_models(self):
        rows = [
            {
                "pid": 10,
                "started": "Sat Aug 15 10:00:00 2026",
                "command": recorder.BIONIC_EXECUTABLE,
            },
            {
                "pid": 11,
                "started": "Sat Aug 15 10:00:01 2026",
                "command": "/Applications/Bionic.app/Contents/Frameworks/Bionic Helper",
            },
            {
                "pid": 12,
                "started": "Sat Aug 15 10:00:02 2026",
                "command": "llama-server --model /tmp/other.gguf --fit-ctx 4096",
            },
            {
                "pid": 13,
                "started": "Sat Aug 15 10:00:03 2026",
                "command": (
                    f"llama-server --model {recorder.MODEL_ARTIFACT} "
                    "--fit-ctx 16384 --parallel 4 --api-key secret"
                ),
            },
        ]
        with mock.patch.object(recorder, "_process_rows", return_value=rows):
            self.assertEqual(recorder._bionic_process()["pid"], 10)
            model = recorder._model_process()
        self.assertEqual(model["pid"], 13)
        self.assertEqual(recorder._flag_value(model["command"], "--fit-ctx"), "16384")
        self.assertEqual(recorder._flag_value(model["command"], "--parallel"), "4")

    def test_duplicate_exact_processes_fail_closed(self):
        app = {
            "pid": 10,
            "started": "Sat Aug 15 10:00:00 2026",
            "command": recorder.BIONIC_EXECUTABLE,
        }
        with mock.patch.object(
            recorder,
            "_process_rows",
            return_value=[app, {**app, "pid": 11}],
        ):
            with self.assertRaisesRegex(RuntimeError, "more than one Bionic"):
                recorder._bionic_process()


if __name__ == "__main__":
    unittest.main()

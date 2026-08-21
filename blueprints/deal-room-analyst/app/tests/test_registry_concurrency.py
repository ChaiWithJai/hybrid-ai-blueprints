import copy
import hashlib
import multiprocessing
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import server as server_module


def room_for(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    return {
        "id": "local_" + hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12],
        "name": resolved.name,
        "target": "Operator-selected local folder",
        "type": "Private folder",
        "path": str(resolved),
        "description": "Concurrent registration test",
    }


def _commit_room_process(room):
    server_module.commit_local_deal_room(room)


class LocalDealRoomRegistryConcurrencyTests(unittest.TestCase):
    def test_competing_processes_preserve_all_rooms_and_live_process_reloads(self):
        context = multiprocessing.get_context("fork")
        original_registry = server_module.CUSTOM_DEAL_ROOM_REGISTRY
        original_identity = server_module.CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY
        original_rooms = copy.deepcopy(server_module.CUSTOM_DEAL_ROOMS)
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                registry = root / "runtime" / "registrations.v1.json"
                rooms = []
                for index in range(12):
                    source = root / f"process_deal_{index}"
                    source.mkdir()
                    rooms.append(room_for(source))

                server_module.CUSTOM_DEAL_ROOM_REGISTRY = registry
                server_module.CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY = None
                server_module.CUSTOM_DEAL_ROOMS.clear()
                processes = [
                    context.Process(target=_commit_room_process, args=(room,))
                    for room in rooms
                ]
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(timeout=10)
                    self.assertEqual(process.exitcode, 0)

                expected = {room["id"] for room in rooms}
                restored = server_module.load_local_deal_rooms(registry)
                self.assertEqual(set(restored), expected)
                # The parent did not write these rooms. Its normal read path
                # must notice the replaced registry and refresh process state.
                visible = server_module.all_deal_rooms()
                self.assertTrue(expected.issubset(visible))
                self.assertEqual(set(server_module.CUSTOM_DEAL_ROOMS), expected)
                lock_path = registry.with_name(f".{registry.name}.lock")
                self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)
        finally:
            server_module.CUSTOM_DEAL_ROOM_REGISTRY = original_registry
            server_module.CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY = original_identity
            server_module.CUSTOM_DEAL_ROOMS.clear()
            server_module.CUSTOM_DEAL_ROOMS.update(original_rooms)

    def test_folder_registry_drift_and_failed_replace_preserve_prior_bytes(self):
        original = copy.deepcopy(server_module.CUSTOM_DEAL_ROOMS)
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / "deal"
                source.mkdir()
                registry = root / "runtime" / "registrations.v1.json"
                room = room_for(source)
                server_module.CUSTOM_DEAL_ROOMS.clear()
                server_module.commit_local_deal_room(room, registry)
                before = registry.read_bytes()

                drifted = {**room, "description": "different canonical metadata"}
                with self.assertRaisesRegex(ValueError, "differs for the canonical room ID"):
                    server_module.commit_local_deal_room(drifted, registry)
                self.assertEqual(registry.read_bytes(), before)

                other_source = root / "other"
                other_source.mkdir()
                with mock.patch("server.os.replace", side_effect=OSError("commit failed")):
                    with self.assertRaisesRegex(OSError, "commit failed"):
                        server_module.commit_local_deal_room(room_for(other_source), registry)
                self.assertEqual(registry.read_bytes(), before)
        finally:
            server_module.CUSTOM_DEAL_ROOMS.clear()
            server_module.CUSTOM_DEAL_ROOMS.update(original)

    def test_concurrent_commits_persist_every_room_without_temp_file_collisions(self):
        original = copy.deepcopy(server_module.CUSTOM_DEAL_ROOMS)
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                registry = root / "runtime" / "registrations.v1.json"
                rooms = []
                for index in range(32):
                    path = root / f"deal_{index}"
                    path.mkdir()
                    rooms.append(room_for(path))

                server_module.CUSTOM_DEAL_ROOMS.clear()
                with ThreadPoolExecutor(max_workers=12) as pool:
                    list(pool.map(
                        lambda room: server_module.commit_local_deal_room(room, registry),
                        rooms,
                    ))

                restored = server_module.load_local_deal_rooms(registry)
                expected_ids = {room["id"] for room in rooms}
                self.assertEqual(set(restored), expected_ids)
                self.assertEqual(set(server_module.CUSTOM_DEAL_ROOMS), expected_ids)
                self.assertEqual(registry.stat().st_mode & 0o777, 0o600)
                self.assertEqual(list(registry.parent.glob("*.tmp")), [])
        finally:
            with server_module.CUSTOM_DEAL_ROOM_LOCK:
                server_module.CUSTOM_DEAL_ROOMS.clear()
                server_module.CUSTOM_DEAL_ROOMS.update(original)


if __name__ == "__main__":
    unittest.main()

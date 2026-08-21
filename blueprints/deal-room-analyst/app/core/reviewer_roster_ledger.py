"""Locked, validated replacement for domain-owner reviewer rosters."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable


_THREAD_LOCK = threading.RLock()


@contextmanager
def _roster_lock(root: Path, roster_path: Path):
    """Serialize a roster transaction across threads and local processes."""
    lock_directory = root / ".runtime" / "locks"
    lock_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    relative = str(roster_path.resolve().relative_to(root.resolve()))
    lock_name = hashlib.sha256(relative.encode("utf-8")).hexdigest() + ".lock"
    lock_path = lock_directory / lock_name
    with _THREAD_LOCK:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            os.chmod(lock_path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def mutate_reviewer_roster(
    root: Path,
    roster_path: Path,
    *,
    validate: Callable[[dict[str, Any]], list[str]],
    mutate: Callable[[dict[str, Any]], Any],
) -> Any:
    """Reread, mutate, validate, and replace one roster under a local lock."""
    root = root.resolve()
    roster_path = roster_path.resolve()
    roster_path.relative_to(root)
    with _roster_lock(root, roster_path):
        roster = json.loads(roster_path.read_text(encoding="utf-8"))
        current_errors = validate(roster)
        if current_errors:
            raise ValueError("current reviewer roster is invalid: " + "; ".join(current_errors))
        result = mutate(roster)
        updated_errors = validate(roster)
        if updated_errors:
            raise ValueError("updated reviewer roster is invalid: " + "; ".join(updated_errors))
        _atomic_json(roster_path, roster)
        return result

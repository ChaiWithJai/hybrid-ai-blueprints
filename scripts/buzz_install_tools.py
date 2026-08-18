#!/usr/bin/env python3
"""Build the pinned Buzz CLI and ACP toolchain into .runtime/buzz/bin."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "buzz"
SOURCE = RUNTIME / "source"
BIN = RUNTIME / "bin"
BUZZ_REPOSITORY = "https://github.com/block/buzz.git"
BUZZ_COMMIT = "82f7ed1532f50e0d28afca5580ed522f1c2ef1ca"
PACKAGES = ("buzz-cli", "buzz-agent", "buzz-acp", "buzz-dev-mcp")
BINARIES = ("buzz", "buzz-agent", "buzz-acp", "buzz-dev-mcp")


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if not (SOURCE / ".git").exists():
        run("git", "clone", "--filter=blob:none", BUZZ_REPOSITORY, str(SOURCE), cwd=ROOT)
    run("git", "fetch", "--depth", "1", "origin", BUZZ_COMMIT, cwd=SOURCE)
    run("git", "checkout", "--detach", BUZZ_COMMIT, cwd=SOURCE)
    package_args = " ".join(f"-p {package}" for package in PACKAGES)
    run(
        "bash", "-lc",
        f". ./bin/activate-hermit && cargo build --release {package_args}",
        cwd=SOURCE,
    )
    BIN.mkdir(parents=True, exist_ok=True)
    for binary in BINARIES:
        shutil.copy2(SOURCE / "target" / "release" / binary, BIN / binary)
    print(f"Installed Buzz tools from {BUZZ_COMMIT} into {BIN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


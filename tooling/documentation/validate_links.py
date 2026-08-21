#!/usr/bin/env python3
"""Check local Markdown links in tracked documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
TOP_LEVEL_FILES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "GETTING_STARTED.md",
    ROOT / "GOVERNANCE.md",
    ROOT / "SECURITY.md",
]

# Directories that contain markdown we do not author and must never gate the
# suite. Without this, installing a blueprint's dependencies turns the repo red:
# rglob walks into blueprints/*/app/.venv/ and validates third-party package
# READMEs, e.g. mlx_audio's higgs_audio README links to paths in ITS OWN
# upstream repository that do not exist here.
VENDORED_PARTS = frozenset({
    ".venv", "venv", "node_modules", "site-packages", "__pycache__",
    ".git", ".mypy_cache", ".pytest_cache", "dist", "build",
    # Runtime state: .runtime/ holds a vendored Buzz source checkout and its
    # hermit-managed Rust toolchain, whose markdown links point inside their own
    # upstream repositories.
    ".runtime", ".hermit", "checkouts", "target", "registry",
})
DOCUMENTATION_ROOTS = [
    ROOT / "blueprints",
    ROOT / "use-cases",
    ROOT / "models",
    ROOT / "packages",
    ROOT / "examples",
    ROOT / "research",
    ROOT / "docs",
]


def is_vendored(path: Path) -> bool:
    return any(part in VENDORED_PARTS for part in path.parts)


def markdown_files() -> list[Path]:
    files = [path for path in TOP_LEVEL_FILES if path.exists()]
    for directory in DOCUMENTATION_ROOTS:
        if directory.exists():
            files.extend(
                path for path in directory.rglob("*.md") if not is_vendored(path)
            )
    return sorted(set(files))


def local_target(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    if target.startswith("/"):
        return ROOT / target.removeprefix("/")
    return (source.parent / target).resolve()


def validate() -> list[str]:
    errors = []
    for source in markdown_files():
        text = source.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = local_target(source, raw_target)
            if target is None:
                continue
            if not target.exists():
                errors.append(
                    f"{source.relative_to(ROOT)} links to missing {raw_target}"
                )
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Checked local links in {len(markdown_files())} Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

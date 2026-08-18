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
    ROOT / "GOVERNANCE.md",
    ROOT / "SECURITY.md",
]
DOCUMENTATION_ROOTS = [
    ROOT / "blueprints",
    ROOT / "use-cases",
    ROOT / "models",
    ROOT / "packages",
    ROOT / "examples",
    ROOT / "research",
    ROOT / "docs",
]


def markdown_files() -> list[Path]:
    files = [path for path in TOP_LEVEL_FILES if path.exists()]
    for directory in DOCUMENTATION_ROOTS:
        if directory.exists():
            files.extend(directory.rglob("*.md"))
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

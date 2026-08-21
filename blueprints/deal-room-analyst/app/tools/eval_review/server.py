#!/usr/bin/env python3
"""Retired standalone entry point for Prism room evaluation."""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "The standalone evaluation server has been retired. "
        "Start Prism and open /rooms/{room}/evaluation on the Prism server.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

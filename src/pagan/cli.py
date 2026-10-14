"""Command-line interface for PAGAN."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from pagan import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pagan",
        description="PAGAN (Pixel Art Grammar And Notation): turn text pixel art into PNGs.",
    )
    parser.add_argument("--version", action="version", version=f"pagan {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0

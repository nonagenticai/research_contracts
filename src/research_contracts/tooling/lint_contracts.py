"""Compile authoritative schemas and enforce the pre-ADR regulatory denylist."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contract_tools import lint_repository
from .errors import ContractError
from .paths import DENYLIST, REPOSITORY_ROOT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository to lint; schemas are read from <repo-root>/schemas and every "
        "JSON/YAML document under <repo-root> is scanned",
    )
    parser.add_argument(
        "--denylist",
        type=Path,
        default=DENYLIST,
        help="pre-ADR regulatory denylist to enforce",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    try:
        errors = lint_repository(repo_root, args.denylist.expanduser().resolve())
    except ContractError as exc:
        print(exc, file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"contract lint passed: {repo_root}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

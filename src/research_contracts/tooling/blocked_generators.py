"""Blocked client-generation entry points.

The source OpenAPI contracts are not frozen and the Python package/registry
decision (IMP-DEC-001) is UNASSIGNED, so these generators must refuse to run
rather than emit a client that looks authoritative.
"""

from __future__ import annotations

import sys

BLOCKED_EXIT = 1

GENERATORS: dict[str, str] = {
    "fr-callback": "blocked: FR callback contract and Python package/registry decision are UNASSIGNED",
    "kag-context": "blocked: KAG context contract and Python package/registry decision are UNASSIGNED",
    "kag-fr-control": (
        "blocked: FR control-plane contract and Python package/registry decision are UNASSIGNED"
    ),
}


def blocked(name: str) -> int:
    """Report the blocker for ``name`` on stderr and return a failing exit code."""
    try:
        message = GENERATORS[name]
    except KeyError:
        raise ValueError(
            f"unknown generator {name!r}; expected one of {sorted(GENERATORS)}"
        ) from None
    print(message, file=sys.stderr)
    return BLOCKED_EXIT

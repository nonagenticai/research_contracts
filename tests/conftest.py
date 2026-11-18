"""Shared test fixtures.

Entry points run in a subprocess and the dev tools are required, never skipped:
a gate that cannot run is a gate that cannot fail.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKFLOW = ROOT / ".github/workflows/ci-public.yml"


def run_script(
    name: str, *args: object, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a ``scripts/*.py`` entry point in a subprocess and return the result."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


@pytest.fixture
def script_runner() -> Callable[..., subprocess.CompletedProcess[str]]:
    return run_script


def require_tool(name: str) -> str:
    """Return the path to a dev tool, failing loudly when it is not installed.

    Skipping here would reproduce the defect this repository exists to fix: a
    gate that cannot run is a gate that cannot fail.
    """
    found = shutil.which(name)
    if found is None:
        pytest.fail(
            f"{name!r} is not on PATH; run `uv sync --all-groups` so the lint gates actually run"
        )
    return found

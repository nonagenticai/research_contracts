"""The fleet lint gates, run bare, over source, scripts and tests.

Baseline defect D16: ``ty check`` reported ``invalid-type-form`` in
``scripts/contract_tools.py``, ``ruff format --check`` failed on four files and
``ruff check --select BLE`` flagged the ``except (ContractError, Exception)``
tuple. None of it ran, because the repository had no lint configuration and CI
installed no linters.

These run as tests as well as CI steps so a local ``pytest`` cannot be green
while CI is red.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest
from conftest import ROOT, require_tool

LINT_TARGETS = ["src", "scripts", "tests"]


def run(tool: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [require_tool(tool), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )


def test_ruff_check_is_clean() -> None:
    result = run("ruff", "check", "--no-cache", *LINT_TARGETS)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ruff_format_is_clean() -> None:
    result = run("ruff", "format", "--no-cache", "--check", *LINT_TARGETS)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ty_check_is_clean() -> None:
    result = run("ty", "check", *LINT_TARGETS)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bandit_is_clean() -> None:
    result = run("bandit", "-q", "-r", "src", "scripts", "-ll")
    assert result.returncode == 0, result.stdout + result.stderr


def test_blind_except_is_selected_by_ruff() -> None:
    """The rule that would have caught ``except (ContractError, Exception)``."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    selected = config["tool"]["ruff"]["lint"]["select"]
    assert "BLE" in selected


def test_blind_except_is_actually_reported(tmp_path: Path) -> None:
    """Falsifiable probe: the configured rule must fire on the baseline pattern."""
    offender = ROOT / "src/research_contracts/tooling/_ble_probe.py"
    offender.write_text(
        "def f() -> None:\n"
        "    try:\n"
        "        pass\n"
        "    except (ValueError, Exception):\n"
        "        pass\n",
        encoding="utf-8",
    )
    try:
        result = run("ruff", "check", "--no-cache", str(offender))
    finally:
        offender.unlink()
    assert result.returncode == 1
    assert "BLE001" in result.stdout


def test_project_declares_the_fleet_toolchain() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["requires-python"] == ">=3.14"
    assert config["build-system"]["build-backend"] == "hatchling.build"
    assert "uv" not in config["tool"]
    assert config["tool"]["ruff"]["line-length"] == 100
    assert config["tool"]["ruff"]["target-version"] == "py314"
    assert config["tool"]["ty"]["environment"]["python-version"] == "3.14"

    dev = " ".join(config["dependency-groups"]["dev"])
    for tool in ("pytest", "ruff", "ty", "bandit", "pip-audit", "detect-secrets"):
        assert tool in dev, f"dev group does not pin {tool}"


def test_lockfile_and_hook_configuration_exist() -> None:
    for name in ("uv.lock", ".pre-commit-config.yaml", ".detect-secrets-baseline.json"):
        assert (ROOT / name).is_file(), f"{name} is missing"
    assert not (ROOT / "requirements-dev.txt").exists(), (
        "the unpinned requirements-dev.txt flow was replaced by uv.lock"
    )


def test_sibling_package_root_is_declared() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/research_contracts"
    ]
    assert (ROOT / "src/research_contracts/__init__.py").is_file()


@pytest.mark.parametrize("key", ["permissions", "concurrency"])
def test_workflow_declares_required_top_level_keys(key: str) -> None:
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci-public.yml").read_text(encoding="utf-8")
    )
    assert key in workflow, f"workflow does not declare {key}:"


def test_every_workflow_job_has_a_timeout() -> None:
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci-public.yml").read_text(encoding="utf-8")
    )
    for name, job in workflow["jobs"].items():
        assert "timeout-minutes" in job, f"job {name} has no timeout-minutes"

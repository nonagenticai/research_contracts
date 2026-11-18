"""Every script in ``scripts/`` is executed here, so none can rot unobserved.

Baseline defects covered:

* D14 six of eight scripts were extensionless, so ruff, ty, bandit and every
  ``types: [python]`` pre-commit hook were structurally blind to them.
* D15 the scripts were mode 644 despite ``#!/usr/bin/env python3`` shebangs, so
  ``./scripts/lint-contracts`` was "Permission denied", exit 126.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import SCRIPTS, WORKFLOW, run_script

PYTHON_SCRIPTS = sorted(path.name for path in SCRIPTS.glob("*.py"))
SHELL_SCRIPTS = sorted(path.name for path in SCRIPTS.glob("*.sh"))
ALL_SCRIPTS = sorted(path.name for path in SCRIPTS.iterdir() if path.is_file())

BLOCKED_GENERATORS = {
    "generate_fr_callback_client.py": "blocked: FR callback contract",
    "generate_kag_context_client.py": "blocked: KAG context contract",
    "generate_kag_fr_control_client.py": "blocked: FR control-plane contract",
}


def test_scripts_directory_is_not_empty() -> None:
    assert ALL_SCRIPTS, "scripts/ is empty — an empty enumeration is not a clean one"


# --------------------------------------------------------------------------
# D14 — the fleet linters must actually see the scripts
# --------------------------------------------------------------------------


def test_every_script_carries_a_linted_extension() -> None:
    extensionless = [name for name in ALL_SCRIPTS if Path(name).suffix not in {".py", ".sh"}]
    assert not extensionless, (
        f"{extensionless} have no extension, so ruff/ty/bandit and every "
        "`types: [python]` pre-commit hook are structurally blind to them"
    )


def test_ruff_enumerates_every_python_script(ruff: str) -> None:
    result = subprocess.run(
        [ruff, "check", "--no-cache", "--show-files", str(SCRIPTS)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS.parent),
    )
    assert result.returncode == 0, result.stderr
    seen = sorted(Path(line).name for line in result.stdout.split() if line.strip())
    assert seen == PYTHON_SCRIPTS, f"ruff sees {seen}, scripts/ holds {PYTHON_SCRIPTS}"


# --------------------------------------------------------------------------
# D15 — a shebang without the executable bit is exit 126
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_SCRIPTS)
def test_every_script_is_executable(name: str) -> None:
    path = SCRIPTS / name
    assert path.read_text(encoding="utf-8").startswith("#!"), f"{name} has no shebang"
    assert os.access(path, os.X_OK), f"{name} is not executable: ./scripts/{name} exits 126"


@pytest.mark.parametrize("name", PYTHON_SCRIPTS)
def test_every_python_script_runs_directly_from_its_shebang(name: str, tmp_path: Path) -> None:
    """`./scripts/<name> --help` must execute, not die with Permission denied.

    No PYTHONPATH is supplied: each entry point bootstraps its own ``src/``
    from ``__file__``, so it is anchored to the repository that contains it.
    """
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [str(SCRIPTS / name), "--help"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )
    assert result.returncode != 126, f"./scripts/{name}: Permission denied"
    assert "Permission denied" not in result.stderr
    assert "No module named 'research_contracts'" not in result.stderr


# --------------------------------------------------------------------------
# Every entry point is executed and its contract asserted
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "fragment"), sorted(BLOCKED_GENERATORS.items()))
def test_blocked_generators_refuse_to_run(
    name: str, fragment: str, script_runner: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    result = script_runner(name)
    assert result.returncode != 0, f"{name} produced a client while the contract is not frozen"
    assert fragment in result.stderr


def test_canonical_fixture_harness_runs_and_passes(
    script_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """FND-002/FND-005 landed the real harness; it must replay every real fixture.

    The old assertion here was ``int(count) > 0``, which is tautologically true:
    ``check_rfc8785`` reads three hardcoded filenames, so the counter is at least
    two on any run that does not die outright. The docstring claimed a zero-check
    run was exit 2 "by construction" — that guard was unreachable dead code, and
    deleting 107 of 109 fixtures still printed green.

    The count is now asserted against the pinned total, so a deleted, renamed or
    silently added fixture fails here as well as in the harness.
    """
    from research_contracts.tooling.canonical_fixtures import EXPECTED_CHECKS

    result = script_runner("verify_canonical_fixtures.py")
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"canonical fixtures passed: (\d+) checks", result.stdout)
    assert match, f"harness did not report a check count: {result.stdout!r}"
    assert int(match.group(1)) == EXPECTED_CHECKS, (
        f"the harness ran {match.group(1)} checks, {EXPECTED_CHECKS} are pinned"
    )


def _fixture_tree(destination: Path) -> Path:
    shutil.copytree(SCRIPTS.parent / "fixtures", destination)
    return destination


def test_canonical_fixture_harness_is_green_on_an_untouched_copy(tmp_path: Path) -> None:
    """Control for the coverage probes below: an intact copy must still pass."""
    tree = _fixture_tree(tmp_path / "fixtures")
    result = run_script("verify_canonical_fixtures.py", "--fixtures-root", tree)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "suite",
    [
        "canonical-hash/v1/mutations",
        "canonical-hash/v1/rejected",
        "canonical-hash/v1/vectors",
        "canonical-hash/v1/manifests",
        "canonical-references/v1/invalid",
        "canonical-references/v1/valid",
        "canonical-references/v1/verification",
    ],
)
def test_deleting_a_fixture_suite_is_not_a_pass(tmp_path: Path, suite: str) -> None:
    """The exact probe: ``glob("*.json")`` on a missing directory returns ``[]``.

    Dropping the three adversarial suites used to print "98 checks", exit 0.
    """
    tree = _fixture_tree(tmp_path / "fixtures")
    shutil.rmtree(tree / suite)
    result = run_script("verify_canonical_fixtures.py", "--fixtures-root", tree)
    assert result.returncode != 0, f"deleting {suite} was accepted: {result.stdout}"
    assert f"{tree / suite}: suite" in result.stderr, result.stderr
    assert "is missing" in result.stderr


def test_emptying_a_fixture_suite_is_not_a_pass(tmp_path: Path) -> None:
    """A suite that still exists but lost its fixtures must breach its floor."""
    tree = _fixture_tree(tmp_path / "fixtures")
    for fixture in (tree / "canonical-hash/v1/rejected").glob("*.json"):
        fixture.unlink()
    result = run_script("verify_canonical_fixtures.py", "--fixtures-root", tree)
    assert result.returncode == 2, result.stdout
    assert "below its floor" in result.stderr


def test_renaming_a_fixture_out_of_the_glob_is_not_a_pass(tmp_path: Path) -> None:
    tree = _fixture_tree(tmp_path / "fixtures")
    fixture = next((tree / "canonical-hash/v1/mutations").glob("*.json"))
    fixture.rename(fixture.with_suffix(".json.disabled"))
    result = run_script("verify_canonical_fixtures.py", "--fixtures-root", tree)
    assert result.returncode == 2, result.stdout
    assert "below its floor" in result.stderr


def test_an_added_fixture_breaks_the_pinned_total(tmp_path: Path) -> None:
    """Growth is as much a coverage change as shrinkage, and must be reviewed."""
    tree = _fixture_tree(tmp_path / "fixtures")
    vectors = tree / "canonical-hash/v1/vectors"
    source = next(vectors.glob("*.json"))
    shutil.copyfile(source, vectors / "zz-unreviewed-addition.json")
    result = run_script("verify_canonical_fixtures.py", "--fixtures-root", tree)
    assert result.returncode == 2, result.stdout
    assert "EXPECTED_CHECKS" in result.stderr


def test_deleting_a_pinned_rfc8785_fixture_is_not_a_pass(tmp_path: Path) -> None:
    tree = _fixture_tree(tmp_path / "fixtures")
    (tree / "canonical-hash/v1/rfc8785/property-name-ordering.json").unlink()
    result = run_script("verify_canonical_fixtures.py", "--fixtures-root", tree)
    assert result.returncode != 0, result.stdout
    assert "property-name-ordering.json" in result.stderr


def test_a_corrupt_fixture_is_diagnosed_not_tracebacked(tmp_path: Path) -> None:
    """An unreadable input is a diagnosed condition, not evidence of a gate bug."""
    tree = _fixture_tree(tmp_path / "fixtures")
    (tree / "canonical-hash/v1/vectors/ordered-array-preserves-order.json").write_text(
        "{ not json", encoding="utf-8"
    )
    result = run_script("verify_canonical_fixtures.py", "--fixtures-root", tree)
    assert result.returncode == 1, result.stdout
    assert "Traceback" not in result.stderr, result.stderr
    assert "ordered-array-preserves-order.json" in result.stderr


def test_canonical_fixture_harness_fails_when_a_fixture_is_wrong(tmp_path: Path) -> None:
    """Falsifiable probe: the harness must fail on a corrupted golden vector.

    Without this, "exit 0" only proves the harness ran, not that it binds.
    """
    vector = (
        SCRIPTS.parent / "fixtures/canonical-hash/v1/vectors/ordered-array-preserves-order.json"
    )
    original = vector.read_bytes()
    fixture = json.loads(original)
    fixture["expected_content_hash"] = "sha256:" + "0" * 64
    try:
        vector.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
        result = run_script("verify_canonical_fixtures.py", cwd=tmp_path)
    finally:
        vector.write_bytes(original)
    assert result.returncode == 1, "a forged expected_content_hash was accepted"
    assert "ordered-array-preserves-order.json" in result.stderr


# --------------------------------------------------------------------------
# Every script must be wired into CI
# --------------------------------------------------------------------------


def workflow_document() -> dict[str, Any]:
    import yaml

    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def workflow_run_commands() -> list[str]:
    """Every ``run:`` command in the workflow, from every job and every step."""
    commands: list[str] = []
    for job in workflow_document()["jobs"].values():
        for step in job.get("steps", []):
            command = step.get("run")
            if isinstance(command, str):
                commands.append(command)
    return commands


def test_every_script_is_executed_by_a_ci_run_command() -> None:
    """A substring match on the whole file proved nothing about execution.

    Every step's ``name:`` title contains its script filename, so replacing a
    step's ``run:`` with ``true`` while keeping the title satisfied the old
    check. Only ``run:`` commands are inspected now.
    """
    commands = "\n".join(workflow_run_commands())
    unwired = [name for name in ALL_SCRIPTS if f"scripts/{name}" not in commands]
    assert not unwired, (
        f"{unwired} exist but appear in no `run:` command in {WORKFLOW.name} — "
        "a title is not an invocation"
    )


def test_the_workflow_run_commands_are_not_the_whole_file() -> None:
    """Falsifiable probe for the test above: titles must not count as commands.

    If ``workflow_run_commands`` ever degraded back into reading the file, this
    fails: the step titles are in the file and not in any ``run:``.
    """
    commands = "\n".join(workflow_run_commands())
    assert "— every canonical fixture replays" not in commands
    assert "name:" not in commands


@pytest.fixture
def ruff() -> str:
    from conftest import require_tool

    return require_tool("ruff")

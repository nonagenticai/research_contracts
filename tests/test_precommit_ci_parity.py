"""`.pre-commit-config.yaml`'s own rule, made executable.

The config opens with:

    # Every hook here must also exist as a CI step. A local gate that is stricter
    # than CI cannot pass and only teaches `--no-verify`.

That was **prose only**, and prose does not fail. Seven upstream hooks --
``check-yaml``, ``check-json``, ``check-added-large-files``, ``check-merge-conflict``,
``check-executables-have-shebangs``, ``check-shebang-scripts-are-executable`` and
``detect-private-key`` -- had no CI step at all, and nothing went red.

The gap was worse than "local is stricter than CI", which is the inversion the comment
warns about. ``.git/hooks/pre-commit`` in this repository is the **fleet ruff+ty script**
(`gitops-production/scripts/hooks/`), not the pre-commit framework, so the config never ran
automatically either. Those seven checks executed **nowhere**: not on commit, not in CI.
They were a declared gate with no runtime.

This file closes that in both directions. A hook with no CI counterpart is red, and a
mapping entry naming a CI command that no longer exists is also red -- so the table cannot
rot into a second piece of prose.
"""

from __future__ import annotations

import re

import yaml
from conftest import ROOT, WORKFLOW

PRE_COMMIT = ROOT / ".pre-commit-config.yaml"

#: Hooks whose CI counterpart is spelled differently from the hook id, mapped to a fragment
#: of the CI ``run:`` that covers them. Each fragment is asserted to appear in the workflow,
#: so an entry here cannot outlive the step it claims.
#:
#: This table is deliberately small and explicit. A regex that "found the hook somewhere in
#: the workflow" would match a comment mentioning it, which is how a gate becomes decorative.
COVERED_BY_A_DIFFERENT_COMMAND: dict[str, str] = {
    # `generated` is part of the fragment on purpose. The two ruff hooks select by FILE TYPE
    # and already covered generated/python/foundation_types.py while these CI steps named
    # three directories and did not -- the local-stricter-than-CI inversion this file exists
    # to catch, in the one directory nothing else in the repository reads. Pinning the
    # widened command here means dropping it from CI is red rather than silent.
    "ruff": "ruff check --no-cache src scripts tests generated",
    "ruff-format": "ruff format --no-cache --check src scripts tests generated",
    "ty": "ty check src scripts tests generated",
    "bandit": "bandit -q -r src scripts -ll",
    "pytest": "uv run pytest",
    # The mapping key is a HOOK NAME, not a credential; detect-secrets reads any
    # `"...secret...": "..."` pair as a Secret Keyword.
    "detect-secrets": "detect-secrets",  # pragma: allowlist secret
    "file-hygiene": "scripts/check_file_hygiene.py",
    "pip-audit": "scripts/pip-audit.sh",
    # The `contract-gates` hook chains five scripts behind `bash -c`; CI runs each as its
    # own step, which is strictly more legible. All five are asserted individually below.
    "contract-gates": "scripts/lint_contracts.py",
}

#: The five scripts the `contract-gates` hook chains, each of which must be a CI step.
CONTRACT_GATE_SCRIPTS = (
    "scripts/lint_contracts.py",
    "scripts/check_draft_governance.py",
    "scripts/verify_canonical_fixtures.py",
    "scripts/verify_foundation_fixtures.py",
    "scripts/generate_types.py --check",
)


def hook_ids() -> list[str]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    return [hook["id"] for repo in config["repos"] for hook in repo["hooks"]]


def ci_run_commands() -> str:
    """Every ``run:`` body in the workflow, concatenated.

    Read from the parsed YAML rather than the raw text, so a hook id appearing in a COMMENT
    cannot satisfy the parity check. That distinction is the whole point: the failure this
    file exists to catch is a gate that is described but not executed.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    commands: list[str] = []
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run")
            if isinstance(run, str):
                commands.append(run)
    return "\n".join(commands)


def test_the_config_and_the_workflow_are_both_readable() -> None:
    """Non-vacuity: an unreadable file would make every assertion below trivially true."""
    assert hook_ids(), "no hooks parsed from .pre-commit-config.yaml"
    assert len(ci_run_commands()) > 500, "no run: commands parsed from the workflow"


def test_the_config_still_claims_every_hook_has_a_ci_step() -> None:
    """The prose rule this file makes executable must still be the stated rule.

    If someone deletes the comment because the rule became inconvenient, the tests below
    would keep passing while the repository had quietly abandoned the policy.
    """
    text = PRE_COMMIT.read_text(encoding="utf-8")
    assert "must also exist as a CI step" in text


def test_every_pre_commit_hook_has_a_ci_counterpart() -> None:
    """The rule, enforced. A hook that runs locally and nowhere in CI is red."""
    commands = ci_run_commands()
    missing = []
    for hook in hook_ids():
        fragment = COVERED_BY_A_DIFFERENT_COMMAND.get(hook, hook)
        if fragment not in commands:
            missing.append(f"{hook} (looked for {fragment!r})")
    assert not missing, (
        "these pre-commit hooks have no CI step, which .pre-commit-config.yaml forbids: "
        + "; ".join(missing)
    )


def test_the_mapping_table_has_no_stale_entries() -> None:
    """Drift in the other direction: an entry naming a CI command that no longer exists.

    Without this, deleting a CI step would stay green as long as its mapping entry survived
    -- the table would be asserting its own contents rather than the workflow's.
    """
    commands = ci_run_commands()
    stale = [
        hook
        for hook, fragment in COVERED_BY_A_DIFFERENT_COMMAND.items()
        if fragment not in commands
    ]
    assert not stale, f"mapping entries name CI commands that do not exist: {stale}"

    known = set(hook_ids())
    unknown = sorted(set(COVERED_BY_A_DIFFERENT_COMMAND) - known)
    assert not unknown, f"mapping entries for hooks that are no longer declared: {unknown}"


def test_every_contract_gate_script_is_its_own_ci_step() -> None:
    """The chained hook is five gates; CI must run all five, not just the first."""
    commands = ci_run_commands()
    missing = [script for script in CONTRACT_GATE_SCRIPTS if script not in commands]
    assert not missing, f"contract-gates chains these, but CI does not run them: {missing}"


def test_the_seven_upstream_hooks_are_named_in_the_ci_step_that_runs_them() -> None:
    """The specific regression: these seven executed nowhere at all.

    Asserted by id rather than by counting, so adding an eighth upstream hook without a CI
    step fails ``test_every_pre_commit_hook_has_a_ci_counterpart`` rather than silently
    shifting a number here.
    """
    commands = ci_run_commands()
    for hook in (
        "check-yaml",
        "check-json",
        "check-added-large-files",
        "check-merge-conflict",
        "check-executables-have-shebangs",
        "check-shebang-scripts-are-executable",
        "detect-private-key",
    ):
        assert hook in commands, f"{hook} still has no CI step"


def test_pre_commit_is_a_declared_dependency() -> None:
    """The CI step invokes ``uv run pre-commit``, so it must be in the locked dev group.

    A step that shells out to a tool nobody installed fails at run time rather than at
    review time -- and on a self-hosted runner it might find a stray global install and
    pass for the wrong reason.
    """
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'"pre-commit>=', pyproject), (
        "the workflow runs `uv run pre-commit` but pre-commit is not in [dependency-groups]"
    )

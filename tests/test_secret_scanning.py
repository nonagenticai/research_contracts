"""The two detect-secrets entry points must be one configuration, not two.

The verified defect: CI passed ``--exclude-files '…|^\\.github/workflows/|…'``
and the pre-commit hook did not. Two separate problems in one line.

* CI was blind to secrets in ``.github/workflows/`` — the file where people most
  often paste a token, and the only file in this repository that legitimately
  references secrets at all;
* the two entry points disagreed, and disagreed in the direction that makes the
  local gate stricter than CI. A local gate stricter than CI cannot pass and
  teaches ``--no-verify``. (It also disagreed the other way: CI passed
  ``--force-use-all-plugins`` and the hook did not.)

The exclusion regex now lives in three places that must be byte-identical — the
workflow, the hook args, and the pattern detect-secrets persists into
``.detect-secrets-baseline.json`` — so this module asserts all three agree and that none of
them excludes the workflows directory. The final test is a live probe: a planted
token in a workflow file must be reported.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from conftest import ROOT, require_tool

WORKFLOW = ROOT / ".github/workflows/ci-public.yml"
PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
BASELINE = ROOT / ".detect-secrets-baseline.json"

#: A GitHub personal-access-token shape. Not a real credential: the digits run
#: 1-0 twice in order, which no issued token does.
PLANTED_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # pragma: allowlist secret

WORKFLOWS_PATH = ".github/workflows/ci-public.yml"


def workflow_document() -> dict[str, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def ci_exclude_regex() -> str:
    """The ``--exclude-files`` regex the CI detect-secrets step actually uses."""
    for job in workflow_document()["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            if "detect-secrets scan" not in run:
                continue
            env = step.get("env") or {}
            assert "EXCLUDE_FILES" in env, (
                "the CI detect-secrets step must carry its exclusion in EXCLUDE_FILES so it "
                "can be compared to the hook's"
            )
            assert '--exclude-files "$EXCLUDE_FILES"' in run, run
            return str(env["EXCLUDE_FILES"])
    raise AssertionError("no CI step runs detect-secrets scan")


def hook_exclude_regex() -> str:
    """The ``--exclude-files`` regex the pre-commit hook actually uses."""
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            if hook["id"] != "detect-secrets":
                continue
            args = [str(arg) for arg in hook.get("args", [])]
            assert "--exclude-files" in args, f"the hook passes no --exclude-files: {args}"
            assert "exclude" not in hook, (
                "pre-commit's `exclude:` filters which files are handed to the hook, which is "
                "a different mechanism from detect-secrets' own --exclude-files; using both is "
                "how the two entry points drifted apart"
            )
            return args[args.index("--exclude-files") + 1]
    raise AssertionError("no detect-secrets hook in .pre-commit-config.yaml")


def baseline_exclude_regex() -> str:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    patterns = [
        pattern
        for entry in baseline["filters_used"]
        if entry["path"].endswith("should_exclude_file")
        for pattern in entry["pattern"]
    ]
    assert len(patterns) == 1, f"expected exactly one exclusion pattern, got {patterns}"
    return patterns[0]


def test_ci_and_the_local_hook_use_the_same_exclusion() -> None:
    assert ci_exclude_regex() == hook_exclude_regex()


def test_the_baseline_persists_the_same_exclusion() -> None:
    """The baseline carries the filter too; a third spelling is a third policy."""
    assert baseline_exclude_regex() == ci_exclude_regex()


def test_no_entry_point_excludes_the_workflows_directory() -> None:
    """The exact defect: the one directory that holds secret references was skipped."""
    import re

    for label, pattern in (
        ("CI", ci_exclude_regex()),
        ("pre-commit", hook_exclude_regex()),
        ("baseline", baseline_exclude_regex()),
    ):
        assert re.search(pattern, WORKFLOWS_PATH) is None, (
            f"{label} excludes {WORKFLOWS_PATH} from secret scanning"
        )


def test_the_baseline_pins_every_plugin() -> None:
    """``--force-use-all-plugins`` is scan-only; the hook has no such flag.

    A ``--baseline`` run uses the plugins the baseline names. The two entry
    points are therefore equivalent only while the baseline names all of them —
    so that is asserted rather than assumed.
    """
    detect_secrets = require_tool("detect-secrets")
    listing = subprocess.run(
        [detect_secrets, "scan", "--list-all-plugins"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert listing.returncode == 0, listing.stderr
    available = {line.strip() for line in listing.stdout.splitlines() if line.strip()}
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    pinned = {plugin["name"] for plugin in baseline["plugins_used"]}
    assert pinned == available, (
        f"the baseline pins {len(pinned)} plugins but detect-secrets ships {len(available)}; "
        f"missing: {sorted(available - pinned)}"
    )


def git_free_env() -> dict[str, str]:
    """The environment with every ``GIT_*`` variable removed.

    ``cwd=`` does NOT isolate a ``git`` subprocess. Git exports ``GIT_DIR`` and
    ``GIT_INDEX_FILE`` into every hook it runs, and those variables outrank the working
    directory: a ``git add -A`` launched from a scratch directory then writes into the
    *inherited* repository's index instead of the scratch one.

    That is not hypothetical. Under the repository's ``pre-push`` hook, which runs this
    suite, the test below staged its two-line planted ``ci-public.yml`` into the real
    worktree's index and staged a deletion for all 194 tracked files absent from
    ``tmp_path``. Two agents hit the resulting phantom mass-deletion independently, and
    ``git reset`` was the only thing standing between it and someone "recovering" a
    worktree that was never damaged. Reproduced exactly by exporting ``GIT_INDEX_FILE``
    and ``GIT_DIR`` before running this one test; ``test_the_git_subprocesses_are_isolated_
    from_an_inherited_repository`` pins the fix.
    """
    return {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}


def test_the_git_subprocesses_are_isolated_from_an_inherited_repository(tmp_path: Path) -> None:
    """Falsifiable probe: a ``git`` call must not follow an inherited ``GIT_INDEX_FILE``.

    Fails on the unfixed code — ``git add -A`` writes ``decoy`` — and passes on the fixed
    code. Uses a decoy index inside ``tmp_path`` rather than the real one, so the probe
    cannot damage the worktree it protects.
    """
    git = require_tool("git")
    scratch = tmp_path / "repo"
    scratch.mkdir()
    (scratch / "file.txt").write_text("x", encoding="utf-8")
    decoy_index = tmp_path / "decoy-index"

    hook_env = {**os.environ, "GIT_INDEX_FILE": str(decoy_index)}
    for command in ([git, "init", "-q", "."], [git, "add", "-A"]):
        os.environ.update(hook_env)
        try:
            result = subprocess.run(
                command, check=False, capture_output=True, cwd=str(scratch), env=git_free_env()
            )
        finally:
            os.environ.pop("GIT_INDEX_FILE", None)
        assert result.returncode == 0, result.stderr

    assert not decoy_index.exists(), (
        "a git subprocess followed the inherited GIT_INDEX_FILE instead of its cwd; under a "
        "git hook that variable points at the real worktree index"
    )
    assert (scratch / ".git").is_dir()


def test_a_secret_planted_in_a_workflow_is_reported(tmp_path: Path) -> None:
    """Live probe. Without the fix this scan reported nothing at all.

    Run against a throwaway copy of the repository so the committed baseline is
    never rewritten: ``detect-secrets scan --baseline X`` overwrites X in place,
    and a scoped scan can prune entries out of it.
    """
    detect_secrets = require_tool("detect-secrets")
    git = require_tool("git")
    scratch = tmp_path / "repo"
    (scratch / ".github/workflows").mkdir(parents=True)
    shutil.copyfile(BASELINE, scratch / ".detect-secrets-baseline.json")
    (scratch / ".github/workflows/ci-public.yml").write_text(
        f"env:\n  PLANTED: {PLANTED_TOKEN}\n", encoding="utf-8"
    )
    # A directory scan enumerates via `git ls-files`, exactly as it does in CI.
    for command in ([git, "init", "-q", "."], [git, "add", "-A"]):
        created = subprocess.run(
            command, check=False, capture_output=True, cwd=str(scratch), env=git_free_env()
        )
        assert created.returncode == 0, created.stderr

    result = subprocess.run(
        [
            detect_secrets,
            "scan",
            "--baseline",
            ".detect-secrets-baseline.json",
            "--force-use-all-plugins",
            "--exclude-files",
            ci_exclude_regex(),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(scratch),
    )
    assert result.returncode == 0, result.stderr
    scanned = json.loads((scratch / ".detect-secrets-baseline.json").read_text(encoding="utf-8"))
    assert WORKFLOWS_PATH in scanned["results"], (
        f"a planted token in a workflow file was not reported: {sorted(scanned['results'])}"
    )


def test_the_committed_baseline_is_unchanged_by_the_probe() -> None:
    """The probe above must not have rewritten or pruned the real baseline."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert sorted(baseline["results"]) == [
        # IEEE-754 double bit patterns from the RFC 8785 es6testfile vectors.
        "fixtures/canonical-hash/v1/rfc8785/number-serialization.json",
        # The `canonical_counts_hash` of the flow-ledger fixture: the digest the
        # producer's own `flow_derivation.canonical_counts_hash` produces over that
        # fixture's counts block. A content address, not a credential, and
        # deliberately the REAL one rather than an invented hex string.
        "tests/test_review_flow_ledger_schema.py",
    ]

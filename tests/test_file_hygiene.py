"""The whitespace gate must be one configuration, and it must never rewrite.

The verified defect: ``.pre-commit-config.yaml`` ran the upstream
``end-of-file-fixer`` and ``trailing-whitespace`` hooks. Both rewrite tracked
files, neither existed as a CI step, and ``pre-commit run --all-files`` mutated
29 tracked files on ``main`` while CI was green.

This module asserts the replacement gate is (a) one command shared by the hook
and CI, (b) falsifiable in every rule it claims, with a false-positive control,
and (c) incapable of writing to the tree it inspects.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import ROOT, SCRIPTS, WORKFLOW, require_tool, run_script

from research_contracts.tooling.file_hygiene import (
    BINARY_BYTE_FILES,
    git_free_env,
    tracked_files,
)

PRE_COMMIT = ROOT / ".pre-commit-config.yaml"
SCRIPT = "check_file_hygiene.py"
HOOK_ID = "file-hygiene"

#: The hooks that rewrote tracked files. They must not come back: a hook that
#: edits a tracked file mid-commit is what silently re-digested the fixture.
REWRITING_HOOK_IDS = frozenset({"trailing-whitespace", "end-of-file-fixer"})


# --------------------------------------------------------------------------
# The hook and the CI step are one command
# --------------------------------------------------------------------------


def pre_commit_document() -> dict[str, object]:
    document = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def hook_entries() -> dict[str, dict[str, object]]:
    hooks: dict[str, dict[str, object]] = {}
    for repo in pre_commit_document()["repos"]:  # ty: ignore[not-iterable]
        for hook in repo["hooks"]:
            hooks[hook["id"]] = hook
    return hooks


def ci_run_commands() -> list[str]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [
        step["run"]
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step.get("run"), str)
    ]


def test_the_hook_and_the_ci_step_are_the_same_command() -> None:
    """Byte-identical, not merely similar: a paraphrase is a second policy."""
    hooks = hook_entries()
    assert HOOK_ID in hooks, f"{HOOK_ID} is not configured in {PRE_COMMIT.name}"
    entry = str(hooks[HOOK_ID]["entry"])
    matching = [command for command in ci_run_commands() if SCRIPT in command]
    assert matching, f"no CI step in {WORKFLOW.name} runs {SCRIPT}"
    assert matching == [entry], (
        f"the hook runs {entry!r} and CI runs {matching!r}; the two entry points must be one "
        "command or they will drift back into a local-stricter-than-CI inversion"
    )


def test_the_hook_checks_the_same_file_set_as_ci() -> None:
    """CI has no staged-file list, so the hook must not be given one either.

    ``pass_filenames: false`` plus ``always_run: true`` means both entry points
    enumerate the git index. A hook handed only the staged paths would inspect a
    strictly smaller set than CI, and a hook that skipped when no file matched
    would inspect none at all.
    """
    hook = hook_entries()[HOOK_ID]
    assert hook["pass_filenames"] is False
    assert hook["always_run"] is True
    assert "files" not in hook and "exclude" not in hook and "types" not in hook


def test_no_rewriting_hook_survives() -> None:
    """The exact defect: hooks that edit tracked files during a commit.

    A rewriting hook re-creates the exact defect this gate replaced: the tree it
    edits mid-commit is not the tree that was reviewed.
    """
    present = REWRITING_HOOK_IDS & set(hook_entries())
    assert not present, (
        f"{sorted(present)} rewrite tracked files and have no CI counterpart; "
        "a hook that edits a tracked file mid-commit is how the reviewed tree and the "
        "committed tree stop being the same tree"
    )


# --------------------------------------------------------------------------
# The gate is green on the committed tree — the false-positive control
# --------------------------------------------------------------------------


def test_the_gate_is_green_on_the_committed_tree() -> None:
    """Control for every probe below: an unmodified checkout must pass."""
    result = run_script(SCRIPT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "file hygiene passed" in result.stdout


def test_the_gate_enumerated_a_non_empty_tree() -> None:
    """An empty enumeration renders as a clean one; it must not be reachable."""
    result = run_script(SCRIPT)
    count = int(result.stdout.split("passed:")[1].split()[0])
    assert count > 100, f"the gate inspected only {count} files: {result.stdout!r}"


# --------------------------------------------------------------------------
# Falsification: each rule the gate claims must actually fire
# --------------------------------------------------------------------------


def make_repo(tmp_path: Path) -> Path:
    """A minimal git repository with no violations."""
    git = require_tool("git")
    tree = tmp_path / "repo"
    tree.mkdir()
    (tree / "clean.txt").write_text("clean\n", encoding="utf-8")

    for command in ([git, "init", "-q", "."], [git, "add", "-A"]):
        created = subprocess.run(
            command, check=False, capture_output=True, cwd=str(tree), env=git_free_env()
        )
        assert created.returncode == 0, created.stderr
    return tree


def stage(tree: Path) -> None:
    git = require_tool("git")
    added = subprocess.run(
        [git, "add", "-A"], check=False, capture_output=True, cwd=str(tree), env=git_free_env()
    )
    assert added.returncode == 0, added.stderr


def test_a_constructed_repository_is_green_before_anything_is_planted(tmp_path: Path) -> None:
    """The second control: the scratch tree must pass before it is broken."""
    tree = make_repo(tmp_path)
    result = run_script(SCRIPT, "--root", tree)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"trailing space \nand more\n", "trailing whitespace"),
        (b"trailing tab\t\n", "trailing whitespace"),
        (b"no final newline", "does not end with a newline"),
        (b"two final newlines\n\n", "ends with more than one newline"),
    ],
)
def test_a_planted_violation_is_red(tmp_path: Path, content: bytes, expected: str) -> None:
    tree = make_repo(tmp_path)
    (tree / "planted.txt").write_bytes(content)
    stage(tree)
    result = run_script(SCRIPT, "--root", tree)
    assert result.returncode == 1, f"{content!r} was accepted: {result.stdout}"
    assert expected in result.stderr, result.stderr
    assert "planted.txt" in result.stderr


def test_an_untracked_file_is_not_checked(tmp_path: Path) -> None:
    """The inverse inversion: local must not be stricter than CI either.

    A CI checkout has no scratch files. If the gate walked the filesystem instead
    of the index, an untracked local scratch file would fail the hook and pass
    CI — the same inversion in the opposite direction.
    """
    tree = make_repo(tmp_path)
    (tree / "scratch.txt").write_bytes(b"untracked trailing space \n\n")
    result = run_script(SCRIPT, "--root", tree)
    assert result.returncode == 0, result.stdout + result.stderr


# --------------------------------------------------------------------------
# A raw NUL byte is an error, not a skip
# --------------------------------------------------------------------------


def test_a_planted_nul_byte_is_red(tmp_path: Path) -> None:
    """The gate used to ``continue`` past any file containing a 0x00.

    ``packages/typescript/src/structural.ts`` carried exactly one, at offset 22323, written
    as a raw byte instead of the ``\\x00`` escape inside a template literal. It passed this
    gate for its whole life while ``file`` called it ``data``, ``grep -n const`` printed
    nothing and exited 1, and ripgrep and ``gh search code`` returned no hits at all -- so
    every repository-wide census was blind to all 870 lines of the cross-field collector.
    """
    tree = make_repo(tmp_path)
    (tree / "planted.ts").write_bytes(b"const marker = `a\x00b`;\n")
    stage(tree)
    result = run_script(SCRIPT, "--root", tree)
    assert result.returncode == 1, f"a raw NUL was accepted: {result.stdout}"
    assert "raw NUL byte" in result.stderr, result.stderr
    assert "planted.ts:17" in result.stderr, result.stderr


def test_the_escaped_form_of_the_same_source_is_green(tmp_path: Path) -> None:
    """The false-positive control, and the shape the real fix takes: the escape carries the
    identical runtime value and is plain text, so the gate must accept it."""
    tree = make_repo(tmp_path)
    (tree / "planted.ts").write_bytes(rb"const marker = `a\x00b`;" + b"\n")
    stage(tree)
    result = run_script(SCRIPT, "--root", tree)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_stale_binary_exemption_is_red(tmp_path: Path) -> None:
    """An exemption that exempts nothing must not render as a pass. Without this, a path
    could stay on the list after the file was fixed and silently cover the next raw NUL."""
    tree = make_repo(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;"
            "from research_contracts.tooling import file_hygiene as m;"
            "m.BINARY_BYTE_FILES = ('never-existed.bin',);"
            "sys.exit(m.main(['--root', sys.argv[1]]))",
            str(tree),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "stale exemption" in result.stderr, result.stderr


def test_no_tracked_file_in_this_repository_carries_a_nul() -> None:
    """The corpus measurement that makes the empty exemption list a fact, not a guess.

    Recomputed from ``git ls-files`` rather than listed, so a binary fixture added later
    fails here until it is named in ``BINARY_BYTE_FILES`` on purpose.
    """
    names = tracked_files(ROOT)
    assert len(names) > 100, len(names)  # non-vacuity: an empty index proves nothing
    carrying = [
        name
        for name in names
        if (ROOT / name).is_file()
        and not (ROOT / name).is_symlink()
        and b"\x00" in (ROOT / name).read_bytes()
    ]
    assert carrying == list(BINARY_BYTE_FILES), carrying


def test_the_typescript_collector_is_readable_by_a_text_tool() -> None:
    """The regression itself, stated as the property that was lost: a source file every
    audit has to be able to grep. Asserted through the same byte the gate rejects, and with
    a positive control so "no NUL found" cannot be "no file read"."""
    source = (ROOT / "packages/typescript/src/structural.ts").read_bytes()
    assert b"collectCrossFieldRuleSites" in source, "the collector source was not read at all"
    assert b"\x00" not in source
    assert rb"`${identityMarker(rule)}\x00${JSON.stringify(steps)}`" in source


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# The citation count is an EXACT PIN, not a floor of one
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# The gate must not write, and must not follow an inherited repository
# --------------------------------------------------------------------------


def snapshot(tree: Path) -> dict[Path, bytes]:
    """Every worktree file and its bytes. ``.git/`` is excluded: git's own
    metadata is not what the gate must leave alone, the tracked content is."""
    return {
        path: path.read_bytes()
        for path in sorted(tree.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(tree).parts
    }


def test_the_gate_reports_and_never_rewrites(tmp_path: Path) -> None:
    """The shape defect, pinned: a check may not edit the tree it inspects."""
    tree = make_repo(tmp_path)
    (tree / "planted.txt").write_bytes(b"trailing space \n\n")
    stage(tree)
    before = snapshot(tree)
    result = run_script(SCRIPT, "--root", tree)
    assert result.returncode == 1
    after = snapshot(tree)
    changed = sorted(str(path) for path in before if before[path] != after.get(path))
    assert not changed, f"the gate rewrote {changed}; it must report, never fix"
    assert set(before) == set(after)


def test_the_gate_ignores_an_inherited_git_directory(tmp_path: Path) -> None:
    """``--root`` must mean the root, even under a git hook.

    Git exports ``GIT_DIR`` and ``GIT_INDEX_FILE`` into every hook it runs, and
    those outrank ``cwd=``. This gate runs as a pre-commit hook and enumerates
    with ``git ls-files``, so without the ``GIT_*`` strip it would enumerate the
    inherited repository — reporting the real repository's files while claiming
    to inspect ``--root``, or writing into the real index.
    """
    tree = make_repo(tmp_path)
    (tree / "planted.txt").write_bytes(b"trailing space \n\n")
    stage(tree)
    hostile = {
        **os.environ,
        "GIT_DIR": str(ROOT / ".git"),
        "GIT_INDEX_FILE": str(tmp_path / "decoy-index"),
        "GIT_WORK_TREE": str(ROOT),
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / SCRIPT), "--root", str(tree)],
        check=False,
        capture_output=True,
        text=True,
        env=hostile,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "planted.txt" in result.stderr, (
        "the gate did not enumerate --root; it followed the inherited GIT_DIR"
    )
    assert not (tmp_path / "decoy-index").exists()


def test_the_gate_fails_loudly_outside_a_repository(tmp_path: Path) -> None:
    """A gate that cannot enumerate must be red, never a silent zero-file pass."""
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    result = run_script(SCRIPT, "--root", bare)
    assert result.returncode == 1, result.stdout
    assert "git ls-files" in result.stderr

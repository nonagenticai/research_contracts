"""Regression tests for the governance gate.

**Inverted 2026-08-08 with the gate itself (IMP-DEC-001, Python half).** The gate
used to assert the repository was an explicitly *blocked* draft; it now asserts
governance is explicitly *assigned*. Every structural defect below is still
covered, because each one is about how the file is read, not about which value it
is read to hold — a substring grep, a cwd anchor and a dead filter are equally
wrong in both directions.

Baseline defects covered here:

* D3 the gate was a substring grep, so an ``OWNERS.yaml`` whose real state
  contradicted the required strings passed as long as those strings appeared
  anywhere — including inside a ``notes:`` history string. Probed in both
  directions now: a blocked file wearing assigned-looking prose, and an assigned
  file wearing blocked-looking prose.
* D4 the gate was cwd-anchored, not repo-anchored: it tracebacked from ``/tmp``
  and reported green from a scratch directory holding a copied ``OWNERS.yaml``
  and no records directory at all.
* D5 ``if path.name != ".gitkeep"`` filtered a ``glob("*.json")`` that can never
  yield a ``.gitkeep``, so the filter was dead code.

And the property the inversion adds:

* A promotion that is real at the root and hollow one level down is a
  half-assignment, and must be rejected wherever the placeholder hides.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import ROOT, run_script

SCRIPT = "check_draft_governance.py"
ASSIGNED_OWNERS = yaml.safe_load((ROOT / "OWNERS.yaml").read_text(encoding="utf-8"))

#: The mirror of the old D3 probe: every governance key present and every
#: assigned-looking string available to a grep, while the real state is blocked.
BLOCKED_OWNERS = {
    "lifecycle": "draft",
    "candidate_status": "blocked",
    "accountable_owner": "UNASSIGNED",
    "accountable_reviewer": "UNASSIGNED",
    "schema_version_policy": "UNASSIGNED",
    "model_source_repository": "UNASSIGNED",
    "model_source_revision_policy": "UNASSIGNED",
    "blocking_decisions": {"IMP-DEC-001": "UNASSIGNED"},
    "deferred_decisions": {"IMP-DEC-001-NPM": "UNASSIGNED"},
    "notes": [
        "history: promoted to lifecycle: candidate / candidate_status: candidate with "
        "accountable_owner: georgiedekker and accountable_reviewer: georgiedekker "
        "once IMP-DEC-001 was ratified as research-contracts",
    ],
}


def make_repo(root: Path, owners: object, *, records: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "OWNERS.yaml").write_text(yaml.safe_dump(owners, sort_keys=False), encoding="utf-8")
    if records:
        records_dir = root / "review-records"
        records_dir.mkdir(parents=True, exist_ok=True)
        (records_dir / ".gitkeep").write_text("", encoding="utf-8")
    return root


def check(root: Path) -> subprocess.CompletedProcess[str]:
    return run_script(SCRIPT, "--repo-root", root)


def test_repository_governance_is_explicitly_assigned() -> None:
    result = run_script(SCRIPT)
    assert result.returncode == 0, result.stderr
    assert "explicitly assigned" in result.stdout


def test_constructed_assigned_repo_passes(tmp_path: Path) -> None:
    result = check(make_repo(tmp_path / "repo", ASSIGNED_OWNERS))
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# D3 — parse YAML, assert the real state, in both directions
# --------------------------------------------------------------------------


def test_blocked_owners_file_with_assigned_history_notes_is_rejected(tmp_path: Path) -> None:
    """The exact probe, mirrored: assigned-looking substrings inside a notes string."""
    result = check(make_repo(tmp_path / "repo", BLOCKED_OWNERS))
    assert result.returncode == 1, result.stdout
    assert "'lifecycle' must be one of" in result.stderr
    assert "must hold an assigned value" in result.stderr


def test_notes_prose_mentioning_draft_is_still_accepted(tmp_path: Path) -> None:
    """Falsifiable control for the probe above: prose is prose, not state."""
    owners = {
        **ASSIGNED_OWNERS,
        "notes": ["history: this repository was lifecycle: draft / candidate_status: blocked"],
    }
    result = check(make_repo(tmp_path / "repo", owners))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("lifecycle", "draft"),
        ("lifecycle", "retired"),
        ("candidate_status", "blocked"),
        ("accountable_owner", "UNASSIGNED"),
        ("accountable_owner", "unassigned"),
        ("accountable_owner", " UNASSIGNED"),
        ("accountable_reviewer", "TBD"),
        ("schema_version_policy", "placeholder"),
        ("model_source_repository", "n/a"),
        ("model_source_revision_policy", "ACCOUNTABLE_REVIEWER"),
    ],
)
def test_any_unassigned_governance_key_is_rejected(tmp_path: Path, key: str, value: str) -> None:
    owners = {**ASSIGNED_OWNERS, key: value}
    result = check(make_repo(tmp_path / "repo", owners))
    assert result.returncode == 1, f"{key}={value!r} passed: {result.stdout}"


@pytest.mark.parametrize("key", list(ASSIGNED_OWNERS))
def test_removing_any_governance_key_is_rejected(tmp_path: Path, key: str) -> None:
    if key == "notes":
        pytest.skip("notes is prose, not governance state")
    owners = {name: value for name, value in ASSIGNED_OWNERS.items() if name != key}
    result = check(make_repo(tmp_path / "repo", owners))
    assert result.returncode == 1, f"removing {key!r} passed: {result.stdout}"


def test_unratified_blocking_decision_is_rejected(tmp_path: Path) -> None:
    owners = {**ASSIGNED_OWNERS, "blocking_decisions": {"IMP-DEC-001": "UNASSIGNED"}}
    result = check(make_repo(tmp_path / "repo", owners))
    assert result.returncode == 1
    assert "IMP-DEC-001" in result.stderr


def test_missing_blocking_decisions_mapping_is_rejected(tmp_path: Path) -> None:
    owners = {key: value for key, value in ASSIGNED_OWNERS.items() if key != "blocking_decisions"}
    result = check(make_repo(tmp_path / "repo", owners))
    assert result.returncode == 1
    assert "blocking_decisions" in result.stderr


# --------------------------------------------------------------------------
# The still-blocked half stays blocked by the original mechanism
# --------------------------------------------------------------------------


def test_silently_promoting_a_deferred_decision_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing a deferred decision must mean editing the gate, not only the YAML.

    ⚠️ This test used to name ``IMP-DEC-001-NPM`` and read it out of the real
    ``OWNERS.yaml``. That decision was **ratified 2026-09-04** and
    ``REQUIRED_DEFERRED_DECISIONS`` is now empty, so a test pinned to it fails on a
    ``KeyError`` and says nothing about the mechanism.

    Deleting it would have been the easy move and the wrong one: the guard it proves
    is the reason nobody could add an npm publish step for a month, and the next
    genuinely-open decision needs that guard intact. So the test now proves the
    MECHANISM against a synthetic decision it injects itself, and therefore keeps
    working whether the real tuple is empty or full. A gate whose only proof
    evaporates the moment it is first used successfully is not a gate.
    """
    from research_contracts.tooling import governance

    monkeypatch.setattr(governance, "REQUIRED_DEFERRED_DECISIONS", ("IMP-DEC-SYNTHETIC",))
    owners = {
        **ASSIGNED_OWNERS,
        "deferred_decisions": {"IMP-DEC-SYNTHETIC": "@nonagentic/some-decided-value"},
    }
    errors = governance.governance_errors(make_repo(tmp_path / "repo", owners))
    assert any("IMP-DEC-SYNTHETIC" in e and "must still be 'UNASSIGNED'" in e for e in errors), (
        errors
    )


def test_the_real_deferred_tuple_and_owners_file_agree() -> None:
    """Whatever is declared open in the module is declared open in the YAML, and vice versa.

    The two halves of the guard are in different files and nothing but this
    assertion keeps them honest. An entry in the module with no row in the YAML is a
    gate that fails for a decision nobody recorded; a row in the YAML with no entry
    in the module is a decision that looks blocked and is not.
    """
    from research_contracts.tooling import governance

    declared = set(governance.REQUIRED_DEFERRED_DECISIONS)
    recorded = set(ASSIGNED_OWNERS.get("deferred_decisions") or {})
    assert declared == recorded


def test_deleting_the_deferred_decisions_mapping_is_rejected(tmp_path: Path) -> None:
    """Deleting the open decision is not the same fact as closing it."""
    owners = {key: value for key, value in ASSIGNED_OWNERS.items() if key != "deferred_decisions"}
    result = check(make_repo(tmp_path / "repo", owners))
    assert result.returncode == 1
    assert "deferred_decisions" in result.stderr


# --------------------------------------------------------------------------
# A half-assignment is a failure wherever the placeholder hides
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "graft",
    [
        {"extra": {"owner": "TBD"}},
        {"extra": {"nested": {"deeper": {"reviewer": "UNASSIGNED"}}}},
        {"notes": [{"owner": "placeholder"}]},
        {"history": {"lifecycle": "draft"}},
        {"history": {"candidate_status": "blocked"}},
    ],
)
def test_a_hollow_promotion_is_rejected_at_any_depth(tmp_path: Path, graft: dict) -> None:
    owners = {**ASSIGNED_OWNERS, **graft}
    result = check(make_repo(tmp_path / "repo", owners))
    assert result.returncode == 1, f"{graft} passed: {result.stdout}"


def test_a_placeholder_under_deferred_decisions_is_the_one_legitimate_place(
    tmp_path: Path,
) -> None:
    """Falsifiable control: the exemption is scoped to the key that needs it.

    ⚠️ Rewritten 2026-09-04, same reason as the test above. This used to read
    ``IMP-DEC-001-NPM`` straight out of the real ``OWNERS.yaml`` to show that a
    placeholder is tolerated under ``deferred_decisions``. That decision is now
    ratified and ``deferred_decisions`` is an empty mapping, so the old assertion
    raised ``KeyError`` and proved nothing.

    The control is worth keeping and is stronger stated as a pair, so it now asserts
    BOTH directions with a placeholder it injects itself: tolerated under
    ``deferred_decisions``, rejected one key over. A one-sided control cannot fail
    for the reason it exists.
    """
    assert check(make_repo(tmp_path / "repo", ASSIGNED_OWNERS)).returncode == 0

    tolerated = {
        **ASSIGNED_OWNERS,
        "deferred_decisions": {"IMP-DEC-SYNTHETIC": "UNASSIGNED"},
    }
    assert check(make_repo(tmp_path / "tolerated", tolerated)).returncode == 0

    rejected = {**ASSIGNED_OWNERS, "accountable_reviewer": "UNASSIGNED"}
    result = check(make_repo(tmp_path / "rejected", rejected))
    assert result.returncode == 1, result.stdout


def test_the_placeholder_vocabulary_is_read_from_the_meta_schema() -> None:
    """It is not restated here or in the gate; a second blacklist is defect D12."""
    schema = json.loads(
        (ROOT / "schemas/meta/assigned-identifier.v1.schema.json").read_text(encoding="utf-8")
    )
    from research_contracts.tooling.governance import _assigned_identifier_schema

    assert _assigned_identifier_schema() == schema["$defs"]["assignedIdentifier"]


# --------------------------------------------------------------------------
# Parse failures are diagnosed, not tracebacked
# --------------------------------------------------------------------------


def test_non_mapping_owners_file_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "OWNERS.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    result = check(root)
    assert result.returncode == 1
    assert "must parse to a YAML mapping" in result.stderr


def test_unparseable_owners_file_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "OWNERS.yaml").write_text("lifecycle: [candidate\n", encoding="utf-8")
    result = check(root)
    assert result.returncode == 1


# --------------------------------------------------------------------------
# D4 — repo-anchored, and a missing path fails loudly
# --------------------------------------------------------------------------


def test_gate_is_repo_anchored_not_cwd_anchored(tmp_path: Path) -> None:
    """Run from an unrelated cwd; the real repository is still what gets checked."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = run_script(SCRIPT, cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert str(ROOT) in result.stdout


def test_copied_owners_file_without_a_records_directory_fails(tmp_path: Path) -> None:
    """The exact probe: a missing directory globbed to [] and read as 'no records'."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    shutil.copy(ROOT / "OWNERS.yaml", scratch / "OWNERS.yaml")
    result = run_script(SCRIPT, "--repo-root", scratch, cwd=scratch)
    assert result.returncode == 1, result.stdout
    assert "required directory is missing" in result.stderr


def test_missing_owners_file_fails_with_a_diagnosis_not_a_traceback(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run_script(SCRIPT, "--repo-root", empty, cwd=empty)
    assert result.returncode == 1
    assert "required governance file is missing" in result.stderr
    assert "Traceback" not in result.stderr


# --------------------------------------------------------------------------
# D5 / V1 — the records enumeration must recurse, and must not follow a symlink
#
# Records are legitimate now that governance is assigned, so they are REPORTED
# rather than treated as an error. The enumeration is still what distinguishes
# "none were filed" from "the directory could not be read", so every recursion
# and symlink guarantee stays asserted — through stdout instead of stderr.
# --------------------------------------------------------------------------


def test_no_records_is_stated_explicitly_not_silently(tmp_path: Path) -> None:
    result = check(make_repo(tmp_path / "repo", ASSIGNED_OWNERS))
    assert result.returncode == 0, result.stderr
    assert "conformance records on file: none" in result.stdout


def test_a_review_record_is_reported(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", ASSIGNED_OWNERS)
    (root / "review-records/FND-001.v1.json").write_text(
        json.dumps({"package_id": "FND-001"}), encoding="utf-8"
    )
    result = check(root)
    assert result.returncode == 0, result.stderr
    assert "FND-001.v1.json" in result.stdout


def test_a_non_json_review_record_is_also_reported(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", ASSIGNED_OWNERS)
    (root / "review-records/FND-001.v1.yaml").write_text("x: 1\n", encoding="utf-8")
    result = check(root)
    assert result.returncode == 0, result.stderr
    assert "FND-001.v1.yaml" in result.stdout


@pytest.mark.parametrize(
    "relative",
    [
        "fnd-002/FND-002.v1.json",
        "fnd-002/v1/FND-002.json",
        "by-package/kag/kag-context.v1.yaml",
        "a/b/c/d/deeply-filed.json",
    ],
)
def test_a_record_in_a_subfolder_is_reported(tmp_path: Path, relative: str) -> None:
    """``iterdir()`` + ``is_file()`` saw only the top level.

    Per-package subfoldering is the obvious filing pattern, and it was invisible.
    """
    root = make_repo(tmp_path / "repo", ASSIGNED_OWNERS)
    record = root / "review-records" / relative
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"package_id": "FND-002"}), encoding="utf-8")
    result = check(root)
    assert result.returncode == 0, result.stderr
    assert relative in result.stdout, f"{relative} was invisible: {result.stdout}"


def test_a_gitkeep_in_a_subfolder_is_still_not_a_record(tmp_path: Path) -> None:
    """Falsifiable control: recursion must not start counting placeholders."""
    root = make_repo(tmp_path / "repo", ASSIGNED_OWNERS)
    nested = root / "review-records/fnd-002"
    nested.mkdir(parents=True)
    (nested / ".gitkeep").write_text("", encoding="utf-8")
    result = check(root)
    assert result.returncode == 0, result.stderr
    assert "conformance records on file: none" in result.stdout


def test_a_records_directory_replaced_by_a_symlink_is_rejected(tmp_path: Path) -> None:
    """``is_dir()`` follows symlinks, so a link to an empty directory exited 0.

    The deliberate decision is *not* to follow it: the real records can then sit
    anywhere on the runner while the gate inspects a decoy, and this repository
    has no legitimate use for a symlinked records directory.
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "OWNERS.yaml").write_text(
        yaml.safe_dump(ASSIGNED_OWNERS, sort_keys=False), encoding="utf-8"
    )
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (root / "model-conformance").mkdir()
    (root / "review-records").symlink_to(decoy, target_is_directory=True)
    result = check(root)
    assert result.returncode == 1, result.stdout
    assert "must be a real directory, not a symlink" in result.stderr


def test_a_symlinked_record_inside_the_directory_is_reported(tmp_path: Path) -> None:
    """A symlinked *entry* is an entry; only the directory itself is refused."""
    root = make_repo(tmp_path / "repo", ASSIGNED_OWNERS)
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"package_id": "FND-003"}), encoding="utf-8")
    (root / "review-records/linked.json").symlink_to(target)
    result = check(root)
    assert result.returncode == 0, result.stderr
    assert "linked.json" in result.stdout


def test_an_unreadable_records_directory_is_diagnosed_not_tracebacked(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", ASSIGNED_OWNERS)
    records_dir = root / "review-records"
    records_dir.chmod(0o000)
    try:
        result = check(root)
    finally:
        records_dir.chmod(0o755)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "not evidence" in result.stderr


def test_an_unreadable_owners_file_is_diagnosed_not_tracebacked(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", ASSIGNED_OWNERS)
    owners = root / "OWNERS.yaml"
    owners.chmod(0o000)
    try:
        result = check(root)
    finally:
        owners.chmod(0o644)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


# --------------------------------------------------------------------------
# Strict loading — duplicate keys cannot hide a state behind a later one
# --------------------------------------------------------------------------


def test_a_duplicate_key_in_owners_is_rejected(tmp_path: Path) -> None:
    """PyYAML silently takes the last of duplicate keys.

    ``lifecycle: draft`` followed by ``lifecycle: candidate`` must not read as
    assigned; the file is ambiguous and ambiguity is not evidence.
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    records_dir = root / "review-records"
    records_dir.mkdir(parents=True)
    (records_dir / ".gitkeep").write_text("", encoding="utf-8")
    body = yaml.safe_dump(ASSIGNED_OWNERS, sort_keys=False)
    (root / "OWNERS.yaml").write_text(f"lifecycle: draft\n{body}", encoding="utf-8")
    result = check(root)
    assert result.returncode == 1, result.stdout

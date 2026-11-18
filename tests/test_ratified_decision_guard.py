"""``REQUIRED_ASSIGNED_DECISIONS`` was a surviving mutant. This is what observes it.

WHAT WAS WRONG
==============

Measured on ``main`` at ``e82395a``: emptying ``governance.REQUIRED_ASSIGNED_DECISIONS``
to ``()`` left the **entire suite green**. The one test that looks like it covers
the guard — ``test_unratified_blocking_decision_is_rejected`` — writes
``blocking_decisions: {"IMP-DEC-001": "UNASSIGNED"}`` and asserts exit 1. It does
get exit 1, but from the *generic* placeholder scan, which rejects the string
``UNASSIGNED`` anywhere outside ``deferred_decisions``. Delete the guard entirely
and that test still passes.

The consequence was not theoretical. ``OWNERS.yaml`` records three ratified
decisions and the tuple named **one**, so ``IMP-DEC-001-NPM`` (the npm scope and
package name) and ``IMP-DEC-002`` (the JWS parameters, and the explicit statement
that the attestation ISSUER is still unowned) could be **deleted from the file
outright** and the gate reported green. Deletion is the case the generic scan is
blind to by construction: it scans values, and a deleted key has no value.

THE TWO EMPTY TUPLES, AND HOW TO TELL THEM APART
================================================

``governance.py`` has two sibling constants and one of them is **legitimately
empty**:

* ``REQUIRED_DEFERRED_DECISIONS = ()`` was emptied on 2026-09-04 as a sanctioned
  act when ``IMP-DEC-001-NPM`` was ratified. Its module comment says so, and
  ``OWNERS.yaml`` carries ``deferred_decisions: {}`` — an empty **mapping**, not a
  deleted key — plus a note explaining that the key stays so the validator can
  report its absence as a defect.
* ``REQUIRED_ASSIGNED_DECISIONS`` was under-populated, and nothing anywhere
  noticed.

The discriminator is **not** the constant's name and it is not prose. It is
whether the emptiness is *recorded in the other file*:

    an empty tuple is legitimate exactly when the mapping it guards is also empty

Under that predicate, ``REQUIRED_DEFERRED_DECISIONS = ()`` is correct — it agrees
with ``deferred_decisions: {}`` — while ``REQUIRED_ASSIGNED_DECISIONS = ()``
against three populated ``blocking_decisions`` rows is a mutant. And emptying the
guard the honest way now costs an edit to ``OWNERS.yaml`` in the same reviewable
commit, which is exactly the mechanism the deferred half was built to have.

So this file does not add a second, differently-shaped rule for the ratified half.
It applies ``test_the_real_deferred_tuple_and_owners_file_agree`` (in
``test_draft_governance.py``) to **both** constants, parametrised, because the
defect was that only one of the two ever got it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import ROOT, run_script

from research_contracts.tooling import governance

SCRIPT = "check_draft_governance.py"
OWNERS = yaml.safe_load((ROOT / "OWNERS.yaml").read_text(encoding="utf-8"))

#: ``(module constant name, OWNERS.yaml key)``. Both halves of the guard, held to
#: one rule. Adding a third decision class means adding a row here, and the
#: enumeration test below refuses a row that names a constant that no longer exists.
GUARDED: tuple[tuple[str, str], ...] = (
    ("REQUIRED_ASSIGNED_DECISIONS", "blocking_decisions"),
    ("REQUIRED_DEFERRED_DECISIONS", "deferred_decisions"),
)


def make_repo(root: Path, owners: object) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "OWNERS.yaml").write_text(yaml.safe_dump(owners, sort_keys=False), encoding="utf-8")
    records = root / "review-records"
    records.mkdir(parents=True, exist_ok=True)
    (records / ".gitkeep").write_text("", encoding="utf-8")
    return root


def check(root: Path) -> subprocess.CompletedProcess[str]:
    return run_script(SCRIPT, "--repo-root", root)


def ratified_ids() -> list[str]:
    return sorted(OWNERS["blocking_decisions"])


# --------------------------------------------------------------------------
# Non-vacuity. A parametrisation over an empty list runs zero tests and reports
# success, which is the same failure mode as the guard it is meant to protect.
# --------------------------------------------------------------------------


def test_there_is_something_to_guard() -> None:
    assert len(ratified_ids()) >= 3, (
        f"OWNERS.yaml records {ratified_ids()}; the probes below would be near-vacuous "
        "with fewer, and the defect was specifically that two of three rows were decorative"
    )
    assert set(ratified_ids()) >= {"IMP-DEC-001", "IMP-DEC-001-NPM", "IMP-DEC-002"}


def test_a_reconstructed_untouched_repository_passes(tmp_path: Path) -> None:
    """Control, built the same way the probes are.

    Without it, every "deleting X is rejected" below could be red for a reason that
    has nothing to do with X — a wrong ``safe_dump`` round trip, a missing records
    directory — and the whole file would be measuring its own fixture.
    """
    result = check(make_repo(tmp_path / "repo", OWNERS))
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# One rule, applied to BOTH constants. The defect was that only one had it.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("constant", "key"), GUARDED)
def test_the_module_tuple_and_the_owners_file_agree(constant: str, key: str) -> None:
    """An entry in the module with no row in the YAML is a gate firing for a decision
    nobody recorded. A row in the YAML with no entry in the module is a decision that
    looks guarded and is not — which is what two of the three ratified rows were.
    """
    declared = set(getattr(governance, constant))
    recorded = set(OWNERS.get(key) or {})
    assert declared == recorded, (
        f"governance.{constant} declares {sorted(declared)} while OWNERS.yaml "
        f"{key} records {sorted(recorded)}"
    )


@pytest.mark.parametrize(("constant", "key"), GUARDED)
def test_an_empty_tuple_is_legitimate_only_when_the_mapping_is_empty_too(
    constant: str, key: str
) -> None:
    """The discriminator between the sanctioned empty tuple and the surviving mutant.

    ``REQUIRED_DEFERRED_DECISIONS`` is empty and passes, because ``deferred_decisions``
    is ``{}`` — emptiness recorded in the file a reviewer reads.
    ``REQUIRED_ASSIGNED_DECISIONS`` emptied against three populated rows fails, because
    nothing recorded it. Same predicate, opposite verdicts, no special case.
    """
    declared = getattr(governance, constant)
    recorded = OWNERS.get(key)
    assert isinstance(recorded, dict), f"OWNERS.yaml {key} must be a mapping, got {recorded!r}"
    assert bool(declared) == bool(recorded), (
        f"governance.{constant} is {'empty' if not declared else 'populated'} while "
        f"OWNERS.yaml {key} is {'empty' if not recorded else 'populated'}; an empty guard "
        "is only honest when the emptiness is recorded in the YAML as well"
    )


def test_the_guarded_table_names_constants_that_exist() -> None:
    """Drift in the other direction: a row here outliving the constant it names."""
    for constant, key in GUARDED:
        assert isinstance(getattr(governance, constant, None), tuple), (
            f"governance.{constant} is not a tuple; this table is asserting its own contents"
        )
        assert key in OWNERS, f"OWNERS.yaml has no {key!r} key"


# --------------------------------------------------------------------------
# The mutant, killed. This is the case the generic placeholder scan cannot see.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("decision", ratified_ids())
def test_deleting_any_ratified_decision_is_rejected(tmp_path: Path, decision: str) -> None:
    """Deletion, not a placeholder value. The generic scan reads values; a deleted
    key has none, so only ``REQUIRED_ASSIGNED_DECISIONS`` can catch this.
    """
    owners = {
        **OWNERS,
        "blocking_decisions": {
            name: value for name, value in OWNERS["blocking_decisions"].items() if name != decision
        },
    }
    result = check(make_repo(tmp_path / "repo", owners))
    assert result.returncode == 1, f"deleting {decision} was accepted: {result.stdout}"
    assert decision in result.stderr
    assert "is absent" in result.stderr


@pytest.mark.parametrize("decision", ratified_ids())
def test_the_deletion_probe_fires_through_this_guard_and_not_the_generic_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, decision: str
) -> None:
    """The falsifiable half, and the reason this file exists.

    With the guard emptied — the exact mutant that survived on ``main`` — deleting a
    ratified decision must be **accepted**. If this test ever fails, the probe above
    is passing for some other reason and has stopped observing the guard, which is
    precisely what ``test_unratified_blocking_decision_is_rejected`` had been doing.
    """
    monkeypatch.setattr(governance, "REQUIRED_ASSIGNED_DECISIONS", ())
    owners = {
        **OWNERS,
        "blocking_decisions": {
            name: value for name, value in OWNERS["blocking_decisions"].items() if name != decision
        },
    }
    errors = governance.governance_errors(make_repo(tmp_path / "repo", owners))
    assert not [error for error in errors if decision in error], (
        f"with the guard emptied, deleting {decision} was still reported: {errors}. "
        "Some other check is covering it, so the probe above is not measuring this guard"
    )


def test_the_guard_still_rejects_an_unratified_value_for_every_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The value half, isolated from the generic placeholder scan.

    ``UNASSIGNED`` is caught by the generic scan too, so a synthetic decision whose
    value is a placeholder only the ``assignedIdentifier`` definition refuses is used
    here — asserted through ``governance_errors`` so the specific message can be read.
    """
    monkeypatch.setattr(governance, "REQUIRED_ASSIGNED_DECISIONS", ("IMP-DEC-SYNTHETIC",))
    owners = {
        **OWNERS,
        "blocking_decisions": {**OWNERS["blocking_decisions"], "IMP-DEC-SYNTHETIC": "TBD"},
    }
    errors = governance.governance_errors(make_repo(tmp_path / "repo", owners))
    assert any("IMP-DEC-SYNTHETIC" in error and "must be ratified" in error for error in errors), (
        errors
    )

"""Fail if governance stops being explicitly assigned.

**Inverted 2026-08-08 (IMP-DEC-001, Python half).** This gate used to assert that
the repository was an explicitly *blocked* draft: every governance scalar had to
read exactly ``UNASSIGNED``. The Python half of ``IMP-DEC-001`` was ratified —
distribution ``research-contracts``, published from this repository — so the
assertion is now its mirror image: every governance scalar must hold a value that
has *actually been assigned*, and the one decision that is still open must still
say so out loud.

Two properties survive the inversion unchanged, because they are what made the
old gate worth having:

* **What is still blocked is still asserted blocked.** The npm scope/package name
  half of ``IMP-DEC-001`` is undecided. It lives under ``deferred_decisions``,
  where every entry must read exactly ``UNASSIGNED`` — the original mechanism,
  relocated to the part of the decision that is genuinely still open. A deferred
  decision cannot be promoted by editing ``OWNERS.yaml`` alone; promoting it means
  editing this module, in a reviewable commit, exactly as unblocking the draft did.
* **A half-assignment is a failure, at any depth.** No placeholder may appear as a
  scalar anywhere in the document except under ``deferred_decisions``. That is the
  direct analogue of the old nested post-draft check: it catches a promotion that
  is real at the root and hollow one level down, including behind a YAML anchor or
  inside a list.

The placeholder vocabulary is not restated here. It is read out of
``schemas/canonical/model-conformance-record.v1.schema.json`` ``$defs/assignedIdentifier``
— the same definition that already refuses ``UNASSIGNED``/``TBD``/``placeholder``
when a conformance record is minted — so the two gates cannot drift into disagreeing
about what "assigned" means. A hand-copied second blacklist is precisely the defect
D12 was filed for.

Proven defects in the baseline gate this replaces:

* it substring-grepped ``OWNERS.yaml``, so an ``OWNERS.yaml`` declaring
  ``lifecycle: released`` / ``candidate_status: approved`` with a real owner and
  reviewer passed as long as the five required strings appeared *anywhere* —
  including inside a ``notes:`` history string;
* it was anchored to the process working directory, so from a scratch directory
  holding a copied ``OWNERS.yaml`` and no ``review-records`` it
  reported green: a missing directory globbed to ``[]`` and read as "no illicit
  records".

Three more found by the adversarial verifier, closed here:

* the records enumeration was a flat ``iterdir()``, so ``records/fnd-002/…`` —
  per-package subfoldering, the obvious filing pattern — was invisible;
* ``records/`` replaced by a symlink to an empty directory passed, because
  ``is_dir()`` follows symlinks. It is now rejected outright: a symlink can point
  the gate at a decoy while the real records live anywhere on the runner, and
  there is no legitimate reason for this repository's records directory to be
  anything but a real directory;
* only *top-level* keys were inspected and PyYAML silently takes the last of
  duplicate keys, so ``lifecycle: released`` followed by ``lifecycle: draft``
  passed, as did a released/approved block nested under any other key. Loading
  is now strict (see :mod:`.yaml_strict`) and every mapping at every depth is
  inspected.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from .errors import ContractError
from .paths import ASSIGNED_IDENTIFIER_SCHEMA, REPOSITORY_ROOT
from .yaml_strict import strict_yaml_load

#: Scalar keys that must hold a real, assigned value — never a placeholder.
REQUIRED_ASSIGNED_SCALARS: tuple[str, ...] = (
    "accountable_owner",
    "accountable_reviewer",
    "schema_version_policy",
    "model_source_repository",
    "model_source_revision_policy",
)

#: Decisions that are ratified. Every entry must be PRESENT in
#: ``blocking_decisions`` and must hold an assigned value.
#:
#: ⚠️ **Under-populated until 2026-09-06, and nothing noticed.** This tuple named
#: ``IMP-DEC-001`` alone while ``OWNERS.yaml`` recorded three ratified decisions, so
#: ``IMP-DEC-001-NPM`` and ``IMP-DEC-002`` were decorative: deleting either row from
#: the file outright was ACCEPTED. Emptying the tuple entirely also left the whole
#: suite green — 2290 passed, measured — because the one test that looks like it
#: covers this guard writes ``IMP-DEC-001: UNASSIGNED`` and is satisfied by the
#: GENERIC placeholder scan below, which rejects that string wherever it appears
#: outside ``deferred_decisions``. The generic scan reads values; a deleted key has
#: no value, so deletion is the case only this tuple can catch, and it was the case
#: nothing tested.
#:
#: The tuple is now required to equal ``blocking_decisions`` exactly
#: (``tests/test_ratified_decision_guard.py``), in both directions. An entry here
#: with no row there is a gate firing for a decision nobody recorded; a row there
#: with no entry here is the defect above.
#:
#: ⚠️ **An empty tuple is not automatically wrong — see the sibling constant.**
#: ``REQUIRED_DEFERRED_DECISIONS`` below is legitimately ``()``. The discriminator is
#: not the constant's name and it is not this comment: it is whether the emptiness is
#: RECORDED in ``OWNERS.yaml``. ``deferred_decisions: {}`` is an empty mapping a
#: reviewer can check, so an empty deferred tuple agrees with the file. Three
#: populated ``blocking_decisions`` rows against an empty tuple agree with nothing.
#: One predicate covers both constants and neither is special-cased.
REQUIRED_ASSIGNED_DECISIONS: tuple[str, ...] = (
    "IMP-DEC-001",
    "IMP-DEC-001-NPM",
    "IMP-DEC-002",
)

#: Decisions still genuinely open. Every entry must read exactly this, so the
#: still-blocked half cannot be promoted by editing ``OWNERS.yaml`` alone.
DEFERRED_DECISION_VALUE = "UNASSIGNED"

#: **Emptied 2026-09-04 (IMP-DEC-001, npm half).** This tuple held
#: ``IMP-DEC-001-NPM`` from the 2026-08-08 inversion until the architecture owner
#: named the scope. The mechanism worked exactly as designed and is worth stating
#: plainly, because the temptation on the day a decision closes is to edit the YAML
#: and move on: the npm publish step could not be added while this entry stood,
#: ``OWNERS.yaml`` alone could not promote it, and closing it required this commit
#: to touch this module where a reviewer would see it. That is the whole point of
#: the guard, and emptying the tuple is the sanctioned way through it, not a way
#: around it.
#:
#: It is now empty, and ``deferred_decisions`` in ``OWNERS.yaml`` is an empty
#: mapping rather than a deleted key. Two reasons, both deliberate. The key must
#: remain for the validator below, which requires a mapping and reports its absence
#: as a defect. And an empty mapping is a claim a reader can check — "nothing is
#: deferred" — whereas a missing key is indistinguishable from a key someone
#: removed to make a gate pass. The next genuinely-open decision adds a row here
#: and a row there, and the mechanism is intact for it.
REQUIRED_DEFERRED_DECISIONS: tuple[str, ...] = ()

#: ``lifecycle`` must name a promoted state. ``draft`` is now a failure: the
#: repository has been promoted, so a file still claiming draft is stale or a
#: silent revert.
ASSIGNED_LIFECYCLES: frozenset[str] = frozenset(
    {"candidate", "approved", "released", "stable", "stable-v1"}
)

#: ``candidate_status`` must name a promoted state, by the same argument.
ASSIGNED_CANDIDATE_STATUSES: frozenset[str] = frozenset(
    {"approved", "accepted", "candidate", "released", "unblocked", "ready"}
)

#: Draft-era states. Asserted as an absence at every depth in addition to the
#: positive checks, so a re-blocked block nested behind a YAML anchor is caught.
BLOCKED_STATES: frozenset[str] = frozenset({"draft", "blocked"})

#: Where a placeholder is legitimate. Everywhere else it is a half-assignment.
PLACEHOLDER_EXEMPT_ROOT_KEY = "deferred_decisions"


def _assigned_identifier_schema() -> dict[str, Any]:
    """``$defs/assignedIdentifier`` from the assigned-identifier meta-schema.

    Read, never restated. A second hand-maintained blacklist here would be free
    to drift from the schema the gate validates against, which is the shape of
    defect D12.
    """
    try:
        document = json.loads(ASSIGNED_IDENTIFIER_SCHEMA.read_text(encoding="utf-8"))
        return dict(document["$defs"]["assignedIdentifier"])
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise ContractError(
            f"{ASSIGNED_IDENTIFIER_SCHEMA}: $defs/assignedIdentifier is unreadable ({exc}) — "
            "the placeholder vocabulary is the whole substance of this gate, so a gate that "
            "cannot load it must fail, not pass with an empty blacklist"
        ) from exc


@lru_cache(maxsize=1)
def _assigned_validator() -> Any:
    return jsonschema.Draft202012Validator(_assigned_identifier_schema())


def is_assigned(value: Any) -> bool:
    """True when ``value`` is a string that has actually been assigned."""
    return isinstance(value, str) and _assigned_validator().is_valid(value)


def _load_owners(owners_file: Path) -> dict[str, Any]:
    if not owners_file.is_file():
        raise ContractError(f"{owners_file}: required governance file is missing")
    try:
        document = strict_yaml_load(owners_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ContractError(f"{owners_file}: {exc}") from exc
    if not isinstance(document, dict):
        raise ContractError(f"{owners_file}: governance file must parse to a YAML mapping")
    return document


def _iter_mappings(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Yield every mapping in the document with its pointer, root included."""
    if isinstance(node, dict):
        yield path, node
        for key, child in node.items():
            yield from _iter_mappings(child, (*path, str(key)))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _iter_mappings(child, (*path, str(index)))


def _record_entries(records_dir: Path) -> list[str]:
    """Every entry under ``records_dir``, recursively, excluding ``.gitkeep``.

    ``os.walk`` with ``followlinks=False``: a symlinked subdirectory is reported
    as an entry in its own right rather than silently descended into or silently
    dropped by an ``is_file()`` filter.
    """
    entries: list[str] = []
    walk_errors: list[OSError] = []
    for directory, subdirectories, filenames in os.walk(
        records_dir, followlinks=False, onerror=walk_errors.append
    ):
        base = Path(directory)
        for name in (*subdirectories, *filenames):
            candidate = base / name
            if candidate.is_dir() and not candidate.is_symlink():
                continue
            if name == ".gitkeep":
                continue
            entries.append(candidate.relative_to(records_dir).as_posix())
    if walk_errors:
        raise ContractError(
            f"{records_dir}: could not be enumerated: {walk_errors[0]} — an unreadable "
            "records directory is not evidence that no review records exist"
        )
    return sorted(entries)


def governance_report(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return ``(errors, conformance_records)`` for ``repo_root``.

    The records are returned rather than asserted-empty. Governance being assigned
    is exactly the condition under which review records become legitimate, so the
    old "records exist while governance is unassigned" error is gone — but the
    enumeration is not, because it is the only thing that distinguishes "no records
    were filed" from "the directory could not be read". Reporting them keeps the
    recursion and symlink guarantees observable, and therefore testable.
    """
    owners_file = repo_root / "OWNERS.yaml"
    document = _load_owners(owners_file)
    errors: list[str] = []
    records: list[str] = []

    for key in REQUIRED_ASSIGNED_SCALARS:
        if key not in document:
            errors.append(f"{owners_file}: required key {key!r} is absent")
        elif not is_assigned(document[key]):
            errors.append(
                f"{owners_file}: {key!r} must hold an assigned value, got {document[key]!r} — "
                "a placeholder here means the promotion is hollow"
            )

    lifecycle = document.get("lifecycle")
    if not (isinstance(lifecycle, str) and lifecycle.strip().lower() in ASSIGNED_LIFECYCLES):
        errors.append(
            f"{owners_file}: 'lifecycle' must be one of {sorted(ASSIGNED_LIFECYCLES)}, "
            f"got {lifecycle!r}"
        )
    status = document.get("candidate_status")
    if not (isinstance(status, str) and status.strip().lower() in ASSIGNED_CANDIDATE_STATUSES):
        errors.append(
            f"{owners_file}: 'candidate_status' must be one of "
            f"{sorted(ASSIGNED_CANDIDATE_STATUSES)}, got {status!r}"
        )

    for pointer, mapping in _iter_mappings(document):
        nested = "/".join(pointer) or "<root>"
        deferred_here = pointer[:1] == (PLACEHOLDER_EXEMPT_ROOT_KEY,)
        for key in ("lifecycle", "candidate_status"):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip().lower() in BLOCKED_STATES:
                errors.append(
                    f"{owners_file}: {nested}: {key} {value!r} re-blocks the repository; "
                    "a blocked block anywhere in the file — including behind a YAML anchor — "
                    "is a revert, and reverting means editing this gate too"
                )
        if deferred_here:
            continue
        for key, value in mapping.items():
            if isinstance(value, str) and value.strip() and not is_assigned(value):
                errors.append(
                    f"{owners_file}: {nested}/{key}: {value!r} is a placeholder outside "
                    f"{PLACEHOLDER_EXEMPT_ROOT_KEY!r} — governance is assigned or it is not; "
                    "a promotion that is real at the root and hollow one level down is the "
                    "failure this check exists to catch"
                )

    decisions = document.get("blocking_decisions")
    if not isinstance(decisions, dict):
        errors.append(f"{owners_file}: 'blocking_decisions' must be a YAML mapping")
    else:
        for decision in REQUIRED_ASSIGNED_DECISIONS:
            if decision not in decisions:
                errors.append(f"{owners_file}: blocking_decisions[{decision!r}] is absent")
            elif not is_assigned(decisions[decision]):
                errors.append(
                    f"{owners_file}: blocking_decisions[{decision!r}] must be ratified, got "
                    f"{decisions[decision]!r}"
                )

    deferred = document.get(PLACEHOLDER_EXEMPT_ROOT_KEY)
    if not isinstance(deferred, dict):
        errors.append(f"{owners_file}: {PLACEHOLDER_EXEMPT_ROOT_KEY!r} must be a YAML mapping")
    else:
        for decision in REQUIRED_DEFERRED_DECISIONS:
            actual = deferred.get(decision)
            if actual != DEFERRED_DECISION_VALUE:
                errors.append(
                    f"{owners_file}: {PLACEHOLDER_EXEMPT_ROOT_KEY}[{decision!r}] must still be "
                    f"{DEFERRED_DECISION_VALUE!r}, got {actual!r} — this half of the decision is "
                    "open, and closing it means editing this module, not only the YAML"
                )

    records_dir = repo_root / "review-records"
    if records_dir.is_symlink():
        errors.append(
            f"{records_dir}: must be a real directory, not a symlink — is_dir() follows "
            "symlinks, so a link elsewhere lets the real records sit anywhere on the runner "
            "while this gate reports on a decoy"
        )
    elif not records_dir.is_dir():
        errors.append(
            f"{records_dir}: required directory is missing — a missing directory is not "
            "evidence about the review records that should live in it"
        )
    else:
        records = _record_entries(records_dir)

    return errors, records


def governance_errors(repo_root: Path) -> list[str]:
    """Every way ``repo_root``'s governance has stopped being explicitly assigned."""
    return governance_report(repo_root)[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify governance ownership is explicitly assigned."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository to check; defaults to the repository containing this module",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.expanduser().resolve()
    try:
        errors, records = governance_report(repo_root)
    except ContractError as exc:
        print(exc, file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(
        "governance ownership is explicitly assigned; the deferred npm half of IMP-DEC-001 "
        f"remains explicitly open: {repo_root}"
    )
    if records:
        print(f"conformance records on file ({len(records)}): {', '.join(records)}")
    else:
        print("conformance records on file: none")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

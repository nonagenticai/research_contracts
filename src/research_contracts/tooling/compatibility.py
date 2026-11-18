"""Compare a released schema against a candidate and classify the difference.

Document 13 section 8.3 gates event emission on four merged artifacts: a schema,
an example, a consumer-matrix row and a **compatibility test**. Measured
2026-09-04, three of those four had a home in this repository and the fourth did
not. What existed was `tests/test_inclusion_set_export_v2_schema.py`, one
hand-authored comparison of `inclusion-set-export:1` against `:2`, written for
that pair and reusable for nothing. Every other released document was covered by
a test that asserts its CURRENT shape -- which catches an accidental edit, and
cannot answer the question compatibility is about: whether a change that is
already made may keep its `$id`.

The rule this module enforces is not invented here. It is `schema_version_policy`
in `research_contracts/OWNERS.yaml`, quoted in full:

    semver on the schema $id: adding a name or an optional member is minor and
    keeps the $id; any change to what a released rule means mints a new $id major
    and bumps DERIVATION_PROFILE_VERSION in the same commit as every manifest it
    invalidates.

WHY THIS IS A COMPARISON AND NOT A LINTER. A schema cannot be judged compatible
on its own. "Optional member added" is only meaningful against the version that
was released, so this module takes two documents and never one. That is also why
it lives in `tooling/` beside `governance.py` rather than in the runtime package:
it is authoring-time machinery, and nothing a service imports at runtime should
be able to reach it.

WHICH WAY IT FAILS. Toward MAJOR. Every difference this module does not
positively recognise as minor is reported as breaking, including differences it
does not understand. A comparator that guessed "probably fine" for a construct it
had not been taught would hand a false clearance to exactly the change nobody
reviewed, and a false MAJOR costs an argument while a false MINOR costs a silent
break in every consumer. `UNKNOWN` is therefore a subclass of breaking, not a
third outcome, and it names the construct so the gap can be closed deliberately.

TWO RULES THAT ARE THE WHOLE REASON THAT PROMISE HOLDS, both added after an audit
measured it failing toward SAFE on all 41 released documents:

1. **A subschema is not always an object.** `true` and `false` are legal
   subschemas -- `true` accepts anything, `false` accepts nothing -- and both
   recursion sites used to guard themselves with `isinstance(sub, Mapping)` and
   fall silently through. `properties` and `$defs` are in `_compare_unhandled`'s
   skip-list, so nothing else looked either: `$defs/sealed -> true` (which drops
   the `unevaluatedProperties: false` closing every event document) reported
   IDENTICAL on 41 of 41. `_compare_subschema` owns every boolean direction now,
   and reports anything that is neither an object nor a boolean as breaking.

2. **`==` is the wrong operator here, everywhere.** Python says `True == 1` and
   `0 == False`, at any depth, so every `if old == new: continue` in this file was
   a silent clearance. `_same_json` is the only equality this module uses.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "Change",
    "CompatibilityReport",
    "Verdict",
    "compare",
    "compare_files",
]


class Verdict(StrEnum):
    """What a set of differences requires of the `$id`.

    ⚠️ **This class deliberately defines NO ordering, and that is a fix, not an
    omission.** It used to define `__lt__` and a `_rank`, and a report's verdict was
    `max(...)` over its changes. That was broken in the most dangerous possible
    direction and shipped: `max()` calls `__gt__` first, which `StrEnum` inherits
    from `str` and this class never overrode, so comparison fell back to
    LEXICOGRAPHIC order — `"identical" < "major" < "minor"` — and `max()` returned
    **MINOR** whenever a MINOR and a MAJOR change appeared in the same report.

    Measured before the fix:

        MAJOR > MINOR            -> False
        max(MINOR, MAJOR)        -> minor
        mixed report .verdict    -> minor,  .keeps_its_id -> True

    So a candidate that bundled one safe addition with one breaking change — the
    ordinary shape of a real schema edit — was cleared to keep its `$id`. The
    module's whole stated contract is that it fails TOWARD major, and one language
    detail inverted it. The suite missed it because every mutation test produced a
    single change class, so MINOR and MAJOR never met in one report.

    Ordering is now computed explicitly in `CompatibilityReport.verdict` by asking
    whether any change is MAJOR, then whether any is MINOR. Do not re-add
    comparison operators here to make `max()` work again: an enum whose severity
    depends on inherited string comparison is one refactor away from this bug, and
    an explicit two-line rule cannot be silently overridden by a base class.
    """

    IDENTICAL = "identical"
    MINOR = "minor"
    MAJOR = "major"


@dataclass(frozen=True)
class Change:
    """One difference, its verdict, and the reason in the policy's own terms.

    `pointer` is a JSON Pointer into the candidate document so a reviewer can go
    straight to the construct rather than diffing two files by eye.
    """

    pointer: str
    verdict: Verdict
    reason: str

    def __str__(self) -> str:
        return f"{self.verdict.value.upper():8} {self.pointer or '/'}  {self.reason}"


@dataclass
class CompatibilityReport:
    """The verdict for a whole document, plus every difference behind it."""

    released_id: str
    candidate_id: str
    changes: list[Change] = field(default_factory=list)

    @property
    def verdict(self) -> Verdict:
        """The most severe verdict among the changes.

        Explicit, not `max()`. See the long note on `Verdict` for why: `max()` over
        a `StrEnum` used inherited string ordering and returned MINOR for a report
        containing both a MINOR and a MAJOR change, clearing breaking candidates to
        keep their `$id`.
        """
        if any(change.verdict is Verdict.MAJOR for change in self.changes):
            return Verdict.MAJOR
        if any(change.verdict is Verdict.MINOR for change in self.changes):
            return Verdict.MINOR
        return Verdict.IDENTICAL

    @property
    def keeps_its_id(self) -> bool:
        """True when the candidate may be released under the same `$id`.

        A MAJOR difference does not merely warrant a new `$id` -- under
        OWNERS.yaml it REQUIRES one, together with a DERIVATION_PROFILE_VERSION
        bump in the same commit as every manifest it invalidates. This property
        answers only the first half; the manifest sweep is the author's.
        """
        return self.verdict is not Verdict.MAJOR

    def breaking(self) -> list[Change]:
        return [c for c in self.changes if c.verdict is Verdict.MAJOR]

    def __str__(self) -> str:
        head = f"{self.released_id} -> {self.candidate_id}: {self.verdict.value}"
        if not self.changes:
            return f"{head}\n  (no differences)"
        return "\n".join([head, *(f"  {c}" for c in self.changes)])


# The keywords this module has been taught to reason about. A keyword outside
# this set that differs between the two documents is reported UNKNOWN-as-MAJOR
# rather than ignored -- see the module docstring on which way it fails.
_KNOWN_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$comment",
        "$defs",
        "title",
        "description",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "items",
        "enum",
        "const",
        "oneOf",
        "anyOf",
        "allOf",
        "not",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minProperties",
        "maxProperties",
        "pattern",
        "format",
        "dependentRequired",
    }
)

# Keywords that carry no constraint. A difference in one of these is prose and
# cannot break a consumer, so it is not reported at all. `$comment` is here
# deliberately: this repository's house style puts long authoring rationale in
# it, and a comparator that called a rewritten explanation "breaking" would
# train authors to stop explaining themselves.
#
# ⚠️ `$schema` used to be here, and that was a gap, not a decision: an audit
# found it present in published 0.9.1/0.9.2 and flagged it as pre-existing.
# `$schema` is not decoration -- it selects the JSON Schema DIALECT, which
# governs what every other keyword in the document means. `additionalProperties`
# under draft-07 and under 2020-12 is not the same rule, and a document that
# silently changed dialect could redefine every keyword in it while this module
# reported IDENTICAL. It is handled in `_compare_simple` now, unconditionally
# MAJOR when it differs -- the same treatment `type`/`$ref`/`format` already get,
# because whether a dialect change is actually safe is exactly the kind of
# judgement this module refuses to guess at.
_PROSE_KEYWORDS = frozenset({"$comment", "title", "description"})

# Bounds where a LARGER number is more permissive, and its opposite. Loosening a
# bound accepts everything it accepted before, so it is minor; tightening one
# rejects a document that used to validate, so it is major.
_LOOSENS_WHEN_LARGER = frozenset({"maxLength", "maximum", "maxItems", "maxProperties"})
_LOOSENS_WHEN_SMALLER = frozenset({"minLength", "minimum", "minItems", "minProperties"})


#: A keyword that is not present at all. Distinct from a keyword whose value is
#: literally ``null``: ``{"const": null}`` pins the value null, and ``{}`` pins
#: nothing, so a comparator that reads both as ``None`` cannot tell a released pin
#: being DROPPED from a released pin being KEPT. Every keyword lookup in this
#: module goes through ``.get(keyword, _MISSING)`` for that reason.
_MISSING: Any = object()


def _join(pointer: str, token: str | int) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"


def _show(value: Any) -> str:
    """Render a keyword value for a reason string, with a name for "not present".

    ``repr(_MISSING)`` is ``<object object at 0x...>``: unreadable, and a different
    string on every run, which would make two identical reports compare unequal.
    """
    return "absent" if value is _MISSING else repr(value)


def _is_number(value: Any) -> bool:
    """True for a JSON number. ``bool`` is excluded, because Python says it is an ``int``.

    ``isinstance(True, int)`` is ``True`` in Python and ``true`` is not a number in
    JSON. Every numeric comparison in this module asks this question first, so a
    bound that became a boolean is reported rather than silently ordered.
    """
    return isinstance(value, int | float) and not isinstance(value, bool)


def _same_json(left: Any, right: Any) -> bool:
    """JSON value equality that never conflates ``true`` with ``1``, at any depth.

    ⚠️ **This exists because ``==`` is the wrong operator for this module, and the
    audit that produced it found the same defect at seven sites.** Python's ``==``
    says ``True == 1``, ``False == 0``, ``{"a": 1} == {"a": True}`` and
    ``[{"a": 0}] == [{"a": False}]``. Every one of those pairs is two DIFFERENT
    documents to a JSON Schema validator, so every ``old == new: continue`` in this
    module was a silent clearance for a change that alters what a released rule
    accepts. Measured before this function existed:

        {"const": 0}     -> {"const": false}   ->  identical, 0 changes
        {"const": 1}     -> {"const": true}    ->  identical, 0 changes
        {"minLength": 1} -> {"minLength": true}->  identical, 0 changes

    The ``enum`` comparison had been fixed once, with a shallow ``(type name,
    value)`` pair. Shallow is not enough: the pair still compares its second
    element with ``==``, so ``[{"a": 1}]`` and ``[{"a": true}]`` matched. The rule
    has to recurse, so it lives here and every site calls it.

    Numbers are the one deliberate leniency: JSON has a single number type and
    ``1`` and ``1.0`` are the same value, so they compare equal. ``true`` is not a
    number and never compares equal to one.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        if not (isinstance(left, Mapping) and isinstance(right, Mapping)):
            return False
        return set(left) == set(right) and all(_same_json(left[k], right[k]) for k in left)
    if isinstance(left, list) or isinstance(right, list):
        if not (isinstance(left, list) and isinstance(right, list)):
            return False
        return len(left) == len(right) and all(
            _same_json(a, b) for a, b in zip(left, right, strict=True)
        )
    if _is_number(left) and _is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    return bool(left == right)


def _required_names(schema: Mapping[str, Any]) -> set[str]:
    """The declared required member names, or the empty set for a malformed ``required``.

    Malformed input is REPORTED by ``_compare_required``, which owns the keyword.
    This helper only has to avoid crashing on it: ``set("id")`` is ``{'i', 'd'}``
    and ``set(5)`` raises, and neither may happen before the report is built.
    """
    value = schema.get("required")
    if not isinstance(value, list):
        return set()
    return {name for name in value if isinstance(name, str)}


def _is_optional_addition(schema: Mapping[str, Any], name: str) -> bool:
    return name not in _required_names(schema)


def _document_id(document: Any) -> str:
    if isinstance(document, Mapping):
        return str(document.get("$id", "<no $id>"))
    return f"<not an object: {type(document).__name__}>"


def compare(released: Any, candidate: Any) -> CompatibilityReport:
    """Classify every difference between a released document and a candidate.

    Both arguments are parsed JSON Schema documents. Neither is mutated.

    Neither is required to be an object, either. ``true`` and ``false`` are legal
    JSON Schema documents, and anything else is malformed input that must be
    reported rather than crashed on: this function used to read ``$id`` off both
    arguments before anything checked them, so ``compare(True, {...})`` raised
    ``AttributeError`` out of the gate a CI job calls, which is a failure with no
    verdict at all rather than a failure toward MAJOR.
    """
    report = CompatibilityReport(
        released_id=_document_id(released),
        candidate_id=_document_id(candidate),
    )
    _compare_subschema(released, candidate, "", report)
    return report


def _compare_subschema(
    released: Any,
    candidate: Any,
    pointer: str,
    report: CompatibilityReport,
) -> None:
    """Compare two subschemas, either of which may be a JSON Schema BOOLEAN.

    ⚠️ **This function exists because the two recursion sites guarded themselves
    with ``isinstance(sub, Mapping)`` and did nothing at all when the guard
    failed.** ``properties`` and ``$defs`` are both in ``_compare_unhandled``'s
    skip-list -- the sweep trusts the dedicated functions to own those keywords --
    so a subschema that was not a mapping was reported by NOTHING. Measured across
    the 41 released documents before this fix:

        $defs/sealed          -> true    ->  identical, 0 changes, on 41 of 41
        properties/<member>   -> false   ->  identical, 0 changes, on 20 of 20

    The first drops the ``unevaluatedProperties: false`` that closes every event
    document; the second makes a released member impossible to send. Both were
    cleared to keep their ``$id``.

    ``true`` and ``false`` are not malformed input. RFC 8927 / JSON Schema core
    make them legal subschemas: ``true`` is the empty schema and accepts anything,
    ``false`` accepts nothing. So they are handled AS SCHEMAS, in all four
    directions:

    * ``false`` -> ``false``   no change; the position still accepts nothing.
    * ``false`` -> anything    MINOR. It accepted nothing and now accepts
      something, so every document that validated before still validates.
    * anything -> ``false``    MAJOR. The position now accepts nothing, which is
      the most complete break a subschema can express.
    * otherwise                ``true`` is normalised to ``{}``, its exact
      equivalent, and the ordinary keyword diff runs. That way ``true`` -> ``{}``
      is correctly IDENTICAL, while ``{...}`` -> ``true`` reports every keyword
      that disappeared.

    Anything that is neither a mapping nor a boolean is not a schema at all, and is
    reported breaking like every other construct this module cannot read.
    """
    if isinstance(released, Mapping) and isinstance(candidate, Mapping):
        _walk(released, candidate, pointer, report)
        return

    for source, value in (("released", released), ("candidate", candidate)):
        if not isinstance(value, Mapping | bool):
            report.changes.append(
                Change(
                    pointer,
                    Verdict.MAJOR,
                    f"{source} subschema is {type(value).__name__}, which is not a schema "
                    "(a schema is an object, or the boolean true/false); the diff beneath it "
                    "could not run, so it is reported breaking rather than skipped",
                )
            )
            return

    if released is False or candidate is False:
        if released is False and candidate is False:
            return
        if released is False:
            report.changes.append(
                Change(
                    pointer,
                    Verdict.MINOR,
                    "subschema was `false` and accepted nothing; it now accepts something, so "
                    "every document that validated before still validates",
                )
            )
        else:
            report.changes.append(
                Change(
                    pointer,
                    Verdict.MAJOR,
                    "subschema became `false`, which accepts NOTHING; every document carrying "
                    "this construct now fails",
                )
            )
        return

    # `true` is the empty schema. Normalising it lets the ordinary keyword diff run
    # in both directions instead of being a fourth special case.
    _walk(
        {} if released is True else released,
        {} if candidate is True else candidate,
        pointer,
        report,
    )


def _walk(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    _compare_properties(released, candidate, pointer, report)
    _compare_required(released, candidate, pointer, report)
    _compare_enum_and_const(released, candidate, pointer, report)
    _compare_bounds(released, candidate, pointer, report)
    _compare_closedness(released, candidate, pointer, report)
    _compare_simple(released, candidate, pointer, report)
    _compare_defs(released, candidate, pointer, report)
    _compare_unhandled(released, candidate, pointer, report)


def _compare_properties(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    # `.get(kw, _MISSING)`, NOT `.get(kw) or {}`. `or` tests TRUTHINESS, so `0`, `false`,
    # `""` and `[]` were all silently read as "no properties at all" and never reached the
    # malformed branch below: `{"properties": 0}` against `{"properties": false}` reported
    # IDENTICAL, and so did either of them against a document with an empty property set.
    # Same idiom, same defect, in `_compare_defs`.
    old = released.get("properties", _MISSING)
    new = candidate.get("properties", _MISSING)
    if (old is not _MISSING and not isinstance(old, Mapping)) or (
        new is not _MISSING and not isinstance(new, Mapping)
    ):
        # It used to `return` here, silently. `properties` is also in
        # `_compare_unhandled`'s skip-list — it trusts THIS function to cover the
        # keyword — so a malformed `properties` on either side meant the entire
        # property diff was skipped and the report came back IDENTICAL. Measured:
        # `{"properties": "not-a-mapping"}` against a real property set reported no
        # changes at all. A construct this function cannot read is reported
        # breaking, like every other thing the module does not understand.
        report.changes.append(
            Change(
                _join(pointer, "properties"),
                Verdict.MAJOR,
                "'properties' is not an object on one or both sides, so the property diff "
                "could not run; reported breaking rather than skipped",
            )
        )
        return
    if old is _MISSING:
        old = {}
    if new is _MISSING:
        new = {}

    for name in sorted(set(old) - set(new)):
        report.changes.append(
            Change(
                _join(_join(pointer, "properties"), name),
                Verdict.MAJOR,
                "member removed; a producer that still writes it now fails a closed schema",
            )
        )

    for name in sorted(set(new) - set(old)):
        if _is_optional_addition(candidate, name):
            report.changes.append(
                Change(
                    _join(_join(pointer, "properties"), name),
                    Verdict.MINOR,
                    "optional member added -- minor under OWNERS.yaml schema_version_policy",
                )
            )
        else:
            report.changes.append(
                Change(
                    _join(_join(pointer, "properties"), name),
                    Verdict.MAJOR,
                    "REQUIRED member added; every existing document is now invalid",
                )
            )

    for name in sorted(set(old) & set(new)):
        # `_compare_subschema`, not a `isinstance(..., Mapping)` guard around
        # `_walk`. The guard meant a member whose subschema became `false` -- which
        # makes the member impossible to send -- was reported by nothing at all.
        _compare_subschema(old[name], new[name], _join(_join(pointer, "properties"), name), report)


def _compare_required(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    # `required` must be a LIST. `set("id")` is `{'i', 'd'}`, so a schema written
    # with `required: "id"` instead of `required: ["id"]` was silently read as two
    # single-character member names — and a genuinely new property called `"i"`
    # then reported as newly-required. Malformed input is reported, never guessed.
    for source, doc in (("released", released), ("candidate", candidate)):
        value = doc.get("required", _MISSING)
        if value is _MISSING:
            continue
        if not isinstance(value, list):
            report.changes.append(
                Change(
                    _join(pointer, "required"),
                    Verdict.MAJOR,
                    f"{source} 'required' is {type(value).__name__}, not a list; "
                    "iterating it would read a string as its characters",
                )
            )
            return
        # `required` holds member NAMES. A non-string member is not one, and
        # `set([{"a": 1}])` raises TypeError before any report exists -- the same
        # class as the string case above, one element deeper. Report, never guess.
        if any(not isinstance(name, str) for name in value):
            report.changes.append(
                Change(
                    _join(pointer, "required"),
                    Verdict.MAJOR,
                    f"{source} 'required' holds a non-string member, which is not a member "
                    "name; the required diff could not run",
                )
            )
            return

    old = _required_names(released)
    new = _required_names(candidate)
    for name in sorted(new - old):
        report.changes.append(
            Change(
                _join(pointer, "required"),
                Verdict.MAJOR,
                f"{name!r} became required; a document that omitted it used to validate",
            )
        )
    for name in sorted(old - new):
        report.changes.append(
            Change(
                _join(pointer, "required"),
                Verdict.MINOR,
                f"{name!r} became optional; every previously valid document still validates",
            )
        )


def _compare_enum_and_const(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    old_enum = released.get("enum", _MISSING)
    new_enum = candidate.get("enum", _MISSING)

    # An `enum` that is present but is not a list is malformed, and `enum` is in
    # `_compare_unhandled`'s skip-list because THIS function owns it. So
    # `{"enum": ["a", "b"]} -> {"enum": "a"}` fell between the two branches below --
    # both sides are non-None, so the "introduced or dropped" test was False -- and
    # reported IDENTICAL while the accepted set collapsed to one string's characters.
    for source, value in (("released", old_enum), ("candidate", new_enum)):
        if value is not _MISSING and not isinstance(value, list):
            report.changes.append(
                Change(
                    _join(pointer, "enum"),
                    Verdict.MAJOR,
                    f"{source} 'enum' is {type(value).__name__}, not a list; the enum diff "
                    "could not run, so it is reported breaking rather than skipped",
                )
            )
            return

    if isinstance(old_enum, list) and isinstance(new_enum, list):
        # Membership by `_same_json`, not by `in`. Python's `in` uses `==` and
        # `True == 1`, so removing `true` from `[1, 2, true]` reported NO change —
        # a released name silently stopped being accepted and the verdict was
        # IDENTICAL. A first fix compared `(type name, value)` pairs, which fixes
        # the SCALAR case only: the pair's second element is still compared with
        # `==`, so `[{"a": 1}]` and `[{"a": true}]` still matched. `_same_json`
        # recurses, and is also stable for the unhashable members an enum may hold.
        removed = [v for v in old_enum if not any(_same_json(v, w) for w in new_enum)]
        added = [v for v in new_enum if not any(_same_json(v, w) for w in old_enum)]
        if removed:
            report.changes.append(
                Change(
                    _join(pointer, "enum"),
                    Verdict.MAJOR,
                    f"value(s) removed: {removed!r}; a released name stopped being accepted",
                )
            )
        if added:
            report.changes.append(
                Change(
                    _join(pointer, "enum"),
                    Verdict.MINOR,
                    f"name(s) added: {added!r} -- 'adding a name' is minor under the policy",
                )
            )
    elif (old_enum is _MISSING) != (new_enum is _MISSING):
        report.changes.append(
            Change(
                _join(pointer, "enum"),
                Verdict.MAJOR,
                "an enum was introduced or dropped; the set of accepted values changed shape",
            )
        )

    # `_same_json`, not `!=`. `{"const": 0} -> {"const": false}` and
    # `{"const": 1} -> {"const": true}` both reported IDENTICAL, because Python says
    # `0 == False`. This is the version pin a consumer branches on, so a false
    # clearance here is a silent break in every consumer at once. The `_MISSING`
    # sentinel is what distinguishes an explicit `const: null` from no const at all.
    if not _same_json(released.get("const", _MISSING), candidate.get("const", _MISSING)):
        report.changes.append(
            Change(
                _join(pointer, "const"),
                Verdict.MAJOR,
                "const changed; this is the version pin a consumer branches on",
            )
        )


def _compare_bounds(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    for keyword in sorted(_LOOSENS_WHEN_LARGER | _LOOSENS_WHEN_SMALLER):
        old = released.get(keyword, _MISSING)
        new = candidate.get(keyword, _MISSING)
        # `_same_json`, not `==`: `{"minLength": 1} -> {"minLength": true}` reported
        # IDENTICAL, because `1 == True`. A bound that stopped being a number is a
        # different rule, not the same one.
        if _same_json(old, new):
            continue

        # A present bound that is not a JSON number cannot be ORDERED, and ordering
        # it was not a false clearance but a crash: `new > old` on a string raised
        # TypeError straight out of the gate a CI job calls, which is a failure with
        # no verdict rather than a failure toward MAJOR.
        malformed = False
        for source, value in (("released", old), ("candidate", new)):
            if value is not _MISSING and not _is_number(value):
                report.changes.append(
                    Change(
                        _join(pointer, keyword),
                        Verdict.MAJOR,
                        f"{source} {keyword!r} is {type(value).__name__}, not a number, so "
                        "whether the bound loosened cannot be decided; reported breaking "
                        "rather than guessed",
                    )
                )
                malformed = True
        if malformed:
            continue

        if old is _MISSING or new is _MISSING:
            added = new is not _MISSING
            report.changes.append(
                Change(
                    _join(pointer, keyword),
                    Verdict.MAJOR if added else Verdict.MINOR,
                    "bound added" if added else "bound removed (loosened)",
                )
            )
            continue
        looser = new > old if keyword in _LOOSENS_WHEN_LARGER else new < old
        report.changes.append(
            Change(
                _join(pointer, keyword),
                Verdict.MINOR if looser else Verdict.MAJOR,
                f"{old!r} -> {new!r}; {'loosened' if looser else 'TIGHTENED, rejecting documents that used to validate'}",
            )
        )

    if not _same_json(released.get("pattern", _MISSING), candidate.get("pattern", _MISSING)):
        report.changes.append(
            Change(
                _join(pointer, "pattern"),
                Verdict.MAJOR,
                "pattern changed; whether it loosened cannot be decided by comparing regexes, "
                "so it is reported breaking rather than guessed",
            )
        )


def _compare_closedness(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    for keyword in ("additionalProperties", "unevaluatedProperties"):
        old = released.get(keyword, _MISSING)
        new = candidate.get(keyword, _MISSING)
        # `_same_json`, not `==`. These keywords take a boolean OR a schema, and
        # `0 == False` — so `{"additionalProperties": false} -> {..: 0}` compared
        # equal and skipped, while `is False` below would then have called the
        # document open. Two different wrong answers from one operator.
        if _same_json(old, new):
            continue
        # Both keywords take a SCHEMA, and `true`/`false` are schemas; nothing else
        # is. Without this guard `{"additionalProperties": false} -> {..: 0}` fell
        # into the `old is False and new is not False` branch below and was reported
        # MINOR, "document opened" — a fail-open verdict on input that means nothing.
        malformed = False
        for source, value in (("released", old), ("candidate", new)):
            if value is not _MISSING and not isinstance(value, Mapping | bool):
                report.changes.append(
                    Change(
                        _join(pointer, keyword),
                        Verdict.MAJOR,
                        f"{source} {keyword!r} is {type(value).__name__}; it takes a schema or "
                        "a boolean, so whether the document opened or closed cannot be decided",
                    )
                )
                malformed = True
        if malformed:
            continue
        if old is False and new is not False:
            report.changes.append(
                Change(
                    _join(pointer, keyword),
                    Verdict.MINOR,
                    "document opened; it now accepts everything it accepted before and more",
                )
            )
        elif new is False and old is not False:
            report.changes.append(
                Change(
                    _join(pointer, keyword),
                    Verdict.MAJOR,
                    "document CLOSED; a producer sending an extra member now fails",
                )
            )
        else:
            report.changes.append(
                Change(_join(pointer, keyword), Verdict.MAJOR, f"{_show(old)} -> {_show(new)}")
            )


def _compare_simple(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    for keyword in ("type", "$ref", "format"):
        old = released.get(keyword, _MISSING)
        new = candidate.get(keyword, _MISSING)
        if not _same_json(old, new):
            report.changes.append(
                Change(
                    _join(pointer, keyword),
                    Verdict.MAJOR,
                    f"{_show(old)} -> {_show(new)}; what a released member MEANS changed",
                )
            )

    # `$schema` used to sit in `_PROSE_KEYWORDS` and was skipped entirely -- a gap
    # present in published 0.9.1/0.9.2, not introduced here. It is not prose: it
    # selects the JSON Schema DIALECT, which governs what every other keyword in
    # the document means. Whether a given dialect change is actually compatible
    # is undecidable without a per-dialect keyword table this module does not
    # have, so -- consistent with the module's "fails toward MAJOR" contract --
    # a difference here is reported unconditionally breaking rather than guessed,
    # the same treatment `type`/`$ref`/`format` get above.
    old_dialect = released.get("$schema", _MISSING)
    new_dialect = candidate.get("$schema", _MISSING)
    if not _same_json(old_dialect, new_dialect):
        report.changes.append(
            Change(
                _join(pointer, "$schema"),
                Verdict.MAJOR,
                f"{_show(old_dialect)} -> {_show(new_dialect)}; $schema selects the validation "
                "dialect for every keyword in the document, so a change here can silently "
                "redefine what the whole document means",
            )
        )

    if not _same_json(released.get("$id", _MISSING), candidate.get("$id", _MISSING)):
        if pointer == "":
            report.changes.append(
                Change(
                    "/$id",
                    Verdict.MINOR,
                    "the candidate already carries a new $id, which is what a MAJOR change "
                    "requires; the differences below are reported against the document it "
                    "succeeds",
                )
            )
        else:
            # A NESTED `$id` was checked by nothing. This function only looked at
            # the root, and `_compare_unhandled` skips `$id` entirely because it
            # trusts this function to cover it — so a changed `$id` inside `$defs`
            # or a subschema produced a report of IDENTICAL with zero changes.
            # That is not cosmetic: a nested `$id` changes the base URI for
            # relative `$ref` resolution beneath it, so every reference under it
            # can silently resolve somewhere else.
            report.changes.append(
                Change(
                    _join(pointer, "$id"),
                    Verdict.MAJOR,
                    f"nested $id changed {_show(released.get('$id', _MISSING))} -> "
                    f"{_show(candidate.get('$id', _MISSING))}; "
                    "this moves the base URI that relative $refs beneath it resolve against",
                )
            )


def _compare_defs(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    # `.get(kw, _MISSING)`, not `.get(kw) or {}`: see `_compare_properties`. A falsy `$defs`
    # -- `0`, `false`, `[]` -- was read as an empty definition bag and cleared.
    old = released.get("$defs", _MISSING)
    new = candidate.get("$defs", _MISSING)
    if (old is not _MISSING and not isinstance(old, Mapping)) or (
        new is not _MISSING and not isinstance(new, Mapping)
    ):
        # It used to `return` here, silently -- the identical hole that
        # `_compare_properties` above was already fixed for, left open in the
        # sibling function. `$defs` is likewise in `_compare_unhandled`'s
        # skip-list, so a malformed `$defs` on either side skipped the WHOLE
        # remaining diff for that node and the report came back IDENTICAL:
        # measured, `{"$defs": {...}}` against `{"$defs": ["..."]}` reported no
        # changes on 41 of 41 released documents.
        report.changes.append(
            Change(
                _join(pointer, "$defs"),
                Verdict.MAJOR,
                "'$defs' is not an object on one or both sides, so the definition diff "
                "could not run; reported breaking rather than skipped",
            )
        )
        return
    if old is _MISSING:
        old = {}
    if new is _MISSING:
        new = {}
    for name in sorted(set(old) - set(new)):
        report.changes.append(
            Change(
                _join(_join(pointer, "$defs"), name),
                Verdict.MAJOR,
                "definition removed; any document $ref-ing it no longer resolves",
            )
        )
    for name in sorted(set(new) - set(old)):
        report.changes.append(
            Change(
                _join(_join(pointer, "$defs"), name),
                Verdict.MINOR,
                "definition added; nothing references it yet, so nothing can break on it",
            )
        )
    for name in sorted(set(old) & set(new)):
        # A definition that became the boolean `true` drops every constraint it
        # carried -- including the `unevaluatedProperties: false` that `$defs/sealed`
        # uses to close all twelve event documents. The old `isinstance` guard
        # reported that as no change whatsoever.
        _compare_subschema(old[name], new[name], _join(_join(pointer, "$defs"), name), report)


def _compare_unhandled(
    released: Mapping[str, Any],
    candidate: Mapping[str, Any],
    pointer: str,
    report: CompatibilityReport,
) -> None:
    """Report a differing keyword this module was never taught to reason about.

    This is the honest half of the design. `oneOf`, `anyOf`, `allOf` and `not`
    are recognised as keywords but their SEMANTICS are not modelled here -- a
    branch added to a `oneOf` can widen or narrow depending on what the other
    branches already accept, and deciding that correctly is subsumption checking,
    not a diff. Rather than pretend, a difference in one of them is reported as
    breaking and named, so a human decides and, if the pattern recurs, teaches
    this module the case explicitly.
    """
    for keyword in sorted(set(released) | set(candidate)):
        if keyword in _PROSE_KEYWORDS:
            continue
        if keyword in {
            "properties",
            "required",
            "enum",
            "const",
            "additionalProperties",
            "unevaluatedProperties",
            "type",
            "$ref",
            "format",
            "$schema",
            "$id",
            "$defs",
            "pattern",
            *_LOOSENS_WHEN_LARGER,
            *_LOOSENS_WHEN_SMALLER,
        }:
            continue
        old = released.get(keyword, _MISSING)
        new = candidate.get(keyword, _MISSING)
        # `_same_json`, not `==`, and it has to RECURSE: these are the unmodelled
        # keywords, so their values are whole subschemas. `{"oneOf": [{"const": 1}]}`
        # and `{"oneOf": [{"const": true}]}` compare equal under `==` at any depth,
        # and this sweep is the only thing that looks at them at all.
        if _same_json(old, new):
            continue
        known = keyword in _KNOWN_KEYWORDS
        report.changes.append(
            Change(
                _join(pointer, keyword),
                Verdict.MAJOR,
                (
                    f"{keyword!r} differs and its effect on compatibility is not modelled here"
                    if known
                    else f"unrecognised keyword {keyword!r} differs"
                )
                + "; reported breaking rather than guessed -- see the module docstring",
            )
        )


def compare_files(released: Path | str, candidate: Path | str) -> CompatibilityReport:
    """Compare two schema documents on disk."""
    released_doc = json.loads(Path(released).read_text(encoding="utf-8"))
    candidate_doc = json.loads(Path(candidate).read_text(encoding="utf-8"))
    return compare(released_doc, candidate_doc)


def breaking_changes(reports: Iterable[CompatibilityReport]) -> list[Change]:
    """Every breaking change across several reports, for a CI gate's message."""
    return [change for report in reports for change in report.breaking()]

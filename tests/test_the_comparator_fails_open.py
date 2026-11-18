"""The comparator promised to fail toward MAJOR. Measured, it failed toward SAFE.

``compatibility.py``'s module docstring states its contract in one line: *every difference
this module does not positively recognise as minor is reported as breaking, including
differences it does not understand*. An adversarial audit ran that claim against the 41
released documents and found four ways to make it report **IDENTICAL, zero changes,
keeps_its_id=True** for a change that destroys a released rule. Two of them reproduced on
**41 of 41** documents. This file is the regression suite for all four, plus the class-level
sweeps that keep the fixes from being undone one site at a time.

WHY A SEPARATE FILE FROM ``test_the_twenty_one_events.py``. That suite's comparator section
covers the defects found in the FIRST audit, and its own docstring records the blind spot
that let the worst of them ship: *every mutation it ran produced a single change class, so
MINOR and MAJOR never appeared in one report*. The defects here share a different shape --
each is a construct the comparator's recursion never REACHED, so no mutation of a document's
ordinary keywords could ever have produced one. Mixing them into a per-event parametrisation
would hide that; they are their own population and they get their own file.

THE FOUR, AND WHAT EACH ONE CLEARED:

1. **A subschema that is a boolean is reported by nothing.** ``true`` and ``false`` are legal
   JSON Schema subschemas. Both recursion sites -- ``_compare_properties`` and
   ``_compare_defs`` -- guarded themselves with ``isinstance(sub, Mapping)`` and fell
   silently through, and ``properties`` and ``$defs`` are in ``_compare_unhandled``'s
   skip-list because those two functions are supposed to own them. So nothing looked.
   ``$defs/sealed -> true`` drops the ``unevaluatedProperties: false`` that closes every
   event document, on 41 of 41. ``properties/<member> -> false`` makes a released member
   impossible to send, on 20 of the 20 documents that have a top-level property set.

2. **A malformed ``$defs`` skipped the definition diff.** The identical hole
   ``_compare_properties`` had already been fixed for, left open in its sibling: a bare
   ``return``, and ``$defs`` in the skip-list. 41 of 41.

3. **``==`` is the wrong operator, and it was used everywhere.** ``True == 1`` and
   ``0 == False`` in Python, at every depth. The ``enum`` site had been fixed once, with a
   shallow ``(type name, value)`` pair that still compares its second element with ``==``.
   Every other site was untouched: ``const``, both closedness keywords, both bound
   comparisons, ``type``/``$ref``/``format``, ``pattern``, and the unmodelled-keyword sweep
   that is the only thing looking at ``oneOf``/``anyOf``/``allOf``/``items`` at all.

4. **Malformed input raised instead of reporting.** A bound that became a string raised
   ``TypeError`` and a non-object document raised ``AttributeError``, out of the gate a CI
   job calls. A crash is not a verdict, and the module's promise is about verdicts.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from research_contracts.tooling.compatibility import (
    _KNOWN_KEYWORDS,
    _PROSE_KEYWORDS,
    Change,
    CompatibilityReport,
    Verdict,
    compare,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "schemas"

#: One real released document, used wherever a test needs a body rather than a shape. It has
#: a `$defs/sealed`, a top-level property set, `additionalProperties: false` and a `$id`:
#: everything the defects below live in.
REAL = SCHEMAS_DIR / "events" / "review-created.v1.schema.json"


def _released_documents() -> list[Path]:
    """Every released schema document. An equality with the tree, not a hand-listed subset.

    41 files, measured. The two boolean-subschema defects reproduced on ALL of the ones that
    carry the construct, which is why these are swept rather than sampled: a single toy
    example would have shown the same red and would not have shown the blast radius.
    """
    paths = sorted(SCHEMAS_DIR.rglob("*.schema.json"))
    assert paths, "no released schemas found; the sweep below would be vacuous"
    return paths


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _with_defs(paths: list[Path]) -> list[Path]:
    return [p for p in paths if isinstance(_load(p).get("$defs"), dict) and _load(p)["$defs"]]


def _with_properties(paths: list[Path]) -> list[Path]:
    return [
        p for p in paths if isinstance(_load(p).get("properties"), dict) and _load(p)["properties"]
    ]


ALL_RELEASED = _released_documents()
WITH_DEFS = _with_defs(ALL_RELEASED)
WITH_PROPERTIES = _with_properties(ALL_RELEASED)


def _ids(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


# ------------------------------------------------------------------- the control ---


@pytest.mark.parametrize("path", ALL_RELEASED, ids=_ids(ALL_RELEASED))
def test_every_released_document_is_still_compatible_with_itself(path: Path) -> None:
    """The control, over the WHOLE released corpus rather than the twelve event payloads.

    A comparator made stricter until it reports MAJOR for everything would pass every other
    test in this file and be worthless. This is the assertion that costs the fixes something.
    """
    doc = _load(path)
    report = compare(doc, doc)
    assert report.verdict is Verdict.IDENTICAL, str(report)
    assert report.changes == []


# -------------------------------------- C1: a boolean subschema is still a subschema ---


@pytest.mark.parametrize("path", WITH_DEFS, ids=_ids(WITH_DEFS))
def test_a_released_definition_replaced_by_true_is_breaking(path: Path) -> None:
    """`$defs/<name> -> true` reported IDENTICAL on 41 of 41 released documents.

    `true` is the EMPTY schema: it accepts anything. Replacing a definition with it deletes
    every constraint the definition carried. For the twelve event payloads that is
    `$defs/sealed`, whose `unevaluatedProperties: false` is the only thing closing the
    composed document -- so the mutation opens all twelve at once, and the comparator cleared
    it to keep its `$id`.
    """
    doc = _load(path)
    candidate = copy.deepcopy(doc)
    name = sorted(candidate["$defs"])[0]
    candidate["$defs"][name] = True

    report = compare(doc, candidate)
    assert report.changes, f"no change reported at all for $defs/{name} -> true"
    assert report.verdict is Verdict.MAJOR, str(report)
    assert not report.keeps_its_id
    assert any(c.pointer.startswith(f"/$defs/{name}") for c in report.changes), str(report)


@pytest.mark.parametrize("path", WITH_PROPERTIES, ids=_ids(WITH_PROPERTIES))
def test_a_released_member_replaced_by_false_is_breaking(path: Path) -> None:
    """`properties/<member> -> false` reported IDENTICAL on all 20 documents that can carry it.

    `false` is the schema that accepts NOTHING. A released member pinned to it can never be
    sent again -- and if the member is also `required`, the document as a whole becomes
    unsatisfiable. Nothing in the module looked at it.
    """
    doc = _load(path)
    candidate = copy.deepcopy(doc)
    name = sorted(candidate["properties"])[0]
    candidate["properties"][name] = False

    report = compare(doc, candidate)
    assert report.changes, f"no change reported at all for properties/{name} -> false"
    assert report.verdict is Verdict.MAJOR, str(report)
    assert not report.keeps_its_id
    assert any(c.pointer == f"/properties/{name}" for c in report.changes), str(report)


@pytest.mark.parametrize("location", ["properties", "$defs"])
@pytest.mark.parametrize(
    ("released", "candidate", "expected"),
    [
        # mapping -> boolean, in both boolean directions.
        ({"type": "string"}, True, Verdict.MAJOR),
        ({"type": "string"}, False, Verdict.MAJOR),
        # boolean -> mapping, in both boolean directions.
        (True, {"type": "string"}, Verdict.MAJOR),
        (False, {"type": "string"}, Verdict.MINOR),
        # boolean -> boolean.
        (True, False, Verdict.MAJOR),
        (False, True, Verdict.MINOR),
        (True, True, Verdict.IDENTICAL),
        (False, False, Verdict.IDENTICAL),
        # `true` IS `{}`. Normalising it, rather than special-casing it, is what makes this
        # pair correctly identical instead of a false MAJOR.
        (True, {}, Verdict.IDENTICAL),
        ({}, True, Verdict.IDENTICAL),
    ],
)
def test_every_boolean_direction_is_classified(
    location: str, released: Any, candidate: Any, expected: Verdict
) -> None:
    """All four directions, at both recursion sites, including the two that must NOT be major.

    A fix that reported MAJOR for every boolean would pass a one-sided test and would make
    `true -> {}` -- a pure spelling change -- cost a new `$id`. The two IDENTICAL rows and
    the two MINOR rows are the ones that keep this honest: `false` accepted nothing, so
    anything it becomes is a loosening, and every previously valid document still validates.
    """
    old = {"$id": "urn:x:1", location: {"member": released}}
    new = {"$id": "urn:x:1", location: {"member": candidate}}
    report = compare(old, new)
    assert report.verdict is expected, str(report)


@pytest.mark.parametrize("location", ["properties", "$defs"])
@pytest.mark.parametrize("not_a_schema", ["nope", 1, 1.5, [], None])
def test_a_subschema_that_is_not_a_schema_at_all_is_reported(
    location: str, not_a_schema: Any
) -> None:
    """A schema is an object or a boolean. Anything else is unreadable, not absent.

    The old guard was `isinstance(sub, Mapping)`, so a string, a number, a list and a null
    all fell through it exactly as the booleans did -- and unlike the booleans, they carry no
    meaning at all. Reported breaking, per the module docstring.
    """
    old = {"$id": "urn:x:1", location: {"member": {"type": "string"}}}
    new = {"$id": "urn:x:1", location: {"member": not_a_schema}}
    report = compare(old, new)
    assert report.verdict is Verdict.MAJOR, str(report)
    assert any("not a schema" in c.reason for c in report.changes), str(report)


def test_a_boolean_definition_mixes_change_classes_in_one_report() -> None:
    """The blind spot the FIRST audit's fix was written around, exercised on a REAL document.

    ``test_the_twenty_one_events.py`` records why the `max()`-over-`StrEnum` inversion
    survived: *every mutation it ran produced a single change class, so MINOR and MAJOR never
    appeared in one report*. Its fix-test builds a synthetic pair to force the mix.

    This one does not have to. `$defs/sealed -> true` on a released event document produces
    the mix by itself -- MINOR at `/$defs/sealed/unevaluatedProperties` because dropping a
    `false` opens the document, MAJOR at `/$defs/sealed/allOf` because the composition it
    modelled is gone -- so it is simultaneously the C1 regression and a live control on the
    severity rule. If someone re-derives the verdict from `max()` over a `StrEnum` again,
    this goes red against real released bytes rather than against a fixture.
    """
    doc = _load(REAL)
    candidate = copy.deepcopy(doc)
    candidate["$defs"]["sealed"] = True

    report = compare(doc, candidate)
    assert {c.verdict for c in report.changes} == {Verdict.MINOR, Verdict.MAJOR}, str(report)
    assert report.verdict is Verdict.MAJOR, str(report)
    assert not report.keeps_its_id
    assert report.breaking(), "MAJOR verdict with no breaking change listed"


def test_a_mixed_report_is_major_whatever_order_the_changes_arrive_in() -> None:
    """The same mix, both orders. A severity rule that depended on arrival order would pass
    one and fail the other, and every report in this repository is built by a walk whose
    order is an implementation detail."""
    minor = Change("/a", Verdict.MINOR, "loosened")
    major = Change("/b", Verdict.MAJOR, "tightened")
    for changes in ([minor, major], [major, minor]):
        report = CompatibilityReport("r", "r", list(changes))
        assert report.verdict is Verdict.MAJOR
        assert not report.keeps_its_id


# ------------------------------------------------ C2: a malformed $defs skipped the diff ---


@pytest.mark.parametrize("path", WITH_DEFS, ids=_ids(WITH_DEFS))
def test_a_malformed_defs_is_reported_not_skipped(path: Path) -> None:
    """`_compare_defs` did a bare `return`, and `$defs` is in the unknown-keyword skip-list.

    So `{"$defs": {...}} -> {"$defs": ["..."]}` -- every definition in the document replaced
    by a list of their names -- reported IDENTICAL on 41 of 41. This is the same hole
    `_compare_properties` was already fixed for; it was fixed in one sibling and not the
    other, which is why the sweep below runs over the corpus and not over one example.
    """
    doc = _load(path)
    candidate = copy.deepcopy(doc)
    candidate["$defs"] = sorted(candidate["$defs"])

    report = compare(doc, candidate)
    assert report.changes, "malformed $defs reported nothing at all"
    assert report.verdict is Verdict.MAJOR, str(report)
    assert any(c.pointer == "/$defs" for c in report.changes), str(report)


@pytest.mark.parametrize("malformed", ["not-an-object", ["A"], 1, True])
def test_a_malformed_defs_is_reported_from_either_side(malformed: Any) -> None:
    """Either side. A comparator that only guards the candidate cannot compare a released
    document that was itself authored wrong."""
    good = {"$id": "urn:x:1", "$defs": {"A": {"type": "string"}}}
    bad = {"$id": "urn:x:1", "$defs": malformed}
    assert compare(good, bad).verdict is Verdict.MAJOR
    assert compare(bad, good).verdict is Verdict.MAJOR


# ------------------------------------------ C3: `==` conflates true with 1, at every site ---


@pytest.mark.parametrize(
    ("released", "candidate"),
    [
        ({"const": 0}, {"const": False}),
        ({"const": False}, {"const": 0}),
        ({"const": 1}, {"const": True}),
        ({"const": True}, {"const": 1}),
    ],
)
def test_a_const_that_changed_type_is_breaking(released: Any, candidate: Any) -> None:
    """`const` is the version pin a consumer branches on, and it was compared with `!=`.

    `0 != False` is `False` in Python, so a pin that stopped being a number and started
    being a boolean -- which is a different value to every JSON Schema validator on earth --
    reported IDENTICAL. The `enum` sibling four lines above had been fixed for exactly this;
    `const` had not.
    """
    report = compare({"$id": "urn:x:1", **released}, {"$id": "urn:x:1", **candidate})
    assert report.verdict is Verdict.MAJOR, str(report)
    assert any(c.pointer == "/const" for c in report.changes), str(report)


def test_an_explicit_const_null_is_not_the_same_as_no_const() -> None:
    """`{"const": null}` pins the value null; `{}` pins nothing. `.get()` reads both as
    `None`, so dropping a released `const: null` was invisible. Every keyword lookup in the
    module goes through a `_MISSING` sentinel now, and this is the test that says why."""
    assert compare({"$id": "r", "const": None}, {"$id": "r"}).verdict is Verdict.MAJOR
    assert compare({"$id": "r"}, {"$id": "r", "const": None}).verdict is Verdict.MAJOR


@pytest.mark.parametrize("keyword", ["minLength", "maxLength", "minimum", "maximum"])
def test_a_bound_that_became_a_boolean_is_breaking(keyword: str) -> None:
    """`minLength: 1 -> true` reported IDENTICAL: the guard was `if old == new: continue`.

    It is not a loosened bound and not a tightened one. It is not a bound.
    """
    report = compare({"$id": "r", keyword: 1}, {"$id": "r", keyword: True})
    assert report.verdict is Verdict.MAJOR, str(report)


@pytest.mark.parametrize("wrong", ["x", [], {}, None, True])
def test_a_bound_of_the_wrong_type_is_reported_rather_than_raised(wrong: Any) -> None:
    """`new > old` raised `TypeError` for a string bound -- out of the gate a CI job calls.

    A crash is not a verdict. The module's whole promise is about which verdict it produces
    when it cannot understand something, and it cannot keep that promise from a traceback.
    """
    report = compare({"$id": "r", "minLength": 1}, {"$id": "r", "minLength": wrong})
    assert report.verdict is Verdict.MAJOR, str(report)
    assert not report.keeps_its_id


def test_a_bound_written_as_a_float_is_the_same_bound() -> None:
    """The leniency that keeps the strictness honest. JSON has ONE number type: `1` and
    `1.0` are the same value, and a comparator that called that a breaking change would be
    unusable against any document a float-parsing language round-tripped."""
    assert compare({"$id": "r", "minLength": 1}, {"$id": "r", "minLength": 1.0}).verdict is (
        Verdict.IDENTICAL
    )


@pytest.mark.parametrize("wrong", ["a", {"a": 1}, 1, True, None])
def test_an_enum_that_is_not_a_list_is_reported(wrong: Any) -> None:
    """`enum: [...] -> "a"` fell between two branches and reported IDENTICAL.

    Both sides were non-None, so the "introduced or dropped" test was False; both were not
    lists, so the diff never ran; and `enum` is in the unknown-keyword skip-list because
    `_compare_enum_and_const` is supposed to own it. The accepted set collapsed to a string's
    characters and the verdict was IDENTICAL.
    """
    report = compare({"$id": "r", "enum": ["a", "b"]}, {"$id": "r", "enum": wrong})
    assert report.verdict is Verdict.MAJOR, str(report)
    assert any(c.pointer == "/enum" for c in report.changes), str(report)


def test_typed_equality_recurses_rather_than_comparing_pairs() -> None:
    """The first `enum` fix was `(type(v).__name__, v)`, which is SHALLOW.

    The pair's second element is still compared with `==`, so a boolean nested one level
    inside an enum member matched the integer it replaced. `[{"a": 1}]` and `[{"a": true}]`
    are different enums; so are `[[0]]` and `[[false]]`.
    """
    assert compare(
        {"$id": "r", "enum": [{"a": 1}]}, {"$id": "r", "enum": [{"a": True}]}
    ).verdict is (Verdict.MAJOR)
    assert compare({"$id": "r", "enum": [[0]]}, {"$id": "r", "enum": [[False]]}).verdict is (
        Verdict.MAJOR
    )


def test_the_unmodelled_keyword_sweep_sees_a_nested_type_change() -> None:
    """`oneOf`, `anyOf`, `allOf`, `items` and `not` are whole SUBSCHEMAS, and the sweep that
    is the only thing looking at them compared them with `==`. A `const` that turned from
    `1` into `true` inside a `oneOf` branch was invisible to the entire module."""
    for keyword in ("oneOf", "anyOf", "allOf"):
        report = compare(
            {"$id": "r", keyword: [{"const": 1}]}, {"$id": "r", keyword: [{"const": True}]}
        )
        assert report.verdict is Verdict.MAJOR, f"{keyword}: {report}"
    assert (
        compare(
            {"$id": "r", "items": {"const": 0}}, {"$id": "r", "items": {"const": False}}
        ).verdict
        is Verdict.MAJOR
    )


def test_a_closedness_keyword_that_became_a_number_is_not_an_opened_document() -> None:
    """Two wrong answers from one operator.

    `additionalProperties: false -> 0` compared EQUAL under `==` and was skipped. Had the
    skip not fired, the very next line -- `old is False and new is not False` -- would have
    called it "document opened" and reported MINOR. `0` is neither a boolean nor a schema; it
    is unreadable, and unreadable is breaking.
    """
    for keyword in ("additionalProperties", "unevaluatedProperties"):
        report = compare({"$id": "r", keyword: False}, {"$id": "r", keyword: 0})
        assert report.verdict is Verdict.MAJOR, str(report)


def test_a_dialect_change_is_reported_major() -> None:
    """`$schema` used to sit in `_PROSE_KEYWORDS` and was reported by nothing at all.

    It is not decoration: it selects the JSON Schema DIALECT, which governs what every other
    keyword in the document means. A document that moved from draft-07 to 2020-12 -- or to
    any other dialect -- did not necessarily change a single other byte, and the comparator
    still reported IDENTICAL, because `$schema` was skipped before the keyword sweep ever
    saw it. That is present in published 0.9.1/0.9.2, not introduced by later comparator
    work. Fixed: `$schema` gets the same unconditional-MAJOR treatment `type`/`$ref`/`format`
    already get in `_compare_simple`.
    """
    real = json.loads(REAL.read_text(encoding="utf-8"))
    mutant = copy.deepcopy(real)
    mutant["$schema"] = "http://json-schema.org/draft-07/schema#"
    assert real["$schema"] != mutant["$schema"]

    report = compare(real, mutant)
    assert report.verdict is Verdict.MAJOR, str(report)
    assert any(c.pointer == "/$schema" for c in report.changes), str(report)

    # Also true with no other machinery in play -- a plain two-key document, not just the
    # one real fixture the module happens to ship.
    plain = compare(
        {"$id": "r", "$schema": "https://json-schema.org/draft/2020-12/schema"},
        {"$id": "r", "$schema": "http://json-schema.org/draft-07/schema#"},
    )
    assert plain.verdict is Verdict.MAJOR, str(plain)


def test_a_dialect_left_unchanged_is_not_reported() -> None:
    """The other half: `$schema` must not become noisy. Two documents that declare the SAME
    dialect, with everything else identical, are IDENTICAL -- the same shape every one of
    the 41 released documents is in against itself."""
    real = json.loads(REAL.read_text(encoding="utf-8"))
    same = copy.deepcopy(real)
    assert real == same
    report = compare(real, same)
    assert report.verdict is Verdict.IDENTICAL, str(report)


#: Every keyword the module recognises, plus two it does not, MINUS the prose keywords.
#:
#: The prose set -- `$comment`, `title`, `description` -- is excluded because the module
#: deliberately reports NO change for any difference in it: this repository's house style
#: puts long authoring rationale in `$comment`, and a comparator that called a rewritten
#: explanation breaking would train authors to stop explaining themselves. That is a
#: documented decision, not the defect this sweep hunts. It is subtracted here rather than
#: hard-coded so that adding a keyword to either set keeps the sweep exact. `$schema` is NOT
#: in the prose set -- it selects the dialect, is handled unconditionally-MAJOR in
#: `_compare_simple`, and this sweep now covers it like `type`/`$ref`/`format`.
_SWEEP_KEYWORDS = sorted(
    (_KNOWN_KEYWORDS | {"minContains", "maxContains", "x-unrecognised"}) - _PROSE_KEYWORDS
)


@pytest.mark.parametrize("keyword", _SWEEP_KEYWORDS)
@pytest.mark.parametrize(("number", "boolean"), [(1, True), (0, False)])
def test_no_comparison_in_the_module_conflates_a_boolean_with_a_number(
    keyword: str, number: int, boolean: bool
) -> None:
    """The class-level sweep, and the reason C3 was not fixed as three call sites.

    The audit named `const`, `minLength` and `enum`. Fixing those three would have left the
    same defect in `additionalProperties`, `unevaluatedProperties`, `pattern`, `type`,
    `$ref`, `format`, `$id`, both bound directions and the unmodelled-keyword sweep -- ten
    more sites, each one a silent clearance, each one findable only by someone who thought to
    look. This parametrisation asserts the CLASS: for every keyword the module recognises,
    plus two it does not, swapping a number for the boolean Python says equals it must never
    report IDENTICAL. A new keyword added to `_KNOWN_KEYWORDS` is swept automatically.
    """
    report = compare({"$id": "urn:x:1", keyword: number}, {"$id": "urn:x:1", keyword: boolean})
    assert report.verdict is not Verdict.IDENTICAL, str(report)
    assert report.changes, f"{keyword}: {number!r} -> {boolean!r} reported no change at all"


@pytest.mark.parametrize("keyword", _SWEEP_KEYWORDS)
def test_no_keyword_comparison_raises_on_a_wrong_typed_value(keyword: str) -> None:
    """The other half of the class: a wrong-typed value must produce a VERDICT, not a
    traceback. Two sites raised -- `_compare_bounds` on an unorderable pair and `compare`
    itself on a non-object document -- and a gate that dies has said nothing about the
    change it was asked to judge."""
    for wrong in ("x", 1, 1.5, True, None, [], {}, [{"a": 1}]):
        report = compare({"$id": "urn:x:1", keyword: "a"}, {"$id": "urn:x:1", keyword: wrong})
        assert isinstance(report.verdict, Verdict)


def test_a_required_holding_a_non_string_is_reported_not_raised() -> None:
    """`required` holds member NAMES. `set([{"a": 1}])` raises TypeError before any report
    exists -- the same class as the already-fixed `required: "id"` string case, one element
    deeper."""
    report = compare(
        {"$id": "r", "required": [{"a": 1}], "properties": {"a": {"type": "string"}}},
        {"$id": "r", "required": ["a"], "properties": {"a": {"type": "string"}}},
    )
    assert report.verdict is Verdict.MAJOR, str(report)


# --------------------------------------------------- the low ones: a crash is not a verdict ---


@pytest.mark.parametrize("document", [[], "a schema", 1, None, 1.5])
def test_a_document_that_is_not_a_schema_is_reported_not_raised(document: Any) -> None:
    """`compare` read `$id` off both arguments before anything checked them, so
    `compare(True, {...})` raised `AttributeError` -- out of the gate a CI job calls.

    A list, a string, a number and a null are not schemas in either direction, and malformed
    is breaking.
    """
    real = _load(REAL)
    for released, candidate in ((document, real), (real, document)):
        report = compare(released, candidate)
        assert report.verdict is Verdict.MAJOR, str(report)
        assert not report.keeps_its_id


def test_a_boolean_root_document_is_classified_as_the_schema_it_is() -> None:
    """`true` and `false` ARE legal schema documents at the ROOT, not just as subschemas,
    and they get the same four rules -- which means one of the six pairs below is correctly
    MINOR. A fix that reported MAJOR for every boolean would pass a sloppier version of this
    test and would be wrong about the one direction that loosens.
    """
    real = _load(REAL)
    # `true` is the empty schema; a real document is strictly narrower than it.
    assert compare(True, real).verdict is Verdict.MAJOR
    # ...and narrowing to nothing is the most complete break there is.
    assert compare(real, False).verdict is Verdict.MAJOR
    assert compare(True, False).verdict is Verdict.MAJOR
    # `false` accepted nothing, so anything it becomes accepts everything it used to.
    assert compare(False, real).verdict is Verdict.MINOR
    assert compare(False, True).verdict is Verdict.MINOR
    assert compare(False, False).verdict is Verdict.IDENTICAL


@pytest.mark.parametrize("keyword", ["properties", "$defs"])
@pytest.mark.parametrize("falsy", [0, False, [], ""])
def test_a_falsy_properties_or_defs_is_malformed_not_empty(keyword: str, falsy: Any) -> None:
    """`released.get(kw) or {}` tests TRUTHINESS, and the malformed branch then never ran.

    So `{"properties": 0}` against `{"properties": false}` reported IDENTICAL, and so did
    either of them against a document whose property set is genuinely empty. The value is not
    an empty object; it is not an object at all, and the diff could not run.
    """
    empty = {"$id": "urn:x:1", keyword: {}}
    broken = {"$id": "urn:x:1", keyword: falsy}
    assert compare(empty, broken).verdict is Verdict.MAJOR, keyword
    assert compare(broken, empty).verdict is Verdict.MAJOR, keyword
    assert compare(broken, {"$id": "urn:x:1", keyword: False}).verdict is Verdict.MAJOR


def test_a_report_over_malformed_documents_still_renders() -> None:
    """The `_MISSING` sentinel must never reach a reason string: `repr(object())` embeds a
    memory address, so two runs of the same comparison would produce two different reports.
    """
    text = str(compare({"$id": "r", "type": "string"}, {"$id": "r"}))
    assert "0x" not in text, text
    assert "absent" in text, text

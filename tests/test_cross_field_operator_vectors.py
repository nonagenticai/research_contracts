"""The two operator divergences ``EXTENSIONS.md`` recorded and neither engine had closed.

Both were *derived*, not decided. Nothing normative is invented here.

**§4.2 -- what ``equal`` means across languages.** The document already prescribed the
answer: *"A second implementation MUST use RFC 8785 canonical-byte equality, which agrees
with Python on every value the released schemas permit and is the same comparator
``unique_by`` and ``disjoint`` are being moved to (D1)."* The engine used Python ``==``,
where ``bool`` IS an ``int``, so ``{"left": true, "right": 1}`` and ``{"left": 0, "right":
false}`` were reported as HOLDING. That is §7.5's shape exactly: an unimplemented check is
not an undecided question. It was also not hypothetical -- the TypeScript port had *already*
moved to canonical bytes, so the two engines answered the same released rule on the same
instance differently until this landed.

**§4.5 -- a member missing its key.** ``unique_by`` reported it (step 2) and ``disjoint``
skipped it in silence (steps 2 and 3), so "the two sets are disjoint" could be true by
vacuity, one member at a time. The repository had already answered the identical question in
released code: ``hash_view`` raises ``MissingOrderKeyError`` because *every member of a
set-like array must carry its whole released order key, and an absent key is not the same
fact as a shared one*. Skipping is the fail-open half, and fail-open is the class this
repository exists to eliminate, so ``disjoint`` was aligned onto ``unique_by`` rather than
the reverse.

**Why one committed file rather than two test suites.** §9's principle: a Python-only
closure "derives a manifest the Python engine cannot derive, which is a cross-language
split". ``fixtures/canonical-cross-field/v1/operator-vectors.json`` is the record, and
``packages/typescript/test/crossFieldOperatorVectors.test.ts`` replays the same bytes. The
expected failure lists are compared element by element, in order, so a rewording on either
side is red with no second copy of the text to keep in step.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import registry as registry_module
from research_contracts.canonical import structural as structural_module
from research_contracts.canonical.registry import canonical_schemas

ROOT = Path(__file__).resolve().parents[1]
VECTORS_PATH = ROOT / "fixtures" / "canonical-cross-field" / "v1" / "operator-vectors.json"
TS_MIRROR = ROOT / "packages" / "typescript" / "test" / "crossFieldOperatorVectors.test.ts"

VECTORS: dict[str, Any] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = VECTORS["cases"]

#: An EQUALITY, not a floor. A vector that disappears and a vector that appears are both
#: changes to what is measured, and a floor cannot catch the first. 23 = 10 for §4.2 + 13
#: for §4.5.
EXPECTED_CASES = 23

#: Per section, ``(vectors expecting a FAILURE, vectors expecting NONE)`` -- EXACT, for the
#: same reason :data:`EXPECTED_CASES` is. The second number is the one that matters: without
#: it an engine that reported every pair as violating, which is the trivial way to satisfy
#: every failing vector, would satisfy this whole file.
#:
#: It was written as a pair of FLOORS and the floors were then quoted as a count -- "six of
#: them expect no failure" when the answer is five. A floor invites exactly that: it is not
#: the number, so nobody can read the number off it. Both are now the number.
EXPECTED_PER_SECTION = {"4.2": (7, 3), "4.5": (11, 2)}

#: How many vectors may declare a DIFFERENT expectation for the port, as an equality.
#:
#: There is one, and it is not an engine defect: `JSON.parse` collapses an integer literal
#: outside the exact IEEE-754 double range before the port's engine ever runs, where Python's
#: ``json.loads`` yields the exact ``int`` and RFC 8785 refuses it. No engine change removes
#: that. Pinning the COUNT is what stops the mechanism becoming a way to launder a real
#: divergence into the record: adding ``failures_port`` to a second case is red until someone
#: moves this number on purpose.
EXPECTED_PORT_DIVERGENCES = 1


def evaluate(case: dict[str, Any]) -> list[str]:
    """Run one vector against the released Python engine, with its probe schema registered."""
    probe = case["probe_schema"]
    schemas = {**canonical_schemas(), probe["$id"]: probe}
    monkey = pytest.MonkeyPatch()
    monkey.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        return structural_module.check_cross_field_rules(case["instance"], probe["$id"])
    finally:
        monkey.undo()
        structural_module._collect.cache_clear()


def test_the_vector_record_measures_something_and_not_only_failures() -> None:
    """Non-vacuity and the false-positive partition, per section rather than in aggregate.

    A shared total lets one section's vectors satisfy the other's floor, which is how a
    section that contributes nothing reads as covered.
    """
    assert len(CASES) == EXPECTED_CASES, [case["name"] for case in CASES]
    assert {case["section"] for case in CASES} == set(VECTORS["sections"])
    assert set(VECTORS["sections"]) == set(EXPECTED_PER_SECTION)
    for section, (expect_failing, expect_passing) in EXPECTED_PER_SECTION.items():
        in_section = [case for case in CASES if case["section"] == section]
        failing = [case for case in in_section if case["expect"]["failures"]]
        passing = [case for case in in_section if not case["expect"]["failures"]]
        assert len(failing) == expect_failing, (section, [c["name"] for c in failing])
        assert len(passing) == expect_passing, (section, [c["name"] for c in passing])
    assert len({case["name"] for case in CASES}) == len(CASES), "two vectors share a name"


def test_a_per_engine_expectation_is_declared_counted_and_justified() -> None:
    """The escape hatch that would otherwise launder a real split into the record.

    A case may answer differently in the two engines only by carrying ``failures_port``, only
    together with a ``port_divergence`` saying why, and only while the COUNT of such cases
    matches :data:`EXPECTED_PORT_DIVERGENCES`. Without the count this mechanism would let any
    future divergence be absorbed by adding a key, which is the shape of every escape hatch
    this repository has had to close.
    """
    declared = [case for case in CASES if "failures_port" in case["expect"]]
    assert len(declared) == EXPECTED_PORT_DIVERGENCES, [case["name"] for case in declared]
    for case in declared:
        reason = case["expect"].get("port_divergence", "")
        assert isinstance(reason, str) and len(reason) >= 80, case["name"]
        assert case["expect"]["failures"] != case["expect"]["failures_port"], (
            f"{case['name']} declares a port divergence and then states the same expectation, "
            "which is a declaration that measures nothing"
        )
    # ...and no case may carry the justification without the divergence it justifies.
    orphans = [
        case["name"]
        for case in CASES
        if "port_divergence" in case["expect"] and "failures_port" not in case["expect"]
    ]
    assert orphans == [], orphans


def test_the_typescript_mirror_replays_this_exact_file() -> None:
    """Both engines or neither.

    The record names its two replayers; if the port's suite is deleted, renamed or pointed
    at a different file, this file's guarantee silently becomes a Python-only one -- which is
    the cross-language split §9 forbids, arriving as an absence rather than as a failure.
    """
    assert VECTORS["replayed_by"] == [
        "tests/test_cross_field_operator_vectors.py",
        "packages/typescript/test/crossFieldOperatorVectors.test.ts",
    ]
    assert Path(__file__).relative_to(ROOT).as_posix() == VECTORS["replayed_by"][0]
    assert TS_MIRROR.relative_to(ROOT).as_posix() == VECTORS["replayed_by"][1]
    mirror = TS_MIRROR.read_text(encoding="utf-8")
    assert "operator-vectors.json" in mirror, "the port's suite does not read this record"
    # Every expected string is compared BYTE FOR BYTE on both sides, so neither engine may
    # hold a private copy of the text it is supposedly being measured against.
    for case in CASES:
        assert case["name"] not in mirror, (
            f"{case['name']} is hardcoded in the port's suite instead of read from the record"
        )


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_engine_reproduces_the_recorded_failures(case: dict[str, Any]) -> None:
    """Exact list, in order, byte for byte -- not a substring and not a count."""
    assert evaluate(case) == case["expect"]["failures"]


#: The four ways a weakened comparison would still read green, as functions of
#: ``(expected, actual)``. Each is a spelling the replay above could have been written in.
#: The point of naming them is that they are applied to a REAL engine result below -- an
#: earlier version of this test asserted them against two hand-written lists, which is a
#: statement about Python's ``list.__eq__`` and measures nothing about the suite.
_WEAKER_COMPARISONS = {
    "set equality (blind to order and to duplicates)": lambda e, a: set(e) == set(a),
    "containment (blind to an extra failure)": lambda e, a: all(item in a for item in e),
    "count only (blind to every word)": lambda e, a: len(e) == len(a),
    "joined substring (blind to order and to extras)": lambda e, a: all(
        item in " | ".join(a) for item in e
    ),
}


@pytest.mark.parametrize("weakening", sorted(_WEAKER_COMPARISONS), ids=list(_WEAKER_COMPARISONS))
def test_a_weaker_comparison_would_miss_a_real_engine_defect(
    monkeypatch: pytest.MonkeyPatch, weakening: str
) -> None:
    """Each weaker spelling of the replay assertion is shown to ACCEPT a broken engine.

    A clean corpus cannot falsify a weakened comparison, so the discriminating power is
    measured against an engine that has actually been broken rather than against synthetic
    lists. The mutation reverses the failure ORDER -- the property §4.5 newly makes contract
    text -- and every comparison below is blind to it while ``==`` on the list is not.
    """
    case = next(
        c for c in CASES if c["name"] == "4.5-both-sides-report-and-the-left-side-reports-first"
    )
    expected = case["expect"]["failures"]
    assert len(expected) == 2, "the premise is gone: this vector no longer has two failures"
    assert evaluate(case) == expected, "the unmutated engine already disagrees"

    real = structural_module._missing_member_key
    monkeypatch.setattr(
        structural_module,
        "_missing_member_key",
        lambda name, at, index, role, key: real(name, at, index, role, key),
    )
    monkeypatch.setattr(
        structural_module,
        "_check_disjoint",
        lambda instance, rule, name, base="": list(
            reversed(_check_disjoint_unmutated(instance, rule, name, base))
        ),
    )
    broken = evaluate(case)
    assert broken != expected, "the mutation did not change the engine's answer"
    assert _WEAKER_COMPARISONS[weakening](expected, broken), (
        f"{weakening!r} already rejects this defect, so it is not the weakening it claims to "
        "be and this control proves nothing"
    )


#: Captured at import so the monkeypatch above can call the real implementation without
#: recursing through the attribute it is replacing.
_check_disjoint_unmutated = structural_module._check_disjoint


def test_an_operand_with_no_canonical_bytes_is_a_failure_and_never_a_raise() -> None:
    """The regression the first version of this closure shipped, in the two shapes no
    committed fixture can carry.

    ``validate_instance`` is documented to RETURN every released failure, and it deliberately
    concatenates the schema layer with the cross-field layer instead of short-circuiting -- so
    malformed input is precisely the input it exists to describe. Routing ``equal`` through
    the canonicalizer made that call RAISE: measured, an instance carrying two integers past
    the exact double range returned 16 failures before the change and raised
    ``UnstableFloatError`` after.

    ``NaN`` and ``inf`` cannot be written into the committed record, because JSON has no
    literal for either and the record must stay strict JSON -- ``json.loads`` accepts the bare
    tokens as a Python extension on its DEFAULT settings, which is exactly why they are
    reachable and exactly why they are tested here in code instead.
    """
    released = "urn:datacompany:evidence-location-version:1"
    for label, value in (
        ("NaN", json.loads("NaN")),
        ("Infinity", json.loads("Infinity")),
        ("-Infinity", json.loads("-Infinity")),
        ("int past 2**53", 9007199254740993),
        ("lone surrogate", json.loads('"\\ud800"')),
    ):
        instance = {"evidence_location_id": value, "entity_id": value}
        failures = structural_module.validate_instance(instance, released)
        assert isinstance(failures, list), label
        named = [f for f in failures if "cannot be decided" in f]
        assert len(named) == 2, (label, named)
    # The control: a value that CAN be canonicalized still reaches the equality verdict, so
    # the guard above cannot have been satisfied by refusing everything.
    same = "urn:datacompany:x"
    decided = structural_module.check_cross_field_rules(
        {"evidence_location_id": same, "entity_id": same}, released
    )
    assert [f for f in decided if "cannot be decided" in f] == []
    assert [f for f in decided if "typed_alias" in f] == []


def test_every_released_equal_rule_is_decided_by_the_same_comparator_the_vectors_pin() -> None:
    """The vectors run on a probe; the released rules must run on the same code path.

    A closure that reached only the probe schema would be a test-only fix -- the class this
    repository found four times in one week. ``_equal`` is therefore asserted to be what the
    evaluator actually calls, by breaking it and watching a RELEASED rule change its answer.
    """
    sites = [
        (ref, rule)
        for ref in sorted(registry_module.canonical_schemas())
        for rule, _ in structural_module.collect_cross_field_rule_sites(ref)
        if rule["rule"] in ("equal", "equal_when_both_present")
    ]
    assert len(sites) >= 3, sites
    ref, rule = next((ref, rule) for ref, rule in sites if rule["rule"] == "equal")
    same = {"consumer": True}
    instance: dict[str, Any] = {}
    for pointer in (rule["left"], rule["right"]):
        node = instance
        tokens = pointer.lstrip("/").split("/")
        for token in tokens[:-1]:
            node = node.setdefault(token, {})
        node[tokens[-1]] = same
    holds = [
        f for f in structural_module.check_cross_field_rules(instance, ref) if rule["name"] in f
    ]
    assert holds == [], holds
    # The same instance with a boolean on one side and the number 1 on the other is the
    # divergent pair, evaluated through the RELEASED rule rather than through a probe.
    node = instance
    tokens = rule["right"].lstrip("/").split("/")
    for token in tokens[:-1]:
        node = node[token]
    node[tokens[-1]] = {"consumer": 1}
    diverging = [
        f for f in structural_module.check_cross_field_rules(instance, ref) if rule["name"] in f
    ]
    assert diverging != [], "a released equal rule still accepts true where 1 is written"

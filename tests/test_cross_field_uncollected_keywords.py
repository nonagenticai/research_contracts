"""A cross-field rule under an uncollected applicator fails closed instead of vanishing.

``_APPLICATOR_BRANCHES`` is ``allOf``/``anyOf``/``oneOf``/``then``/``else``. A rule declared
under ``if``, ``not``, ``dependentSchemas`` or ``unevaluatedProperties`` was reached by
nothing: the collector never visited the node, so ``collect_cross_field_rules`` returned an
empty list and ``check_cross_field_rules`` reported NO failures against an instance that
violates the rule -- while the same rule under ``allOf`` or ``then`` reported it. The schema
read as enforced and enforced nothing, which is the vacuity class, and it was invisible
because there was no error to see.

``contains`` and ``propertyNames`` already had the right shape: they raise. This extends that
precedent to the other four rather than inventing a new one. Failing closed rather than
COLLECTING them is deliberate -- ``not`` and ``dependentSchemas`` are genuinely evaluable
in-place applicators, so collecting them is a behaviour EXPANSION that needs a decision, and
failing closed is its conservative, reversible half. The claim that this costs nothing today
is not asserted, it is recomputed from the released corpus below.

The list of blocked keywords was then itself incomplete, in the same silent way it exists to
prevent: ``unevaluatedItems`` was absent while its direct sibling ``unevaluatedProperties`` --
same vocabulary, same justification, same sentence in the comment -- was present. A rule under
it collected nothing, reported nothing and raised nothing. Adding it by hand would have fixed
one omission and left the enumeration exactly as unverifiable as before, so the sweep at the
bottom of this module derives EVERY subschema-bearing 2020-12 keyword from the official
vocabulary meta-schemas and requires each one to be either collected or refused. A keyword
that silently drops a rule is red there, whether or not anybody remembered it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema.validators import SPECIFICATIONS

from research_contracts.canonical import CrossFieldError, check_cross_field_rules
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical import structural as structural_module
from research_contracts.canonical.registry import canonical_schemas
from research_contracts.canonical.structural import (
    collect_cross_field_rule_sites,
    collect_cross_field_rules,
)

ROOT = Path(__file__).resolve().parents[1]
TS_STRUCTURAL = ROOT / "packages" / "typescript" / "src" / "structural.ts"

PROBE_ID = "urn:datacompany:uncollected-keyword-probe:1"
NESTED_ID = "urn:datacompany:uncollected-keyword-nested:1"

#: A rule that a released schema could legally declare, opted in to relative scope so that
#: nothing but the collector's reach is under test.
RULE: dict[str, Any] = {"rule": "equal", "scope": "relative", "left": "/a", "right": "/b"}

#: The instance the rule is violated by. Both members are present and unequal, so a rule that
#: is evaluated ANYWHERE has an opinion about it.
VIOLATING: dict[str, Any] = {"a": 1, "b": 2}

#: The keywords that fail closed because the collector does not descend into them, each as
#: the schema body that puts ``NESTED_ID`` under it.
UNCOLLECTED: dict[str, Any] = {
    "if": {"if": {"$ref": NESTED_ID}},
    "not": {"not": {"$ref": NESTED_ID}},
    "dependentSchemas": {"dependentSchemas": {"a": {"$ref": NESTED_ID}}},
    "unevaluatedProperties": {"unevaluatedProperties": {"$ref": NESTED_ID}},
    "unevaluatedItems": {"unevaluatedItems": {"$ref": NESTED_ID}},
}

#: The keywords that fail closed for the OTHER reason: no instance location at all.
#: ``contentSchema`` joins the two originals -- it applies to the DECODED contents of a
#: string, which is not a location in this document, and 2020-12's content vocabulary is
#: annotation-only besides, so nothing asserts it anywhere.
UNLOCATABLE: dict[str, Any] = {
    "contains": {"contains": {"$ref": NESTED_ID}},
    "propertyNames": {"propertyNames": {"$ref": NESTED_ID}},
    "contentSchema": {"contentSchema": {"$ref": NESTED_ID}},
}

#: Shapes that are not 2020-12 at all, so the SPECIFICATION applies nothing there. Blocked for
#: a third reason: the rule is dropped twice over and by neither engine's choice.
LEGACY: dict[str, Any] = {
    "additionalItems": {"additionalItems": {"$ref": NESTED_ID}},
    # The 2019-09 tuple form. 2020-12 requires `items` to be one schema and spells the tuple
    # as `prefixItems`, so an array here is read by no 2020-12 validator.
    "items": {"items": [{"$ref": NESTED_ID}]},
}

#: The deliberate NON-blocking case, and the only placement that may collect nothing without
#: raising. A bag of subschemas sits at no instance location: nothing applies its contents
#: until a ``$ref`` composes them, and where one does, the collector reaches the rule through
#: that ``$ref`` unblocked (asserted below). Blocking the bag would make a rule inside a
#: ``$def`` raise even when it IS composed, because the walk reaches the same node by both
#: routes -- a reusable subschema carrying a rule would become undeclarable.
DEFINITION_BAGS: dict[str, Any] = {
    "$defs": {"$defs": {"d": {"$ref": NESTED_ID}}},
    "definitions": {"definitions": {"d": {"$ref": NESTED_ID}}},
}

#: The collected branches. These are the control: without them, an engine that raised on
#: EVERY placement would satisfy the sweeps above.
COLLECTED: dict[str, Any] = {
    "allOf": {"allOf": [{"$ref": NESTED_ID}]},
    "anyOf": {"anyOf": [{"$ref": NESTED_ID}]},
    "oneOf": {"oneOf": [{"$ref": NESTED_ID}]},
    "then": {"if": {"type": "object"}, "then": {"$ref": NESTED_ID}},
    "else": {"if": {"type": "string"}, "else": {"$ref": NESTED_ID}},
}


@pytest.fixture
def place(monkeypatch: pytest.MonkeyPatch):
    """Put ``RULE`` under a keyword and return the collector/evaluator over a real registry."""
    nested = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": NESTED_ID,
        "type": "object",
        "x-datacompany-cross-field": [RULE],
    }

    def _place(
        body: dict[str, Any], instance: Any = VIOLATING
    ) -> tuple[list[dict[str, Any]], list[str]]:
        probe = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": PROBE_ID, **body}
        schemas = {**canonical_schemas(), NESTED_ID: nested, PROBE_ID: probe}
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
        structural_module._collect.cache_clear()
        return collect_cross_field_rules(PROBE_ID), check_cross_field_rules(instance, PROBE_ID)

    yield _place
    structural_module._collect.cache_clear()


# ------------------------------------------------------------------- non-vacuity first ---


@pytest.mark.parametrize("keyword", sorted(COLLECTED))
def test_a_collected_branch_still_reports_the_violation(place, keyword: str) -> None:
    """The control. Every sweep below is a ``pytest.raises``; without this, an engine that
    raised on every placement -- or one that collected nothing anywhere -- would be green."""
    rules, failures = place(COLLECTED[keyword])
    assert rules == [RULE]
    assert failures == ["equal: /a and /b must both be present and equal"]


@pytest.mark.parametrize("keyword", sorted(COLLECTED))
def test_a_collected_branch_is_silent_when_the_rule_holds(place, keyword: str) -> None:
    """The false-positive control: the rule discriminates between instances rather than
    firing unconditionally, so "it reported a failure" above is evidence about the rule and
    not about an evaluator that always complains."""
    rules, failures = place(COLLECTED[keyword], {"a": 1, "b": 1})
    assert rules == [RULE]
    assert failures == []


# ------------------------------------------------------------------------ the defect ---


@pytest.mark.parametrize("keyword", sorted(UNCOLLECTED))
def test_a_rule_under_an_uncollected_applicator_raises_and_names_the_keyword(
    place, keyword: str
) -> None:
    """The silent drop, turned into an authoring error that says which keyword to move out
    of. Naming the keyword is asserted, not just the raise: a generic "unevaluable" message
    would leave an author with four candidates and no way to tell them apart."""
    with pytest.raises(CrossFieldError) as raised:
        place(UNCOLLECTED[keyword])
    message = str(raised.value)
    assert f"declared under {keyword!r}" in message, message
    assert "does not collect cross-field rules from" in message, message


@pytest.mark.parametrize("keyword", sorted(UNLOCATABLE))
def test_the_existing_unlocatable_precedent_is_unchanged(place, keyword: str) -> None:
    """``contains``/``propertyNames`` still raise, still for their own reason. The two
    families must stay distinguishable: an author whose rule is under ``contains`` cannot fix
    it by moving to ``allOf``, and one whose rule is under ``if`` can."""
    with pytest.raises(CrossFieldError) as raised:
        place(UNLOCATABLE[keyword])
    message = str(raised.value)
    assert f"declared under {keyword!r}" in message, message
    assert "no single instance location" in message, message


@pytest.mark.parametrize("keyword", sorted(LEGACY))
def test_a_rule_under_a_dead_pre_2020_shape_raises(place, keyword: str) -> None:
    """``additionalItems`` and an array-valued ``items`` are not 2020-12 keywords.

    A 2020-12 validator reads no subschema in either, so a rule declared there is dropped by
    the specification before this engine gets a say -- and dropped invisibly, since an
    unknown member is legal and produces no diagnostic anywhere. It fails closed instead, and
    the message names the 2020-12 keyword the author meant.
    """
    with pytest.raises(CrossFieldError) as raised:
        place(LEGACY[keyword])
    message = str(raised.value)
    assert f"declared under {keyword!r}" in message, message
    assert "2020-12" in message, message


@pytest.mark.parametrize("keyword", sorted(DEFINITION_BAGS))
def test_a_rule_in_an_uncomposed_definition_bag_is_collected_by_nothing(
    place, keyword: str
) -> None:
    """The deliberate exclusion, asserted rather than left implicit.

    This is the one placement that neither collects nor raises, and it is not the vacuity
    class: JSON Schema applies nothing in an uncomposed bag either, so there is no
    enforcement to lose. The half that makes it safe is the next test.
    """
    rules, failures = place(DEFINITION_BAGS[keyword])
    assert rules == []
    assert failures == []


@pytest.mark.parametrize("keyword", sorted(DEFINITION_BAGS))
def test_composing_a_definition_bag_entry_reaches_its_rule(place, keyword: str) -> None:
    """Why the bag is an exclusion and not a hole: ``$ref`` reaches the rule, unblocked.

    Without this the previous test would be indistinguishable from a silent drop, and a
    future decision to block the bag would look free. It is not: blocking it would make this
    case raise, because the walk reaches the same node by both routes.
    """
    body = dict(DEFINITION_BAGS[keyword])
    body["allOf"] = [{"$ref": f"{PROBE_ID}#/{keyword.replace('~', '~0').replace('/', '~1')}/d"}]
    rules, failures = place(body)
    assert rules == [RULE]
    assert failures == ["equal: /a and /b must both be present and equal"]


def test_the_outermost_blocking_keyword_is_the_one_reported(place) -> None:
    """Nesting is reported at the keyword an author would have to move out of FIRST."""
    with pytest.raises(CrossFieldError, match="declared under 'not'"):
        place({"not": {"if": {"$ref": NESTED_ID}}})


# ------------------------------------------- the blocked flag survives every crossing ---
#
# The test above only exercises `{"not": {"if": ...}}`, which crosses from one blocked
# keyword into another and so never leaves the blocked-keyword loop. Three of the four
# `blocked=` hand-offs in `_collect` were therefore unpinned, and each could be replaced with
# `blocked=None` with the whole module still green:
#
#   * the `properties` child step,
#   * the `patternProperties` child step,
#   * the collected applicator branches (allOf/anyOf/oneOf/then/else).
#
# The last is the serious one. Dropping the flag there re-opens `if.allOf[0].<rule>` being
# COLLECTED -- the schema declares a rule under `if`, the collector walks into the `allOf`
# beneath it, forgets it was blocked, and enforces a rule that JSON Schema applies only
# conditionally. That is defect 2 itself, in the code that closed it.

#: One entry per crossing the collector can make while blocked, with the keyword whose name
#: has to survive it. Both nesting orders, so the flag is asserted going in and coming out.
BLOCKED_CROSSINGS: dict[str, tuple[dict[str, Any], str]] = {
    # blocked keyword OUTSIDE, applicator/child keyword INSIDE: the flag must be carried in.
    "if.allOf[0]": ({"if": {"allOf": [{"$ref": NESTED_ID}]}}, "if"),
    "not.allOf[0]": ({"not": {"allOf": [{"$ref": NESTED_ID}]}}, "not"),
    "if.anyOf[0]": ({"if": {"anyOf": [{"$ref": NESTED_ID}]}}, "if"),
    "if.oneOf[0]": ({"if": {"oneOf": [{"$ref": NESTED_ID}]}}, "if"),
    "if.then": ({"if": {"then": {"$ref": NESTED_ID}}}, "if"),
    "if.else": ({"if": {"else": {"$ref": NESTED_ID}}}, "if"),
    "if.properties.x": ({"if": {"properties": {"x": {"$ref": NESTED_ID}}}}, "if"),
    "if.patternProperties": (
        {"if": {"patternProperties": {"^x$": {"$ref": NESTED_ID}}}},
        "if",
    ),
    "if.prefixItems[0]": ({"if": {"prefixItems": [{"$ref": NESTED_ID}]}}, "if"),
    "if.items": ({"if": {"items": {"$ref": NESTED_ID}}}, "if"),
    "if.additionalProperties": ({"if": {"additionalProperties": {"$ref": NESTED_ID}}}, "if"),
    "if.contains": ({"if": {"contains": {"$ref": NESTED_ID}}}, "if"),
    "if.not": ({"if": {"not": {"$ref": NESTED_ID}}}, "if"),
    "not.if": ({"not": {"if": {"$ref": NESTED_ID}}}, "not"),
    # applicator/child keyword OUTSIDE, blocked keyword INSIDE: the flag must be raised there
    # and reported even though the walk has already moved.
    "allOf[0].if": ({"allOf": [{"if": {"$ref": NESTED_ID}}]}, "if"),
    "allOf[0].not": ({"allOf": [{"not": {"$ref": NESTED_ID}}]}, "not"),
    "properties.x.if": ({"properties": {"x": {"if": {"$ref": NESTED_ID}}}}, "if"),
    "patternProperties.if": (
        {"patternProperties": {"^x$": {"if": {"$ref": NESTED_ID}}}},
        "if",
    ),
    "contains.if": ({"contains": {"if": {"$ref": NESTED_ID}}}, "contains"),
    # ...and across a `$ref`, which is its own hand-off.
    "if.$ref": (
        {"if": {"$ref": f"{PROBE_ID}#/$defs/d"}, "$defs": {"d": {"$ref": NESTED_ID}}},
        "if",
    ),
}


@pytest.mark.parametrize("crossing", sorted(BLOCKED_CROSSINGS))
def test_the_blocked_flag_survives_every_crossing(place, crossing: str) -> None:
    """A rule under a blocked keyword stays blocked however deeply it is then nested.

    The outermost blocking keyword is the one named, so the diagnostic points at what an
    author has to move out of first rather than at an inner keyword they never wrote.
    """
    body, keyword = BLOCKED_CROSSINGS[crossing]
    with pytest.raises(CrossFieldError) as raised:
        place(body)
    assert f"declared under {keyword!r}" in str(raised.value), (crossing, str(raised.value))


def test_the_same_crossings_without_a_blocking_keyword_are_collected(place) -> None:
    """The false-positive control for the sweep above.

    Every crossing there is a `pytest.raises`, so a collector that raised on ANY nesting --
    or one that had simply stopped collecting -- would be green. These are the same shapes
    with the blocked keyword removed, and they must collect and evaluate the rule.
    """
    unblocked: dict[str, Any] = {
        "allOf[0].allOf[0]": {"allOf": [{"allOf": [{"$ref": NESTED_ID}]}]},
        "allOf[0].then": {"allOf": [{"then": {"$ref": NESTED_ID}}]},
        "then.allOf[0]": {"then": {"allOf": [{"$ref": NESTED_ID}]}},
        "allOf[0].$ref": {
            "allOf": [{"$ref": f"{PROBE_ID}#/$defs/d"}],
            "$defs": {"d": {"$ref": NESTED_ID}},
        },
    }
    for label, body in sorted(unblocked.items()):
        rules, failures = place(body)
        assert rules == [RULE], label
        assert failures == ["equal: /a and /b must both be present and equal"], label


# ---------------------------------------------------- the claim this change rests on ---


def released_refs() -> list[str]:
    """Every released ``$id`` and every ``$defs`` entry at ANY depth, from the corpus.

    Listed by hand this would stay green as the corpus grows, which is the exact failure
    mode this repository keeps finding. Nested ``$defs`` are walked as well as top-level
    ones, so an uncomposed bag entry -- the one placement this engine deliberately does not
    block -- is still swept as its own root wherever it sits. The corpus has no nested bag
    today; sweeping only the top level would make that a silent assumption instead of a
    property that keeps holding.
    """
    refs: list[str] = []

    def walk(node: Any, schema_id: str, pointer: str) -> None:
        if not isinstance(node, dict):
            return
        bag = node.get("$defs")
        if isinstance(bag, dict):
            for name, subschema in bag.items():
                escaped = name.replace("~", "~0").replace("/", "~1")
                nested = f"{pointer}/$defs/{escaped}"
                refs.append(f"{schema_id}#{nested}")
                walk(subschema, schema_id, nested)
        for keyword, value in node.items():
            if keyword == "$defs":
                continue
            escaped = keyword.replace("~", "~0").replace("/", "~1")
            if isinstance(value, dict):
                walk(value, schema_id, f"{pointer}/{escaped}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, schema_id, f"{pointer}/{escaped}/{index}")

    for schema_id, schema in canonical_schemas().items():
        refs.append(schema_id)
        walk(schema, schema_id, "")
    return sorted(set(refs))


#: The number of rule SITES the released corpus collects, measured 2026-08-02 across 112
#: references. Pinned exactly rather than as a floor, and the difference is not cosmetic: the
#: floor this replaced was ``>= 9`` against a real value of 15, and a collector mutated to
#: stop following ``$ref`` drops to 13 and still passes it. A floor cannot catch the drop it
#: exists for. If a released schema gains or loses a rule, update this number in the same
#: commit -- that is the point.
#:
#: 15 -> 16 when the FND-002 task 4 evidence tier merged: ``evidence-location-version:1``
#: declares one released ``equal`` rule binding ``evidence_location_id`` to ``entity_id``
#: (IMP-DEC-FND002-034). The pin doing exactly what it was built for -- the merge of two
#: independently green branches is precisely the case a floor would have absorbed in silence.
RELEASED_RULE_SITES = 16


def test_no_released_schema_declares_a_rule_under_a_now_blocked_keyword() -> None:
    """Failing closed only costs nothing if nothing released is under a blocked keyword.

    Measured, not assumed, and measured through the real collector: every released reference
    is collected, and a rule that had drifted under ``if``/``not``/``dependentSchemas``/
    ``unevaluatedProperties``/``unevaluatedItems``/``contentSchema``/``additionalItems``
    would raise here rather than in a consumer.
    """
    refs = released_refs()
    assert len(refs) > 50, refs  # non-vacuity: an empty sweep proves nothing
    collected = 0
    for ref in refs:
        collected += len(collect_cross_field_rule_sites(ref))
    # ...and the sweep really reached every rule, so "nothing raised" is not "nothing was
    # walked", and a collector that stopped reaching some of them is red rather than quiet.
    assert collected == RELEASED_RULE_SITES, collected


def test_no_released_schema_uses_a_shape_this_collector_cannot_reach() -> None:
    """The measurement that bounds the two deliberate non-blocking decisions.

    ``definitions`` is excluded from blocking for the same reason as ``$defs``, but unlike
    ``$defs`` it is not swept as a root by :func:`released_refs`, so an unreferenced rule
    inside one would be unreached. ``$dynamicRef`` cannot be blocked at all -- its value is a
    URI string, not a subschema -- and it cannot be resolved statically either, so a rule at
    a dynamic target would be unreachable. Neither exposure is argued away: nothing released
    uses any of them, recomputed here, and this is red the day one appears.
    """
    schemas = canonical_schemas()
    assert len(schemas) > 10, len(schemas)  # non-vacuity

    def census(wanted: tuple[str, ...]) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {keyword: [] for keyword in wanted}

        def walk(node: Any, schema_id: str) -> None:
            if isinstance(node, dict):
                for keyword, value in node.items():
                    if keyword in found:
                        found[keyword].append(schema_id)
                    walk(value, schema_id)
            elif isinstance(node, list):
                for item in node:
                    walk(item, schema_id)

        for schema_id, schema in schemas.items():
            walk(schema, schema_id)
        return found

    assert census(("definitions", "$dynamicRef", "$dynamicAnchor")) == {
        "definitions": [],
        "$dynamicRef": [],
        "$dynamicAnchor": [],
    }
    # ...and the walker really visits nested members, so three empty lists are a measurement
    # and not a walker that never descended.
    assert len(census(("$ref",))["$ref"]) > 10


# ====================== the enumeration is complete, derived rather than listed ===
#
# `unevaluatedItems` was missing from the blocked list while `unevaluatedProperties` -- its
# sibling in the same vocabulary, with the same justification -- was present, and nothing was
# red. Adding it by hand would fix one omission and leave the enumeration exactly as
# unverifiable. So the keyword set is READ OUT of the official 2020-12 vocabulary
# meta-schemas that `jsonschema` bundles, and every keyword in it must be either collected or
# refused.

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
META_BASE = "https://json-schema.org/draft/2020-12/meta/"

#: Every vocabulary the 2020-12 meta-schema composes, from its own ``$vocabulary`` member.
META_VOCABULARIES = tuple(
    sorted(url.rsplit("/", 1)[1] for url in SPECIFICATIONS.contents(DRAFT_2020_12)["$vocabulary"])
)

#: How the meta-schema spells "the value here is a schema": a dynamic reference back to it.
_SUBSCHEMA: dict[str, Any] = {"$dynamicRef": "#meta"}


def subschema_bearing_keywords() -> dict[str, str]:
    """Every 2020-12 keyword whose value is, holds, or maps to a subschema, and its shape.

    Derived from the released vocabulary meta-schemas rather than typed out: every
    hand-listed keyword scope this repository has audited came back undercounted.
    """
    shapes: dict[str, str] = {}
    for vocabulary in META_VOCABULARIES:
        contents = SPECIFICATIONS.contents(f"{META_BASE}{vocabulary}")
        for keyword, declared in (contents.get("properties") or {}).items():
            if not isinstance(declared, dict):
                continue
            if declared == _SUBSCHEMA:
                shapes[keyword] = "schema"
            elif declared.get("$ref") == "#/$defs/schemaArray":
                shapes[keyword] = "list"
            elif declared.get("additionalProperties") == _SUBSCHEMA:
                shapes[keyword] = "map"
    return shapes


def test_the_derived_keyword_sweep_is_not_vacuous() -> None:
    """Non-vacuity and a false-positive control for the two sweeps below.

    Without this, a typo in a meta-schema URL would make ``subschema_bearing_keywords``
    return ``{}`` and every sweep would pass by inspecting nothing.
    """
    shapes = subschema_bearing_keywords()
    assert len(META_VOCABULARIES) == 7, META_VOCABULARIES
    assert len(shapes) == 19, sorted(shapes)
    # The keyword whose omission started this, and one of each shape.
    assert shapes["unevaluatedItems"] == "schema"
    assert shapes["allOf"] == "list"
    assert shapes["properties"] == "map"
    # ...and the control: a keyword whose value is NOT a subschema must not be swept up, or
    # "every keyword is accounted for" would be a statement about the whole vocabulary.
    for not_a_subschema in ("maxLength", "required", "format", "contentMediaType", "$ref"):
        assert not_a_subschema not in shapes, not_a_subschema


def test_every_subschema_bearing_2020_12_keyword_has_a_declared_family() -> None:
    """The enumeration, checked against the specification instead of against itself."""
    families = {
        "collected": structural_module._APPLICATOR_BRANCHES,
        "child map": structural_module._CHILD_MAP_KEYWORDS,
        "child schema": structural_module._CHILD_SCHEMA_KEYWORDS,
        "child list": structural_module._CHILD_LIST_KEYWORDS,
        "unlocatable": structural_module._UNLOCATABLE_KEYWORDS,
        "uncollected schema": structural_module._UNCOLLECTED_SCHEMA_KEYWORDS,
        "uncollected map": structural_module._UNCOLLECTED_MAP_KEYWORDS,
        "legacy": structural_module._LEGACY_SCHEMA_KEYWORDS,
        "definition bag": structural_module._DEFINITION_BAG_KEYWORDS,
    }
    declared: list[str] = [keyword for family in families.values() for keyword in family]
    # No keyword may sit in two families, or one engine would both collect and reject it.
    assert sorted(declared) == sorted(set(declared)), declared
    unaccounted = set(subschema_bearing_keywords()) - set(declared)
    assert unaccounted == set(), unaccounted
    # The families also carry pre-2020 names on purpose; they are the deliberate additions.
    assert set(declared) - set(subschema_bearing_keywords()) == {"additionalItems", "definitions"}


def placement(keyword: str, shape: str) -> dict[str, Any]:
    """Put the nested rule schema under ``keyword`` in the shape its vocabulary declares."""
    target = {"$ref": NESTED_ID}
    if shape == "list":
        return {keyword: [target]}
    if shape == "map":
        return {keyword: {"d": target}}
    return {keyword: target}


def test_no_2020_12_keyword_drops_a_released_rule_in_silence(place) -> None:
    """The sweep that catches the NEXT omission, whether or not anybody remembers it.

    Every subschema-bearing keyword gets the same violated rule underneath it, and the
    outcome must be one of two things: the rule is collected (so it is enforced), or the
    collector refuses it by name (so an author is told). Collecting nothing without raising
    is the silent drop, and the only keyword permitted to do it is the definitions bag, whose
    contents JSON Schema does not apply either until something composes them.
    """
    silent: list[str] = []
    collected: list[str] = []
    refused: list[str] = []
    for keyword, shape in sorted(subschema_bearing_keywords().items()):
        try:
            rules, _ = place(placement(keyword, shape))
        except CrossFieldError as raised:
            assert f"declared under {keyword!r}" in str(raised), (keyword, str(raised))
            refused.append(keyword)
            continue
        (collected if rules == [RULE] else silent).append(keyword)
    assert silent == ["$defs"], silent
    # Non-vacuity in both directions: an engine that refused everything, or collected
    # everything, would satisfy the assertion above.
    assert len(refused) >= 8, refused
    assert len(collected) >= 8, collected


#
# Parsed from BOTH sides: `packages/typescript/test/structural.test.ts` reads this module's
# Python counterpart, and this reads the port.


def test_the_typescript_port_blocks_exactly_the_same_keywords() -> None:
    source = TS_STRUCTURAL.read_text(encoding="utf-8")
    # Non-vacuity first: an unparsed file makes every membership check trivially absent.
    assert "function collect(" in source, TS_STRUCTURAL

    def declared(name: str) -> list[str]:
        match = re.search(rf"const {name} = \[([^\]]*)\] as const;", source)
        assert match is not None, f"{name} is not declared in {TS_STRUCTURAL}"
        return sorted(re.findall(r"'([^']+)'", match.group(1)))

    assert declared("UNCOLLECTED_SCHEMA_KEYWORDS") == sorted(
        structural_module._UNCOLLECTED_SCHEMA_KEYWORDS
    )
    assert declared("UNCOLLECTED_MAP_KEYWORDS") == sorted(
        structural_module._UNCOLLECTED_MAP_KEYWORDS
    )
    assert declared("UNLOCATABLE_KEYWORDS") == sorted(structural_module._UNLOCATABLE_KEYWORDS)
    assert declared("LEGACY_SCHEMA_KEYWORDS") == sorted(structural_module._LEGACY_SCHEMA_KEYWORDS)
    assert declared("APPLICATOR_BRANCHES") == sorted(structural_module._APPLICATOR_BRANCHES)
    # The blocked keywords and the collected branches must stay disjoint, or one engine
    # would both collect and reject the same placement.
    blocked = (
        set(structural_module._UNCOLLECTED_SCHEMA_KEYWORDS)
        | set(structural_module._UNCOLLECTED_MAP_KEYWORDS)
        | set(structural_module._UNLOCATABLE_KEYWORDS)
        | set(structural_module._LEGACY_SCHEMA_KEYWORDS)
    )
    assert blocked.isdisjoint(structural_module._APPLICATOR_BRANCHES)
    # ...and the port must carry the same per-keyword diagnostics, not just the same lists.
    for keyword in sorted(blocked | {"items"}):
        assert f"'{keyword}'" in source or f"\n  {keyword}:" in source, keyword

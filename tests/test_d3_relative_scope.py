"""D3 landed as option B: a rule chooses the base its operand pointers resolve against.

This file replaces ``test_fnd002_task4_blocked.py``, which asserted the *blocker* and was
written to go red the moment D3 was decided. It did, in all 51 of the cells that encoded the
block, and this is the rewrite its own docstring called for. Everything the old file proved
about the blocker is preserved here as a regression guard, because the one good property of
the old behaviour -- it failed CLOSED rather than silently asserting the wrong proposition --
is the property option B had to keep.

What is asserted here, in the order it matters:

* the released corpus really is annotated (non-vacuity: without this every case below could
  pass against a corpus that declares no rules at all);
* every rule-bearing schema at every child position now COLLECTS and EVALUATES, and does so
  at the child location rather than the root -- with a false-positive control at each
  position, on an instance the composed subschema reaches nowhere, requiring silence;
* the workaround the old file proved hazardous is now genuinely unnecessary: a nested pin's
  violation is REPORTED, where before it was silently missed;
* an ``absolute``-scoped rule below a child keyword still raises, unchanged;
* ``contains`` and ``propertyNames`` still raise at any scope, because they have no single
  instance location for a relative pointer to be relative to;
* relative and absolute agree exactly at a document root, which is the claim that let D3 land
  as an additive minor bump instead of a vocabulary version 2.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from research_contracts.canonical import CrossFieldError, check_cross_field_rules
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical import structural as structural_module
from research_contracts.canonical.registry import canonical_schemas

PROBE_ID = "urn:datacompany:d3-relative-scope-probe:1"


def rule_bearing_refs() -> list[str]:
    """Released ``$id``s and ``$defs`` entries that declare a rule at their own root.

    Derived, never listed by hand: a new rule-bearing released schema joins this set
    automatically and a deleted rule drops out of it, so the sweeps below cannot silently
    stop measuring.
    """
    found: list[str] = []
    for schema_id, schema in canonical_schemas().items():
        if schema.get("x-datacompany-cross-field"):
            found.append(schema_id)
        for name, definition in (schema.get("$defs") or {}).items():
            if isinstance(definition, dict) and definition.get("x-datacompany-cross-field"):
                found.append(f"{schema_id}#/$defs/{name}")
    return sorted(found)


def declared_rules(ref: str) -> list[dict[str, Any]]:
    """The rules declared at ``ref``'s own root, read straight from the released corpus."""
    schema_id, _, pointer = ref.partition("#")
    node = canonical_schemas()[schema_id]
    if pointer:
        for token in pointer.lstrip("/").split("/"):
            node = node[token.replace("~1", "/").replace("~0", "~")]
    return node["x-datacompany-cross-field"]


#: The JSON Schema positions that move the instance location. Each carries:
#:
#: 1. a builder composing ``ref`` at that position;
#: 2. an instance putting an EMPTY object at the location the composed schema applies to --
#:    an empty object violates every released rule, since each names members it does not
#:    carry, which is what makes "did it evaluate here?" a question with a visible answer;
#: 3. the pointer that location has;
#: 4. an instance at which the composed subschema applies NOWHERE, for the false-positive
#:    control. Note this is position-specific and cannot be shared: under
#:    ``additionalProperties`` with no sibling ``properties``, EVERY member is an additional
#:    property, so the only instance the subschema does not reach is one with no members.
CHILD_POSITIONS: dict[str, tuple[Any, Any, str, Any]] = {
    "properties": (
        lambda ref: {"type": "object", "properties": {"child": {"$ref": ref}}},
        {"child": {}},
        "/child",
        {"unrelated": {}},
    ),
    "items": (
        lambda ref: {"type": "array", "items": {"$ref": ref}},
        [{}],
        "/0",
        [],
    ),
    "prefixItems": (
        lambda ref: {"type": "array", "prefixItems": [{"$ref": ref}]},
        [{}],
        "/0",
        [],
    ),
    "additionalProperties": (
        lambda ref: {"type": "object", "additionalProperties": {"$ref": ref}},
        {"anything": {}},
        "/anything",
        {},
    ),
    "patternProperties": (
        lambda ref: {"type": "object", "patternProperties": {"^child": {"$ref": ref}}},
        {"child_x": {}},
        "/child_x",
        {"does_not_match": {}},
    ),
    "allOf-then-properties": (
        lambda ref: {"allOf": [{"type": "object", "properties": {"child": {"$ref": ref}}}]},
        {"child": {}},
        "/child",
        {"unrelated": {}},
    ),
}

#: The positions that do NOT move the instance location. A rule is evaluable at these
#: whatever its scope, and was before D3.
IN_PLACE_POSITIONS: dict[str, Any] = {
    "root $ref": lambda ref: {"$ref": ref},
    "root allOf": lambda ref: {"allOf": [{"$ref": ref}]},
    "root anyOf": lambda ref: {"anyOf": [{"$ref": ref}]},
    "root oneOf": lambda ref: {"oneOf": [{"$ref": ref}]},
}


@pytest.fixture
def compose(monkeypatch: pytest.MonkeyPatch):
    """Register a synthetic schema and evaluate an instance against it.

    The probe is a real registered schema resolved through the real registry, so this
    exercises the released collector rather than a re-implementation of it.
    """

    def _compose(body: dict[str, Any], instance: Any) -> list[str]:
        probe = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": PROBE_ID,
            **body,
        }
        schemas = {**canonical_schemas(), PROBE_ID: probe}
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
        structural_module._collect.cache_clear()
        return check_cross_field_rules(instance, PROBE_ID)

    yield _compose
    structural_module._collect.cache_clear()


# ----------------------------------------------------------------- non-vacuity first ---


def test_the_released_corpus_really_declares_root_level_rules() -> None:
    """An empty sweep would make every parametrised case below vacuously green."""
    refs = rule_bearing_refs()
    assert refs == [
        "urn:datacompany:bitemporal-assertion:1",
        "urn:datacompany:bitemporal-assertion:1#/$defs/command",
        "urn:datacompany:canonical-hash-profile:1",
        "urn:datacompany:evidence-location-version:1",
        "urn:datacompany:page:1#/$defs/page_request",
        "urn:datacompany:pinned-version-ref:1#/$defs/singleton",
        "urn:datacompany:reference-verification-receipt:1",
        "urn:datacompany:research-access-context:1",
        "urn:datacompany:run-manifest:1",
    ], refs


@pytest.mark.parametrize("ref", rule_bearing_refs())
def test_every_released_rule_declares_its_scope(ref: str) -> None:
    """D3 is only landed if the released rules actually opted in.

    Without this, every "it evaluates at the child location" case below would be satisfied by
    a corpus that had not been annotated at all -- the sweep would simply raise, and a
    ``pytest.raises`` that was never reached is not evidence.
    """
    for rule in declared_rules(ref):
        assert rule.get("scope") == "relative", f"{ref}: {rule.get('name', rule.get('rule'))}"


# --------------------------------------------------- the blocker, now the capability ---


@pytest.mark.parametrize("ref", rule_bearing_refs())
@pytest.mark.parametrize("position", sorted(CHILD_POSITIONS))
def test_every_rule_bearing_schema_evaluates_at_every_child_position(
    compose, ref: str, position: str
) -> None:
    """Nine released rule-bearing schemas x six child positions: all 54 now evaluate.

    Before D3 every one of these raised ``CrossFieldError``. The assertion is not merely
    "did not raise": a collector that quietly dropped the nested rule would also not raise,
    and would report nothing. Each failure must also name a pointer UNDER the child location,
    which is what distinguishes evaluating the nested object from evaluating the root.
    """
    build, instance, base, _ = CHILD_POSITIONS[position]
    failures = compose(build(ref), instance)
    assert failures, f"{ref} at {position} collected no evaluable rule"
    assert all(f"{base}/" in failure for failure in failures), failures


@pytest.mark.parametrize("ref", rule_bearing_refs())
@pytest.mark.parametrize("position", sorted(CHILD_POSITIONS))
def test_a_relative_rule_is_silent_where_its_subschema_does_not_apply(
    compose, ref: str, position: str
) -> None:
    """The false-positive control: the rules are discriminating, not unconditionally firing.

    The composed subschema reaches no location in this instance, so there is nowhere the
    rule could have an opinion and it must report nothing. Without this half, the 54 cells
    above would also be satisfied by an engine that reported every rule as failed at every
    composition, which is a different bug wearing the same green.
    """
    build, _, _, applies_nowhere = CHILD_POSITIONS[position]
    assert compose(build(ref), applies_nowhere) == []


@pytest.mark.parametrize("ref", rule_bearing_refs())
@pytest.mark.parametrize("position", sorted(IN_PLACE_POSITIONS))
def test_the_same_schema_at_an_in_place_position_is_still_evaluable(
    compose, ref: str, position: str
) -> None:
    """The in-place positions were never blocked and must not have regressed."""
    failures = compose(IN_PLACE_POSITIONS[position](ref), {})
    assert failures, f"{ref} at {position} collected no evaluable rule"


# --------------------------------------------------- what task 4 concretely needed ---

#: The three compositions FND-002 task 4 cannot avoid, in the shape the task words them.
TASK_4_COMPOSITIONS = {
    "EvidenceLocation pinned to a registered-singleton owner": (
        "urn:datacompany:pinned-version-ref:1#/$defs/singleton",
        "task 4: 'migrate document/evidence/rights/artifact references to compose the "
        "complete canonical ref shape'",
    ),
    "EvidenceResolutionReceipt embedded in an evidence record": (
        "urn:datacompany:reference-verification-receipt:1",
        "task 4: 'define its action/use-basis-specific EvidenceResolutionReceipt'",
    ),
    "a bitemporal evidence assertion carried as a member": (
        "urn:datacompany:bitemporal-assertion:1",
        "task 4: evidence carries validity and recording intervals",
    ),
}


@pytest.mark.parametrize("label", sorted(TASK_4_COMPOSITIONS))
def test_task_4_can_now_be_written(compose, label: str) -> None:
    """Each of task 4's three unavoidable compositions is now evaluable as a member."""
    ref, rationale = TASK_4_COMPOSITIONS[label]
    failures = compose({"type": "object", "properties": {"child": {"$ref": ref}}}, {"child": {}})
    assert failures, rationale
    assert all("/child/" in failure for failure in failures), failures


def test_the_old_workaround_is_no_longer_needed_and_the_real_rule_now_fires(compose) -> None:
    """The composed pin's OWN violation is reported. This is the defect D3 existed for.

    ``test_the_documented_workaround_is_not_one`` proved that re-declaring
    ``equal /entity_id /version_id`` at the composing root evaluates, reports nothing, and
    asserts a different proposition -- while the nested pin genuinely violates the singleton
    equality. Composing the released singleton now catches exactly that instance, with no
    locally invented mapping, which is what ``pinned-version-ref``'s own ``$comment``
    requires ("Consumers MUST NOT invent this mapping locally").
    """
    body = {
        "type": "object",
        "properties": {"pin": {"$ref": "urn:datacompany:pinned-version-ref:1#/$defs/singleton"}},
    }
    violating: dict[str, Any] = {
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "version_id": "11111111-1111-4111-8111-111111111111",
        "pin": {
            "entity_id": "22222222-2222-4222-8222-222222222222",
            "version_id": "33333333-3333-4333-8333-333333333333",
        },
    }
    failures = compose(body, violating)
    assert failures == ["equal: /pin/entity_id and /pin/version_id must both be present and equal"]

    # The control: the same composition is silent when the nested pin actually holds, so the
    # rule is discriminating between instances rather than always firing.
    holding = copy.deepcopy(violating)
    holding["pin"]["version_id"] = holding["pin"]["entity_id"]
    assert compose(body, holding) == []


def test_a_relative_rule_under_items_is_evaluated_once_per_element(compose) -> None:
    """Per-location evaluation, with each failure naming the element it is about.

    This is the cost the D3 brief flagged for relative scope: a rule under ``items`` runs
    once per element. It is only acceptable because each failure identifies its own location,
    so N failures are N findings rather than one finding repeated N times.
    """
    body = {
        "type": "array",
        "items": {"$ref": "urn:datacompany:pinned-version-ref:1#/$defs/singleton"},
    }
    same = "11111111-1111-4111-8111-111111111111"
    other = "22222222-2222-4222-8222-222222222222"
    instance = [
        {"entity_id": same, "version_id": other},
        {"entity_id": same, "version_id": same},
        {"entity_id": same, "version_id": other},
    ]
    assert compose(body, instance) == [
        "equal: /0/entity_id and /0/version_id must both be present and equal",
        "equal: /2/entity_id and /2/version_id must both be present and equal",
    ]


# ------------------------------------------- what option B deliberately did NOT change ---


ABSOLUTE_RULE_DEF = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:datacompany:d3-absolute-probe:1",
    "type": "object",
    "x-datacompany-cross-field": [{"rule": "equal", "left": "/entity_id", "right": "/version_id"}],
}


@pytest.mark.parametrize("position", sorted(CHILD_POSITIONS))
def test_an_absolute_scoped_rule_below_a_child_keyword_still_raises(
    monkeypatch: pytest.MonkeyPatch, position: str
) -> None:
    """The fail-closed property option B had to keep.

    A rule that has NOT opted in keeps instance-root-absolute operands, so evaluating it at a
    child location would assert a proposition about the wrong object. It raises, exactly as
    it did before D3. Silently evaluating it as if it were relative is the failure mode this
    guards.
    """
    build, instance, _, _ = CHILD_POSITIONS[position]
    absolute_id = ABSOLUTE_RULE_DEF["$id"]
    probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROBE_ID,
        **build(absolute_id),
    }
    schemas = {**canonical_schemas(), absolute_id: ABSOLUTE_RULE_DEF, PROBE_ID: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        with pytest.raises(CrossFieldError, match="instance-root-absolute"):
            check_cross_field_rules(instance, PROBE_ID)
    finally:
        structural_module._collect.cache_clear()


@pytest.mark.parametrize("keyword", ["contains", "propertyNames"])
@pytest.mark.parametrize("scope", ["relative", "absolute"])
def test_a_rule_under_an_unlocatable_keyword_raises_at_any_scope(
    monkeypatch: pytest.MonkeyPatch, keyword: str, scope: str
) -> None:
    """``relative`` is not a universal solvent, and the engine says so rather than guessing.

    ``contains`` applies to *some* unidentified element and ``propertyNames`` applies to a
    property NAME rather than to a value, so neither has a single instance location for a
    relative pointer to be relative to. Both fail closed, and the parametrisation over scope
    is what proves ``relative`` does not quietly acquire a meaning here.
    """
    rule = {"rule": "equal", "left": "/entity_id", "right": "/version_id", "scope": scope}
    nested_id = "urn:datacompany:d3-unlocatable-probe:1"
    nested = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": nested_id,
        "type": "object",
        "x-datacompany-cross-field": [rule],
    }
    probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROBE_ID,
        keyword: {"$ref": nested_id},
    }
    schemas = {**canonical_schemas(), nested_id: nested, PROBE_ID: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        with pytest.raises(CrossFieldError, match="no single instance location"):
            check_cross_field_rules({}, PROBE_ID)
    finally:
        structural_module._collect.cache_clear()


@pytest.mark.parametrize("ref", rule_bearing_refs())
def test_relative_and_absolute_agree_exactly_at_a_document_root(
    monkeypatch: pytest.MonkeyPatch, ref: str
) -> None:
    """The claim that made D3 an additive bump rather than a vocabulary version 2.

    At a document root the base is the empty pointer, so a relative operand and an absolute
    operand address the same location. That is asserted here rather than assumed: each
    released rule is evaluated once as released (relative) and once with ``scope`` stripped
    (absolute), at a root, over instances that make the rules both fail and hold. The two
    readings must produce byte-identical failure text, which is also what keeps the released
    fixtures' ``expected_error_contains`` pins valid.
    """
    instances: list[Any] = [
        {},
        {
            "entity_id": "11111111-1111-4111-8111-111111111111",
            "version_id": "22222222-2222-4222-8222-222222222222",
            "valid_from": "2026-01-02T00:00:00Z",
            "valid_to": "2026-01-01T00:00:00Z",
            "recorded_at": "2026-01-02T00:00:00Z",
            "requested_at": "2026-01-02T00:00:00Z",
            "expires_at": "2026-01-01T00:00:00Z",
            "sort": [{"field": "a"}, {"field": "a"}],
            "arrays": [{"pointer": "/x"}, {"pointer": "/x"}],
            "excluded_pointers": [{"pointer": "/x"}],
            "included_pointers": ["/x"],
            "opaque_pointers": ["/x"],
        },
    ]
    relative: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROBE_ID,
    }
    relative.update({"x-datacompany-cross-field": copy.deepcopy(declared_rules(ref))})
    absolute = copy.deepcopy(relative)
    for rule in absolute["x-datacompany-cross-field"]:
        rule.pop("scope", None)

    def evaluate(probe: dict[str, Any], instance: Any) -> list[str]:
        schemas = {**canonical_schemas(), PROBE_ID: probe}
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
        structural_module._collect.cache_clear()
        return check_cross_field_rules(instance, PROBE_ID)

    try:
        for instance in instances:
            assert evaluate(relative, instance) == evaluate(absolute, instance), instance
    finally:
        structural_module._collect.cache_clear()

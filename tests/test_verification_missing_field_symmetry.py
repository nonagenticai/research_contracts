"""A field missing on both sides of the owner comparison is a mismatch, not a match.

``compare_pin_to_owner_response`` compared every field with
``pin.get(field) != response.get(field)``. Two objects that both LACK a field therefore
compared ``None == None`` and agreed about it, so ``compare_pin_to_owner_response({}, {})``
returned ``None`` -- the code that means "every compared field matched, verified". The
``content_hash`` branch had the same shape. Section 4.2 says the opposite in as many words:
"Any missing field or mismatch fails closed."

The fix is not "absence is always a mismatch": the released scope conditional
(``stable-identity:1#/$defs/resource_scope_conditional``) REQUIRES ``resource_tenant_id``
iff ``resource_scope`` is ``tenant`` and FORBIDS it otherwise, so two global-scope references
agree about it by both omitting it, and a rule that rejected that would reject every legal
global verification -- including the released ``verification-verified`` fixture. What is
required is read out of the pin schema (``required_pin_fields``) rather than restated, so the
one legal absence is derived and not hardcoded.

Nor is it "``resource_tenant_id`` may always be absent on both sides", which is what the
first fix left behind and what this module asserted as EXPECTED with a justification that was
factually wrong. ``required_pin_fields`` reads only the UNCONDITIONAL ``required``, so a
tenant-scoped pin with no tenant id, answered by a tenant-scoped response with no tenant id,
still returned ``None`` -- verified. The condition itself is now read from the same schema
(``conditional_pin_fields``) and evaluated against the pair, so the legal absence is exactly
the global-scope one and nothing wider.

No failure code was invented. The closed enum on
``reference-verification-receipt:1`` carries a ``*_mismatch`` member per compared field and
nothing that describes absence separately, so absence reports the field's own code.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical.verification import (
    COMPARED_FIELDS,
    compare_pin_to_owner_response,
    conditional_pin_fields,
    required_pin_fields,
)

ROOT = Path(__file__).resolve().parents[1]
TS_VERIFICATION = ROOT / "packages" / "typescript" / "src" / "verification.ts"
VERIFICATION_FIXTURES = ROOT / "fixtures" / "canonical-references" / "v1" / "verification"

#: A complete, matching global-scope pair. Every compared field except the conditionally
#: forbidden ``resource_tenant_id`` is present and equal on both sides.
MATCHING_GLOBAL: dict[str, Any] = {
    "owner_context": "terminology-broker",
    "entity_type": "approved_mapping",
    "entity_id": "004417a8-a2b9-7ca3-e5c9-9037ddf2f225",
    "version_id": "30bb8090-40d7-6b65-eb0f-c3017a8a1dc9",
    "version_number": 3,
    "resource_scope": "global",
    "schema_ref": "urn:datacompany:stable-identity:1",
    "content_hash": "sha256:" + "c" * 64,
}

MATCHING_TENANT: dict[str, Any] = {
    **MATCHING_GLOBAL,
    "resource_scope": "tenant",
    "resource_tenant_id": "6f8f57715090da2632453988d9a1501b",
}


# ------------------------------------------------------------------- non-vacuity first ---


def test_a_complete_matching_pair_still_verifies() -> None:
    """The false-positive control, and the one the whole change has to survive: a fix that
    made absence a mismatch unconditionally would also reject every legal comparison."""
    assert compare_pin_to_owner_response(dict(MATCHING_GLOBAL), dict(MATCHING_GLOBAL)) is None
    assert compare_pin_to_owner_response(dict(MATCHING_TENANT), dict(MATCHING_TENANT)) is None


def test_the_matching_pair_really_exercises_every_compared_field() -> None:
    """Without this, the sweep below could be dropping fields that were never compared."""
    compared = {field for field, _ in COMPARED_FIELDS}
    assert compared - set(MATCHING_TENANT) == set(), compared - set(MATCHING_TENANT)
    assert len(compared) == 9


# ------------------------------------------------------------------------ the defect ---


def test_two_empty_objects_do_not_verify() -> None:
    """The reported reproduction, verbatim."""
    assert compare_pin_to_owner_response({}, {}) == "owner_context_mismatch"


@pytest.mark.parametrize("field,code", list(COMPARED_FIELDS))
def test_a_required_field_absent_on_both_sides_is_that_field_s_mismatch(
    field: str, code: str
) -> None:
    """Every compared field, one at a time, dropped from BOTH sides of a TENANT-scoped pair.

    There is no exception here, and the exception this test used to carry was the defect.
    It asserted that dropping ``resource_tenant_id`` from both sides returned ``None``, and
    justified it with "dropping the tenant id from a tenant-scoped pair leaves a global-scope
    pair that legitimately agrees about it". It does not: ``MATCHING_TENANT["resource_scope"]``
    is ``"tenant"`` and is not deleted. What was left was a pair that both sides declare
    tenant-scoped while neither carries the tenant id the released scope conditional REQUIRES
    of exactly that pair -- a silent VERIFIED on two references that agree about nothing. The
    legal case is a genuinely global pair, constructed separately below.
    """
    pin = dict(MATCHING_TENANT)
    response = dict(MATCHING_TENANT)
    del pin[field]
    del response[field]
    assert compare_pin_to_owner_response(pin, response) == code, field


def test_a_tenant_scoped_pair_missing_the_tenant_id_on_both_sides_does_not_verify() -> None:
    """The hole, stated on its own rather than as a branch of the sweep above.

    ``required_pin_fields`` reads only what the pin schema requires UNCONDITIONALLY and
    deliberately does not follow ``if``/``then``/``else``, so it never learned that
    ``resource_tenant_id`` is required when ``resource_scope`` is ``"tenant"``. Both engines
    answered ``None`` -- VERIFIED -- for a tenant-scoped pin with no tenant id answered by a
    tenant-scoped response with no tenant id. ``verify_reference`` refuses that pin at schema
    validation, but ``compare_pin_to_owner_response`` is exported and a direct caller got the
    silent pass.
    """
    pin = dict(MATCHING_TENANT)
    del pin["resource_tenant_id"]
    response = dict(pin)
    # The precondition the old comment got wrong: this pair is still tenant-scoped.
    assert pin["resource_scope"] == "tenant"
    assert response["resource_scope"] == "tenant"
    assert compare_pin_to_owner_response(pin, response) == "resource_tenant_mismatch"


def test_the_genuinely_legal_absence_is_a_global_scope_pair() -> None:
    """The false-positive control for the case above, correctly constructed this time.

    Both sides global-scope, neither carrying a tenant id -- which the released conditional
    does not merely permit but FORBIDS. This pair must verify, and the released
    ``verification-verified`` fixture is exactly this shape.
    """
    pair = dict(MATCHING_GLOBAL)
    assert pair["resource_scope"] == "global"
    assert "resource_tenant_id" not in pair
    assert compare_pin_to_owner_response(dict(pair), dict(pair)) is None


@pytest.mark.parametrize("field,code", list(COMPARED_FIELDS))
def test_a_field_absent_on_one_side_only_is_still_a_mismatch(field: str, code: str) -> None:
    """Unchanged behaviour, asserted so the fix cannot be a wash: this half already worked
    through ``dict.get`` returning ``None`` against a real value, and it must keep working
    in both directions."""
    for absent_from, present in (("pin", "response"), ("response", "pin")):
        sides = {"pin": dict(MATCHING_TENANT), "response": dict(MATCHING_TENANT)}
        del sides[absent_from][field]
        assert compare_pin_to_owner_response(sides["pin"], sides["response"]) == code, (
            field,
            absent_from,
            present,
        )


def test_a_global_pin_answered_with_a_tenant_scoped_target_is_a_mismatch() -> None:
    """The case the docstring always claimed ``dict.get`` bought, now asserted."""
    assert (
        compare_pin_to_owner_response(dict(MATCHING_GLOBAL), dict(MATCHING_TENANT))
        == "resource_scope_mismatch"
    )
    global_scope_pin = {**MATCHING_GLOBAL, "resource_scope": "tenant"}
    assert (
        compare_pin_to_owner_response(global_scope_pin, dict(MATCHING_TENANT))
        == "resource_tenant_mismatch"
    )


def test_a_missing_content_hash_on_either_side_is_a_content_hash_mismatch() -> None:
    """The ``content_hash`` branch had its own copy of the defect: ``expected`` was
    ``response.get("content_hash")``, so two objects carrying neither the hash nor any
    canonical content compared ``None == None`` and passed."""
    both = dict(MATCHING_GLOBAL)
    del both["content_hash"]
    assert compare_pin_to_owner_response(both, dict(both)) == "content_hash_mismatch"
    assert compare_pin_to_owner_response(dict(MATCHING_GLOBAL), both) == "content_hash_mismatch"
    assert compare_pin_to_owner_response(both, dict(MATCHING_GLOBAL)) == "content_hash_mismatch"


def test_an_explicit_null_is_not_the_same_fact_as_an_absent_member() -> None:
    """``None`` is a value a JSON document can carry. It must not be able to impersonate an
    absent member, or the sentinel would be decorative."""
    nulled = {**MATCHING_GLOBAL, "version_number": None}
    absent = dict(MATCHING_GLOBAL)
    del absent["version_number"]
    assert compare_pin_to_owner_response(nulled, absent) == "version_number_mismatch"
    assert compare_pin_to_owner_response(absent, nulled) == "version_number_mismatch"
    # ...and two explicit nulls DO agree, because they are the same value.
    assert compare_pin_to_owner_response(nulled, dict(nulled)) is None


# --------------------------------------------------- the derived set, not a hardcoded one ---


def test_the_required_set_is_the_pin_schema_s_unconditional_required() -> None:
    """Pinned as an equality. A walker that also read the scope conditional's ``then``
    would add ``resource_tenant_id`` and break every global verification; one that read
    nothing would make the whole comparison permissive again."""
    assert required_pin_fields() == frozenset(
        {
            "owner_context",
            "entity_type",
            "entity_id",
            "resource_scope",
            "version_id",
            "version_number",
            "schema_ref",
            "content_hash",
            "resolved_at",
        }
    )
    compared = {field for field, _ in COMPARED_FIELDS}
    assert compared - required_pin_fields() == {"resource_tenant_id"}


def test_the_conditional_set_is_read_from_the_schema_and_depends_on_the_pair() -> None:
    """The other half of the derivation: the condition itself, not a wider required set.

    Teaching ``required_pin_fields`` to follow ``then`` would have closed the hole and broken
    every legal global verification with it; the mutant that does so is red in the test above.
    What closes it is the condition evaluated against the pair being compared, and both the
    discriminator and the member it requires are read out of the pin schema.
    """
    assert conditional_pin_fields(dict(MATCHING_TENANT), dict(MATCHING_TENANT)) == frozenset(
        {"resource_tenant_id"}
    )
    # Global on both sides: nothing extra is required, which is what keeps the released
    # `verification-verified` fixture verifying.
    assert conditional_pin_fields(dict(MATCHING_GLOBAL), dict(MATCHING_GLOBAL)) == frozenset()
    # One side only is not agreement about the discriminator, and the mismatch is already
    # reported on `resource_scope`, which precedes the tenant id in COMPARED_FIELDS.
    assert conditional_pin_fields(dict(MATCHING_TENANT), dict(MATCHING_GLOBAL)) == frozenset()
    assert conditional_pin_fields(dict(MATCHING_GLOBAL), dict(MATCHING_TENANT)) == frozenset()
    # A resolver that answered nothing at all has no scope to agree about.
    assert conditional_pin_fields(dict(MATCHING_TENANT), None) == frozenset()
    # ...and the discriminator's absence does not make the condition vacuously true: JSON
    # Schema's `properties` does not apply to an absent member, which is why the released
    # `if` also `require`s it and why this engine refuses to read one that does not.
    scopeless = {key: value for key, value in MATCHING_TENANT.items() if key != "resource_scope"}
    assert conditional_pin_fields(dict(scopeless), dict(scopeless)) == frozenset()


def test_the_released_verification_fixtures_still_replay() -> None:
    """The corpus is the oracle. Read here as well as through the harness, because the
    ``verified`` fixture is global-scope and is exactly what a naive "absence is always a
    mismatch" fix would turn into ``resource_tenant_mismatch``."""
    paths = sorted(VERIFICATION_FIXTURES.glob("*.json"))
    assert len(paths) == 14, paths  # non-vacuity: an empty glob would prove nothing
    for path in paths:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        code = compare_pin_to_owner_response(
            fixture["pinned_version_ref"], fixture["owner_response"]
        )
        assert code == fixture["expected_failure_code"], path.name


# ================================================================= two-language parity ===


def test_the_typescript_port_derives_the_same_required_set() -> None:
    source = TS_VERIFICATION.read_text(encoding="utf-8")
    # Non-vacuity first: an unreadable or renamed file makes every check trivially absent.
    assert "export function comparePinToOwnerResponse" in source, TS_VERIFICATION
    assert "export function requiredPinFields" in source
    assert "export function conditionalPinFields" in source
    # The port must read the same schema rather than list the fields.
    assert "resolvePointer(PIN_SCHEMA_REF)" in source
    # The "must not name" checks below read CODE, not prose: the comments quote the schema on
    # purpose, and a check that failed on its own explanation would be a check nobody keeps.
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    # ...and not the COMPARED_FIELDS table either, which names every field on purpose: its
    # ORDER decides which code a multi-field mismatch reports and is itself the contract.
    code = re.sub(r"COMPARED_FIELDS[^=]*=\s*\[.*?\n\];", "", code, flags=re.DOTALL)
    assert "export function conditionalPinFields" in code  # non-vacuity for the stripped view
    assert "['owner_context'," not in code  # the table really was removed
    for field, _ in COMPARED_FIELDS:
        assert not re.search(rf"required\.add\('{field}'\)", source), field
    # Beyond that table, the port may not NAME the conditionally required member or the value
    # that triggers it. Both are derived here too, from the same schema the port reads: a port
    # that shipped `field === 'resource_tenant_id'` would pass every behavioural test above
    # and drift silently the moment the released conditional changed.
    conditional = conditional_pin_fields(dict(MATCHING_TENANT), dict(MATCHING_TENANT))
    assert conditional, "nothing is conditionally required, so this check verifies nothing"
    for member in sorted(conditional):
        assert f"'{member}'" not in code, member
    assert f"'{MATCHING_TENANT['resource_scope']}'" not in code
    # ...and it must use a sentinel rather than `undefined`, which a caller can supply.
    assert "const ABSENT = Symbol('absent')" in source
    assert "Object.hasOwn(record, field)" in source
    # `undefined` is ABSENT in the port, because `JSON.stringify({x: undefined})` is `{}` and
    # the comparison must answer the same about an object and its JSON round trip. Python has
    # no `undefined`, so this half exists only here.
    assert "record[field] === undefined" in source

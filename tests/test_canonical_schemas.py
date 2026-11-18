"""FND-002: the six canonical envelope schemas must be executable assertions.

Every fixture under ``fixtures/canonical-references/v1`` is exercised here. An invalid
fixture is not merely required to fail: it must fail with the specific error the fixture
names, so a schema that fails for the wrong reason cannot pass this suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from research_contracts.canonical import (
    CANONICAL_SCHEMA_DIR,
    CrossFieldError,
    SchemaValidationError,
    build_receipt,
    canonical_schemas,
    check_cross_field_rules,
    collect_cross_field_rules,
    compare_pin_to_owner_response,
    schema_registry,
    validate_instance,
    validate_schema_only,
    verify_reference,
)
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical import structural as structural_module

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "canonical-references" / "v1"

RELEASED_FILES = (
    "stable-identity.v1.schema.json",
    "immutable-version.v1.schema.json",
    "bitemporal-assertion.v1.schema.json",
    "identity-ref.v1.schema.json",
    "pinned-version-ref.v1.schema.json",
    "reference-verification-receipt.v1.schema.json",
    "canonical-hash-profile.v1.schema.json",
    "typed-refs.v1.schema.json",
)

IDENTITY_REF = "urn:datacompany:identity-ref:1"
PINNED_REF = "urn:datacompany:pinned-version-ref:1"
STABLE_IDENTITY = "urn:datacompany:stable-identity:1"
IMMUTABLE_VERSION = "urn:datacompany:immutable-version:1"
BITEMPORAL = "urn:datacompany:bitemporal-assertion:1"
RECEIPT = "urn:datacompany:reference-verification-receipt:1"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixtures(kind: str) -> list[Path]:
    paths = sorted((FIXTURE_ROOT / kind).glob("*.json"))
    assert paths, f"no {kind} reference fixtures found under {FIXTURE_ROOT / kind}"
    return paths


def errors_for(instance: Any, schema_ref: str) -> list[str]:
    """Every failure a released schema produces, including its cross-field rules."""
    return validate_instance(instance, schema_ref) + check_cross_field_rules(instance, schema_ref)


# --------------------------------------------------------------------------- release ---


def test_released_canonical_file_set_is_exactly_the_declared_set() -> None:
    on_disk = sorted(path.name for path in CANONICAL_SCHEMA_DIR.glob("*.schema.json"))
    assert on_disk == sorted(RELEASED_FILES)


@pytest.mark.parametrize("name", RELEASED_FILES)
def test_every_released_schema_compiles_as_2020_12(name: str) -> None:
    schema = load(CANONICAL_SCHEMA_DIR / name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_every_cross_file_reference_resolves() -> None:
    resolver = schema_registry().resolver()
    unresolved: list[str] = []

    def walk(node: Any, source: str) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                try:
                    resolver.lookup(ref)
                except Exception:  # noqa: BLE001 - the message is the assertion
                    unresolved.append(f"{source}: {ref}")
            for value in node.values():
                walk(value, source)
        elif isinstance(node, list):
            for value in node:
                walk(value, source)

    for schema_id, schema in canonical_schemas().items():
        walk(schema, schema_id)
    assert unresolved == []


# ---------------------------------------------------------------------- envelope law ---


def test_identity_ref_has_exactly_five_fields() -> None:
    fields = load(CANONICAL_SCHEMA_DIR / "identity-ref.v1.schema.json")["$defs"][
        "identity_ref_fields"
    ]["properties"]
    assert sorted(fields) == [
        "entity_id",
        "entity_type",
        "owner_context",
        "resource_scope",
        "resource_tenant_id",
    ]


@pytest.mark.parametrize("extra", ["version_id", "content_hash", "version_number", "schema_ref"])
def test_identity_ref_rejects_every_pin_field(extra: str) -> None:
    """The closure is real: it behaves exactly like additionalProperties:false would."""
    base = load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"]
    ref = {
        key: base[key] for key in ("owner_context", "entity_type", "entity_id", "resource_scope")
    }
    assert validate_instance(ref, IDENTITY_REF) == []
    assert validate_instance({**ref, extra: base[extra]}, IDENTITY_REF) != []


@pytest.mark.parametrize(
    "schema_ref",
    [IDENTITY_REF, PINNED_REF, STABLE_IDENTITY + "#/$defs/sealed"],
)
def test_scope_conditional_is_identical_at_every_nesting_depth(schema_ref: str) -> None:
    """global forbids resource_tenant_id, tenant requires it, in every released shape."""
    fixture = load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"]
    base = dict(fixture)
    if schema_ref.startswith(STABLE_IDENTITY):
        base = {
            "entity_id": fixture["entity_id"],
            "entity_type": fixture["entity_type"],
            "resource_scope": "global",
            "created_at": "2026-07-30T00:00:00Z",
            "created_by": "service:test",
            "aggregate_version": 0,
        }
    elif schema_ref == IDENTITY_REF:
        base = {
            key: fixture[key]
            for key in ("owner_context", "entity_type", "entity_id", "resource_scope")
        }

    tenant_id = "1a2b3c4d-0000-4000-8000-000000000001"
    assert validate_instance(base, schema_ref) == []
    assert validate_instance({**base, "resource_tenant_id": tenant_id}, schema_ref) != []
    assert validate_instance({**base, "resource_scope": "tenant"}, schema_ref) != []
    assert (
        validate_instance(
            {**base, "resource_scope": "tenant", "resource_tenant_id": tenant_id}, schema_ref
        )
        == []
    )


def test_nested_pin_scope_conditional_is_enforced_inside_an_immutable_version() -> None:
    """Depth is not a loophole: a bad pin nested two levels down still fails."""
    receipt = load(FIXTURE_ROOT / "valid" / "resolved-pin-verification-receipt.json")["instance"]
    broken = json.loads(json.dumps(receipt))
    broken["pinned_version_ref"]["resource_tenant_id"] = "1a2b3c4d-0000-4000-8000-000000000001"
    assert validate_instance(broken, RECEIPT) != []


def test_unevaluated_properties_seals_a_composed_domain_schema() -> None:
    """A domain schema composes the envelope and seals the fully composed boundary."""
    domain_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:datacompany:test-domain-recommendation:1",
        "allOf": [
            {"$ref": IMMUTABLE_VERSION},
            {
                "type": "object",
                "required": ["recommendation_text"],
                "properties": {"recommendation_text": {"type": "string"}},
            },
        ],
        "unevaluatedProperties": False,
    }
    validator = Draft202012Validator(domain_schema, registry=schema_registry())
    base = load(FIXTURE_ROOT / "invalid" / "invalid-correction-without-supersession.json")[
        "instance"
    ]
    composed = {**base, "version_number": 1, "recommendation_text": "Do the thing."}
    assert list(validator.iter_errors(composed)) == []
    assert list(validator.iter_errors({**composed, "smuggled_status": "active"})) != []


def test_domain_schema_cannot_weaken_the_scope_conditional_by_composition() -> None:
    """A domain schema that tries to permit a global tenant ID still fails."""
    domain_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:datacompany:test-domain-weakened-pin:1",
        "allOf": [{"$ref": PINNED_REF}],
        "properties": {"resource_tenant_id": {"type": "string"}},
        "unevaluatedProperties": False,
    }
    validator = Draft202012Validator(domain_schema, registry=schema_registry())
    pin = load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"]
    assert list(validator.iter_errors(pin)) == []
    assert (
        list(
            validator.iter_errors(
                {**pin, "resource_tenant_id": "1a2b3c4d-0000-4000-8000-000000000001"}
            )
        )
        != []
    )


@pytest.mark.parametrize(
    ("version_number", "supersedes", "valid"),
    [(1, False, True), (1, True, False), (2, True, True), (2, False, False), (0, False, False)],
)
def test_supersession_conditional(version_number: int, supersedes: bool, valid: bool) -> None:
    instance = {
        "version_id": "aaaaaaaa-0000-4000-8000-000000000001",
        "entity_id": "aaaaaaaa-0000-4000-8000-000000000002",
        "version_number": version_number,
        "schema_ref": "urn:datacompany:recommendation-version:1",
        "content_hash": "sha256:" + "0" * 64,
        "created_at": "2026-07-30T00:00:00Z",
        "created_by": "service:test",
    }
    if supersedes:
        instance["supersedes_version_id"] = "aaaaaaaa-0000-4000-8000-000000000003"
    assert (validate_instance(instance, IMMUTABLE_VERSION) == []) is valid


@pytest.mark.parametrize(
    ("result", "with_code", "valid"),
    [
        ("verified", False, True),
        ("verified", True, False),
        ("rejected", True, True),
        ("rejected", False, True),
    ],
)
def test_failure_code_is_permitted_only_when_rejected(
    result: str, with_code: bool, valid: bool
) -> None:
    receipt = load(FIXTURE_ROOT / "valid" / "resolved-pin-verification-receipt.json")["instance"]
    instance = {**receipt, "result": result}
    if with_code:
        instance["failure_code"] = "content_hash_mismatch"
    assert (validate_instance(instance, RECEIPT) == []) is valid


@pytest.mark.parametrize("field", ["recorded_at", "recorded_until"])
def test_system_time_is_read_only_in_the_command_schema(field: str) -> None:
    command = load(
        FIXTURE_ROOT / "valid" / "bitemporal-assertion-command-without-system-time.json"
    )["instance"]
    command_ref = BITEMPORAL + "#/$defs/command"
    assert validate_instance(command, command_ref) == []
    assert validate_instance({**command, field: "2026-07-30T09:30:00Z"}, command_ref) != []
    schema = load(CANONICAL_SCHEMA_DIR / "bitemporal-assertion.v1.schema.json")
    assert schema["$defs"]["system_time_fields"]["properties"][field]["readOnly"] is True


@pytest.mark.parametrize(
    ("valid_from", "valid_to", "ok"),
    [
        ("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z", True),
        ("2026-01-01T00:00:00Z", None, True),
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", False),
        ("2027-01-01T00:00:00Z", "2026-01-01T00:00:00Z", False),
    ],
)
def test_intervals_are_half_open_and_non_empty(
    valid_from: str, valid_to: str | None, ok: bool
) -> None:
    base = load(FIXTURE_ROOT / "invalid" / "invalid-empty-valid-interval.json")["instance"]
    instance = {**base, "valid_from": valid_from}
    if valid_to is None:
        instance.pop("valid_to", None)
    else:
        instance["valid_to"] = valid_to
    assert (errors_for(instance, BITEMPORAL) == []) is ok


# ------------------------------------------------------------------ pre-ADR hard gate ---


@pytest.mark.parametrize(
    "token",
    [
        "regulatory_instrument",
        "regulatory_provision",
        "regulatory_effect",
        "regulatory_applicability",
        "regulatory_change",
        "legal_event",
        "legal_status",
        "normative_citation",
        "consolidation_snapshot",
    ],
)
def test_no_generic_type_token_can_activate_a_regulatory_canonical_type(token: str) -> None:
    pin = load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"]
    assert validate_instance({**pin, "entity_type": token}, PINNED_REF) != []


def test_released_schemas_declare_no_regulatory_type_and_no_work_type_discriminator() -> None:
    source = "\n".join(
        (CANONICAL_SCHEMA_DIR / name).read_text(encoding="utf-8") for name in RELEASED_FILES
    )
    for forbidden in ('"work_type"', '"regulatory_instrument"', '"regulatory_provision"'):
        assert forbidden not in source


# ---------------------------------------------------------------------- fixture laws ---


@pytest.mark.parametrize("path", fixtures("valid"), ids=lambda p: p.stem)
def test_valid_reference_fixture_validates(path: Path) -> None:
    fixture = load(path)
    assert fixture["expect"] == "valid"
    assert errors_for(fixture["instance"], fixture["schema_ref"]) == []


@pytest.mark.parametrize("path", fixtures("invalid"), ids=lambda p: p.stem)
def test_invalid_reference_fixture_fails_with_its_named_error(path: Path) -> None:
    fixture = load(path)
    assert fixture["expect"] == "invalid"
    failures = errors_for(fixture["instance"], fixture["schema_ref"])
    assert failures, f"{fixture['fixture_id']} was expected to fail but validated"
    rendered = " | ".join(failures)
    for expected in fixture["expected_error_contains"]:
        assert expected in rendered, (
            f"{fixture['fixture_id']} failed, but not for the named reason {expected!r}: {rendered}"
        )


# ---------------------------------------------------------- owner-resolver comparison ---


@pytest.mark.parametrize("path", fixtures("verification"), ids=lambda p: p.stem)
def test_owner_resolver_comparison_produces_the_exact_receipt(path: Path) -> None:
    fixture = load(path)
    calls: list[tuple[str, str]] = []

    def resolver(entity_id: str, version_id: str) -> Any:
        calls.append((entity_id, version_id))
        return fixture["owner_response"]

    receipt = verify_reference(
        fixture["pinned_version_ref"],
        resolver=resolver,
        consumer_context=fixture["consumer_context"],
        subject_local_ref=fixture["subject_local_ref"],
        verification_profile_ref=fixture["verification_profile_ref"],
        verified_at="2026-07-30T10:00:05Z",
        receipt_id="bbbbbbbb-0000-4000-8000-000000000001",
    )
    # The resolver is called by exact entity_id/version_id: there is no latest fallback.
    assert calls == [
        (
            fixture["pinned_version_ref"]["entity_id"],
            fixture["pinned_version_ref"]["version_id"],
        )
    ]
    assert receipt["result"] == fixture["expected_result"]
    assert receipt.get("failure_code") == fixture["expected_failure_code"]
    assert errors_for(receipt, RECEIPT) == []


def test_a_rejected_receipt_discloses_nothing_about_the_target() -> None:
    fixture = load(FIXTURE_ROOT / "verification" / "verification-wrong-tenant.json")
    receipt = verify_reference(
        fixture["pinned_version_ref"],
        resolver=lambda *_: fixture["owner_response"],
        consumer_context=fixture["consumer_context"],
        subject_local_ref=fixture["subject_local_ref"],
        verification_profile_ref=fixture["verification_profile_ref"],
        verified_at="2026-07-30T10:00:05Z",
        receipt_id="bbbbbbbb-0000-4000-8000-000000000002",
    )
    rendered = json.dumps(receipt)
    assert fixture["owner_response"]["resource_tenant_id"] not in rendered


def test_a_malformed_pin_produces_no_receipt_at_all() -> None:
    """Section 4.2: a rejected receipt exists only for a schema-valid pin."""
    with pytest.raises(SchemaValidationError):
        verify_reference(
            {"id": "not-a-pin", "version": 3},
            resolver=lambda *_: None,
            consumer_context="kag-research",
            subject_local_ref=load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"],
            verification_profile_ref="urn:datacompany:verification-profile-strict:1",
            verified_at="2026-07-30T10:00:05Z",
            receipt_id="bbbbbbbb-0000-4000-8000-000000000003",
        )


def test_comparison_never_falls_back_to_latest() -> None:
    """An owner answering with a newer version is a mismatch, not an upgrade."""
    fixture = load(FIXTURE_ROOT / "verification" / "verification-verified.json")
    newer = {
        **fixture["owner_response"],
        "version_id": "cccccccc-0000-4000-8000-000000000009",
        "version_number": 9,
    }
    assert compare_pin_to_owner_response(fixture["pinned_version_ref"], newer) == (
        "version_id_mismatch"
    )


# -------------------------------------------------- the safe validation path is default ---


def receipt_with_foreign_subject() -> dict[str, Any]:
    """A receipt whose subject_local_ref is owned by somebody other than the consumer.

    Section 4.2: ``subject_local_ref`` is a released reference "whose ``owner_context``
    equals ``consumer_context``". JSON Schema cannot compare two instance locations, so the
    receipt schema declares it as ``x-datacompany-cross-field`` instead.
    """
    receipt = load(FIXTURE_ROOT / "valid" / "resolved-pin-verification-receipt.json")["instance"]
    broken = json.loads(json.dumps(receipt))
    broken["subject_local_ref"]["owner_context"] = "not-the-consumer"
    return broken


def test_the_default_validation_entry_point_evaluates_the_cross_field_rules() -> None:
    """The obvious call is the safe call; only the explicitly raw one skips the rules."""
    broken = receipt_with_foreign_subject()
    assert validate_schema_only(broken, RECEIPT) == []
    failures = validate_instance(broken, RECEIPT)
    assert failures == check_cross_field_rules(broken, RECEIPT)
    assert any("subject_local_ref_is_owned_by_consumer" in failure for failure in failures)


def test_build_receipt_refuses_a_subject_not_owned_by_the_consumer() -> None:
    """The sanctioned constructor may not emit a receipt the release gate would reject."""
    broken = receipt_with_foreign_subject()
    with pytest.raises(CrossFieldError, match="subject_local_ref_is_owned_by_consumer"):
        build_receipt(
            receipt_id=broken["reference_verification_receipt_id"],
            consumer_context=broken["consumer_context"],
            subject_local_ref=broken["subject_local_ref"],
            pinned_version_ref=broken["pinned_version_ref"],
            verification_profile_ref=broken["verification_profile_ref"],
            verified_at=broken["verified_at"],
            failure_code=None,
            verified_owner_context=broken["verified_owner_context"],
            verified_schema_ref=broken["verified_schema_ref"],
            verified_content_hash=broken["verified_content_hash"],
        )


def test_verify_reference_refuses_a_foreign_subject_before_calling_the_resolver() -> None:
    """No receipt, and no resolver call, for a subject that cannot carry a receipt at all."""
    fixture = load(FIXTURE_ROOT / "verification" / "verification-verified.json")
    calls: list[tuple[str, str]] = []

    def resolver(entity_id: str, version_id: str) -> Any:
        calls.append((entity_id, version_id))
        return fixture["owner_response"]

    foreign = {**fixture["subject_local_ref"], "owner_context": "not-the-consumer"}
    with pytest.raises(CrossFieldError, match="not owned by the consumer"):
        verify_reference(
            fixture["pinned_version_ref"],
            resolver=resolver,
            consumer_context=fixture["consumer_context"],
            subject_local_ref=foreign,
            verification_profile_ref=fixture["verification_profile_ref"],
            verified_at="2026-07-30T10:00:05Z",
            receipt_id="bbbbbbbb-0000-4000-8000-000000000004",
        )
    assert calls == []


def test_verify_reference_refuses_a_subject_that_is_not_a_released_reference_form() -> None:
    fixture = load(FIXTURE_ROOT / "verification" / "verification-verified.json")
    with pytest.raises(SchemaValidationError, match="not a released reference form"):
        verify_reference(
            fixture["pinned_version_ref"],
            resolver=lambda *_: fixture["owner_response"],
            consumer_context=fixture["consumer_context"],
            subject_local_ref={"id": "not-a-ref"},
            verification_profile_ref=fixture["verification_profile_ref"],
            verified_at="2026-07-30T10:00:05Z",
            receipt_id="bbbbbbbb-0000-4000-8000-000000000005",
        )


# ----------------------------------------------------- PinnedVersionRef closure (M20) ---


@pytest.mark.parametrize(
    "extra",
    [
        "aggregate_version",
        "created_at",
        "created_by",
        "workspace_id",
        "project_id",
        "resolver_policy_ref",
        "supersedes_version_id",
        "latest",
        "smuggled_status",
    ],
)
def test_pinned_version_ref_closure_rejects_every_undeclared_property(extra: str) -> None:
    """The PinnedVersionRef root seal is real, not decorative.

    ``unevaluatedProperties: false`` at the root is the ONLY thing closing this shape: the
    three composed ``allOf`` branches each declare their own properties and none of them
    carries ``additionalProperties``. None of these probe names is constrained by any other
    rule, so each one isolates the closure itself.
    """
    pin = load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"]
    assert validate_instance(pin, PINNED_REF) == []
    assert validate_instance({**pin, extra: "smuggled"}, PINNED_REF) != []


def test_content_hash_hexadecimal_case_alone_is_rejected() -> None:
    """Isolates hex case from the ``sha256:`` prefix, which the older fixture also varied."""
    pin = load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"]
    lower = pin["content_hash"]
    assert lower.startswith("sha256:")
    upper_hex = "sha256:" + lower.removeprefix("sha256:").upper()
    assert upper_hex != lower
    assert upper_hex.startswith("sha256:")  # the prefix is untouched
    assert validate_instance({**pin, "content_hash": upper_hex}, PINNED_REF) != []


# ------------------------------------------------------------ hashable integer bounds ---


@pytest.mark.parametrize(
    ("version_number", "valid"),
    [(1, True), (3, True), (2**53, True), (2**53 + 1, False), (10**20, False), (0, False)],
)
def test_version_number_never_exceeds_the_exact_double_range(
    version_number: int, valid: bool
) -> None:
    """The boundary may not accept a number the canonical hash algorithm cannot serialize."""
    pin = load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"]
    assert (validate_instance({**pin, "version_number": version_number}, PINNED_REF) == []) is valid


# --------------------------------------------- nested cross-field rules: fail closed ---


NESTED_RULE_SCHEMA_ID = "urn:datacompany:test-nested-cross-field:1"
NESTED_RULE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": NESTED_RULE_SCHEMA_ID,
    "type": "object",
    "properties": {
        "resolved_pin": {
            "type": "object",
            "x-datacompany-cross-field": [
                {"rule": "equal", "left": "/entity_id", "right": "/version_id"}
            ],
        }
    },
}


def test_a_nested_cross_field_rule_fails_closed_instead_of_being_silently_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Documented limitation, pinned: rule pointers are instance-root-absolute.

    ``collect_cross_field_rules`` walks only ``$ref`` and the in-place applicators, so a
    rule reached through ``properties`` -- for example ``pinned-version-ref#/$defs/singleton``
    nested as some enclosing schema's member -- cannot be evaluated: its ``/entity_id`` would
    address the enclosing instance's root, not the nested pin. No released schema nests one
    today. Rather than dropping such a rule, the collector raises. This test pins that
    behaviour so the limitation cannot quietly become a hole.
    """
    schemas = {**canonical_schemas(), NESTED_RULE_SCHEMA_ID: NESTED_RULE_SCHEMA}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        with pytest.raises(CrossFieldError, match="instance-root-absolute"):
            collect_cross_field_rules(NESTED_RULE_SCHEMA_ID)
    finally:
        structural_module._collect.cache_clear()


def test_no_released_schema_nests_a_cross_field_rule_today() -> None:
    """The premise of the limitation above, asserted rather than assumed."""
    for schema_id in canonical_schemas():
        collect_cross_field_rules(schema_id)
    for nested in (
        PINNED_REF + "#/$defs/singleton",
        BITEMPORAL + "#/$defs/command",
        IDENTITY_REF + "#/$defs/floating_navigation_ref",
    ):
        collect_cross_field_rules(nested)


def test_every_compared_field_has_a_distinct_non_disclosing_failure_code() -> None:
    receipt_schema = load(CANONICAL_SCHEMA_DIR / "reference-verification-receipt.v1.schema.json")
    declared = set(receipt_schema["$defs"]["receipt_fields"]["properties"]["failure_code"]["enum"])
    produced = {
        load(path)["expected_failure_code"]
        for path in fixtures("verification")
        if load(path)["expected_failure_code"] is not None
    }
    assert produced <= declared
    assert declared - produced == set(), f"failure codes with no fixture: {declared - produced}"

"""Owner-resolver comparison and immutable ReferenceVerificationReceipt construction.

Shared foundation section 4.2: before first use the consumer calls the registered owner
resolver by exact ``entity_id``/``version_id``, validates the returned schema, recomputes
``content_hash`` when canonical content is returned, and compares owner context, entity
type, identity, version identity/number, scope, tenant, schema and hash byte for byte.
Any missing field or mismatch fails closed. There is no fallback to latest.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from typing import Any

from .engine import compute_content_hash
from .errors import CanonicalError, CrossFieldError, SchemaValidationError
from .registry import resolve_pointer, resolve_ref
from .structural import assert_valid_instance, check_cross_field_rules, validate_instance

__all__ = [
    "COMPARED_FIELDS",
    "OwnerResponse",
    "build_receipt",
    "compare_pin_to_owner_response",
    "conditional_pin_fields",
    "required_pin_fields",
    "verify_reference",
]

RECEIPT_SCHEMA_REF = "urn:datacompany:reference-verification-receipt:1"
PIN_SCHEMA_REF = "urn:datacompany:pinned-version-ref:1"
#: The receipt schema's own declaration of the permitted subject forms. Read from the
#: schema rather than restated here, so the two can never drift apart.
SUBJECT_SCHEMA_REF = f"{RECEIPT_SCHEMA_REF}#/$defs/receipt_fields/properties/subject_local_ref"

#: Every compared field in the released order, with its non-disclosing failure code.
COMPARED_FIELDS: tuple[tuple[str, str], ...] = (
    ("owner_context", "owner_context_mismatch"),
    ("entity_type", "entity_type_mismatch"),
    ("entity_id", "entity_id_mismatch"),
    ("version_id", "version_id_mismatch"),
    ("version_number", "version_number_mismatch"),
    ("resource_scope", "resource_scope_mismatch"),
    ("resource_tenant_id", "resource_tenant_mismatch"),
    ("schema_ref", "schema_ref_mismatch"),
    ("content_hash", "content_hash_mismatch"),
)

OwnerResponse = dict[str, Any] | None
Resolver = Callable[[str, str], OwnerResponse]

#: Distinguishes "the object does not carry this member" from "it carries ``null``". Two
#: objects that both LACK a required field are not two objects that agree about it.
_ABSENT = object()


@cache
def required_pin_fields() -> frozenset[str]:
    """The members the released pin schema requires UNCONDITIONALLY.

    Read out of ``urn:datacompany:pinned-version-ref:1`` rather than restated here, exactly like
    :data:`SUBJECT_SCHEMA_REF`, so the two cannot drift apart. It is what lets
    :func:`compare_pin_to_owner_response` treat a field that is absent on BOTH sides as a
    mismatch without also rejecting the one released field whose absence is legal.

    Only ``allOf`` and ``$ref`` are followed. ``if``/``then``/``else``, ``anyOf`` and
    ``oneOf`` are deliberately NOT: the pin composes
    ``stable-identity:1#/$defs/resource_scope_conditional``, whose ``then`` requires
    ``resource_tenant_id`` only when ``resource_scope`` is ``tenant`` and whose ``else``
    FORBIDS it. Reading that ``required`` as unconditional would make every legal
    global-scope verification report ``resource_tenant_mismatch``.
    """
    required: set[str] = set()

    def walk(node: Any, base_id: str, seen: frozenset[str]) -> None:
        if not isinstance(node, dict):
            return
        base_id = node.get("$id", base_id)
        declared = node.get("required")
        if isinstance(declared, list):
            required.update(member for member in declared if isinstance(member, str))
        ref = node.get("$ref")
        if isinstance(ref, str):
            target, target_base = resolve_ref(ref, base_id)
            absolute = f"{target_base}{ref}" if ref.startswith("#") else ref
            if absolute not in seen:
                walk(target, target_base, seen | {absolute})
        branch = node.get("allOf")
        if isinstance(branch, list):
            for subschema in branch:
                walk(subschema, base_id, seen)

    base, _, _ = PIN_SCHEMA_REF.partition("#")
    walk(resolve_pointer(PIN_SCHEMA_REF), base, frozenset({PIN_SCHEMA_REF}))
    return frozenset(required)


#: One released ``if``/``then`` requirement: the ``(member, value)`` equalities the ``if``
#: tests, and the members its ``then`` then requires.
_Conditional = tuple[tuple[tuple[str, Any], ...], frozenset[str]]


def _const_condition(node: Any) -> tuple[tuple[str, Any], ...] | None:
    """The ``{member: value}`` equalities a subschema tests, or ``None`` if it tests more.

    Only the exact shape the released scope conditional uses is read: an ``if`` that both
    ``require``s its discriminators and pins each of them with ``const``. Anything richer
    returns ``None`` and is treated as no conditional requirement at all, because guessing
    at a condition this engine does not implement would make a requirement fire on the wrong
    instances -- and a comparison that reports ``resource_tenant_mismatch`` for a pair that
    legitimately agrees is exactly as broken as one that silently passes.

    The ``required`` half is not decoration. Under JSON Schema, ``properties`` does not apply
    to an absent member, so ``if: {properties: {resource_scope: {const: "tenant"}}}`` alone
    is TRUE for an object carrying no ``resource_scope`` at all. The released schema pairs it
    with ``required`` for that reason, and this refuses to read a condition that does not.
    """
    if not isinstance(node, dict):
        return None
    if node.keys() - {"required", "properties", "$comment"}:
        return None
    properties = node.get("properties")
    if not isinstance(properties, dict) or not properties:
        return None
    condition: list[tuple[str, Any]] = []
    for member, subschema in properties.items():
        if not isinstance(subschema, dict) or subschema.keys() - {"const", "$comment"}:
            return None
        if "const" not in subschema:
            return None
        condition.append((member, subschema["const"]))
    declared = node.get("required")
    if not isinstance(declared, list) or set(declared) != {member for member, _ in condition}:
        return None
    return tuple(sorted(condition))


@cache
def _conditional_pin_requirements() -> tuple[_Conditional, ...]:
    """Every ``if``/``then`` requirement the released pin schema declares.

    A SEPARATE walk from :func:`required_pin_fields`, which must keep ignoring the
    conditional branches: folding ``then``'s ``required`` into the unconditional set would
    make every legal global-scope verification report ``resource_tenant_mismatch``, and the
    mutant that does so is red in
    ``tests/test_verification_missing_field_symmetry.py``. What is needed is not a wider
    unconditional set but the condition itself, evaluated against the pair being compared.
    """
    found: list[_Conditional] = []

    def walk(node: Any, base_id: str, seen: frozenset[str]) -> None:
        if not isinstance(node, dict):
            return
        base_id = node.get("$id", base_id)
        condition = _const_condition(node.get("if"))
        consequent = node.get("then")
        if condition is not None and isinstance(consequent, dict):
            declared = consequent.get("required")
            if isinstance(declared, list):
                members = frozenset(m for m in declared if isinstance(m, str))
                if members:
                    found.append((condition, members))
        ref = node.get("$ref")
        if isinstance(ref, str):
            target, target_base = resolve_ref(ref, base_id)
            absolute = f"{target_base}{ref}" if ref.startswith("#") else ref
            if absolute not in seen:
                walk(target, target_base, seen | {absolute})
        branch = node.get("allOf")
        if isinstance(branch, list):
            for subschema in branch:
                walk(subschema, base_id, seen)

    base, _, _ = PIN_SCHEMA_REF.partition("#")
    walk(resolve_pointer(PIN_SCHEMA_REF), base, frozenset({PIN_SCHEMA_REF}))
    return tuple(found)


def _condition_holds(record: dict[str, Any], condition: tuple[tuple[str, Any], ...]) -> bool:
    return all(member in record and record[member] == value for member, value in condition)


def conditional_pin_fields(pin: dict[str, Any], response: OwnerResponse) -> frozenset[str]:
    """The members the released pin schema requires OF THIS PAIR, beyond the unconditional set.

    :func:`required_pin_fields` deliberately reads only what the pin schema requires
    unconditionally, and that left a real hole: the schema requires ``resource_tenant_id``
    iff ``resource_scope`` is ``tenant``, so a pin declaring ``"resource_scope": "tenant"``
    with NO tenant id, answered by a response with no tenant id either, agreed about a member
    the contract says must be there -- and ``compare_pin_to_owner_response`` returned ``None``,
    VERIFIED. ``verify_reference`` blocks that pin at schema validation, but this function is
    exported and a direct caller got the silent pass.

    The fix consults the pair's own scope rather than teaching ``required_pin_fields`` to
    follow ``if``/``then``/``else``, which was avoided on purpose and would break every legal
    global-scope verification. Both halves stay schema-derived: the discriminating member,
    the value that triggers the requirement and the members it requires are all read out of
    ``urn:datacompany:pinned-version-ref:1``, so no field name is restated here either.

    The condition must hold on BOTH sides. A pin and a response that disagree about the
    discriminator do not agree about anything downstream of it, and that disagreement is
    already reported on the discriminator's own field -- ``resource_scope`` precedes
    ``resource_tenant_id`` in :data:`COMPARED_FIELDS` -- so requiring it of a pair that is
    already mismatched would only relabel an existing failure.
    """
    if response is None:
        return frozenset()
    members: set[str] = set()
    for condition, required in _conditional_pin_requirements():
        if _condition_holds(pin, condition) and _condition_holds(response, condition):
            members |= required
    return frozenset(members)


def compare_pin_to_owner_response(pin: dict[str, Any], response: OwnerResponse) -> str | None:
    """Return the non-disclosing failure code, or ``None`` when every field matches.

    A field the released pin schema REQUIRES must be present on both sides. Comparing with
    ``pin.get(field) != response.get(field)`` made two objects that both LACK the field
    compare equal, so ``compare_pin_to_owner_response({}, {})`` answered ``None`` -- "every
    field matched, verified" -- which is the silent pass the whole comparison exists to
    prevent. Absence is now a mismatch on the field's own code, which is the closed enum's
    per-field class for "the pin and the owner do not agree about this field"; nothing in
    the enum describes absence separately and the enum is closed, so no code is invented.

    ``resource_tenant_id`` is the one field absent on both sides legitimately, and only
    conditionally so: the released scope conditional REQUIRES it iff ``resource_scope`` is
    ``tenant`` and FORBIDS it otherwise. Two GLOBAL-scope references therefore agree about it
    by both omitting it, while two TENANT-scoped ones that both omit it agree about nothing --
    they are both missing a member the contract says must be there, and that pair used to
    return ``None``, VERIFIED. Both halves are read from the schema
    (:func:`required_pin_fields` and :func:`conditional_pin_fields`), never from a hardcoded
    field name, and absent-on-one-side-only is still a mismatch -- a global pin answered with
    a tenant-scoped target, or the reverse, does not silently pass.

    An owner that answers with content the released contract rejects -- content that does
    not validate against the declared ``schema_ref``, breaks a cross-field rule, carries an
    unstable binary float or an undeclared array -- is a rejected verification, not an
    exception. ``compute_content_hash`` raises for all of those, and letting the raise
    escape meant a hostile or broken owner service suppressed the audit record entirely:
    ``verify_reference`` produced no receipt at all where the contract wants a rejected one.
    The recorded code is ``content_hash_mismatch``, the closed enum's class for "the pinned
    hash could not be reproduced from what the owner returned"; no other member of the enum
    describes it, and the enum is closed, so none is invented.
    """
    if response is None:
        return "target_not_found"
    if response.get("resolution_denied") is True:
        return "resolution_denied"
    required = required_pin_fields() | conditional_pin_fields(pin, response)
    for field, code in COMPARED_FIELDS:
        pinned = pin.get(field, _ABSENT)
        if field == "content_hash":
            expected = response.get("content_hash", _ABSENT)
            canonical_content = response.get("canonical_content")
            if canonical_content is not None:
                # Never trust a returned hash when the canonical content is available.
                schema_ref = response.get("schema_ref")
                if not isinstance(schema_ref, str):
                    return code
                try:
                    expected = compute_content_hash(canonical_content, schema_ref)
                except CanonicalError:
                    return code
        else:
            expected = response.get(field, _ABSENT)
        if pinned is _ABSENT or expected is _ABSENT:
            # Absent on BOTH sides is agreement only where the released pin schema permits
            # the field to be absent at all; absent on one side only never is.
            if pinned is _ABSENT and expected is _ABSENT and field not in required:
                continue
            return code
        if pinned != expected:
            return code
    return None


def _reject_unusable_subject(consumer_context: str, subject_local_ref: Any) -> None:
    """Fail before the resolver when the local subject cannot carry a receipt at all.

    Section 4.2: ``subject_local_ref`` is a released ``IdentityRef`` or ``PinnedVersionRef``
    whose ``owner_context`` equals ``consumer_context``. Both halves are read from the
    receipt schema -- the permitted forms from its declared subschema, the equality from its
    released cross-field rules evaluated over the two arguments placed at their declared
    receipt locations -- so no field name is restated here.
    """
    errors = validate_instance(subject_local_ref, SUBJECT_SCHEMA_REF)
    if errors:
        raise SchemaValidationError(
            "subject_local_ref is not a released reference form and produces no receipt: "
            + "; ".join(errors)
        )
    failures = check_cross_field_rules(
        {"consumer_context": consumer_context, "subject_local_ref": subject_local_ref},
        RECEIPT_SCHEMA_REF,
    )
    if failures:
        raise CrossFieldError(
            "subject_local_ref is not owned by the consumer and produces no receipt: "
            + "; ".join(failures)
        )


def build_receipt(
    *,
    receipt_id: str,
    consumer_context: str,
    subject_local_ref: dict[str, Any],
    pinned_version_ref: dict[str, Any],
    verification_profile_ref: str,
    verified_at: str,
    failure_code: str | None,
    verified_owner_context: str,
    verified_schema_ref: str,
    verified_content_hash: str,
) -> dict[str, Any]:
    """Build and validate the immutable receipt for one verification attempt.

    Validation is the full released contract, schema *and* cross-field rules. Section 4.2
    states that ``subject_local_ref`` is a released ``IdentityRef`` or ``PinnedVersionRef``
    whose ``owner_context`` equals ``consumer_context``, and that a receipt may not be
    cross-tenant; JSON Schema cannot compare two instance locations, so those two rules live
    in the receipt schema as ``x-datacompany-cross-field``. Checking only the schema layer here
    would emit a ``verified`` receipt that the repository's own release gate rejects.
    """
    receipt: dict[str, Any] = {
        "reference_verification_receipt_id": receipt_id,
        "consumer_context": consumer_context,
        "subject_local_ref": subject_local_ref,
        "pinned_version_ref": pinned_version_ref,
        "verification_profile_ref": verification_profile_ref,
        "verified_owner_context": verified_owner_context,
        "verified_schema_ref": verified_schema_ref,
        "verified_content_hash": verified_content_hash,
        "verified_at": verified_at,
        "result": "rejected" if failure_code else "verified",
    }
    if failure_code:
        receipt["failure_code"] = failure_code
    assert_valid_instance(receipt, RECEIPT_SCHEMA_REF)
    return receipt


def verify_reference(
    pinned_version_ref: dict[str, Any],
    *,
    resolver: Resolver,
    consumer_context: str,
    subject_local_ref: dict[str, Any],
    verification_profile_ref: str,
    verified_at: str,
    receipt_id: str,
) -> dict[str, Any]:
    """Resolve, compare and return the immutable receipt.

    Malformed input never reaches the resolver: a bad pin, or a ``subject_local_ref`` that
    is not a released reference owned by ``consumer_context``, fails validation and produces
    no receipt at all, which is what keeps a rejected receipt meaningful.
    """
    errors = validate_instance(pinned_version_ref, PIN_SCHEMA_REF)
    if errors:
        raise SchemaValidationError(
            "a malformed pin is rejected by schema validation and produces no receipt: "
            + "; ".join(errors)
        )
    _reject_unusable_subject(consumer_context, subject_local_ref)
    response = resolver(pinned_version_ref["entity_id"], pinned_version_ref["version_id"])
    failure_code = compare_pin_to_owner_response(pinned_version_ref, response)
    return build_receipt(
        receipt_id=receipt_id,
        consumer_context=consumer_context,
        subject_local_ref=subject_local_ref,
        pinned_version_ref=pinned_version_ref,
        verification_profile_ref=verification_profile_ref,
        verified_at=verified_at,
        failure_code=failure_code,
        # A receipt records what the consumer compared against, never the target's data.
        verified_owner_context=pinned_version_ref["owner_context"],
        verified_schema_ref=pinned_version_ref["schema_ref"],
        verified_content_hash=pinned_version_ref["content_hash"],
    )

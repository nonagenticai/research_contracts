"""Gates over ``urn:datacompany:approval-attestation:1``.

WHY THIS SUITE EXISTS. Document 13 section 8.3 states the gate: a listed document is not
released until its schema, example, consumer matrix and compatibility test are merged. This
module is the compatibility-test quarter of that four-artifact gate for the FR approval
attestation, written to the precedent commit ``1629809`` set for the research event envelope:
the schema's promises are checked against a body, not restated in prose.

What it is FOR. The attestation's root ``$comment`` records six authoring decisions, and a
comment enforces nothing. Every one of them is made executable below -- the const version
pin, the hash binding, the exactly-pinned target, the approver SET with its declared minimum
and its admissible dissent, the required round, and the absence of any baked-in revocation
boolean. A decision that stops being true of the released document fails here rather than
being discovered by ``FND-008``'s verifier against a signed object in production.

What it is NOT. It does not check anything the JWS envelope owns. Authoring decision 1 puts
issuer, audience, signature, key validity and expiry-at-verification outside this document on
purpose, so a test here asserting them would be asserting against the wrong layer. Nor does it
test section 10.2's application logic: whether a command may be applied NOW depends on current
policy, current rights and the aggregate's current revision, none of which a document signed
in the past can answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import (
    SchemaValidationError,
    canonical_schemas,
    validate_instance,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "approvals" / "approval-attestation.v1.schema.json"

ATTESTATION = "urn:datacompany:approval-attestation:1"

#: The twelve members every attestation MUST carry, in the document's own order. An equality,
#: not a subset: a member silently dropped from ``required`` is exactly the regression this
#: pin exists to catch, and a subset check cannot see it. ``resource_tenant_id`` is absent on
#: purpose -- it is required conditionally, by ``resource_scope_conditional``, never flatly.
REQUIRED = (
    "schema_ref",
    "attestation_id",
    "approval_id",
    "approval_round",
    "resource_scope",
    "target",
    "command_operation",
    "command_hash",
    "approvers",
    "required_approvals",
    "issued_at",
    "expires_at",
)

#: The four members an approver object MUST carry. Section 10.1 requires each approver's
#: subject, role and recorded decision; ``decided_at`` is what makes a round auditable.
APPROVER_REQUIRED = ("subject", "role", "decision", "decided_at")

#: The four members ``target`` MUST carry. Authoring decision 3: an attestation naming only an
#: aggregate id would authorise a command against a state nobody approved.
TARGET_REQUIRED = ("service", "aggregate_type", "aggregate_id", "aggregate_version")


def attestation() -> dict[str, Any]:
    """One whole claim set, as a verified JWS payload would carry it.

    A function, not a constant, so every mutation below starts from an unmutated body -- the
    same reason the envelope, export and flow-ledger suites build theirs the same way.

    Deliberately minimal: every optional member (``task_ref``, ``profile_ref``,
    ``policy_ref``, ``separation_of_duty``, ``revocation_check_ref``, ``target.input_revision``,
    ``approver.rationale_ref``) is omitted, so a mutation that starts failing here is failing
    on a required member rather than on an optional one that happened to be present.
    """
    return {
        "schema_ref": ATTESTATION,
        "attestation_id": "0198f3a1-4b2c-7d3e-8f40-51a6b7c8d9e0",
        "approval_id": "5c1e9a70-2b44-4f18-b6d2-9a0c7e3f1b52",
        "approval_round": 1,
        "resource_scope": "tenant",
        "resource_tenant_id": "b6f2c1d4-3e5a-4c7b-9d81-2f4a6c8e0b13",
        "target": {
            "service": "evidence-review",
            "aggregate_type": "review",
            "aggregate_id": "7c67fcdf-c60e-45d8-9d46-a35189c0ea11",
            "aggregate_version": 12,
        },
        "command_operation": "seal_evidence_snapshot",
        "command_hash": "sha256:" + "0" * 64,
        "approvers": [
            {
                "subject": "32969c16-0000-0000-0000-000000000000",
                "role": "review_lead",
                "decision": "approve",
                "decided_at": "2026-09-02T11:14:07Z",
            }
        ],
        "required_approvals": 1,
        "issued_at": "2026-09-02T11:14:08Z",
        "expires_at": "2026-09-02T23:14:08Z",
    }


def without(member: str) -> dict[str, Any]:
    body = attestation()
    del body[member]
    return body


# ============================================================== 1. release integrity ===


def test_the_document_is_registered_under_its_own_id() -> None:
    """Non-vacuity control for everything below: an unregistered ``$id`` makes every
    ``validate_instance`` call raise rather than measure.

    It is also the check that ``approvals`` actually reached ``FOUNDATION_SCHEMA_DIRS``. That
    tuple is a closed list and this directory held nothing but a ``.gitkeep`` until now, so a
    schema authored into an unlisted directory would be present on disk, absent from every
    resolution, and ``FND-008`` would still have nothing to verify against.
    """
    schema = canonical_schemas().get(ATTESTATION)
    assert schema is not None, f"{ATTESTATION} is not in the released registry"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_registered_copy_is_the_committed_file() -> None:
    """The registry globs a directory; nothing else guarantees the file on disk is what a
    verifier resolves. A drift here means the reviewed document and the enforced document are
    two different objects."""
    on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert on_disk == canonical_schemas()[ATTESTATION], (
        "the committed file and the registered schema differ; the review looked at one of them"
    )


def test_an_unreleased_successor_does_not_silently_resolve() -> None:
    """The negative control the flow-ledger suite established: validating against a document
    nobody released must RAISE, not quietly pass. Without it, every assertion below could be
    measuring an empty registry and reporting green."""
    with pytest.raises(SchemaValidationError):
        validate_instance(attestation(), "urn:datacompany:approval-attestation:2")


def test_the_required_member_set_is_exactly_what_is_pinned() -> None:
    """An equality against the document's own ``required``. A member quietly dropped from it
    stops being checked by every consumer at once, and the parametrized removal tests below
    would silently stop covering it."""
    fields = canonical_schemas()[ATTESTATION]["$defs"]["attestation_fields"]
    assert tuple(fields["required"]) == REQUIRED


# ============================================================== 2. a whole attestation ===


def test_a_minimal_whole_attestation_validates() -> None:
    """The floor for everything else. If the base body does not validate, every refusal below
    is measuring the base body rather than the mutation, and the suite proves nothing."""
    assert validate_instance(attestation(), ATTESTATION) == []


@pytest.mark.parametrize("member", REQUIRED)
def test_every_required_member_is_actually_required(member: str) -> None:
    """A required member that is not enforced is a member a verifier will one day find
    missing at application time, on a signed object it cannot repair."""
    assert validate_instance(without(member), ATTESTATION) != [], (
        f"{member} is listed as required but its absence validates"
    )


def test_an_unknown_top_level_property_is_refused() -> None:
    """``unevaluatedProperties: false`` is what stops an attestation from growing a private
    field that one issuer writes and one verifier reads. The sealed boundary is also what
    makes authoring decision 6 hold: without it, somebody adds ``revoked: false`` and the
    reference-not-status rule is defeated by a property nobody declared."""
    body = attestation()
    body["revoked"] = False
    assert validate_instance(body, ATTESTATION) != [], (
        "an undeclared top-level property validated; the boundary is not sealed"
    )


# ============================================================== 3. the version pin ===


def test_the_schema_ref_is_pinned_to_this_document() -> None:
    """Authoring decision 1's residue in the payload. A verifier holding a STORED receipt --
    which is not a JWS and has no envelope left -- must be able to read which grammar it is
    holding before it checks anything in it."""
    fields = canonical_schemas()[ATTESTATION]["$defs"]["attestation_fields"]
    assert fields["properties"]["schema_ref"]["const"] == ATTESTATION


@pytest.mark.parametrize(
    "claimed",
    [
        "urn:datacompany:approval-attestation:2",
        "urn:datacompany:research-event-envelope:1",
        "approval-attestation",
        "",
    ],
)
def test_an_attestation_claiming_a_different_grammar_is_refused(claimed: str) -> None:
    """A body that names a grammar it is not written in is the one shape a verifier cannot
    recover from: it has already decided which rules to apply by the time it reads the rest."""
    body = attestation()
    body["schema_ref"] = claimed
    assert validate_instance(body, ATTESTATION) != [], claimed


# ============================================================== 4. the tenancy arms ===


def test_a_tenant_scoped_attestation_without_a_tenant_id_is_refused() -> None:
    """First arm of ``resource_scope_conditional``. A tenant-scoped approval with no tenant on
    it is an authorisation with no blast radius: nothing in the object says which tenant's
    aggregate it was granted over, so it fits all of them."""
    body = without("resource_tenant_id")
    assert validate_instance(body, ATTESTATION) != [], (
        "tenant scope without resource_tenant_id validated"
    )


def test_a_global_scope_attestation_carrying_a_tenant_id_is_refused() -> None:
    """Second arm, and the one a subset check never reaches. A global-scope object that also
    names a tenant is ambiguous about which of the two statements is the real one, and the
    conditional forbids it rather than letting a verifier pick."""
    body = attestation()
    body["resource_scope"] = "global"
    assert validate_instance(body, ATTESTATION) != [], (
        "global scope with a resource_tenant_id validated"
    )


def test_a_global_scope_attestation_without_a_tenant_id_validates() -> None:
    """The other half of the same rule: the estate raises global-canon approvals too, and a
    conditional that only ever refused would quietly make the object tenant-only."""
    body = without("resource_tenant_id")
    body["resource_scope"] = "global"
    assert validate_instance(body, ATTESTATION) == []


# ============================================================== 5. the command binding ===


def test_a_canonical_command_hash_is_accepted() -> None:
    """Authoring decision 2. The binding is by hash, and section 10.3's wrong-command-hash
    negative test is only writable because of it. This is the positive half: a bound that
    refused a legitimate RFC 8785 digest would be discovered in production, not here."""
    body = attestation()
    body["command_hash"] = "sha256:" + "9f" * 32
    assert validate_instance(body, ATTESTATION) == []


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("sha256:" + "A" * 64, "uppercase hex: two spellings of one digest compare unequal"),
        ("sha256:" + "0" * 63, "truncated: 63 nibbles is not a sha256"),
        ("sha256:" + "0" * 65, "over-long"),
        ("SHA256:" + "0" * 64, "uppercase algorithm prefix"),
        ("0" * 64, "unprefixed: the algorithm is part of the value"),
        ("sha256:" + "g" * 64, "non-hex"),
        ("sha512:" + "0" * 128, "a different algorithm than the one the profile pins"),
    ],
)
def test_a_command_hash_that_is_not_the_canonical_form_is_refused(value: str, why: str) -> None:
    """One digest must have exactly one spelling. Admitting a second means an attestation and
    the command it binds can hash to strings that differ as text while naming the same bytes,
    and the wrong-command-hash check then fails open on the mismatch it was built to catch."""
    body = attestation()
    body["command_hash"] = value
    assert validate_instance(body, ATTESTATION) != [], why


def test_a_command_operation_may_not_name_a_regulatory_authority() -> None:
    """``command_operation`` is a ``canonical_type_token``, so it inherits the estate's pre-ADR
    regulatory denylist, and this is the test that the inheritance is real rather than assumed.

    Nothing may name itself as an authority the ADR has not granted.
    ADR-DATACOMPANY-REGULATORY-MODEL is ``Proposed`` and unsigned. An attestation is the estate's
    strongest claim object -- it is signed, replayed and copied into audit records -- so it is
    the last place a regulatory-sounding operation should become writable by accident.
    """
    body = attestation()
    body["command_operation"] = "regulatory_signoff"
    assert validate_instance(body, ATTESTATION) != [], (
        "an attestation authorised an operation named regulatory_signoff"
    )


# ============================================================== 6. the target pin ===


@pytest.mark.parametrize("member", TARGET_REQUIRED)
def test_every_target_member_is_actually_required(member: str) -> None:
    """Authoring decision 3. Section 10.2 step 3 verifies the current revision before applying
    and section 10.3 requires a test for an aggregate that changed between approval and
    application. Both are unwritable if any of these four may be absent: an attestation
    missing ``aggregate_version`` authorises a command against whatever the state happens to
    be at application time."""
    body = attestation()
    del body["target"][member]
    assert validate_instance(body, ATTESTATION) != [], (
        f"target.{member} is listed as required but its absence validates"
    )


def test_an_unknown_target_property_is_refused() -> None:
    """``target`` is ``additionalProperties: false``. An undeclared member here is the exact
    way a pin stops being a pin -- somebody adds ``aggregate_version_min`` and the exact
    revision the approval was given against becomes a range nobody approved."""
    body = attestation()
    body["target"]["aggregate_version_min"] = 1
    assert validate_instance(body, ATTESTATION) != [], (
        "an undeclared target property validated; the target is not sealed"
    )


# ============================================================== 7. the approver set ===


def test_a_duplicate_approver_is_refused() -> None:
    """Authoring decision 4: ``approvers`` is a SET, not a list. Without ``uniqueItems`` one
    person's single decision, repeated, satisfies a ``required_approvals`` of three, and the
    count a policy demanded is met by one human. That is the failure this array shape exists
    to make impossible."""
    body = attestation()
    body["required_approvals"] = 2
    body["approvers"] = [body["approvers"][0], dict(body["approvers"][0])]
    assert validate_instance(body, ATTESTATION) != [], (
        "the same approver object appeared twice and the attestation validated"
    )


@pytest.mark.parametrize("member", APPROVER_REQUIRED)
def test_every_approver_member_is_actually_required(member: str) -> None:
    """Section 10.1 requires each approver's subject, role and recorded decision, and
    ``decided_at`` is what makes the round reconstructible afterwards. An approver missing any
    of them cannot be checked for separation of duty: a verifier cannot compare a role it was
    never given, and cannot count a decision that was never recorded."""
    body = attestation()
    del body["approvers"][0][member]
    assert validate_instance(body, ATTESTATION) != [], (
        f"approver.{member} is listed as required but its absence validates"
    )


def test_an_unknown_approver_property_is_refused() -> None:
    """The approver object is ``additionalProperties: false`` for the same reason the target
    is. A free-text ``rationale`` smuggled in beside ``rationale_ref`` would put scientific
    reasoning into an object that is copied into audit records and alerts."""
    body = attestation()
    body["approvers"][0]["rationale"] = "looked fine to me"
    assert validate_instance(body, ATTESTATION) != []


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_both_recorded_decisions_are_admitted(decision: str) -> None:
    """The schema admits ``reject`` DELIBERATELY, so an attestation can carry a dissent.

    Three required approvals with one rejection is not three approvals. A verifier that only
    ever saw approvals could not tell the two apart -- the dissenting approver would simply be
    missing, and the object would look under-approved rather than contested. Refusing
    ``reject`` here would force the issuer to drop the dissent to produce a valid document.
    """
    body = attestation()
    body["approvers"][0]["decision"] = decision
    assert validate_instance(body, ATTESTATION) == [], decision


@pytest.mark.parametrize(
    "decision",
    ["abstain", "approved", "APPROVE", "Approve", "pending", "", "approve ", None],
)
def test_any_other_recorded_decision_is_refused(decision: Any) -> None:
    """The enum is exactly two. A third value is a decision no verifier has a rule for, and
    the safe reading of an unrecognised decision is not derivable from the string itself --
    ``abstain`` and ``pending`` would have to be guessed at, in opposite directions."""
    body = attestation()
    body["approvers"][0]["decision"] = decision
    assert validate_instance(body, ATTESTATION) != [], repr(decision)


# ============================================================== 8. the round and expiry ===


@pytest.mark.parametrize("value", [0, -1, "1", 1.5, None])
def test_an_approval_round_below_one_is_refused(value: Any) -> None:
    """Authoring decision 5. Document 13 section 10.3 requires a wrong-round negative test,
    and that test is unwritable if a round can be absent, zero, or something other than a
    counting number: a re-opened approval that produced a second round must not be satisfiable
    by the first round's attestation, and 'round 0' has no ordinal meaning to compare against.
    """
    body = attestation()
    body["approval_round"] = value
    assert validate_instance(body, ATTESTATION) != [], repr(value)


def test_a_later_approval_round_validates() -> None:
    """The positive half: re-opened approvals are ordinary, and a bound that only ever refused
    would make a second round unrepresentable rather than merely distinguishable."""
    body = attestation()
    body["approval_round"] = 2
    assert validate_instance(body, ATTESTATION) == []


def test_an_attestation_without_an_expiry_is_refused() -> None:
    """An approval that never expires is a standing authorisation nobody reviews.

    ``expires_at`` is required and there is no unbounded form -- no ``null``, no sentinel. The
    expiry negative test section 10.3 requires would be unwritable against an optional field,
    because the absent case would have to be read as either 'not yet expired' or 'invalid',
    and a verifier choosing the first turns every issued attestation into a permanent grant.
    """
    assert validate_instance(without("expires_at"), ATTESTATION) != []


@pytest.mark.parametrize("member", ["issued_at", "expires_at"])
def test_a_naive_instant_is_refused(member: str) -> None:
    """Both instants are canonical UTC with a trailing ``Z``. A local-time expiry in a signed
    object is an expiry no two verifiers in different zones agree on."""
    body = attestation()
    body[member] = "2026-09-02T11:14:07"
    assert validate_instance(body, ATTESTATION) != [], member


# ============================================================== 9. the design record ===


def test_the_document_declares_no_cross_field_rule() -> None:
    """Asserted absent, for the reason the snapshot manifest was: the released operator set
    states no cardinality, so an ``x-datacompany-cross-field`` rule here could not be written
    without inventing one -- and inventing one would extend the foundation vocabulary as a
    side effect of authoring a single domain document.

    The relationships this object does have -- ``required_approvals`` against the size of
    ``approvers``, the decisions within it -- are section 10.2's to check, with current policy
    in hand. Encoding a count here would freeze at signing time a rule that is the verifier's.
    """
    schema = canonical_schemas()[ATTESTATION]
    assert "x-datacompany-cross-field" not in schema, (
        "a cross-field rule appeared; the released operator set states no cardinality"
    )


@pytest.mark.parametrize("decision", [1, 2, 3, 4, 5, 6])
def test_the_root_comment_names_every_authoring_decision(decision: int) -> None:
    """A cheap guard that the design record was not silently trimmed. Every test above cites
    one of these six by number; a ``$comment`` edited down to four leaves those citations
    pointing at nothing, and the next author has no way to tell which constraints were
    deliberate and which are accidents nobody has questioned yet."""
    comment = canonical_schemas()[ATTESTATION]["$comment"]
    assert f"AUTHORING DECISION {decision}" in comment, (
        f"authoring decision {decision} is no longer recorded in the root $comment"
    )

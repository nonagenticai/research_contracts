"""Gates over ``urn:datacompany:research-event-envelope:1``.

WHY THIS SUITE EXISTS. Document 13 section 8.3 states the gate: "No service emits a listed
document 09 event until its schema, example, consumer matrix and compatibility test are
merged." This module is the compatibility test half, and it is the only place the envelope's
promises are checked against a body rather than described in prose.

What it is NOT. It does not pin any producer's member set, because the envelope has no
producer-specific members -- every field below is estate-wide. The producer-side pins live in
each emitting service: ``evidence_review_service`` pins its own event catalogue and asserts
that a committed outbox row validates against this document.
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
SCHEMA_PATH = ROOT / "schemas" / "events" / "research-event-envelope.v1.schema.json"

ENVELOPE = "urn:datacompany:research-event-envelope:1"

#: The eleven members every envelope MUST carry, in the document's own order. An equality,
#: not a subset: a member silently dropped from ``required`` is exactly the regression this
#: pin exists to catch, and a subset check cannot see it.
REQUIRED = (
    "event_id",
    "event_type",
    "schema_ref",
    "producer",
    "resource_scope",
    "resource_tenant_id",
    "aggregate_type",
    "aggregate_id",
    "aggregate_version",
    "occurred_at",
    "payload",
)

#: The three members an envelope MAY carry. Each is optional for a stated reason recorded in
#: the document; see the per-property ``$comment``s.
OPTIONAL = ("correlation_id", "causation_id", "content_hash")


def envelope() -> dict[str, Any]:
    """One whole outbox row, as ``evidence_review_service`` will commit it.

    A function, not a constant, so every mutation below starts from an unmutated body -- the
    same reason the export and flow-ledger suites build theirs the same way.

    The review id is the one live production review this estate actually has
    (``7c67fcdf-...``), so a body that stops validating is a body that stops describing
    something real.
    """
    return {
        "event_id": "0198f3a1-4b2c-7d3e-8f40-51a6b7c8d9e0",
        "event_type": "review.decision.recorded.v1",
        "schema_ref": ENVELOPE,
        "producer": "evidence-review",
        "resource_scope": "tenant",
        "resource_tenant_id": "b6f2c1d4-3e5a-4c7b-9d81-2f4a6c8e0b13",
        "aggregate_type": "review",
        "aggregate_id": "7c67fcdf-c60e-45d8-9d46-a35189c0ea11",
        "aggregate_version": 12,
        "occurred_at": "2026-09-02T11:14:07Z",
        "payload": {
            "decision_id": "3f9a2b6c-1d4e-4a8b-9c02-7e5d3a1b6f84",
            "stage_key": "title_abstract",
            "disposition": "include",
            "reviewer_subject_id": "32969c16-0000-0000-0000-000000000000",
            "blinded": True,
        },
    }


def without(member: str) -> dict[str, Any]:
    body = envelope()
    del body[member]
    return body


# ============================================================== 1. release integrity ===


def test_the_document_is_registered_under_its_own_id() -> None:
    """Non-vacuity control for everything below: an unregistered ``$id`` makes every
    ``validate_instance`` call raise rather than measure.

    It is also the check that ``events`` actually reached ``FOUNDATION_SCHEMA_DIRS``. That
    tuple is a closed list, so a schema authored into an unlisted directory is invisible to
    the registry -- present on disk, absent from every resolution, and the whole suite below
    would fail loudly rather than pass vacuously.
    """
    schema = canonical_schemas().get(ENVELOPE)
    assert schema is not None, f"{ENVELOPE} is not in the released registry"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_registered_copy_is_the_committed_file() -> None:
    """The registry globs a directory; nothing else guarantees the file on disk is what a
    consumer resolves."""
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == canonical_schemas()[ENVELOPE]


def test_the_member_set_is_exactly_what_is_pinned() -> None:
    schema = canonical_schemas()[ENVELOPE]
    assert tuple(schema["required"]) == REQUIRED
    assert tuple(sorted(schema["properties"])) == tuple(sorted(REQUIRED + OPTIONAL))
    assert schema["additionalProperties"] is False


def test_an_unreleased_successor_does_not_silently_resolve() -> None:
    """The negative control the flow-ledger suite established: validating against a document
    nobody released must RAISE, not quietly pass. Without this, every assertion above could
    be measuring an empty registry."""
    with pytest.raises(SchemaValidationError):
        validate_instance(envelope(), "urn:datacompany:research-event-envelope:2")


# ============================================================== 2. a whole envelope ===


def test_a_whole_outbox_row_validates() -> None:
    assert validate_instance(envelope(), ENVELOPE) == []


@pytest.mark.parametrize("member", REQUIRED)
def test_every_required_member_is_actually_required(member: str) -> None:
    assert validate_instance(without(member), ENVELOPE) != []


def full_envelope() -> dict[str, Any]:
    """The same row carrying all three optional members, so the optional-member gates below
    measure removal from a body that HAD them rather than absence from one that never did."""
    return envelope() | {
        "correlation_id": "5c1e9a70-2b44-4f18-b6d2-9a0c7e3f1b52",
        "causation_id": "0198f3a1-0000-7000-8000-000000000001",
        "content_hash": "sha256:" + "a" * 64,
    }


def test_a_row_carrying_every_optional_member_validates() -> None:
    assert validate_instance(full_envelope(), ENVELOPE) == []


@pytest.mark.parametrize("member", OPTIONAL)
def test_every_optional_member_is_actually_optional(member: str) -> None:
    body = full_envelope()
    del body[member]
    assert validate_instance(body, ENVELOPE) == []


def test_an_unknown_member_is_refused() -> None:
    """``additionalProperties: false`` is what stops an envelope from growing a private
    field that only one producer writes and only one consumer reads."""
    body = envelope()
    body["consumed_at"] = "2026-09-02T11:14:08Z"
    assert validate_instance(body, ENVELOPE) != []


# ============================================================== 3. the version pin ===


def test_the_schema_ref_is_pinned_to_this_document() -> None:
    """Authoring decision (1). The envelope must be able to say which envelope grammar it
    is, or a consumer reading a mixed stream has to guess."""
    assert canonical_schemas()[ENVELOPE]["properties"]["schema_ref"]["const"] == ENVELOPE


def test_an_envelope_claiming_a_different_grammar_is_refused() -> None:
    body = envelope()
    body["schema_ref"] = "urn:datacompany:research-event-envelope:2"
    assert validate_instance(body, ENVELOPE) != []


# ============================================================== 4. the event name ===


@pytest.mark.parametrize(
    "name",
    [
        "review.created.v1",
        "review.import.completed.v1",
        "review.duplicate_cluster.proposed.v1",
        "review.evidence_snapshot.created.v1",
        "output.compilation.completed.v1",
        "review.decision.recorded.v12",
    ],
)
def test_every_specified_event_name_shape_is_accepted(name: str) -> None:
    """Sampled across the document 09 section 3.7 catalogue -- including the underscored
    segment (``duplicate_cluster``) and the two-digit version -- because the pattern is a
    respelling and a respelling is where a real name gets refused."""
    body = envelope()
    body["event_type"] = name
    assert validate_instance(body, ENVELOPE) == [], name


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("review", "undotted: a bare token is not an event name"),
        ("review.created", "unversioned: the version is part of the NAME"),
        ("review.created.v0", "v0: versions start at 1"),
        ("Review.Created.v1", "uppercase"),
        ("review..created.v1", "empty segment"),
        ("review.created.v1.", "trailing dot"),
        ("review-created.v1", "hyphen is the bounded-context grammar, not the event one"),
    ],
)
def test_a_malformed_event_name_is_refused(name: str, why: str) -> None:
    body = envelope()
    body["event_type"] = name
    assert validate_instance(body, ENVELOPE) != [], why


@pytest.mark.parametrize(
    "name",
    [
        "regulatory.provision.published.v1",
        "guideline.legal_basis.recorded.v1",
        "text.consolidation.completed.v1",
        "provision.normative.changed.v1",
    ],
)
def test_the_regulatory_denylist_survives_the_respelling(name: str) -> None:
    """Authoring decision (4). ``event_type`` cannot reuse ``canonical_type_token`` -- that
    pattern refuses every dotted name -- so the pattern is respelled, and the estate's
    regulatory guard has to be carried across with it by hand. This is the test that the
    hand-carry happened. An event name is a permanent, replayable record; it is the last
    place the estate wants a gap in that guard.

    ADR-DATACOMPANY-REGULATORY-MODEL is ``Proposed`` and unsigned, and section 2.2 still rejects
    every canonical regulatory table. Until that changes, these names must not be writable.
    """
    body = envelope()
    body["event_type"] = name
    assert validate_instance(body, ENVELOPE) != [], name


# ============================================================== 5. the payload bound ===


def test_a_payload_may_be_empty() -> None:
    """The correct payload for an event whose whole content is the aggregate reference the
    envelope already carries. An empty object is a statement; an absent payload is not."""
    body = envelope()
    body["payload"] = {}
    assert validate_instance(body, ENVELOPE) == []


def test_an_abstract_does_not_fit_in_a_payload() -> None:
    """Authoring decision (2). Document 13 section 8.2 says payloads carry identifiers,
    versions, hashes and minimal facts, and document 14 says never abstracts or full text.
    A comment enforces nothing; the 512-character bound does.
    """
    body = envelope()
    body["payload"] = {"abstract": "x" * 513}
    assert validate_instance(body, ENVELOPE) != []


def test_the_bound_cannot_be_escaped_by_nesting() -> None:
    """``minimal_fact`` recurses deliberately. A bound applied only at the top level is a
    bound on where somebody puts the abstract, not on whether they may."""
    body = envelope()
    body["payload"] = {"record": {"fields": [{"value": "x" * 513}]}}
    assert validate_instance(body, ENVELOPE) != []


def test_a_uuid_urn_and_digest_all_fit_comfortably() -> None:
    """The other half of the bound: 512 was chosen so that nothing legitimate is refused.
    A test that only proved the refusal would leave the over-narrow failure invisible."""
    body = envelope()
    body["payload"] = {
        "corpus_version_id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
        "schema_ref": ENVELOPE,
        "content_hash": "sha256:" + "0" * 64,
        "exclusion_reason": "wrong_population",
        "member_ids": ["1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"] * 8,
        "counts": {"included": 2, "excluded": 2},
        "sealed": True,
        "superseded_by": None,
    }
    assert validate_instance(body, ENVELOPE) == []


def test_a_payload_key_that_is_not_a_snake_case_token_is_refused() -> None:
    body = envelope()
    body["payload"] = {"Decision Id": "x"}
    assert validate_instance(body, ENVELOPE) != []


# ============================================================== 6. the ordering key ===


def test_an_envelope_without_an_aggregate_version_is_refused() -> None:
    """Authoring decision (3). Ordering per (resource_scope, resource_tenant_id,
    aggregate_type, aggregate_id) is guaranteed USING this number; a row that omits it
    silently disables that mechanism for itself, and a consumer cannot tell an unordered row
    from an ordered one after the fact."""
    assert validate_instance(without("aggregate_version"), ENVELOPE) != []


@pytest.mark.parametrize("value", [0, -1, "3", 1.5, None])
def test_an_aggregate_version_that_is_not_a_positive_integer_is_refused(value: Any) -> None:
    body = envelope()
    body["aggregate_version"] = value
    assert validate_instance(body, ENVELOPE) != []


def test_a_naive_timestamp_is_refused() -> None:
    """The released grammar is UTC with a trailing ``Z``. A local-time occurred_at in a
    replayable log is a retention boundary nobody can compute."""
    body = envelope()
    body["occurred_at"] = "2026-09-02T11:14:07"
    assert validate_instance(body, ENVELOPE) != []


def test_a_global_scope_envelope_validates() -> None:
    """``8814``/``8815`` raise global-canon events. The scope is an enum of two and both
    halves have to work, or the envelope quietly becomes tenant-only."""
    body = envelope()
    body["resource_scope"] = "global"
    assert validate_instance(body, ENVELOPE) == []

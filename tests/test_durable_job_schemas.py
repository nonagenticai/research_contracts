"""Gates over ``urn:datacompany:durable-job:1``, ``urn:datacompany:job-attempt:1`` and
``urn:datacompany:operation-idempotency-record:1``.

WHY THIS SUITE EXISTS. Document 13 section 8.3 states the gate: a listed document is not
released until its schema, example, consumer matrix and compatibility test are merged. This
module is the compatibility-test quarter for the three documents ``FND-003`` tasks 1 and 2
owe, written to the precedent the research event envelope set -- the schema's promises are
checked against a body, not restated in prose.

What it is FOR. These three documents were authored FROM a running implementation rather than
onto a blank page: ``evidence_review_service`` has kept ``durable_jobs``, ``job_attempts`` and
``operation_idempotency`` in production against no released grammar at all, and
``research_output_service`` implements the claim-before-work protocol on the third. That makes
the cross-field rules the load-bearing part. Terminality, a failed state naming its failure,
``waiting`` declaring both a reason and a reconcile instant, cancellation's both-or-neither
pair, an attempt's ended/outcome pair, and a completed idempotency record actually being
replayable are all executable below. Each is a row shape that validates without its rule and
is a defect with it.

What it is NOT. It does not test the transitions. The legal edges between states live in a
database trigger and in ``job_catalog``; a document grammar sees one row at a time and cannot
know which row preceded it, so a test here asserting ``running -> succeeded`` would be
asserting against the wrong layer. It does not test lease duration, retry policy or heartbeat
interval either -- section 13.6.4 leaves those to configuration on purpose, and pinning one
service's tuning into a fleet contract is the thing the documents deliberately refuse.
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

JOB = "urn:datacompany:durable-job:1"
ATTEMPT = "urn:datacompany:job-attempt:1"
RECORD = "urn:datacompany:operation-idempotency-record:1"

JOB_PATH = ROOT / "schemas" / "jobs" / "durable-job.v1.schema.json"
ATTEMPT_PATH = ROOT / "schemas" / "jobs" / "job-attempt.v1.schema.json"
RECORD_PATH = ROOT / "schemas" / "common" / "operation-idempotency-record.v1.schema.json"

DOCUMENTS = ((JOB, JOB_PATH), (ATTEMPT, ATTEMPT_PATH), (RECORD, RECORD_PATH))

#: The number of ``AUTHORING DECISION`` paragraphs each root ``$comment`` declares. An
#: equality per document: a decision deleted from the comment is a decision nobody is holding
#: the schema to any more, and that must be as loud as a decision that stopped being true.
DECISION_COUNTS = ((JOB, 5), (ATTEMPT, 4), (RECORD, 5))

#: Members every durable job MUST carry, in the document's own order. An equality, not a
#: subset: a member silently dropped from ``required`` is exactly the regression this pin
#: exists to catch, and the parametrized removals below would silently stop covering it.
JOB_REQUIRED = (
    "schema_ref",
    "job_id",
    "tenant_id",
    "job_type",
    "state",
    "command_hash",
    "attempt",
    "max_attempts",
    "progress",
    "queued_at",
)

ATTEMPT_REQUIRED = (
    "schema_ref",
    "attempt_id",
    "job_id",
    "tenant_id",
    "attempt_number",
    "worker_id",
    "started_at",
)

#: ``resource_tenant_id`` is absent on purpose -- it is required conditionally, by
#: ``resource_scope_conditional``, never flatly. Same shape as the attestation's pin.
RECORD_REQUIRED = (
    "schema_ref",
    "resource_scope",
    "principal_subject_id",
    "operation_id",
    "idempotency_key",
    "request_hash",
    "state",
    "created_at",
)

JOB_STATES = ("queued", "running", "waiting", "succeeded", "failed", "cancelled")
TERMINAL_STATES = ("succeeded", "failed", "cancelled")
LIVE_STATES = ("queued", "running", "waiting")
ATTEMPT_OUTCOMES = ("succeeded", "failed", "cancelled", "lease_expired")

TENANT = "0195f48b-d000-7000-8000-000000000101"
SUBJECT = "aad9fff9-fcd6-4a02-83f3-cf133f15d384"
HASH = "sha256:" + "a" * 64


def job() -> dict[str, Any]:
    """A minimal whole job: queued, never claimed, nothing terminal."""
    return {
        "schema_ref": JOB,
        "job_id": "0195f48b-d000-7000-8000-000000000201",
        "tenant_id": TENANT,
        "job_type": "snapshot_build",
        "state": "queued",
        "command_hash": HASH,
        "attempt": 0,
        "max_attempts": 3,
        "progress": {},
        "queued_at": "2026-09-04T06:00:00Z",
    }


def attempt() -> dict[str, Any]:
    """A minimal whole attempt: in flight, so neither ``ended_at`` nor ``outcome``."""
    return {
        "schema_ref": ATTEMPT,
        "attempt_id": "0195f48b-d000-7000-8000-000000000301",
        "job_id": "0195f48b-d000-7000-8000-000000000201",
        "tenant_id": TENANT,
        "attempt_number": 1,
        "worker_id": "worker-1",
        "started_at": "2026-09-04T06:00:10Z",
    }


def record() -> dict[str, Any]:
    """A minimal whole idempotency record: tenant-scoped, claimed, not yet completed."""
    return {
        "schema_ref": RECORD,
        "resource_scope": "tenant",
        "resource_tenant_id": TENANT,
        "principal_subject_id": SUBJECT,
        "operation_id": "create_output",
        "idempotency_key": "caller-key-1",
        "request_hash": "sha256:" + "b" * 64,
        "state": "processing",
        "created_at": "2026-09-04T06:00:00Z",
    }


BASE = {JOB: job, ATTEMPT: attempt, RECORD: record}


def without(urn: str, member: str) -> dict[str, Any]:
    body = BASE[urn]()
    del body[member]
    return body


def closed(state: str) -> dict[str, Any]:
    """An attempt that ended, with the code a failure needs and no other."""
    body = attempt()
    body["outcome"] = state
    body["ended_at"] = "2026-09-04T06:05:00Z"
    if state == "failed":
        body["error_code"] = "provider_timeout"
    return body


def terminal(state: str) -> dict[str, Any]:
    """A job that reached ``state``, carrying the members that state requires."""
    body = job()
    body["state"] = state
    body["terminal_at"] = "2026-09-04T06:05:00Z"
    if state == "failed":
        body["error_code"] = "lease_exhausted"
    return body


# ============================================================== 1. release integrity ===


@pytest.mark.parametrize(("urn", "path"), DOCUMENTS)
def test_the_document_is_registered_under_its_own_id(urn: str, path: Path) -> None:
    """Non-vacuity control for everything below: an unregistered ``$id`` makes every
    ``validate_instance`` call raise rather than measure.

    It is also the check that ``jobs`` actually reached ``FOUNDATION_SCHEMA_DIRS``. That tuple
    is a closed list and the directory held nothing but a ``.gitkeep`` from 2026-07-30 until
    this release, so a schema authored into an unlisted directory would be present on disk,
    absent from every resolution, and a producer pinning a ``schema_ref`` at it would be
    naming a document the registry does not have.
    """
    schema = canonical_schemas().get(urn)
    assert schema is not None, f"{urn} is not in the released registry"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize(("urn", "path"), DOCUMENTS)
def test_the_registered_copy_is_the_committed_file(urn: str, path: Path) -> None:
    """The registry globs a directory; nothing else guarantees the file on disk is what a
    consumer resolves. A drift here means the reviewed document and the enforced document are
    two different objects."""
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == canonical_schemas()[urn], (
        f"the committed file and the registered {urn} differ; the review looked at one of them"
    )


@pytest.mark.parametrize(("urn", "path"), DOCUMENTS)
def test_an_unreleased_successor_does_not_silently_resolve(urn: str, path: Path) -> None:
    """The negative control: validating against a document nobody released must RAISE, not
    quietly pass. Without it every assertion below could be measuring an empty registry and
    reporting green."""
    with pytest.raises(SchemaValidationError):
        validate_instance(BASE[urn](), urn.replace(":1", ":2"))


@pytest.mark.parametrize(("urn", "path"), DOCUMENTS)
def test_the_schema_ref_is_pinned_to_its_own_document(urn: str, path: Path) -> None:
    """The envelope idiom. A reader holding a STORED row -- which arrived with no envelope
    around it -- must be able to read which grammar it is holding before it checks anything
    in it."""
    schema = canonical_schemas()[urn]
    fields = schema["$defs"]["record_fields"] if urn == RECORD else schema
    assert fields["properties"]["schema_ref"]["const"] == urn


@pytest.mark.parametrize(("urn", "path"), DOCUMENTS)
def test_a_row_claiming_a_different_grammar_is_refused(urn: str, path: Path) -> None:
    """A const that is declared but not enforced is a version pin that admits every other
    version. A row whose ``schema_ref`` names a sibling document must not validate here."""
    body = BASE[urn]()
    body["schema_ref"] = "urn:datacompany:research-event-envelope:1"
    assert validate_instance(body, urn) != [], f"{urn} accepted a row claiming a different grammar"


@pytest.mark.parametrize(("urn", "count"), DECISION_COUNTS)
def test_the_root_comment_names_every_authoring_decision(urn: str, count: int) -> None:
    """A decision paragraph is what a later reader has instead of the review conversation. If
    one is deleted, the schema keeps whatever shape it had and nobody can say why."""
    comment = canonical_schemas()[urn]["$comment"]
    for ordinal in range(1, count + 1):
        assert f"AUTHORING DECISION {ordinal} -" in comment, (
            f"{urn} does not name authoring decision {ordinal}"
        )
    assert f"AUTHORING DECISION {count + 1} -" not in comment, (
        f"{urn} names more decisions than this pin admits"
    )


# ============================================================== 2. whole rows ===


@pytest.mark.parametrize(("urn", "path"), DOCUMENTS)
def test_a_minimal_whole_row_validates(urn: str, path: Path) -> None:
    """The floor for everything else. If a base body does not validate, every refusal below is
    measuring the base body rather than the mutation, and the suite proves nothing."""
    assert validate_instance(BASE[urn](), urn) == []


@pytest.mark.parametrize(
    ("urn", "required"),
    ((JOB, JOB_REQUIRED), (ATTEMPT, ATTEMPT_REQUIRED), (RECORD, RECORD_REQUIRED)),
)
def test_the_required_member_set_is_exactly_what_is_pinned(
    urn: str, required: tuple[str, ...]
) -> None:
    """An equality against the document's own ``required``. A member quietly dropped from it
    stops being checked by every consumer at once."""
    schema = canonical_schemas()[urn]
    fields = schema["$defs"]["record_fields"] if urn == RECORD else schema
    assert tuple(fields["required"]) == required


@pytest.mark.parametrize("member", JOB_REQUIRED)
def test_every_required_job_member_is_actually_required(member: str) -> None:
    assert validate_instance(without(JOB, member), JOB) != [], (
        f"{member} is listed as required but its absence validates"
    )


@pytest.mark.parametrize("member", ATTEMPT_REQUIRED)
def test_every_required_attempt_member_is_actually_required(member: str) -> None:
    assert validate_instance(without(ATTEMPT, member), ATTEMPT) != [], (
        f"{member} is listed as required but its absence validates"
    )


@pytest.mark.parametrize("member", RECORD_REQUIRED)
def test_every_required_record_member_is_actually_required(member: str) -> None:
    assert validate_instance(without(RECORD, member), RECORD) != [], (
        f"{member} is listed as required but its absence validates"
    )


@pytest.mark.parametrize(("urn", "path"), DOCUMENTS)
def test_an_unknown_top_level_property_is_refused(urn: str, path: Path) -> None:
    """The sealed boundary is what stops an operational row growing a private field that one
    writer sets and one reader trusts. It is also what keeps the payload-minimal rule real: an
    undeclared property is exactly where licensed text would arrive."""
    body = BASE[urn]()
    body["operator_note"] = "a free-text field nobody declared"
    assert validate_instance(body, urn) != [], (
        f"{urn} accepted an undeclared top-level property; the boundary is not sealed"
    )


# ============================================================== 3. the job's states ===


@pytest.mark.parametrize("state", JOB_STATES)
def test_every_declared_job_state_validates(state: str) -> None:
    """All six, so the enum is measured rather than assumed. A state that cannot be expressed
    is a row a service can write and no consumer can read."""
    body = terminal(state) if state in TERMINAL_STATES else job()
    body["state"] = state
    if state == "waiting":
        body["waiting_reason"] = "provider_result"
        body["reconcile_after"] = "2026-09-04T06:30:00Z"
    assert validate_instance(body, JOB) == []


@pytest.mark.parametrize("state", ("cancel_requested", "lease_expired", "pending", "done"))
def test_a_state_outside_the_six_is_refused(state: str) -> None:
    """Authoring decision 2 in executable form. ``cancel_requested`` is the one that matters:
    section 13.6.4 keeps cancellation as a flag while external status stays queued, running or
    waiting, and a seventh state would make every consumer's switch wrong. ``lease_expired``
    is the mirror of authoring decision 1 on the attempt -- it is an ATTEMPT outcome and must
    not be expressible as a job state."""
    body = job()
    body["state"] = state
    assert validate_instance(body, JOB) != [], f"{state} validated as a job state"


@pytest.mark.parametrize("state", TERMINAL_STATES)
def test_a_terminal_job_must_say_when_it_became_terminal(state: str) -> None:
    """Authoring decision 3. A terminal row with no terminal instant is the row that proves
    the writer skipped the transition guard, and without this rule it validates."""
    body = terminal(state)
    del body["terminal_at"]
    assert validate_instance(body, JOB) != [], f"{state} validated with no terminal_at"


@pytest.mark.parametrize("state", LIVE_STATES)
def test_a_live_job_may_not_carry_a_terminal_instant(state: str) -> None:
    """The else arm, which is the half that is easy to omit. A queued job carrying
    ``terminal_at`` reads to every consumer as finished while the queue still holds it."""
    body = job()
    body["state"] = state
    if state == "waiting":
        body["waiting_reason"] = "provider_result"
        body["reconcile_after"] = "2026-09-04T06:30:00Z"
    body["terminal_at"] = "2026-09-04T06:05:00Z"
    assert validate_instance(body, JOB) != [], f"a {state} job validated while carrying terminal_at"


def test_a_failed_job_names_its_failure() -> None:
    """Without this rule ``failed`` with no code validates and nothing downstream can route
    it -- the operator gets a red job and no reason."""
    body = terminal("failed")
    del body["error_code"]
    assert validate_instance(body, JOB) != []


def test_a_failed_job_with_its_code_validates() -> None:
    """The positive half. A rule that refuses everything is not a rule, it is an outage."""
    assert validate_instance(terminal("failed"), JOB) == []


@pytest.mark.parametrize("member", ("waiting_reason", "reconcile_after"))
def test_a_waiting_job_declares_both_why_and_when_to_look_again(member: str) -> None:
    """Section 13.6.4 requires both on entering ``waiting``. A row missing either is a job
    nothing will ever reconcile -- it waits forever and no alert fires, because from the
    outside it is a perfectly ordinary non-terminal job."""
    body = job()
    body["state"] = "waiting"
    body["waiting_reason"] = "provider_result"
    body["reconcile_after"] = "2026-09-04T06:30:00Z"
    del body[member]
    assert validate_instance(body, JOB) != [], f"a waiting job validated with no {member}"


@pytest.mark.parametrize(
    ("present", "absent"),
    (
        ("cancel_requested_at", "cancel_requested_by"),
        ("cancel_requested_by", "cancel_requested_at"),
    ),
)
def test_cancellation_intent_is_both_or_neither(present: str, absent: str) -> None:
    """A cancellation with no requester is not attributable, and a requester with no instant
    cannot be ordered against the result that may have committed first. Both directions,
    because ``dependentRequired`` in one direction only is a half-closed door."""
    body = job()
    body[present] = "2026-09-04T06:02:00Z" if present.endswith("_at") else SUBJECT
    assert validate_instance(body, JOB) != [], f"{present} validated without {absent}"


def test_a_complete_cancellation_intent_validates() -> None:
    body = job()
    body["cancel_requested_at"] = "2026-09-04T06:02:00Z"
    body["cancel_requested_by"] = SUBJECT
    assert validate_instance(body, JOB) == []


def test_an_error_detail_at_the_cap_validates_and_one_over_is_refused() -> None:
    """512 is the live constraint. The cap is not cosmetic: an uncapped detail field is where
    licensed text leaks into an operational table that is deliberately payload-minimal."""
    body = terminal("failed")
    body["error_detail"] = "x" * 512
    assert validate_instance(body, JOB) == []
    body["error_detail"] = "x" * 513
    assert validate_instance(body, JOB) != []


@pytest.mark.parametrize(("member", "value"), (("attempt", -1), ("max_attempts", 0)))
def test_an_impossible_attempt_count_is_refused(member: str, value: int) -> None:
    """A negative attempt count is a writer bug; a ceiling of zero is a job that may never be
    attempted, which is not a job."""
    body = job()
    body[member] = value
    assert validate_instance(body, JOB) != []


# ============================================================== 4. the attempt ===


@pytest.mark.parametrize("outcome", ATTEMPT_OUTCOMES)
def test_every_declared_attempt_outcome_validates(outcome: str) -> None:
    assert validate_instance(closed(outcome), ATTEMPT) == []


def test_lease_expired_is_an_attempt_outcome_and_not_a_job_state() -> None:
    """Authoring decision 1, asserted from both sides at once -- which is the only way it can
    fail loudly. If somebody later unifies the two enums, one of these two halves goes red
    whichever direction they unify in, and the fact an attempt uniquely carries -- that nobody
    reported a result at all -- stops being expressible."""
    assert validate_instance(closed("lease_expired"), ATTEMPT) == []
    body = job()
    body["state"] = "lease_expired"
    assert validate_instance(body, JOB) != [], (
        "lease_expired validated as a job state; the two enums have been unified"
    )


def test_an_outcome_outside_the_four_is_refused() -> None:
    body = closed("succeeded")
    body["outcome"] = "timed_out"
    assert validate_instance(body, ATTEMPT) != []


@pytest.mark.parametrize("member", ("ended_at", "outcome"))
def test_an_attempt_ends_and_reports_together(member: str) -> None:
    """Authoring decision 2. The pair is what lets a reader tell a running attempt from one
    whose writer crashed between the two columns; either alone is indistinguishable from a
    torn write."""
    body = closed("succeeded")
    del body[member]
    assert validate_instance(body, ATTEMPT) != [], (
        f"an attempt validated carrying only one of ended_at/outcome (missing {member})"
    )


def test_a_failed_attempt_names_its_failure() -> None:
    body = closed("failed")
    del body["error_code"]
    assert validate_instance(body, ATTEMPT) != []


@pytest.mark.parametrize("outcome", ("succeeded", "cancelled", "lease_expired"))
def test_a_non_failed_attempt_may_not_carry_an_error_code(outcome: str) -> None:
    """A green attempt carrying an error code reads as red to an auditor counting failures,
    and the count is what a retry policy is tuned against."""
    body = closed(outcome)
    body["error_code"] = "provider_timeout"
    assert validate_instance(body, ATTEMPT) != [], (
        f"a {outcome} attempt validated while carrying an error_code"
    )


# ============================================================== 5. the idempotency record ===


def test_a_completed_record_can_actually_be_replayed() -> None:
    """Section 13.6.2 item 3 promises the same scope/key/hash replays the original status,
    headers and body. A ``completed`` row with no status promises a replay it cannot perform,
    and it validates without this rule."""
    body = record()
    body["state"] = "completed"
    assert validate_instance(body, RECORD) != []
    body["response_status"] = 200
    assert validate_instance(body, RECORD) == []


def test_a_claim_in_flight_may_not_carry_a_response_status() -> None:
    """Authoring decision 2's whole point. Both live services encode the in-flight claim as
    ``response_status = 0``, which is not an HTTP status; this document refuses the
    overloading in both directions, so ``processing`` cannot borrow the response field."""
    body = record()
    body["response_status"] = 200
    assert validate_instance(body, RECORD) != []


@pytest.mark.parametrize("status", (99, 600, 0))
def test_a_value_outside_the_http_range_is_not_a_response_status(status: int) -> None:
    """``0`` is listed on purpose: it is the exact sentinel the live services write, and the
    range starting at 100 is what makes authoring decision 2 enforceable rather than advisory."""
    body = record()
    body["state"] = "completed"
    body["response_status"] = status
    assert validate_instance(body, RECORD) != []


def test_a_tenant_scoped_record_without_a_tenant_id_is_refused() -> None:
    """The shared scope conditional, composed rather than respelled. A key missing its tenant
    part collides across tenants, which is the one collision an idempotency key must never
    have."""
    assert validate_instance(without(RECORD, "resource_tenant_id"), RECORD) != []


def test_a_global_scope_record_carrying_a_tenant_id_is_refused() -> None:
    """Section 13.6.2 binds a global operation to the explicit global marker and never to a
    null or borrowed tenant value."""
    body = record()
    body["resource_scope"] = "global"
    assert validate_instance(body, RECORD) != []


def test_a_global_scope_record_without_a_tenant_id_validates() -> None:
    """The positive half, so the two refusals above are measuring the conditional rather than
    a flatly required member."""
    body = record()
    body["resource_scope"] = "global"
    del body["resource_tenant_id"]
    assert validate_instance(body, RECORD) == []

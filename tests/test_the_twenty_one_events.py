"""The compatibility-test quarter of the document 13 section 8.3 gate, for every event payload.

WHY THIS SUITE EXISTS. Document 13 section 8.3 forbids a service emitting a listed document
09 event until that event's schema, example, consumer-matrix row and compatibility test are
merged. Measured 2026-09-04, all twenty-one of ``evidence_review_service``'s events stood at
zero of the four, and the consequence was not theoretical: an outbox, a durable log, a
delivery table and an inbox had shipped across four merged pull requests and every one of
those tables held zero rows, permanently, because the gate could never open.

WHAT IT COVERS THAT A PER-SCHEMA TEST CANNOT. The existing suites each pin ONE document's
current shape. Three things only a suite that walks the whole directory can assert:

1. Every payload document has an example, and the example actually validates. A schema with
   no example satisfies one quarter of the gate while appearing to satisfy two.
2. Every payload is valid INSIDE the envelope, not merely on its own. The envelope bounds
   payload strings to 512 characters at any depth and constrains property names; a payload
   document that permitted a longer string would pass its own tests forever and fail the
   first time a producer committed a row.
3. The comparator that classifies a change is exercised against mutants rather than trusted.

WHY EIGHTEEN EVENT TYPES AND TWELVE DOCUMENTS. Two producer functions each write several
event types from one code path -- ``emit_review_lifecycle`` writes six and ``emit_acceptance``
writes two -- so those event types share a payload document. That is not a shortcut: a single
function produces them, so they cannot diverge without it changing, and giving them separate
documents would advertise independent version lifecycles that no code path can exercise. The
remaining three of the twenty-one are in the service's ``NOT_YET`` map: they have no producer,
so they cannot be emitted, so section 8.3 has nothing to gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import canonical_schemas, validate_instance
from research_contracts.tooling.compatibility import Verdict, compare

ROOT = Path(__file__).resolve().parents[1]
EVENTS_DIR = ROOT / "schemas" / "events"
EXAMPLES_DIR = ROOT / "examples" / "valid"

ENVELOPE = "urn:datacompany:research-event-envelope:1"

#: The twelve payload documents, by ``$id``. An equality, not a subset -- a document added to
#: ``schemas/events/`` without a row here is a document nobody decided to release, and a row
#: here without a file is a release that silently did not happen.
PAYLOAD_IDS = (
    "urn:datacompany:review-created:1",
    "urn:datacompany:review-lifecycle-transition:1",
    "urn:datacompany:review-import-completed:1",
    "urn:datacompany:review-duplicate-cluster-proposed:1",
    "urn:datacompany:review-duplicate-cluster-resolved:1",
    "urn:datacompany:review-decision-recorded:1",
    "urn:datacompany:review-conflict-opened:1",
    "urn:datacompany:review-conflict-resolved:1",
    "urn:datacompany:review-observation-superseded:1",
    "urn:datacompany:review-assertion-recorded:1",
    "urn:datacompany:review-evidence-acceptance-recorded:1",
    "urn:datacompany:review-evidence-snapshot-created:1",
)

#: Which registered event types each document covers. The mapping is the catalogue's
#: ``schema URN`` column, held here as well so the count is checkable from this side: the
#: eighteen wired events of document 09 section 3.7 must be covered exactly once each.
EVENT_TYPES_BY_DOCUMENT: dict[str, tuple[str, ...]] = {
    "urn:datacompany:review-created:1": ("review.created.v1",),
    "urn:datacompany:review-lifecycle-transition:1": (
        "review.activated.v1",
        "review.paused.v1",
        "review.resumed.v1",
        "review.reopened.v1",
        "review.closed.v1",
        "review.archived.v1",
    ),
    "urn:datacompany:review-import-completed:1": ("review.import.completed.v1",),
    "urn:datacompany:review-duplicate-cluster-proposed:1": (
        "review.duplicate_cluster.proposed.v1",
    ),
    "urn:datacompany:review-duplicate-cluster-resolved:1": (
        "review.duplicate_cluster.resolved.v1",
    ),
    "urn:datacompany:review-decision-recorded:1": ("review.decision.recorded.v1",),
    "urn:datacompany:review-conflict-opened:1": ("review.conflict.opened.v1",),
    "urn:datacompany:review-conflict-resolved:1": ("review.conflict.resolved.v1",),
    "urn:datacompany:review-observation-superseded:1": ("review.observation.superseded.v1",),
    "urn:datacompany:review-assertion-recorded:1": ("review.assertion.recorded.v1",),
    "urn:datacompany:review-evidence-acceptance-recorded:1": (
        "review.research_object.approved.v1",
        "review.observation.accepted.v1",
    ),
    "urn:datacompany:review-evidence-snapshot-created:1": ("review.evidence_snapshot.created.v1",),
}

#: The three the service cannot raise, and why. Held here so a future author who adds one of
#: these schemas is reminded that a schema without a producer is not progress through the gate.
NOT_YET = {
    "review.proposal.decided.v1": "no ProposalBundle contract or table (ER-006.3)",
    "review.appraisal.recorded.v1": "no appraisal tables or writer (ER-009/ER-M009)",
    "review.stage.completed.v1": "stage completeness is only read, never written",
}


def _payload_documents() -> list[Path]:
    return sorted(
        p for p in EVENTS_DIR.glob("*.schema.json") if "research-event-envelope" not in p.name
    )


def _example_for(path: Path) -> Path:
    stem = path.name.removesuffix(".v1.schema.json")
    return EXAMPLES_DIR / f"{stem}.example.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _envelope_around(payload: dict[str, Any], event_type: str) -> dict[str, Any]:
    """A minimal valid envelope carrying ``payload``.

    Every member here is estate-wide and none of it is under test; the point is only to put
    the payload where a producer puts it, so the envelope's own bounds apply to it.
    """
    return {
        "event_id": "3f2a6c18-9b47-4d51-8e0a-1c7d5b2e9f43",
        "event_type": event_type,
        "schema_ref": ENVELOPE,
        "producer": "evidence-review",
        "resource_scope": "tenant",
        "resource_tenant_id": "0195f48b-d000-7000-8000-000000000101",
        "aggregate_type": "review",
        "aggregate_id": "7d1e4a92-5c63-4b08-9f27-3a6e8d0c1b54",
        "aggregate_version": 1,
        "occurred_at": "2026-09-04T11:00:00Z",
        "payload": payload,
    }


# --------------------------------------------------------------- release surface ---


def test_every_released_payload_document_is_present_and_no_others() -> None:
    """The directory and ``PAYLOAD_IDS`` agree, in both directions."""
    on_disk = {_load(p)["$id"] for p in _payload_documents()}
    assert on_disk == set(PAYLOAD_IDS)


def test_the_registry_resolves_every_payload_document() -> None:
    """A file that the registry cannot resolve is a file that does not exist to a consumer."""
    resolved = canonical_schemas()
    missing = [schema_id for schema_id in PAYLOAD_IDS if schema_id not in resolved]
    assert missing == []


def test_the_registered_copy_is_the_committed_file() -> None:
    for path in _payload_documents():
        assert _load(path) == canonical_schemas()[_load(path)["$id"]]


def test_the_eighteen_wired_event_types_are_each_covered_exactly_once() -> None:
    """Eighteen wired, three unwired, twenty-one registered -- and no double cover."""
    covered = [t for types in EVENT_TYPES_BY_DOCUMENT.values() for t in types]
    assert len(covered) == 18, "document 09 section 3.7 wires eighteen of its twenty-one"
    assert len(set(covered)) == 18, "an event type is covered by two documents"
    assert set(covered).isdisjoint(NOT_YET), "an unwired event has a schema but no producer"
    assert len(set(covered) | set(NOT_YET)) == 21


@pytest.mark.parametrize("schema_id", PAYLOAD_IDS)
def test_the_document_id_matches_its_filename(schema_id: str) -> None:
    stem = schema_id.removeprefix("urn:datacompany:").removesuffix(":1")
    assert (EVENTS_DIR / f"{stem}.v1.schema.json").is_file()


# ------------------------------------------------------------------- the example ---


@pytest.mark.parametrize("path", _payload_documents(), ids=lambda p: p.name)
def test_every_payload_document_has_an_example(path: Path) -> None:
    """Section 8.3's second quarter. A missing example is a quarter of the gate unmet."""
    assert _example_for(path).is_file(), f"no example for {path.name}"


@pytest.mark.parametrize("path", _payload_documents(), ids=lambda p: p.name)
def test_the_example_validates_against_its_own_document(path: Path) -> None:
    schema_id = _load(path)["$id"]
    assert validate_instance(_load(_example_for(path)), schema_id) == []


@pytest.mark.parametrize("path", _payload_documents(), ids=lambda p: p.name)
def test_the_example_is_valid_inside_the_envelope(path: Path) -> None:
    """The check a per-document suite cannot make.

    A payload document that permitted a 600-character string would pass its own tests
    forever and fail the first time a producer committed a row, because the envelope bounds
    every payload string to 512 at any depth. Validating the payload alone never sees that.
    """
    schema_id = _load(path)["$id"]
    event_type = EVENT_TYPES_BY_DOCUMENT[schema_id][0]
    envelope = _envelope_around(_load(_example_for(path)), event_type)
    assert validate_instance(envelope, ENVELOPE) == []


# ------------------------------------------------------------ structural promises ---


@pytest.mark.parametrize("path", _payload_documents(), ids=lambda p: p.name)
def test_every_payload_document_is_closed(path: Path) -> None:
    """``additionalProperties: false``. An open payload document constrains nothing."""
    assert _load(path).get("additionalProperties") is False


@pytest.mark.parametrize("path", _payload_documents(), ids=lambda p: p.name)
def test_every_payload_document_offers_the_sealed_composition(path: Path) -> None:
    sealed = _load(path).get("$defs", {}).get("sealed")
    assert sealed is not None, "no $defs/sealed; a composing context cannot close over it"
    assert sealed.get("unevaluatedProperties") is False


@pytest.mark.parametrize("path", _payload_documents(), ids=lambda p: p.name)
def test_every_property_name_is_envelope_legal(path: Path) -> None:
    """The envelope's payload ``propertyNames`` pattern, asserted at authoring time.

    Catching this here names the offending member; catching it through the envelope names
    only the object.
    """
    import re

    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    offenders = [name for name in _load(path).get("properties", {}) if not pattern.match(name)]
    assert offenders == []


@pytest.mark.parametrize("path", _payload_documents(), ids=lambda p: p.name)
def test_no_payload_document_carries_an_actor(path: Path) -> None:
    """Document 16 lines 392-394: actor, reviewer and approver identity come from verified
    context and attestations, never from a mutable domain payload field.

    Named members rather than a substring sweep, so the assertion says what it forbids.
    """
    forbidden = {
        "actor",
        "actor_id",
        "actor_subject_id",
        "reviewer",
        "reviewer_id",
        "screener_id",
        "approver",
        "approver_id",
        "adjudicator_subject_id",
        "adjudicator_display_name",
        "assignment_id",
        "created_by",
    }
    present = forbidden & set(_load(path).get("properties", {}))
    assert present == set(), f"{path.name} names an actor: {sorted(present)}"


@pytest.mark.parametrize("path", _payload_documents(), ids=lambda p: p.name)
def test_no_payload_document_carries_free_text(path: Path) -> None:
    """Document 13 section 8.2 confines payloads to IDs, versions, hashes and minimal facts.

    ``rationale`` is the one this catches in practice: document 09 line 238 mandates one on
    pause, resume and close, and it must not ride in an append-only log that cannot be
    redacted per consumer.
    """
    forbidden = {
        "rationale",
        "note",
        "notes",
        "comment",
        "claim_text",
        "title",
        "abstract",
        "reason",
    }
    present = forbidden & set(_load(path).get("properties", {}))
    assert present == set(), f"{path.name} carries free text: {sorted(present)}"


# -------------------------------------------------------------- the comparator ---


def test_a_document_is_compatible_with_itself() -> None:
    """The control. A comparator that cannot report IDENTICAL cannot report anything."""
    for path in _payload_documents():
        doc = _load(path)
        assert compare(doc, doc).verdict is Verdict.IDENTICAL


def test_adding_an_optional_member_keeps_the_id() -> None:
    doc = _load(EVENTS_DIR / "review-decision-recorded.v1.schema.json")
    candidate = json.loads(json.dumps(doc))
    candidate["properties"]["some_new_optional"] = {"type": "string", "maxLength": 64}
    report = compare(doc, candidate)
    assert report.verdict is Verdict.MINOR
    assert report.keeps_its_id


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        (
            "member removed",
            lambda d: d["properties"].pop("stage_id"),
        ),
        (
            "member became required",
            lambda d: d.setdefault("required", []).append("newly_required"),
        ),
        (
            "required member added",
            lambda d: (
                d["properties"].__setitem__("mandatory_thing", {"type": "string"}),
                d["required"].append("mandatory_thing"),
            ),
        ),
        (
            "document closed differently",
            lambda d: d.__setitem__("additionalProperties", True),
        ),
        (
            "a released ref repointed",
            lambda d: d["properties"]["stage_id"].__setitem__(
                "$ref", "urn:datacompany:stable-identity:1#/$defs/version_number"
            ),
        ),
    ],
)
def test_a_breaking_mutation_is_reported_breaking(name: str, mutate: Any) -> None:
    """Seven mutants, killed rather than trusted.

    A comparator is exactly the kind of code that passes its own happy path and silently
    clears the change it exists to catch, so each mutation below is a change that MUST cost
    a new ``$id`` -- except the one that opens the document, which must not.
    """
    doc = _load(EVENTS_DIR / "review-decision-recorded.v1.schema.json")
    candidate = json.loads(json.dumps(doc))
    mutate(candidate)
    report = compare(doc, candidate)
    if name == "document closed differently":
        # Opening a closed document accepts everything it accepted before, and more.
        assert report.verdict is Verdict.MINOR, str(report)
        assert report.keeps_its_id
    else:
        assert report.verdict is Verdict.MAJOR, str(report)
        assert not report.keeps_its_id
        assert report.breaking(), "MAJOR verdict with no breaking change listed"


def test_an_unmodelled_keyword_difference_fails_toward_breaking() -> None:
    """The design's honest half.

    ``oneOf`` semantics are not modelled -- deciding whether an added branch widens or
    narrows is subsumption checking, not a diff. The comparator must say so loudly rather
    than clear a change it does not understand.
    """
    doc = _load(EVENTS_DIR / "review-decision-recorded.v1.schema.json")
    candidate = json.loads(json.dumps(doc))
    candidate["oneOf"] = [{"required": ["review_id"]}]
    report = compare(doc, candidate)
    assert report.verdict is Verdict.MAJOR
    assert any("not modelled" in c.reason for c in report.breaking())


# ---------------------------------------------- the comparator's own defects ---
#
# Every case below was a REAL defect in `compatibility.py`, found by an adversarial
# audit after the module shipped, and every one of them was a FALSE MINOR or a
# FALSE IDENTICAL — the one direction the module's docstring promises it never
# fails in. They are grouped here rather than scattered so a future reader can see
# the shape they share: each was a construct the comparator did not reach, and each
# reported "safe" instead of "I could not tell".


def test_a_report_mixing_minor_and_major_is_major() -> None:
    """The worst of them, and the reason the others were looked for at all.

    `Verdict` was a `StrEnum` defining `__lt__`, and `verdict` was `max(...)` over
    the changes. `max()` calls `__gt__`, which `str` supplies and the class never
    overrode, so severity fell back to LEXICOGRAPHIC order — and `"minor"` sorts
    above `"major"`. A candidate bundling one safe addition with one breaking
    change, which is the ordinary shape of a real edit, reported MINOR and
    `keeps_its_id: True`.

    The original suite missed it because every mutation it ran produced a single
    change class, so MINOR and MAJOR never appeared in one report.
    """
    released = {"$id": "same", "properties": {"a": {"type": "string"}}}
    candidate = {
        "$id": "same",
        "properties": {
            "a": {"type": "string"},
            "opt": {"type": "string"},
            "req": {"type": "number"},
        },
        "required": ["req"],
    }
    report = compare(released, candidate)
    assert {c.verdict for c in report.changes} == {Verdict.MINOR, Verdict.MAJOR}, str(report)
    assert report.verdict is Verdict.MAJOR, str(report)
    assert not report.keeps_its_id


def test_a_nested_id_change_is_breaking() -> None:
    """`$id` was only compared at the root, and the unknown-keyword sweep skips it.

    So a `$id` changed inside `$defs` was checked by nothing and came back
    IDENTICAL with zero changes. It is not cosmetic: a nested `$id` moves the base
    URI that relative `$ref`s beneath it resolve against.
    """
    released = {"$id": "r", "$defs": {"Foo": {"$id": "https://x/foo/v1", "type": "object"}}}
    candidate = {"$id": "r", "$defs": {"Foo": {"$id": "https://x/foo/v2", "type": "object"}}}
    report = compare(released, candidate)
    assert report.verdict is Verdict.MAJOR, str(report)


def test_a_malformed_properties_is_reported_not_skipped() -> None:
    """`_compare_properties` returned silently on a non-mapping, and `properties`
    is in the unknown-keyword skip-list because that function is supposed to own
    it. Net effect: an entire property set could appear from nowhere and the report
    said IDENTICAL."""
    report = compare(
        {"$id": "r", "properties": "not-a-mapping"},
        {"$id": "c", "properties": {"a": {"type": "string"}}},
    )
    assert report.verdict is Verdict.MAJOR, str(report)


def test_removing_true_from_an_enum_containing_one_is_breaking() -> None:
    """`v not in new_enum` uses `==`, and `True == 1`. Removing `true` from
    `[1, 2, true]` therefore reported no change at all — a released name stopped
    being accepted and the verdict was IDENTICAL."""
    report = compare({"$id": "r", "enum": [1, 2, True]}, {"$id": "r", "enum": [1, 2]})
    assert report.verdict is Verdict.MAJOR, str(report)


def test_a_required_that_is_a_string_is_reported() -> None:
    """`set("id")` is `{'i', 'd'}`. A schema written `required: "id"` was read as
    two single-character member names, and a real new property called `"i"` would
    then be misreported as newly required."""
    report = compare(
        {"$id": "r", "required": "id", "properties": {"id": {"type": "string"}}},
        {"$id": "r", "required": ["id"], "properties": {"id": {"type": "string"}}},
    )
    assert report.verdict is Verdict.MAJOR, str(report)


def test_the_severity_rule_does_not_depend_on_enum_ordering() -> None:
    """The control that keeps the fix from being undone.

    `Verdict` deliberately defines no ordering now. If someone re-adds comparison
    operators to make `max()` work again, this test does not care — but the two
    assertions below pin the behaviour that matters, so a regression to
    string-ordered severity fails here rather than in a release six weeks later.
    """
    minor_only = compare(
        {"$id": "r", "properties": {}}, {"$id": "r", "properties": {"b": {"type": "string"}}}
    )
    assert minor_only.verdict is Verdict.MINOR and minor_only.keeps_its_id

    major_only = compare(
        {"$id": "r", "properties": {"a": {"type": "string"}}}, {"$id": "r", "properties": {}}
    )
    assert major_only.verdict is Verdict.MAJOR and not major_only.keeps_its_id

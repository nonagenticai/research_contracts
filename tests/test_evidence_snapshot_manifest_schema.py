"""Gates over ``urn:datacompany:evidence-snapshot-manifest:1``.

WHY THIS SUITE EXISTS. Document 14 ER-007 requires that '8808', '8813' and '8811' retrieve a
snapshot's metadata and authorized artifact refs, pin the snapshot ID/hash, never dereference
``latest``, and reconstruct byte-identical canonical JSON. The released manifest document is
the grammar those four promises are made in; this module is the only place that grammar is
checked against a body rather than described in prose. Without it the document's six recorded
AUTHORING DECISIONS are commentary: a ``$comment`` enforces nothing, and the failure mode of
an unenforced manifest grammar is not a validation error but a REPRODUCIBILITY failure in a
scientific run, discovered by whoever tries to re-derive a published result months later.

WHAT IT IS NOT. It does not pin any producer's member set. Evidence Review 8810 has no
appraisal and no terminology table today, so the manifests it emits carry three member kinds
of the six document 14 lists -- a PRODUCER gap recorded against ER-007, not a gap in this
grammar. Pinning three kinds here would freeze that producer gap into the released contract.
The producer-side pins belong in ``evidence_review_service``.

WHAT IT DOES PIN. The composition. The document is ``allOf [ immutable-version:1 ,
#/$defs/snapshot_fields ]`` sealed with ``unevaluatedProperties: false``, so a valid instance
carries the immutable-version keys AND the snapshot keys and nothing else. Every test below
starts from one whole body and mutates exactly one thing, because a fixture assembled per test
can drift into asserting a shape no producer would ever emit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import canonical_schemas, validate_instance

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "manifests" / "evidence-snapshot-manifest.v1.schema.json"

MANIFEST = "urn:datacompany:evidence-snapshot-manifest:1"

#: The pin fields ``urn:datacompany:pinned-version-ref:1`` requires of every member, composed from
#: its ``identity_ref_fields`` and its ``#/$defs/pin_fields``. Listed here as a closed tuple so
#: that a member field silently dropped from either ``required`` list is a red test rather than
#: a manifest that admits an under-specified pin -- which is exactly the "owner-free
#: {id, version} pair" that document 16 section 3.3 forbids.
PIN_FIELDS = (
    "owner_context",
    "entity_type",
    "entity_id",
    "resource_scope",
    "version_id",
    "version_number",
    "schema_ref",
    "content_hash",
    "resolved_at",
)

#: The four members ``#/$defs/snapshot_artifact`` requires. ``artifact_ref`` and
#: ``serializer_version`` are deliberately absent: both are optional in the released document.
ARTIFACT_REQUIRED = ("artifact_kind", "media_type", "payload_digest", "byte_size")

#: The six recorded design decisions, by the exact heading the document spells them with.
AUTHORING_DECISIONS = tuple(f"AUTHORING DECISION {n}" for n in range(1, 7))


def member() -> dict[str, Any]:
    """One pinned evidence version, as ``evidence_review_service`` would name it.

    A function, not a constant, so every mutation below starts from an unmutated pin -- the
    same reason the envelope and flow-ledger suites build their bodies the same way. Sharing
    one dict would let a mutation in one test leak into the next and turn a real refusal into
    a coincidence.

    Tenant-scoped on purpose: ``resource_scope_conditional`` has two arms and the tenant arm
    is the one that requires an extra field, so a tenant-scoped baseline is the one from which
    BOTH arms can be reached by a single deletion or a single substitution.
    """
    return {
        "owner_context": "evidence-review",
        "entity_type": "evidence_object",
        "entity_id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
        "resource_scope": "tenant",
        "resource_tenant_id": "b6f2c1d4-3e5a-4c7b-9d81-2f4a6c8e0b13",
        "version_id": "2b3c4d5e-6f70-4b8c-9d0e-1f2a3b4c5d6e",
        "version_number": 3,
        "schema_ref": "urn:datacompany:evidence-object-version:1",
        "content_hash": "sha256:" + "1" * 64,
        "resolved_at": "2026-09-02T11:14:07Z",
    }


def manifest() -> dict[str, Any]:
    """One whole snapshot manifest, minimal: every required key and no optional one.

    Minimal rather than maximal because the sealed boundary is what this document adds over
    its two parents, and a maximal body cannot distinguish "this key is accepted" from "this
    key is required". The optional keys (``protocol_pin``, ``corpus_pin``, ``artifacts``) are
    added back explicitly by the tests that are about them.

    ``version_number`` is 1, so ``supersedes_version_id`` MUST be absent -- see the
    supersession pair below. Both keys required by ``immutable-version``'s own root
    (``version_id`` and ``content_hash``) are present: they are easy to miss because they are
    required at that document's root rather than inside ``#/$defs/version_fields``, and a
    fixture that omitted them would make every negative test below pass for the wrong reason.
    """
    return {
        "version_id": "3c4d5e6f-7081-4c9d-8e0f-2a3b4c5d6e7f",
        "entity_id": "4d5e6f70-8192-4d0e-9f10-3b4c5d6e7f80",
        "version_number": 1,
        "schema_ref": MANIFEST,
        "content_hash": "sha256:" + "0" * 64,
        "created_at": "2026-09-02T11:20:00Z",
        "created_by": "service:evidence-review",
        "review_id": "7c67fcdf-c60e-45d8-9d46-a35189c0ea11",
        "intended_use": "publication_run",
        "members": [member()],
        "member_count": 1,
        "member_manifest_hash": "sha256:" + "a" * 64,
    }


def artifact() -> dict[str, Any]:
    """One portable rendering of the manifest, carrying only its required members."""
    return {
        "artifact_kind": "canonical_json",
        "media_type": "application/json",
        "payload_digest": "sha256:" + "b" * 64,
        "byte_size": 4096,
    }


def with_artifacts(*renderings: dict[str, Any]) -> dict[str, Any]:
    return manifest() | {"artifacts": list(renderings)}


def has_key(node: Any, key: str) -> bool:
    """Whether ``key`` appears anywhere in a JSON document, at any depth."""
    if isinstance(node, dict):
        return key in node or any(has_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(has_key(value, key) for value in node)
    return False


# ============================================================== 1. release integrity ===


def test_the_document_is_registered_under_its_own_id() -> None:
    """Non-vacuity control for everything below.

    ``manifests`` is one name in the CLOSED ``FOUNDATION_SCHEMA_DIRS`` tuple, and the registry
    reads only the names in it. A document authored into an unlisted directory is present on
    disk and invisible to every resolution -- so this asserts the file actually reached the
    registry, rather than leaving the whole suite to fail later with an error about an unknown
    ``schema_ref`` that names the wrong cause.
    """
    schema = canonical_schemas().get(MANIFEST)
    assert schema is not None, f"{MANIFEST} is not in the released registry"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_registered_copy_is_the_committed_file() -> None:
    """The registry globs a directory; nothing else guarantees the file on disk is the
    document a consumer resolves. Without this, an edit to the committed file could be
    validated against a stale registered copy and read as a passing change."""
    on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert on_disk == canonical_schemas()[MANIFEST]


# ============================================================== 2. a whole manifest ===


def test_a_minimal_whole_manifest_validates() -> None:
    """The positive control the rest of the suite rests on.

    A failure here means the composition itself is wrong -- the required-key union of
    ``immutable-version`` and ``#/$defs/snapshot_fields`` is not what a producer can actually
    build -- and every refusal test below would then be refusing for a reason it did not name.
    """
    body = manifest()
    assert validate_instance(body, MANIFEST) == [], (
        f"a minimal whole manifest was refused: {validate_instance(body, MANIFEST)}"
    )


def test_an_unknown_top_level_property_is_refused() -> None:
    """``unevaluatedProperties: false`` is what seals the composed boundary.

    ``additionalProperties`` could not do this job: it cannot see the properties contributed
    by ``$ref``, so every key inherited from ``immutable-version`` would be rejected. Without
    the seal a manifest grows private fields that one producer writes and one consumer reads,
    and the grammar stops being the thing both sides agree on -- the exact disagreement this
    document exists to prevent.
    """
    body = manifest() | {"cached_at": "2026-09-02T11:30:00Z"}
    assert validate_instance(body, MANIFEST) != [], (
        f"an unknown top-level property was accepted, so the boundary is not sealed: {body}"
    )


# ============================================================== 3. the version pin ===


def test_the_schema_ref_is_pinned_to_this_document() -> None:
    """Authoring decision 5. A snapshot manifest wraps a FIXED shape, so ``schema_ref`` is
    narrowed to a const of this document's own ``$id`` -- unlike the inclusion-set-export
    documents, which wrap a varying payload and must leave it open. Read off the schema rather
    than inferred from a refusal, so that a const removed by an edit is named directly."""
    narrowed = canonical_schemas()[MANIFEST]["$defs"]["snapshot_fields"]["properties"]
    assert narrowed["schema_ref"]["const"] == MANIFEST


def test_a_manifest_claiming_a_different_grammar_is_refused() -> None:
    """The executable half of authoring decision 5. A consumer reading a mixed stream of
    manifests must be able to tell which grammar it holds without guessing from the caller; a
    body free to name any ``schema_ref`` makes that field an unverified hint."""
    body = manifest() | {"schema_ref": "urn:datacompany:evidence-snapshot-manifest:2"}
    assert validate_instance(body, MANIFEST) != [], (
        f"a manifest claiming a different grammar validated as this one: {body}"
    )


# ============================================================== 4. the impact link ===


def test_a_first_version_must_not_name_a_predecessor() -> None:
    """Authoring decision 1, the ``then`` arm of ``immutable-version``'s supersession rule.

    A version 1 that names a predecessor is claiming an impact link to something that, by its
    own version number, cannot exist. Accepting it would let a lineage be walked backwards
    into a snapshot nobody created.
    """
    body = manifest() | {
        "version_number": 1,
        "supersedes_version_id": "5e6f7081-9203-4e1f-8021-4c5d6e7f8091",
    }
    assert validate_instance(body, MANIFEST) != [], (
        f"version 1 was allowed to name a predecessor: {body}"
    )


def test_a_later_version_must_name_its_predecessor() -> None:
    """Authoring decision 1, the ``else`` arm -- and the reason this document adds no second
    ``impact_link`` field.

    Document 14 requires that changed evidence creates a new snapshot WITH an impact link.
    ``supersedes_version_id`` already IS that link, so the conditional inherited from
    ``immutable-version`` is the whole rule. Both arms are asserted because a conditional
    verified in one direction only is half a gate: a ``then`` that fired for every version
    would pass a one-armed test while silently forbidding every correction.
    """
    orphan = manifest() | {"version_number": 2}
    assert validate_instance(orphan, MANIFEST) != [], (
        f"version 2 was accepted with no impact link back to its predecessor: {orphan}"
    )
    linked = orphan | {"supersedes_version_id": "5e6f7081-9203-4e1f-8021-4c5d6e7f8091"}
    assert validate_instance(linked, MANIFEST) == [], (
        f"a correctly linked version 2 was refused: {validate_instance(linked, MANIFEST)}"
    )


# ============================================================== 5. members are a set ===


def test_a_duplicate_member_is_refused() -> None:
    """Authoring decisions 2 and 3. ``members`` composes ``#/$defs/set_of_pins``, which brings
    ``uniqueItems`` and the released order key with it.

    A duplicate is not a harmless repetition here: ``member_count`` and
    ``member_manifest_hash`` are both computed over this array, so a repeated member changes
    the count and the digest of a snapshot that admits exactly the same evidence. Two
    producers holding identical evidence would then publish different manifests.
    """
    body = manifest() | {"members": [member(), member()], "member_count": 2}
    assert validate_instance(body, MANIFEST) != [], (
        f"a duplicated member was accepted, so members is not a set: {body}"
    )


@pytest.mark.parametrize("field", PIN_FIELDS)
def test_a_member_missing_a_pin_field_is_refused(field: str) -> None:
    """Every member must be a WHOLE pin. Parametrized rather than asserted once, so a member
    set that stopped requiring one particular field names that field.

    Document 16 section 3.3 is explicit that no bare UUID, no ``latest`` alias and no
    owner-free ``{id, version}`` pair may stand in for a pin. A member short one field is one
    of those degenerate shapes: a consumer that receives it cannot resolve the exact version
    it was entitled to read, which is the whole point of a snapshot.
    """
    incomplete = member()
    del incomplete[field]
    body = manifest() | {"members": [incomplete]}
    assert validate_instance(body, MANIFEST) != [], (
        f"a member missing the pin field {field!r} was accepted: {incomplete}"
    )


def test_a_tenant_scoped_member_without_a_tenant_id_is_refused() -> None:
    """The ``then`` arm of ``resource_scope_conditional``. A tenant-scoped pin with no tenant
    is a reference into an unnamed tenant's data; the conditional exists so that no nullable
    tenant column can stand in for it, at any nesting depth."""
    unscoped = member()
    del unscoped["resource_tenant_id"]
    body = manifest() | {"members": [unscoped]}
    assert validate_instance(body, MANIFEST) != [], (
        f"a tenant-scoped member with no resource_tenant_id was accepted: {unscoped}"
    )


def test_a_global_scoped_member_carrying_a_tenant_id_is_refused() -> None:
    """The ``else`` arm of the same conditional, and the reason both arms are tested.

    A global-canon member that also names a tenant is ambiguous about which of the two scopes
    governs it, and a reader resolving the pin has no rule for choosing. A gate checked on the
    tenant side alone would pass while permitting exactly this.
    """
    mixed = member() | {"resource_scope": "global"}
    body = manifest() | {"members": [mixed]}
    assert validate_instance(body, MANIFEST) != [], (
        f"a global-scoped member carrying a resource_tenant_id was accepted: {mixed}"
    )


# ============================================================== 6. the member digest ===


def test_a_well_formed_member_manifest_hash_is_accepted() -> None:
    """The other half of the digest gate. A test that only proved refusals would leave an
    over-narrow pattern -- one that rejects legitimate digests -- completely invisible."""
    body = manifest() | {"member_manifest_hash": "sha256:" + "0123456789abcdef" * 4}
    assert validate_instance(body, MANIFEST) == [], (
        f"a well-formed member_manifest_hash was refused: {validate_instance(body, MANIFEST)}"
    )


@pytest.mark.parametrize(
    ("value", "why"),
    [
        (
            "sha256:" + "A" * 64,
            "upper-case hex: the released form is lower-case, and a "
            "case-insensitive digest has two spellings for one value",
        ),
        ("sha256:" + "a" * 63, "truncated: 63 hex characters is not a sha-256 digest"),
    ],
)
def test_a_malformed_member_manifest_hash_is_refused(value: str, why: str) -> None:
    """Authoring decision 4 depends on this field being comparable byte for byte.

    The consumer recomputes the digest over the sorted members and compares. That comparison
    is only a check if both sides spell a digest the same way: an upper-case variant compares
    unequal to the identical digest in lower case, so a manifest that is in fact intact would
    be reported as corrupt -- and a truncated value has no chance of matching anything at all
    while still LOOKING like a digest to a human reading the record.
    """
    body = manifest() | {"member_manifest_hash": value}
    assert validate_instance(body, MANIFEST) != [], f"{value!r} was accepted -- {why}"


# ============================================================== 7. artifacts ===


def test_a_whole_artifact_validates() -> None:
    """Positive control for the artifact shape, so the four refusals below are refusals of the
    thing they name rather than of the artifact array itself."""
    body = with_artifacts(artifact())
    assert validate_instance(body, MANIFEST) == [], (
        f"a whole artifact was refused: {validate_instance(body, MANIFEST)}"
    )


@pytest.mark.parametrize("field", ARTIFACT_REQUIRED)
def test_an_artifact_missing_a_required_member_is_refused(field: str) -> None:
    """An artifact is a claim that these exact bytes render this exact manifest.

    Each of the four carries part of that claim: ``artifact_kind`` says what it is,
    ``media_type`` how to read it, ``payload_digest`` (authoring decision 6 -- over raw bytes,
    never interchangeable with a content hash) whether it arrived intact, and ``byte_size``
    whether it arrived whole. Drop any one and the reference stops being verifiable, which
    makes it a pointer rather than evidence.
    """
    incomplete = artifact()
    del incomplete[field]
    body = with_artifacts(incomplete)
    assert validate_instance(body, MANIFEST) != [], (
        f"an artifact missing {field!r} was accepted: {incomplete}"
    )


def test_an_unknown_artifact_property_is_refused() -> None:
    """``additionalProperties: false`` on ``#/$defs/snapshot_artifact``.

    The artifact object is a closed list precisely because a manifest is the thing most likely
    to be copied into a cache, a catalogue or a report. An open artifact object is where a
    storage key, a signed URL or a fragment of licensed content would arrive -- and document
    16 section 3.5 warns that even the HASH of licensed content is scope-controlled.
    """
    smuggled = artifact() | {"storage_bucket": "s3://evidence-exports"}
    body = with_artifacts(smuggled)
    assert validate_instance(body, MANIFEST) != [], (
        f"an unknown artifact property was accepted: {smuggled}"
    )


@pytest.mark.parametrize(
    ("media_type", "why"),
    [
        (
            "Text/CSV",
            "upper-case type: the released pattern is lower-case on the left of the "
            "slash, so one media type would otherwise have several spellings",
        ),
        ("application", "no subtype: a bare type names no concrete rendering"),
        (
            "application/json; charset=utf-8",
            "parameters: the released field is the media type "
            "itself, not a full Content-Type header",
        ),
    ],
)
def test_a_malformed_media_type_is_refused(media_type: str, why: str) -> None:
    """``media_type`` is how a consumer decides which parser to hand the bytes to.

    Document 14's completion evidence is byte-identical reconstruction, which is unreachable
    if two producers spell the same rendering two different ways: the parser choice becomes
    caller-specific, and the same artifact reconstructs differently depending on who read it.
    """
    body = with_artifacts(artifact() | {"media_type": media_type})
    assert validate_instance(body, MANIFEST) != [], f"{media_type!r} was accepted -- {why}"


# ============================================================== 8. the design record ===


def test_the_document_declares_no_cross_field_rule() -> None:
    """Authoring decision 4, asserted as an ABSENCE -- which is the unusual half of this suite
    and the reason it is spelled out here.

    ``member_count`` and ``member_manifest_hash`` are redundant against ``members`` by
    construction, and the obvious move would be to declare that redundancy as an
    ``x-datacompany-cross-field`` rule. It cannot be done today: the released operator set is
    ``disjoint``, ``equal``, ``equal_when_both_present``, ``half_open_interval`` and
    ``unique_by``, and NONE of them states a cardinality. Adding a ``count_equals`` operator to
    carry one manifest would extend the FOUNDATION cross-field vocabulary as a side effect of
    an evidence-tier release -- a foundation change smuggled in under an evidence change, in
    the wrong order and reviewed by the wrong people.

    The redundancy is not lost by leaving it undeclared. The consumer recomputes both the
    count and the digest, which is strictly stronger than a declarative equality: it catches a
    member whose CONTENT changed, not merely one that went missing.

    So the property under test is that this document declares no such rule at any depth. If a
    future author needs one, this test is the place that says why the answer is not "just add
    an operator", and it should be changed deliberately rather than deleted quietly.
    """
    document = canonical_schemas()[MANIFEST]
    assert not has_key(document, "x-datacompany-cross-field"), (
        "this document now declares an x-datacompany-cross-field rule; authoring decision 4 "
        "records that a cardinality operator does not exist in the released vocabulary, so "
        "adding one here extends the foundation vocabulary from an evidence release"
    )


def test_the_root_comment_names_all_six_authoring_decisions() -> None:
    """A cheap guard that the design record was not silently trimmed.

    Every gate above is the executable form of one of the six recorded decisions, and the
    ``$comment`` is where the REASON for each lives -- why the document composes rather than
    respells ``immutable-version``, why one ``members`` array and not six, why the set brings
    its own order key, why the redundancy is not a cross-field rule, why ``schema_ref`` is a
    const here but open in the export documents, and why an artifact carries
    ``payload_digest`` and never ``content_hash``. A reviewer shortening the comment removes
    the only record of those trade-offs while every test still passes, so the presence of the
    record is asserted directly rather than assumed.
    """
    comment = canonical_schemas()[MANIFEST]["$comment"]
    present = tuple(heading for heading in AUTHORING_DECISIONS if heading in comment)
    assert present == AUTHORING_DECISIONS, (
        f"the root $comment names {present}, expected {AUTHORING_DECISIONS}"
    )

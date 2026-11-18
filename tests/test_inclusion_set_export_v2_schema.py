"""``inclusion-set-export:2`` must make the seal item-sensitive, not merely mention items.

``:1`` sealed the envelope and left the cargo loose. That was not an oversight in the
abstract — it is a measured, reproduced defect in the consuming service, pinned there as a
PASSING test (``evidence_review_service``,
``tests/security/test_export_verification_outcomes.py``,
``test_rewriting_a_record_in_place_still_verifies_and_that_is_the_gap_items_hash_closes``):
rewrite the title of an included record in the stored payload, recompute the
``payload_digest`` sibling column over the edited bytes, leave the record COUNT alone, and
every check the verifier performs reproduces. ``verified: true``, for an inclusion set naming
a study nobody screened.

``included_count`` and ``omissions_count`` are in the sealed manifest and do catch a record
being **added or removed**. Nothing caught one being **substituted**, because a count cannot
see a substitution.

So this suite asserts the delta and only the delta — ``:1``'s own suite still covers the
thirteen inherited members, and duplicating it here would mean two places to update and one
of them going stale. What is proven here:

1. **The member exists, is required, and is hashed.** Not excluded, not opaque: if
   ``items_hash`` were dropped from the hash view it would be decoration, and the whole
   version would be ceremony.
2. **The property.** Two exports whose items differ by one character in one title, and which
   agree on every other manifest member including both counts, hash **differently**. With the
   negative control that the identical items hash identically — otherwise the test would pass
   against an implementation that simply salts every digest.
3. **Array order is part of the hash**, because the document says it is and a consumer that
   re-sorted would compute a mismatch and read a sound export as forged.
4. **``:1`` genuinely could not carry this**, which is the justification for spending a
   schema version. Asserted, not asserted-by-assumption: ``:1`` REFUSES the member.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from test_inclusion_set_export_schema import manifest as v1_manifest

from research_contracts.canonical import (
    SchemaValidationError,
    build_hash_view,
    canonical_schemas,
    canonical_sha256,
    compute_content_hash,
    derive_hash_profile,
    validate_instance,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "evidence" / "inclusion-set-export.v2.schema.json"

EXPORT_V1 = "urn:datacompany:inclusion-set-export:1"
EXPORT = "urn:datacompany:inclusion-set-export:2"

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def items() -> dict[str, Any]:
    """The two item arrays, in the producing service's own shapes.

    Three included records and two omissions — one screened-out record and one quarantined
    import row, because the omissions array is heterogeneous by construction and a fixture
    carrying only one shape would not exercise what the producer actually emits.

    A function, not a constant, for the same reason ``:1``'s fixture is one: every mutation
    below starts from an unmutated object, so the order the tests run in is not part of what
    they assert.
    """
    return {
        "included": [
            {
                "review_record_id": "11111111-1111-4111-8111-111111111111",
                "review_record_version_id": "aaaaaaaa-1111-4111-8111-111111111111",
                "content_hash": "sha256:" + "1" * 64,
                "record_type": "journal_article",
                "title": "Tocilizumab in hospitalised patients with severe COVID-19",
                "publication_year": 2021,
                "doi": "10.1056/NEJMoa2028836",
                "pmid": "33085857",
            },
            {
                "review_record_id": "22222222-2222-4222-8222-222222222222",
                "review_record_version_id": "aaaaaaaa-2222-4222-8222-222222222222",
                "content_hash": "sha256:" + "2" * 64,
                "record_type": "journal_article",
                "title": "Interleukin-6 receptor antagonists in critically ill patients",
                "publication_year": 2021,
                "doi": "10.1056/NEJMoa2100433",
                "pmid": "33631065",
            },
            {
                "review_record_id": "33333333-3333-4333-8333-333333333333",
                "review_record_version_id": "aaaaaaaa-3333-4333-8333-333333333333",
                "content_hash": "sha256:" + "3" * 64,
                "record_type": "preprint",
                "title": "A trial with no DOI and no PMID",
                "publication_year": 2020,
                "doi": None,
                "pmid": None,
            },
        ],
        "omissions": [
            {
                "review_record_id": "44444444-4444-4444-8444-444444444444",
                "bucket": "excluded",
                "exclusion_reason_code": "wrong_population",
                "adjudicated": False,
            },
            {
                "import_row_id": "55555555-5555-4555-8555-555555555555",
                "bucket": "quarantined",
                "quarantine_reason": "no_title",
            },
        ],
    }


def manifest(item_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """``:1``'s realistic manifest, carried forward with ``items_hash`` over ``item_doc``.

    Composed from ``:1``'s fixture rather than respelled, so that a change to the inherited
    member set breaks this suite instead of quietly leaving it testing a shape ``:2`` no
    longer inherits.

    ``included_count`` and ``omissions_count`` are recomputed from the item document, because
    a fixture whose sealed counts disagreed with its own arrays could not have been produced
    and would make every assertion below a statement about an impossible export.
    """
    doc = item_doc if item_doc is not None else items()
    instance = v1_manifest()
    instance["schema_ref"] = EXPORT
    instance["included_count"] = len(doc["included"])
    instance["omissions_count"] = len(doc["omissions"])
    instance["items_hash"] = canonical_sha256(doc)
    return instance


def without(member: str) -> dict[str, Any]:
    instance = manifest()
    del instance[member]
    return instance


# ================================================= 1. the document is really released ===


def test_the_v2_export_schema_is_registered_under_the_urn_the_engine_can_resolve() -> None:
    """Registration is the whole difference between the sealed path and the fallback."""
    schema = canonical_schemas().get(EXPORT)
    assert schema is not None, f"{EXPORT} is not in the released registry"
    assert schema["$id"] == EXPORT
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_committed_file_is_the_registered_document() -> None:
    """A registry serving something other than the reviewed file would seal the wrong shape."""
    assert json.loads(SCHEMA_PATH.read_text()) == canonical_schemas()[EXPORT]


def test_a_realistic_v2_manifest_validates_derives_and_hashes() -> None:
    """The preferred path, end to end, on an instance the producer could really emit."""
    instance = manifest()
    assert validate_instance(instance, EXPORT) == []
    profile = derive_hash_profile(EXPORT)
    assert profile["schema_ref"] == EXPORT
    assert DIGEST.match(compute_content_hash(instance, EXPORT))


# ============================================= 2. items_hash is required and is hashed ===


def test_items_hash_is_required() -> None:
    """Optional would mean a producer may legally seal an export that binds nothing."""
    assert validate_instance(without("items_hash"), EXPORT) != []
    with pytest.raises(SchemaValidationError):
        compute_content_hash(without("items_hash"), EXPORT)


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("0" * 64, id="bare-hex-without-the-algorithm"),
        pytest.param("sha256:" + "0" * 63, id="one-hex-digit-short"),
        pytest.param("sha256:" + "0" * 65, id="one-hex-digit-long"),
        pytest.param("sha256:" + "A" * 64, id="uppercase-hex"),
        pytest.param("sha1:" + "0" * 40, id="a-different-algorithm"),
        pytest.param("", id="empty"),
    ],
)
def test_a_malformed_items_hash_is_refused(bad: str) -> None:
    """The grammar arrives by ``$ref`` from the released ``content_hash`` and must bite.

    A digest-shaped string that is not a digest is the failure mode a hand-written consumer
    produces, and accepting it would put an unverifiable value inside a sealed manifest.
    """
    instance = manifest()
    instance["items_hash"] = bad
    with pytest.raises(SchemaValidationError):
        compute_content_hash(instance, EXPORT)


def test_items_hash_is_null_is_refused() -> None:
    """Required-and-nullable is the shape ``protocol_version_id`` has, and deliberately not this one."""
    instance = manifest()
    instance["items_hash"] = None
    with pytest.raises(SchemaValidationError):
        compute_content_hash(instance, EXPORT)


def test_items_hash_reaches_the_hash_view() -> None:
    """A declared member that the hash view dropped would be decoration, not a seal.

    This is the assertion that makes the rest of the suite mean something: every "the digest
    moved" test below would pass just as well against a profile that excluded ``items_hash``
    and happened to differ for another reason.
    """
    view = build_hash_view(manifest(), derive_hash_profile(EXPORT))
    assert "items_hash" in view
    assert view["items_hash"] == manifest()["items_hash"]


def test_the_manifest_is_still_sealed_against_undeclared_members() -> None:
    """``additionalProperties: false`` survived the widening — the version added ONE member."""
    instance = manifest()
    instance["payload_digest"] = "sha256:" + "f" * 64
    with pytest.raises(SchemaValidationError):
        compute_content_hash(instance, EXPORT)


# ==================================== 3. the property: the seal now moves with the items ===


def test_substituting_a_record_moves_the_manifest_digest() -> None:
    """THE POINT OF THE VERSION.

    One character changes in one title. Every other manifest member is identical, including
    both counts — which is precisely the tamper ``:1`` could not see, because a count cannot
    detect a substitution.
    """
    honest = items()
    substituted = items()
    substituted["included"][0]["title"] = (
        "Tocilizumab in hospitalised patients with severe COVID-20"
    )

    a, b = manifest(honest), manifest(substituted)
    assert a["included_count"] == b["included_count"]
    assert a["omissions_count"] == b["omissions_count"]
    assert a["items_hash"] != b["items_hash"], "the items hash did not move; the rest is void"
    assert compute_content_hash(a, EXPORT) != compute_content_hash(b, EXPORT)


def test_the_identical_items_hash_identically() -> None:
    """The negative control the test above needs.

    Without it, an implementation that salted every digest with fresh randomness would pass
    ``test_substituting_a_record_moves_the_manifest_digest`` while sealing nothing at all.
    """
    assert canonical_sha256(items()) == canonical_sha256(items())
    assert compute_content_hash(manifest(), EXPORT) == compute_content_hash(manifest(), EXPORT)


def test_the_member_order_of_the_items_document_does_not_matter() -> None:
    """RFC 8785 sorts object members, so ``{included, omissions}`` is one document, not two.

    Producer and consumer build that wrapper independently; if insertion order leaked into
    the digest, every consumer written in a language with ordered maps would disagree with a
    correct export.
    """
    doc = items()
    reversed_members = {"omissions": doc["omissions"], "included": doc["included"]}
    assert canonical_sha256(reversed_members) == canonical_sha256(doc)


def test_the_order_of_the_arrays_themselves_does_matter() -> None:
    """Stated in the document, asserted here, because it is a real consumer trap.

    The producer emits ``included`` sorted by ``review_record_id``; a consumer that re-sorted
    by anything else — or that hashed a set — would compute a mismatching digest from
    byte-identical content and report a sound export as tampered. The rule is: hash what you
    received.
    """
    doc = items()
    swapped = items()
    swapped["included"][0], swapped["included"][1] = swapped["included"][1], swapped["included"][0]
    assert canonical_sha256(swapped) != canonical_sha256(doc)


def test_an_omission_removed_moves_the_items_hash_even_before_the_counts_notice() -> None:
    """Omissions are sealed exactly as hard as inclusions.

    ``ER-009.3`` requires every omission to be enumerated; an export that quietly dropped one
    while leaving ``omissions_count`` alone is the same substitution defect pointed at the
    other array, and it is the one a reader is least likely to check by hand.
    """
    doc = items()
    dropped = items()
    dropped["omissions"] = dropped["omissions"][:1]
    assert canonical_sha256(dropped) != canonical_sha256(doc)


# ================================= 4. why this had to be a version rather than a patch ===


def test_version_1_refuses_items_hash_which_is_why_2_exists() -> None:
    """The justification for spending a schema version, asserted rather than assumed.

    ``:1`` is released with ``additionalProperties: false``. Widening it in place would have
    silently changed what every hash already sealed under it meant.
    """
    instance = v1_manifest()
    instance["items_hash"] = "sha256:" + "d" * 64
    with pytest.raises(SchemaValidationError):
        compute_content_hash(instance, EXPORT_V1)


def test_v2_is_v1_plus_exactly_one_member() -> None:
    """A drift guard over the inherited shape.

    ``:2`` is a widening and nothing else. If a later edit adds, removes or renames an
    inherited member here, this fails rather than letting the two documents diverge into
    versions that no longer describe the same artefact.
    """
    v1 = canonical_schemas()[EXPORT_V1]
    v2 = canonical_schemas()[EXPORT]
    assert set(v2["properties"]) - set(v1["properties"]) == {"items_hash"}
    assert set(v1["properties"]) - set(v2["properties"]) == set()
    assert set(v2["required"]) - set(v1["required"]) == {"items_hash"}
    assert v2["$defs"] == v1["$defs"], (
        "the counts block and the tally bound are inherited unchanged"
    )


def test_the_two_versions_hash_the_same_export_differently() -> None:
    """Sealing under ``:2`` is a different act, and the digest says so.

    Not a defect: a ``:1`` digest attests less. The two must never be compared, and a
    consumer that stored one and re-derived the other would otherwise read the version bump
    itself as tampering.
    """
    as_v2 = manifest()
    as_v1 = v1_manifest()
    as_v1["included_count"] = as_v2["included_count"]
    as_v1["omissions_count"] = as_v2["omissions_count"]
    assert compute_content_hash(as_v1, EXPORT_V1) != compute_content_hash(as_v2, EXPORT)

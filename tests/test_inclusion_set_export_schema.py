"""``inclusion-set-export:1`` must actually seal an export, not merely exist.

The producing service (``evidence_review_service``, ``src/application/services/flow.py``)
seals its inclusion-set export by calling ``compute_content_hash(manifest, schema_ref)`` and
falls back to bare ``canonical_sha256`` on ANY exception. No such schema was registered here,
so every resolution raised and the fallback fired on every export ever produced: the
structural validation, the hash view, the absent-versus-null rule and the refusal of an
unacceptable instance were all skipped, silently, while the product claimed a sealed
contract. A schema that is merely committed changes none of that.

So this suite asserts the two halves that together mean "sealed", each with the control that
makes it falsifiable:

1. **It accepts.** A realistic manifest -- built from the producer's own field list --
   validates, derives a hash profile, and hashes to ``sha256:<64 hex>``. The preferred path
   runs to completion, which is the thing that had never once happened.
2. **It refuses.** A missing required member, a wrong type, an undeclared member and a
   malformed digest each RAISE. A contract that accepts everything seals nothing: the
   fallback already hashes any object at all, and a permissive schema would reproduce it
   with extra ceremony.

The opacity of ``/counts/exclusion_reasons`` gets its own control in both directions, because
it is the one authoring decision here that widens what may be hashed: it must admit dynamic
reason-code keys, the values must still reach the digest, and stripping the annotation must
make the same instance unhashable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import (
    SchemaValidationError,
    build_hash_view,
    canonical_schemas,
    canonical_sha256,
    compute_content_hash,
    derive_hash_profile,
    validate_instance,
)
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical.hash_view import UndeclaredPathError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "evidence" / "inclusion-set-export.v1.schema.json"

EXPORT = "urn:datacompany:inclusion-set-export:1"

#: The grammar ``derive_hash_profile`` demands of any ``schema_ref`` it stamps into a derived
#: manifest, restated from ``stable-identity:1#/$defs/schema_ref``. An HTTPS URL -- which is
#: what the producing service declared -- can never satisfy it, so this is the reason the
#: ``$id`` is a URN and not a style preference.
SCHEMA_REF_GRAMMAR = re.compile(r"^urn:datacompany:[a-z][a-z0-9-]*:[1-9][0-9]*$")

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def manifest() -> dict[str, Any]:
    """A realistic export manifest, in the producer's own member set.

    Built as a function rather than a module constant so that every mutation below starts
    from an unmutated object: a shared dict edited in place would make the order the tests
    happen to run in part of what they assert.

    The counts satisfy the producer's three conservation identities (120 = 4 + 6 + 110;
    110 = 10 + 100 + 0; 100 = 25 + 70 + 5) and ``not_yet_screened`` is zero, because an
    export is refused while any record is unscreened. A fixture that could not have been
    produced would prove the schema accepts something, but not that it accepts THIS.
    """
    return {
        "review_id": "6f1c2b1e-9d3a-4c77-8f2a-1b5e7c9d0a11",
        "tenant_id": "tenant-alpha",
        "flow_revision_number": 3,
        "protocol_version_id": "0a9b8c7d-6e5f-4a3b-8c2d-1e0f9a8b7c6d",
        "protocol_content_hash": "sha256:" + "a" * 64,
        "corpus_version_id": "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
        "member_manifest_hash": "sha256:" + "b" * 64,
        "counts": {
            "identified_total": 120,
            "quarantined": 4,
            "rejected": 6,
            "records_total": 110,
            "duplicates_removed": 10,
            "records_screened": 100,
            "not_yet_screened": 0,
            "included": 25,
            "excluded": 70,
            "uncertain": 5,
            "adjudicated": 8,
            "exclusion_reasons": {
                "wrong_population": 30,
                "wrong_outcome": 25,
                "not_a_trial": 15,
            },
        },
        "canonical_counts_hash": "sha256:" + "c" * 64,
        "included_count": 25,
        "omissions_count": 85,
        "shadow_mode": True,
        "schema_ref": EXPORT,
    }


def without(member: str) -> dict[str, Any]:
    instance = manifest()
    del instance[member]
    return instance


# ================================================= 1. the document is really released ===


def test_the_export_schema_is_registered_under_the_urn_the_engine_can_resolve() -> None:
    """Registration is the whole difference between the sealed path and the fallback."""
    schema = canonical_schemas().get(EXPORT)
    assert schema is not None, (
        f"{EXPORT} is not in the released registry, so compute_content_hash raises and the "
        "producing service falls back to an unvalidated bare digest"
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "InclusionSetExportV1"
    assert SCHEMA_REF_GRAMMAR.match(schema["$id"]), (
        "the $id does not match the grammar a derived hash profile requires of its "
        "schema_ref, so no profile could ever be derived for it"
    )


def test_the_committed_file_is_the_document_that_got_registered() -> None:
    """The registry globs a directory; this pins WHICH file answered.

    A schema dropped in a directory the registry does not glob is invisible, and the
    symptom -- ``unknown schema_ref`` -- is identical to not having written it at all.
    """
    assert SCHEMA_PATH.is_file(), SCHEMA_PATH
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$id"] == EXPORT
    assert SCHEMA_PATH.parent in registry_module.foundation_schema_dirs()


# ============================================================= 2. it accepts and seals ===


def test_a_realistic_manifest_validates_derives_a_profile_and_hashes() -> None:
    """THE proof. Every step of the ordered algorithm runs, and a digest comes out.

    ``compute_content_hash`` validates the instance, derives the hash profile from the
    schema's own annotations, builds the hash view and serializes it under RFC 8785. Any one
    of those raising is what the producing service has been swallowing.
    """
    assert validate_instance(manifest(), EXPORT) == []
    digest = compute_content_hash(manifest(), EXPORT)
    assert DIGEST.match(digest), digest


def test_the_seal_is_stable_under_member_reordering_and_moves_with_the_content() -> None:
    """A hash that ignores its input would satisfy the test above.

    Both directions: re-serializing the same facts in a different member order must not move
    the digest (that is what makes an export verifiable by a consumer who re-serializes it),
    and changing a fact must.
    """
    baseline = compute_content_hash(manifest(), EXPORT)

    reordered = dict(reversed(list(manifest().items())))
    assert list(reordered) != list(manifest()), "the reordering was a no-op"
    assert compute_content_hash(reordered, EXPORT) == baseline

    changed = manifest()
    changed["included_count"] = changed["included_count"] + 1
    assert compute_content_hash(changed, EXPORT) != baseline


def test_an_explicit_null_protocol_is_a_different_seal_from_a_populated_one() -> None:
    """``absent_vs_null`` is ``distinct``, so the nullable pair must be REQUIRED-and-nullable.

    A review with no active protocol emits explicit nulls. Those nulls are kept in the hash
    view and hashed, so they are a different digest from a populated protocol -- and the
    control below is what makes the declaration choice load-bearing rather than cosmetic:
    dropping the member entirely is refused, so "absent" and "null" can never collide into
    one instance that hashes two ways.
    """
    unprotocolled = manifest()
    unprotocolled["protocol_version_id"] = None
    unprotocolled["protocol_content_hash"] = None
    assert DIGEST.match(compute_content_hash(unprotocolled, EXPORT))
    assert compute_content_hash(unprotocolled, EXPORT) != compute_content_hash(manifest(), EXPORT)

    with pytest.raises(SchemaValidationError):
        compute_content_hash(without("protocol_version_id"), EXPORT)


# ==================================================================== 3. it refuses ===

REQUIRED_MEMBERS = (
    "review_id",
    "tenant_id",
    "flow_revision_number",
    "protocol_version_id",
    "protocol_content_hash",
    "corpus_version_id",
    "member_manifest_hash",
    "counts",
    "canonical_counts_hash",
    "included_count",
    "omissions_count",
    "shadow_mode",
    "schema_ref",
)


@pytest.mark.parametrize("member", REQUIRED_MEMBERS)
def test_a_manifest_missing_any_required_member_is_refused(member: str) -> None:
    """One member at a time, so a single over-broad refusal cannot stand in for thirteen."""
    with pytest.raises(SchemaValidationError):
        compute_content_hash(without(member), EXPORT)


#: One wrong value per member class the manifest carries: a UUID, an opaque tenant string, a
#: bounded integer, a digest, a boolean, the schema reference, the nested counts block, and a
#: tally inside it. Each is a value a careless producer really could emit.
WRONG_VALUES: tuple[tuple[str, Any], ...] = (
    ("review_id", "not-a-uuid"),
    ("review_id", 17),
    ("tenant_id", ""),
    ("tenant_id", None),
    ("flow_revision_number", 0),
    ("flow_revision_number", "3"),
    ("member_manifest_hash", "sha256:" + "A" * 64),
    ("member_manifest_hash", "b" * 64),
    ("canonical_counts_hash", None),
    ("included_count", -1),
    ("included_count", 25.5),
    ("shadow_mode", "true"),
    ("schema_ref", "https://contracts.nonagentic.ai/evidence/inclusion-set-export.v1.schema.json"),
    ("counts", {}),
    ("counts", None),
)


@pytest.mark.parametrize(("member", "value"), WRONG_VALUES)
def test_a_manifest_with_a_wrong_typed_member_is_refused(member: str, value: Any) -> None:
    instance = manifest()
    instance[member] = value
    with pytest.raises(SchemaValidationError):
        compute_content_hash(instance, EXPORT)


def test_the_uppercase_digest_control_is_a_real_refusal_not_a_coincidence() -> None:
    """The lowercase original of the mutation above is accepted, so the pair discriminates."""
    assert DIGEST.match(compute_content_hash(manifest(), EXPORT))


@pytest.mark.parametrize(
    ("pointer", "member"),
    [((), "included"), ((), "payload"), (("counts",), "screened_total")],
)
def test_an_undeclared_member_is_refused_at_both_levels(
    pointer: tuple[str, ...], member: str
) -> None:
    """``additionalProperties: false`` seals the manifest AND the counts block.

    ``included`` and ``payload`` are the two members somebody would most plausibly add: the
    export's item arrays live in the payload and are deliberately not part of the sealed
    envelope, so smuggling them in here would change what the seal covers without changing
    what it is called.
    """
    instance = manifest()
    target: Any = instance
    for token in pointer:
        target = target[token]
    target[member] = 1
    with pytest.raises(SchemaValidationError):
        compute_content_hash(instance, EXPORT)


@pytest.mark.parametrize("tally", ["identified_total", "excluded", "adjudicated"])
def test_a_missing_flow_tally_is_refused(tally: str) -> None:
    instance = manifest()
    del instance["counts"][tally]
    with pytest.raises(SchemaValidationError):
        compute_content_hash(instance, EXPORT)


# ============================== 4. the one opaque subtree, controlled in both directions ===


def test_the_derived_profile_declares_exactly_one_opaque_subtree_and_no_arrays() -> None:
    """The document's own claims about itself, measured rather than asserted in prose."""
    profile = derive_hash_profile(EXPORT)
    assert profile["opaque_pointers"] == ["/counts/exclusion_reasons"]
    assert profile["arrays"] == [], "this manifest carries no arrays; none may be declared"
    assert profile["excluded_pointers"] == [], (
        "nothing in this manifest is exempt from its own seal"
    )
    assert profile["absent_vs_null"] == "distinct"
    assert "/counts/exclusion_reasons" in profile["included_pointers"]
    # ...and no member BENEATH it is declared: a declared member revokes the opacity, after
    # which every dynamic reason code would have to be declared, which is impossible.
    assert not [
        p for p in profile["included_pointers"] if p.startswith("/counts/exclusion_reasons/")
    ]


def test_dynamic_reason_codes_are_admitted_and_still_reach_the_digest() -> None:
    """Opacity means "hashed as it arrives", not "not hashed".

    A hash view that simply dropped the subtree would admit any reason code and satisfy the
    admission half on its own, so both a new key and a changed tally are asserted to move
    the digest.
    """
    baseline = compute_content_hash(manifest(), EXPORT)

    renamed = manifest()
    renamed["counts"]["exclusion_reasons"] = {"a-reason-code-nobody-declared": 70}
    assert DIGEST.match(compute_content_hash(renamed, EXPORT))
    assert compute_content_hash(renamed, EXPORT) != baseline

    retallied = manifest()
    retallied["counts"]["exclusion_reasons"]["wrong_population"] = 31
    assert compute_content_hash(retallied, EXPORT) != baseline

    empty = manifest()
    empty["counts"]["exclusion_reasons"] = {}
    assert compute_content_hash(empty, EXPORT) != baseline


def test_a_reason_tally_that_is_not_a_count_is_still_refused_inside_the_opaque_subtree() -> None:
    """Opaque to the HASH VIEW is not unvalidated: ``additionalProperties`` still types it."""
    instance = manifest()
    instance["counts"]["exclusion_reasons"]["wrong_population"] = "thirty"
    with pytest.raises(SchemaValidationError):
        compute_content_hash(instance, EXPORT)


def test_without_the_opacity_annotation_the_same_manifest_cannot_be_hashed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The falsifiability control for the one annotation this document adds.

    Stripping ``x-datacompany-hash-opaque`` leaves the reason-code subtree neither declared nor
    opaque, which is precisely the "declare none or declare all" shape the released rule
    refuses. Without this, the annotation could be deleted and every other test here would
    stay green on a manifest that happened to carry no reason codes.
    """
    probe_id = "urn:datacompany:inclusion-set-export-opacity-probe:1"

    def register(document: dict[str, Any]) -> dict[str, Any]:
        """Register ``document`` under the probe ``$id`` and return its derived manifest.

        Patched as an ATTRIBUTE, the established probe pattern: ``hash_profile`` resolves
        through ``resolve_pointer`` at call time, so a module-level import binding would
        keep answering from the unpatched object. The derivation and the view are exercised
        directly rather than through ``compute_content_hash``, because the JSON Schema
        validator resolves out of a separately cached ``referencing`` registry that a probe
        never enters -- and step 1 is not what this control is about.
        """
        document["$id"] = probe_id
        schemas = {**canonical_schemas(), probe_id: document}
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
        return derive_hash_profile(probe_id)

    # The POSITIVE control first: the committed document, copied verbatim under a probe id,
    # hashes the identical instance. Everything the negative case below changes is one
    # annotation, so the refusal cannot be blamed on the probe, on the copy, or on the
    # instance.
    faithful = register(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    assert faithful["opaque_pointers"] == ["/counts/exclusion_reasons"]
    assert DIGEST.match(canonical_sha256(build_hash_view(manifest(), faithful)))

    stripped = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    reasons = stripped["$defs"]["flow_counts"]["properties"]["exclusion_reasons"]
    assert reasons.pop("x-datacompany-hash-opaque") is True, "the annotation was not there to strip"
    assert stripped != json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    without_opacity = register(stripped)
    assert without_opacity["opaque_pointers"] == [], "the probe still declares what it strips"
    with pytest.raises(UndeclaredPathError):
        build_hash_view(manifest(), without_opacity)

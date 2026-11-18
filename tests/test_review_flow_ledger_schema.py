"""``review-flow-ledger:1`` must describe the body ``8810`` actually returns, not an idealised one.

The producing service has advertised ``schema_ref`` on every flow response since the endpoint
shipped, naming a document that did not exist. That was not an oversight either — it was a
deliberate holding position, recorded in the producer's own constant: a URL spelling announces
"documentation pointer", and minting a ``urn:datacompany:*`` for a document the registry does not
have would have been the worse claim, because a URN in that grammar is the shape a consumer
resolves. The remedy the constant names is the order this document follows: *"the schema gets
authored first and this constant follows it — never the other way round"*
(``evidence_review_service``, ``src/application/services/flow.py``).

So what this suite has to prove is narrower and harder than "the schema compiles". It is that
the document is a true description of a body nobody has ever validated:

1. **The member set is exactly the producer's.** ``_compute_flow`` builds a nine-member dict
   and returns it verbatim. A schema with a tenth member would be describing a body that does
   not exist; one with eight would refuse every real body.
2. **``counts`` is the SAME block the export seals**, by ``$ref`` and not by re-spelling — so
   a rendered report and the sealed export it was taken from cannot drift into two answers
   about what a screening tally is.
3. **The per-stage array is order-sensitive and its reason breakdown reaches the digest.**
   PRISMA reads the stages in order and requires the full-text exclusion box broken down by
   reason; a declaration that lost either would be ceremony.
4. **The permissive members are permissive on purpose.** ``stage_key`` and ``name`` come out
   of unconstrained ``text NOT NULL`` columns, and a schema that narrowed them to a released
   identifier grammar would refuse real bodies — the failure mode ``inclusion-set-export.v2``
   records for ``tenant_id``, in this same tier. Asserted, so that a later "tidy-up" that
   narrows them fails here rather than in production.
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
    compute_content_hash,
    derive_hash_profile,
    validate_instance,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "evidence" / "review-flow-ledger.v1.schema.json"

LEDGER = "urn:datacompany:review-flow-ledger:1"
EXPORT = "urn:datacompany:inclusion-set-export:2"

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

#: The nine members ``_compute_flow`` puts in its response dict, in the producer's own order.
#:
#: Pinned as a literal rather than read from the producer, because this repository cannot
#: import it — the true producer-side pin is ``evidence_review_service``'s own test that
#: validates a derived body against this document. This one is the contract half of that
#: pair: if somebody adds a tenth member here without the producer emitting it, or drops one
#: the producer still emits, exactly one of the two goes red and says which side moved.
PRODUCER_MEMBERS = frozenset(
    {
        "review_id",
        "flow_revision_id",
        "flow_revision_number",
        "counts",
        "counts_by_stage",
        "canonical_counts_hash",
        "schema_ref",
        "projection_stale",
        "projection_computed_at",
    }
)


def counts() -> dict[str, Any]:
    """The flat tallies, exactly as ``derive`` emits them.

    Not invented: this is the output of ``flow_derivation.derive`` over a hand-built
    ``FlowInputs`` carrying eight import rows (one rejected), seven records (one merged away),
    a two-stage review, one conflict resolved by adjudication and two records nobody has
    reached yet. The conservation identities hold on it — ``8 = 0 + 1 + 7``,
    ``7 = 1 + 4 + 2``, ``4 = 2 + 2 + 0`` — which is what makes it a usable fixture rather
    than a plausible-looking one.
    """
    return {
        "identified_total": 8,
        "quarantined": 0,
        "rejected": 1,
        "records_total": 7,
        "duplicates_removed": 1,
        "records_screened": 4,
        "not_yet_screened": 2,
        "included": 2,
        "excluded": 2,
        "uncertain": 0,
        "adjudicated": 1,
        "exclusion_reasons": {"wrong_outcome": 1, "wrong_population": 1},
    }


def stages() -> list[dict[str, Any]]:
    """The per-stage split of the same derivation, in the producer's reading order."""
    return [
        {
            "stage_order": 1,
            "stage_key": "title_abstract",
            "name": "Title and abstract",
            "reached": 4,
            "settled_include": 1,
            "settled_exclude": 1,
            "settled_uncertain": 0,
            "exclusion_reasons": {"wrong_population": 1},
        },
        {
            "stage_order": 2,
            "stage_key": "full_text",
            "name": "Full text",
            "reached": 2,
            "settled_include": 1,
            "settled_exclude": 1,
            "settled_uncertain": 0,
            "exclusion_reasons": {"wrong_outcome": 1},
        },
    ]


def ledger() -> dict[str, Any]:
    """A whole flow response.

    A function, not a constant, so every mutation below starts from an unmutated body — the
    same reason the two export suites build theirs the same way.
    """
    return {
        "review_id": "7c67fcdf-c60e-45d8-9d46-a35189c0ea11",
        "flow_revision_id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
        "flow_revision_number": 3,
        "counts": counts(),
        "counts_by_stage": stages(),
        "canonical_counts_hash": "sha256:"
        + "25f222bcc6a0b11ac91c67216d5e63b7bca9765bdc157dc42c09880d506118cf",
        "schema_ref": LEDGER,
        "projection_stale": False,
        "projection_computed_at": "2026-08-31T10:05:00Z",
    }


def without(member: str) -> dict[str, Any]:
    body = ledger()
    del body[member]
    return body


# ============================================================== 1. release integrity ===


def test_the_document_is_registered_under_its_own_id() -> None:
    """Non-vacuity control for everything below: an unregistered ``$id`` makes every
    ``validate_instance`` call raise rather than measure."""
    schema = canonical_schemas().get(LEDGER)
    assert schema is not None, f"{LEDGER} is not in the released registry"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_the_registered_copy_is_the_committed_file() -> None:
    """The registry globs a directory; nothing else guarantees the file on disk is what a
    consumer resolves."""
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == canonical_schemas()[LEDGER]


def test_a_whole_flow_response_validates_derives_and_hashes() -> None:
    assert validate_instance(ledger(), LEDGER) == []
    assert derive_hash_profile(LEDGER)
    assert DIGEST.match(compute_content_hash(ledger(), LEDGER))


def test_the_member_set_is_exactly_what_the_producer_emits() -> None:
    """Both directions. A schema that permits a member the producer never sends is
    describing something else; one that omits a member the producer does send refuses every
    real body."""
    schema = canonical_schemas()[LEDGER]
    assert set(schema["properties"]) == PRODUCER_MEMBERS
    assert set(schema["required"]) == PRODUCER_MEMBERS
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("member", sorted(PRODUCER_MEMBERS))
def test_every_member_is_required(member: str) -> None:
    """Every one of the nine. The producer builds the dict unconditionally, so an optional
    member here would be a contract admitting a body the producer cannot construct."""
    assert validate_instance(without(member), LEDGER) != []


def test_the_seal_refuses_an_undeclared_member() -> None:
    body = ledger()
    body["records_identified_from_registers"] = 4
    assert validate_instance(body, LEDGER) != []


# ================================================== 2. the members that carry meaning ===


@pytest.mark.parametrize(
    ("member", "value"),
    [
        ("review_id", "not-a-uuid"),
        ("review_id", "7C67FCDF-C60E-45D8-9D46-A35189C0EA11"),
        ("flow_revision_id", 3),
        ("flow_revision_number", 0),
        ("flow_revision_number", "3"),
        ("canonical_counts_hash", "25f222bc"),
        ("canonical_counts_hash", "sha256:NOTHEX"),
        (
            "schema_ref",
            "https://contracts.nonagentic.ai/evidence/review-flow-ledger.v1.schema.json",
        ),
        ("projection_stale", "false"),
        ("projection_computed_at", "2026-08-31T10:05:00+00:00"),
    ],
)
def test_a_malformed_member_is_refused(member: str, value: Any) -> None:
    """The uppercase UUID and the offset timestamp are the two that matter in practice.

    ``uuid`` is lowercase-only and ``timestamp`` is trailing-``Z``-only in the released
    grammar, and Python's ``datetime.isoformat()`` emits ``+00:00``. That is exactly the
    spelling the producer emitted before this document existed, so this case is the one that
    would have let a real body through a contract that had been widened to accept it. The
    ``schema_ref`` case pins the same decision from the other side: the URL the producer used
    to advertise is not a legal value of the member that now names this document.
    """
    body = ledger()
    body[member] = value
    assert validate_instance(body, LEDGER) != []


def test_an_absent_projection_is_null_and_not_omitted() -> None:
    """A review whose projection has never been written is a normal state, not a missing
    field. The released profile fixes absent-vs-null to *distinct*, so admitting both
    spellings would let one ledger produce two canonical forms."""
    body = ledger()
    body["projection_computed_at"] = None
    assert validate_instance(body, LEDGER) == []
    assert validate_instance(without("projection_computed_at"), LEDGER) != []


def test_an_unworked_review_has_an_empty_stage_split() -> None:
    """No ``minItems``. A review that has declared no stages and screened nothing has an
    empty array, and refusing it would refuse the first honest body of every new review."""
    body = ledger()
    body["counts_by_stage"] = []
    assert validate_instance(body, LEDGER) == []


@pytest.mark.parametrize(
    "member",
    [
        "stage_order",
        "stage_key",
        "name",
        "reached",
        "settled_include",
        "settled_exclude",
        "settled_uncertain",
        "exclusion_reasons",
    ],
)
def test_every_stage_member_is_required(member: str) -> None:
    body = ledger()
    del body["counts_by_stage"][0][member]
    assert validate_instance(body, LEDGER) != []


def test_a_stage_tally_refuses_a_fourth_settled_bucket() -> None:
    """``check_stage_conservation`` asserts ``settled_* <= reached`` over exactly three
    buckets. A fourth arriving unnoticed would make the block say something that identity was
    never checked against."""
    body = ledger()
    body["counts_by_stage"][0]["settled_retracted"] = 1
    assert validate_instance(body, LEDGER) != []


def test_the_permissive_stage_strings_stay_permissive() -> None:
    """``review_stages.stage_key`` and ``.name`` are ``text NOT NULL`` with no CHECK of any
    kind, and a synthesized stage takes its name from its key. A body carrying a hyphen, a
    capital or a space is legal in the producer and must be legal here — this is the
    regression guard against a later tidy-up that narrows them to an identifier grammar and
    starts refusing real reviews."""
    body = ledger()
    body["counts_by_stage"][0]["stage_key"] = "Full-Text (round 2)"
    body["counts_by_stage"][0]["name"] = "Pełny tekst — ocena kwalifikowalności"
    assert validate_instance(body, LEDGER) == []


def test_a_blank_stage_name_is_refused() -> None:
    """The one narrowing that IS made, stated so it is a decision rather than an accident: a
    stage nobody can name is not a stage, and a body that trips this is evidence of a defect
    upstream."""
    body = ledger()
    body["counts_by_stage"][0]["name"] = ""
    assert validate_instance(body, LEDGER) != []


# ================================================================ 3. the properties ===


def test_the_counts_block_is_the_export_s_own_definition_and_not_a_copy() -> None:
    """THE POINT OF THE ``$ref``. The producer derives the tallies once and puts that one
    object into both the sealed export manifest and this projection, and
    ``canonical_counts_hash`` is computed over it in both places. Two spellings would be two
    answers to what a screening tally is, and the first divergence would make a hash
    comparison between an export and the ledger it came from mean nothing.

    Asserted structurally — the reference resolves into the export document — and then
    behaviourally: the same counts block is accepted by both schemas and refused by both in
    the same way.
    """
    schema = canonical_schemas()[LEDGER]
    assert schema["properties"]["counts"] == {
        "$comment": schema["properties"]["counts"]["$comment"],
        "$ref": f"{EXPORT}#/$defs/flow_counts",
    }
    assert "flow_counts" not in schema.get("$defs", {})

    body = ledger()
    body["counts"]["records_screened"] = "four"
    assert validate_instance(body, LEDGER) != []


def test_the_stage_order_is_part_of_the_hash() -> None:
    """Declared ``ordered``, not set-like, because the sequence is the reading order of a
    PRISMA diagram. A consumer that re-sorted would compute a different digest, which is the
    correct outcome: it is not the same ledger."""
    body = ledger()
    reordered = ledger()
    reordered["counts_by_stage"] = list(reversed(reordered["counts_by_stage"]))
    assert compute_content_hash(reordered, LEDGER) != compute_content_hash(body, LEDGER)


def test_two_identical_ledgers_hash_identically() -> None:
    """Negative control for the case above — without it that test would pass against an
    implementation that simply salted every digest."""
    assert compute_content_hash(ledger(), LEDGER) == compute_content_hash(ledger(), LEDGER)


def test_every_exclusion_reason_reaches_the_digest_at_every_stage() -> None:
    """Opaque is not excluded. The reason breakdown cannot be declared member by member —
    the keys are the review's own configured codes — but it is hashed exactly as it arrives,
    so changing one count or one code changes the ledger. If it did not, the box PRISMA
    actually requires would be the one part of the document nothing protected."""
    base = compute_content_hash(ledger(), LEDGER)

    retallied = ledger()
    retallied["counts_by_stage"][0]["exclusion_reasons"]["wrong_population"] = 2
    assert compute_content_hash(retallied, LEDGER) != base

    recoded = ledger()
    recoded["counts_by_stage"][1]["exclusion_reasons"] = {"wrong_comparator": 1}
    assert compute_content_hash(recoded, LEDGER) != base


def test_both_reason_subtrees_are_opaque_in_the_derived_profile() -> None:
    """The flat one arrives by ``$ref`` and the per-stage one is annotated here. Both must
    end up opaque, or the composed document raises ``UndeclaredPathError`` the moment a real
    review carries a reason code — which is every review that has excluded anything."""
    profile = derive_hash_profile(LEDGER)
    assert set(profile["opaque_pointers"]) == {
        "/counts/exclusion_reasons",
        "/counts_by_stage/-/exclusion_reasons",
    }
    assert profile["arrays"] == [{"pointer": "/counts_by_stage", "kind": "ordered"}]


def test_the_whole_body_reaches_the_hash_view() -> None:
    """Nothing here is excluded. The ledger has no mutable bookkeeping to drop: it is
    derived from history on every read, so every member of it is content."""
    view = build_hash_view(ledger(), derive_hash_profile(LEDGER))
    assert set(view) == PRODUCER_MEMBERS
    assert view["counts_by_stage"] == stages()


# ================================================ 4. why a document of its own at all ===


def test_the_export_schema_could_not_have_carried_this() -> None:
    """The justification for a new released document rather than a member on an existing one,
    asserted rather than assumed.

    ``inclusion-set-export:2`` is sealed with ``additionalProperties: false`` and describes a
    MANIFEST OF A SEALED EXPORT — it requires ``corpus_version_id``, ``items_hash`` and the
    rest of the seal, none of which a derived projection has or could have. Widening it in
    place would silently change what every already-sealed ``:2`` hash meant.
    """
    assert validate_instance(ledger(), EXPORT) != []

    export_schema = canonical_schemas()[EXPORT]
    assert export_schema["additionalProperties"] is False
    assert {"corpus_version_id", "items_hash", "member_manifest_hash"} <= set(
        export_schema["required"]
    )
    assert not {"counts_by_stage", "projection_stale"} & set(export_schema["properties"])


def test_the_ledger_seals_nothing_and_says_so() -> None:
    """A projection must not grow a payload digest by accident. If one ever belongs here, it
    is a ``:2`` with an argument attached, not a quiet addition — the same rule
    ``inclusion-set-export`` spent a whole version demonstrating."""
    schema = canonical_schemas()[LEDGER]
    assert not {"items_hash", "payload_digest", "sealed_with", "signature"} & set(
        schema["properties"]
    )


def test_an_unknown_schema_id_is_still_refused() -> None:
    """Non-vacuity for the registry itself: ``validate_instance`` must raise on an id nobody
    released, or every negative case above could be passing for the wrong reason."""
    with pytest.raises(SchemaValidationError):
        validate_instance(ledger(), "urn:datacompany:review-flow-ledger:2")

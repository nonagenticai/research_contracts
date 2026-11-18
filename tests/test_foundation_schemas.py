"""FND-002 tasks 2, 3 and 6: the foundation tier must be executable assertions.

Four obligations, in the order of what they catch:

1. **Release integrity** — every foundation schema compiles, resolves, is registered, and
   composes the released primitives instead of restating them.
2. **Non-vacuity** — the corpus is asserted non-empty, the counts are equality pins, and the
   decisions register is bound in BOTH directions to the schemas that cite it. A gate that
   measures nothing must not report zero findings as health.
3. **Falsifiability** — every rule these schemas add is proven able to REJECT, each with a
   passing control that isolates the mutated member. An unfalsified gate is
   indistinguishable from an absent one.
4. **Open defects, pinned** — D8 (a set-like array of scalars is inexpressible) is proven
   here, mechanically, so it cannot be forgotten or quietly invented away.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from research_contracts.canonical import (
    CrossFieldError,
    UndeclaredArrayError,
    UndeclaredPathError,
    build_hash_view,
    canonical_schemas,
    collect_cross_field_rules,
    compute_content_hash,
    derive_hash_profile,
    validate_instance,
)
from research_contracts.canonical.hash_profile import (
    HashProfileError,
    merge_profile_extensions,
    validate_profile_against_schema,
)
from research_contracts.canonical.registry import (
    FOUNDATION_SCHEMA_DIRS,
    SCHEMA_ROOT,
    CanonicalValidator,
    foundation_schema_dirs,
    resolve_ref,
    schema_failure_codes,
    schema_registry,
)
from research_contracts.tooling.canonical_fixtures import EXPECTED_CHECKS
from research_contracts.tooling.canonical_fixtures import SUITES as CANONICAL_SUITES
from research_contracts.tooling.foundation_fixtures import (
    EXPECTED_FOUNDATION_CHECKS,
)
from research_contracts.tooling.foundation_fixtures import SUITES as FOUNDATION_SUITES
from research_contracts.tooling.foundation_fixtures import main as replay_foundation

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "fixtures" / "foundation" / "v1"
DECISIONS = ROOT / "config" / "foundation-decisions.json"

CONTEXT = "urn:datacompany:research-access-context:1"
RELEASE = "urn:datacompany:release-ref:1"
PAGE = "urn:datacompany:page:1"
PROBLEM = "urn:datacompany:problem-details:1"
CAPABILITY = "urn:datacompany:capability-status:1"
MANIFEST = "urn:datacompany:run-manifest:1"
TYPED_REFS = "urn:datacompany:typed-refs:1"
SELECTOR = "urn:datacompany:locator-selector:1"
LOCATION = "urn:datacompany:evidence-location-version:1"
CANDIDATE = "urn:datacompany:evidence-location-candidate:1"

#: Every foundation schema, and the FND-002 task that owns it. Tier membership, so it is
#: keyed on the five ``schemas/`` directories ``FOUNDATION_SCHEMA_DIRS`` names and nothing
#: else -- several tests below assert properties OF THE TIER and would change meaning if a
#: canonical-tier document were added here.
RELEASED = {
    CONTEXT: ("context", "task 2"),
    RELEASE: ("profiles", "task 2"),
    PAGE: ("common", "task 2"),
    PROBLEM: ("common", "task 3"),
    CAPABILITY: ("capabilities", "task 3"),
    MANIFEST: ("manifests", "task 6"),
    SELECTOR: ("evidence", "task 4"),
    LOCATION: ("evidence", "task 4"),
    CANDIDATE: ("evidence", "task 4"),
}

#: Every schema the FOUNDATION FIXTURE CORPUS is allowed to target, which is a different
#: question from tier membership. ``typed-refs:1`` is canonical-tier by directory and is
#: released by FND-002 task 4; its fixtures live in the five foundation suites because
#: ``packages/typescript/test/foundation.test.ts`` asserts there are exactly five, and a
#: sixth ``Suite(...)`` would turn that non-vacuity guard red for the wrong reason.
FIXTURE_TARGETS = {**RELEASED, TYPED_REFS: ("canonical", "task 4")}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixtures(kind: str) -> list[Path]:
    paths = sorted((FIXTURE_ROOT / kind).glob("*.json"))
    assert paths, f"no {kind} foundation fixtures found under {FIXTURE_ROOT / kind}"
    return paths


def instance_of(kind: str, name: str) -> Any:
    return load(FIXTURE_ROOT / kind / f"{name}.json")["instance"]


# ============================================================== 1. release integrity ===


def test_every_declared_foundation_tier_exists_and_holds_schemas() -> None:
    """The premise of the whole tier, asserted rather than assumed."""
    assert len(FOUNDATION_SCHEMA_DIRS) == 9
    populated = {
        directory.name: sorted(p.name for p in directory.glob("*.schema.json"))
        for directory in foundation_schema_dirs()
    }
    assert populated == {
        "capabilities": ["capability-status.v1.schema.json"],
        "common": [
            "operation-idempotency-record.v1.schema.json",
            "page.v1.schema.json",
            "problem-details.v1.schema.json",
        ],
        "context": ["research-access-context.v1.schema.json"],
        # ``inclusion-set-export.v1`` and ``.v2`` are in this tier by DIRECTORY and not by FND-002 task:
        # it is released so ``evidence_review_service`` can seal its inclusion-set export
        # against a declared contract instead of falling back to a bare digest, and it sits
        # here because ``FOUNDATION_SCHEMA_DIRS`` is a closed list -- a new directory would
        # be invisible to the registry. It is deliberately absent from ``RELEASED`` above,
        # which maps foundation schemas to the FND-002 task that owns them and would have to
        # invent one. Its own gates live in ``tests/test_inclusion_set_export_schema.py``.
        "evidence": [
            "evidence-location-candidate.v1.schema.json",
            "evidence-location.v1.schema.json",
            "inclusion-set-export.v1.schema.json",
            # ``:2`` is a WIDENING, and ``:1`` stays released beside it rather than being
            # replaced in place: every hash already sealed under ``:1`` was computed against
            # exactly these members, and deleting the document would leave those digests
            # unverifiable — the verifier resolves an export's OWN recorded ``schema_ref``.
            "inclusion-set-export.v2.schema.json",
            "locator-selector.v1.schema.json",
            # ``review-flow-ledger.v1`` is in this tier by DIRECTORY, on the same footing as
            # the two export documents above and deliberately absent from ``RELEASED`` for
            # the same reason: it is released so ``evidence_review_service`` can point its
            # ``LEDGER_SCHEMA_REF`` at a document that exists, not because an FND-002 task
            # owns it. Unlike them it seals nothing -- the flow ledger is a projection
            # recomputed on every read. Its own gates live in
            # ``tests/test_review_flow_ledger_schema.py``.
            "review-flow-ledger.v1.schema.json",
        ],
        # ``research-event-envelope.v1`` is in this tier by DIRECTORY and, like the three
        # evidence-tier documents above, is deliberately absent from ``RELEASED``: no
        # FND-002 task owns it. It is released because document 13 section 8.3 will not let
        # a service emit a document 09 event until that event's schema is merged, and two
        # services already keep an outbox against no released envelope at all. Its own gates
        # live in ``tests/test_research_event_envelope_schema.py``. The directory itself was
        # empty from 2026-07-30 until this release; see ``FOUNDATION_SCHEMA_DIRS``.
        # Twelve payload documents released 2026-09-04, covering the EIGHTEEN wired events of
        # document 09 section 3.7 -- not twenty-one, and not eighteen documents. Two producer
        # functions in evidence_review_service each write several event types from one code
        # path (``emit_review_lifecycle`` writes six, ``emit_acceptance`` two), so those types
        # share a payload document: one function produces them, so they cannot diverge without
        # it changing, and separate documents would advertise independently versionable
        # contracts that no code path can exercise. The remaining three of the twenty-one sit
        # in that service's ``NOT_YET`` map with no producer at all, so section 8.3 has nothing
        # to gate on them and releasing a schema for one would be a contract without a writer.
        "events": [
            "research-event-envelope.v1.schema.json",
            "review-assertion-recorded.v1.schema.json",
            "review-conflict-opened.v1.schema.json",
            "review-conflict-resolved.v1.schema.json",
            "review-created.v1.schema.json",
            "review-decision-recorded.v1.schema.json",
            "review-duplicate-cluster-proposed.v1.schema.json",
            "review-duplicate-cluster-resolved.v1.schema.json",
            "review-evidence-acceptance-recorded.v1.schema.json",
            "review-evidence-snapshot-created.v1.schema.json",
            "review-import-completed.v1.schema.json",
            "review-lifecycle-transition.v1.schema.json",
            "review-observation-superseded.v1.schema.json",
        ],
        # ``application-receipt.v1`` released 2026-09-04 beside the attestation it records the
        # APPLICATION of. The two are deliberately separate documents: 13-...:648 says the
        # verifier "produces a typed verification result; it does not apply the command", and
        # 08-...:419-421 that "Approval and application are distinct". One document carrying
        # both would make that distinction unrepresentable in the very grammar meant to hold it.
        "approvals": [
            "application-receipt.v1.schema.json",
            "approval-attestation.v1.schema.json",
        ],
        # ``jobs`` joined the tiers on 2026-09-04 with the two halves of ``FND-003``
        # task 2. Like ``events`` before it the directory had existed empty since
        # 2026-07-30, while ``evidence_review_service`` ran the whole durable-job
        # subsystem in production against no released grammar. Its own gates live in
        # ``tests/test_durable_job_schemas.py``.
        "jobs": ["durable-job.v1.schema.json", "job-attempt.v1.schema.json"],
        "manifests": [
            "evidence-snapshot-manifest.v1.schema.json",
            "run-manifest.v1.schema.json",
        ],
        "profiles": ["release-ref.v1.schema.json"],
    }, populated


@pytest.mark.parametrize("schema_id", sorted(RELEASED))
def test_every_foundation_schema_is_registered_and_compiles(schema_id: str) -> None:
    schema = canonical_schemas().get(schema_id)
    assert schema is not None, f"{schema_id} is not in the released registry"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_the_foundation_tier_did_not_displace_the_canonical_tier() -> None:
    """One registry, both tiers. A foundation schema that shadowed a canonical ``$id``
    would silently re-point every released reference at itself."""
    registered = canonical_schemas()
    for canonical_id in (
        "urn:datacompany:stable-identity:1",
        "urn:datacompany:immutable-version:1",
        "urn:datacompany:pinned-version-ref:1",
        "urn:datacompany:reference-verification-receipt:1",
    ):
        assert canonical_id in registered
    assert set(RELEASED) <= set(registered)


@pytest.mark.parametrize("schema_id", sorted(RELEASED))
def test_no_foundation_schema_restates_a_released_primitive(schema_id: str) -> None:
    """A local re-spelling of a released rule is the "weaker local alias" the
    ``FND-CANONICAL-CONTRACT`` gate forbids.

    The two rules that matter most are the scope conditional and the digest pattern. A
    schema that wrote ``^sha256:[0-9a-f]{64}$`` itself, or its own if/then over
    ``resource_scope``, would drift the moment the released one changed -- and the released
    one has already changed once, when B7 corrected its anchor semantics.
    """
    text = json.dumps(canonical_schemas()[schema_id])
    assert "sha256:[0-9a-f]{64}" not in text, (
        f"{schema_id} spells the content-hash pattern itself; $ref "
        "stable-identity:1#/$defs/content_hash instead"
    )
    if '"resource_scope"' in text:
        assert "resource_scope_conditional" in text, (
            f"{schema_id} mentions resource_scope without composing the released "
            "resource_scope_conditional, so its global/tenant discrimination is a local "
            "invention rather than the released one"
        )


def test_no_foundation_schema_declares_an_unevaluable_cross_field_rule() -> None:
    """D3 in the other direction: none of the new schemas may trip the collector.

    Every rule these schemas declare sits at a document root with instance-root-absolute
    pointers, which is the only position the released vocabulary can evaluate. A rule that
    had drifted under a ``properties`` entry would raise here, before it reached a consumer.
    """
    validated_refs = sorted(
        {load(path)["schema_ref"] for kind in ("valid", "invalid") for path in fixtures(kind)}
    )
    for schema_ref in validated_refs:
        collect_cross_field_rules(schema_ref)
    # Non-vacuity: at least three of them really do declare a rule, so a collector that
    # returned [] for everything would not satisfy this test.
    declared = {ref: len(collect_cross_field_rules(ref)) for ref in validated_refs}
    assert sum(declared.values()) >= 3, declared
    assert declared["urn:datacompany:page:1#/$defs/page_request"] == 1, declared


# =================================================================== 2. non-vacuity ===


def test_the_foundation_corpus_is_pinned_as_an_equality_and_replays_clean() -> None:
    assert EXPECTED_FOUNDATION_CHECKS == 98
    assert replay_foundation([]) == 0


def test_the_two_fixture_corpora_are_disjoint_and_independently_pinned() -> None:
    """Neither harness may absorb the other's fixtures or the other's pin.

    ``canonical_fixtures.EXPECTED_CHECKS`` is owned elsewhere and is deliberately untouched
    by this work. If a foundation suite ever pointed at a canonical directory, both totals
    would still add up while one corpus was being counted twice.
    """
    canonical_dirs = {suite.relative for suite in CANONICAL_SUITES}
    foundation_dirs = {suite.relative for suite in FOUNDATION_SUITES}
    assert canonical_dirs & foundation_dirs == set()
    assert EXPECTED_CHECKS != EXPECTED_FOUNDATION_CHECKS
    for suite in FOUNDATION_SUITES:
        assert suite.relative.parts[0] == "foundation"


def test_the_decisions_register_is_bound_to_the_schemas_in_both_directions() -> None:
    """A register nobody cites is documentation; a citation with no register entry is a lie.

    Both directions are checked, because each failure mode is real and they are different:
    an entry that stops being cited has quietly become dead prose, and a ``$comment`` citing
    an id that was renamed sends a reader to nothing.
    """
    register = load(DECISIONS)
    entries = {decision["id"] for decision in register["decisions"]}
    assert entries, "the decisions register is empty"

    # EVERY released schema, not just the foundation tier. Scanning only ``RELEASED`` left a
    # hole: a decision cited solely by a canonical-tier schema read as cited by nothing, and
    # an id a canonical schema invented was never checked against the register at all.
    released = canonical_schemas()
    assert set(RELEASED) <= set(released), sorted(set(RELEASED) - set(released))
    texts = {schema_id: json.dumps(document) for schema_id, document in released.items()}

    cited: set[str] = set()
    for text in texts.values():
        cited |= {entry for entry in entries if entry in text}

    assert entries - cited == set(), (
        f"decisions {sorted(entries - cited)} are recorded but cited by no released schema"
    )

    # ...and every id a schema mentions must exist in the register.
    import re

    mentioned: set[str] = set()
    for text in texts.values():
        mentioned |= set(re.findall(r"IMP-DEC-FND002-\d+", text))
    assert mentioned - entries == set(), (
        f"schemas cite {sorted(mentioned - entries)}, which the register does not define"
    )

    # Non-vacuity: the widened sweep must really reach beyond the foundation tier, or this
    # test would have silently narrowed back to what it checked before.
    beyond = {
        schema_id
        for schema_id, text in texts.items()
        if schema_id not in RELEASED and "IMP-DEC-FND002-" in text
    }
    assert beyond, "no canonical-tier schema cites a decision; the widened sweep proves nothing"


def test_every_decision_states_what_it_rejected_and_why() -> None:
    """An option with no rejected alternative is a preference presented as a decision."""
    for decision in load(DECISIONS)["decisions"]:
        assert decision["citations"], f"{decision['id']} cites nothing"
        assert decision.get("taken"), f"{decision['id']} records no decision"
        assert decision.get("rejected") or decision.get("blocked_on"), (
            f"{decision['id']} records no rejected alternative and names no blocker, so it "
            "documents a preference rather than a decision"
        )


#: A citation opens with ``<file>:<line>`` or ``<file>:<from>-<to>`` when it points at the
#: DataCompany corpus. Everything else -- a released schema URN, a repository path, "JSON Schema
#: 2020-12", a sentence beginning "Measured over..." -- is a citation of something this test
#: cannot resolve and is counted separately rather than silently ignored.
CORPUS_CITATION = re.compile(
    r"^(?P<file>[0-9A-Za-z][\w./-]*\.md):(?P<first>\d+)(?:-(?P<last>\d+))?"
)

#: The quoted runs after the em-dash. ALL of them, not the first: several citations quote two
#: fragments, and at least one run matching is what the check requires. A citation that
#: paraphrases instead of quoting is bounds-checked only, and the two populations are counted
#: separately so the quote-checked half cannot decay into the paraphrase half unnoticed.
#:
#: THE OPENING QUOTE MAY NOT FOLLOW A WORD CHARACTER, because ``'`` is also an apostrophe. The
#: bare ``'([^']*)'`` paired the apostrophe of ``the same plan's done-when names a DIFFERENT
#: four: 'stale-rights, ...'`` with the real opening quote and extracted the GAP between them
#: -- ``"s done-when names a DIFFERENT four: "`` -- which no corpus line contains, so a
#: correctly-cited quotation was reported as unresolvable. That is a FABRICATED finding, and a
#: gate that fabricates findings gets weakened rather than fixed. Measured over the whole
#: register: the guard leaves 126 resolved / 84 quote-checked unchanged, removes the one false
#: finding, and additionally recovers the real quotation in IMP-DEC-FND002-035, which the bare
#: form had been reading as two apostrophe-delimited gaps.
#:
#: An apostrophe INSIDE a run still truncates it, and that is the SAFE direction: a prefix of a
#: real quotation is still a substring of the same corpus window, so it can only weaken the
#: check, never fabricate. Pinned by ``test_the_quoted_fragment_parser_pairs_quotes_not_
#: apostrophes``.
QUOTED_FRAGMENT = re.compile(r"(?<![A-Za-z0-9])'([^']*)'")
MIN_QUOTE = 12


def normalise_prose(text: str) -> str:
    """Compare prose, not typography.

    The corpus hard-wraps, marks code with backticks, and uses curly quotes and en dashes a
    citation retypes as ASCII. None of that is drift, and treating it as drift would produce a
    gate with false positives -- which gets tuned until it is vacuous.
    """
    for old, new in (
        ("`", ""),
        ("\u2019", "'"),
        ("\u2014", "-"),
        ("\u2013", "-"),
        ("\u201c", ""),
        ("\u201d", ""),
        ('"', ""),
        ("'", ""),
    ):
        text = text.replace(old, new)
    return " ".join(text.split()).casefold()


def corpus_citations() -> list[tuple[str, str, int, int, str]]:
    """Every ``(decision_id, file, first, last, text)`` citation that names a corpus file."""
    found = []
    for decision in load(DECISIONS)["decisions"]:
        for citation in decision["citations"]:
            match = CORPUS_CITATION.match(citation)
            if match is None:
                continue
            first = int(match["first"])
            found.append(
                (decision["id"], match["file"], first, int(match["last"] or first), citation)
            )
    return found


def test_the_citation_sweep_finds_a_corpus_citation_in_every_task_4_decision() -> None:
    """Non-vacuity for the resolver below, and it runs everywhere.

    The resolver needs the DataCompany corpus, which is not checked out in CI. This half needs
    nothing: it proves the parse really reaches the register, so a regex that had stopped
    matching would be red here rather than turning the resolver into a green no-op.
    """
    citations = corpus_citations()
    assert len(citations) > 50, len(citations)
    ids = {decision_id for decision_id, *_ in citations}
    task_four = {
        decision["id"]
        for decision in load(DECISIONS)["decisions"]
        if decision["id"] >= "IMP-DEC-FND002-021"
    }
    # 041 records a DEFERRAL and 043 an accounting; both cite the corpus, so all of them do.
    assert task_four <= ids, sorted(task_four - ids)


def test_the_quoted_fragment_parser_pairs_quotes_not_apostrophes() -> None:
    """The control for ``QUOTED_FRAGMENT``, synthetic so a clean register cannot satisfy it.

    Every other assertion about the citation gate is a corpus assertion, and a corpus with no
    possessive in any citation cannot tell the two spellings apart -- which is how the bare
    ``'([^']*)'`` shipped. It fabricated a finding the day a citation used the word ``plan's``.
    """
    # THE DEFECT: the apostrophe must not open a run, so the gap between it and the real
    # opening quote is never extracted as if it were quoted text.
    citation = "the same plan's done-when names a DIFFERENT four: 'stale-rights and the rest'"
    assert QUOTED_FRAGMENT.findall(citation) == ["stale-rights and the rest"]

    # ...and the ordinary cases still work, so "matches nothing" cannot pass as "matches the
    # right thing". Two quotations in one citation is a shape the register really uses.
    assert QUOTED_FRAGMENT.findall("A says 'first quoted run' and B says 'second quoted run'") == [
        "first quoted run",
        "second quoted run",
    ]
    assert QUOTED_FRAGMENT.findall("opens a line with 'a quoted run'") == ["a quoted run"]
    # A quote opening after punctuation or a bracket is still a quote.
    assert QUOTED_FRAGMENT.findall("(see 'the quoted run')") == ["the quoted run"]

    # The DOCUMENTED residual, asserted rather than hoped: an apostrophe inside a run truncates
    # it. Stated here so the weakening is visible, and it is the safe direction -- the truncated
    # prefix is still a substring of the same corpus window.
    assert QUOTED_FRAGMENT.findall("cites 'each service's own schema'") == ["each service"]


#: A STANDING claim about the current value of ``DERIVATION_PROFILE_VERSION``, as opposed to a
#: historical statement about a transition. ``stays at 1`` is the first kind; ``bump 1 -> 2`` and
#: ``moved 1 -> 2`` are the second and are legitimate in a closed entry.
#:
#: The distinction is the whole point. Five entries -- D9, EXT-7.1, EXT-7.2, EXT-7.3 and
#: EXT-7.4 -- each said the constant "stays at 1", which was true when each was written and each
#: still meant "MY change did not bump it". The moment EXT-5.2 bumped it 1 -> 2, all five read as
#: false claims about a constant they never intended to pin. They are reworded to "did not
#: bump", which is the claim they were always making and is timeless.
STANDING_VERSION_CLAIM = re.compile(
    r"DERIVATION_PROFILE_VERSION\b[^.]{0,60}?"
    r"\b(?:stays? at|stays?|remains? at|remains?|is still|is currently)\s+(\d+)"
)


def _register_strings(node: Any) -> Iterator[str]:
    """Every string anywhere in the register, at any depth."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _register_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _register_strings(value)


def test_the_register_never_pins_the_derivation_profile_version_to_a_literal() -> None:
    """Register prose may not assert what ``DERIVATION_PROFILE_VERSION`` currently IS.

    This is a gate for a drift class nothing bound, and it is the class that actually occurred:
    prose in a JSON file making a standing claim about a constant that lives in code, where
    nothing recomputes the claim when the constant moves. Five entries carried "stays at 1"
    into a change that made it 2.

    A closed entry legitimately says what ITS change did -- "did not bump", "bump 1 -> 2" --
    because that is a fact about the change and cannot rot. What it may not do is describe the
    constant's present value, because the register is not where that value lives.

    Deliberately NOT written as "the register must agree with the imported constant". That
    would be the wrong fix twice over: it would force five entries that predate the bump to
    assert something about a bump they had no opinion on, and it would keep the coupling that
    caused the rot, merely automating it.
    """
    document = load(DECISIONS)
    offenders = [
        match.group(0)
        for text in _register_strings(document)
        for match in STANDING_VERSION_CLAIM.finditer(text)
    ]
    assert offenders == [], (
        "register prose pins a literal DERIVATION_PROFILE_VERSION; say what the change did, "
        f"not what the constant is: {offenders}"
    )

    # Non-vacuity: the walk must really reach the prose. A recursion that returned nothing
    # would satisfy the emptiness above over an empty population -- which is the exact shape of
    # every gate this register exists to catch.
    texts = list(_register_strings(document))
    assert len(texts) > 400, len(texts)
    assert sum("DERIVATION_PROFILE_VERSION" in text for text in texts) >= 5, (
        "no register text mentions the constant at all; this gate has stopped discriminating"
    )

    # The detector's discriminating power, synthetically, because the corrected register is
    # clean and a clean corpus cannot falsify a narrowed pattern.
    for fires in (
        "so DERIVATION_PROFILE_VERSION stays at 1 under the strict rule documented on x.",
        "DERIVATION_PROFILE_VERSION therefore stays at 1, by EXTENSIONS.md section 1.3's rule",
        "DERIVATION_PROFILE_VERSION remains 1",
        "DERIVATION_PROFILE_VERSION is still 2 after this",
        "DERIVATION_PROFILE_VERSION is currently 2",
    ):
        assert STANDING_VERSION_CLAIM.search(fires), fires
    # ...and the historical wording a closed entry is entitled to use, which is what stops this
    # from being a keyword ban that gets tuned until it is vacuous.
    for silent in (
        "CLOSED 2026-08-04, with a DERIVATION_PROFILE_VERSION bump 1 -> 2.",
        "DERIVATION_PROFILE_VERSION moved 1 -> 2 in the same change as every manifest",
        "so DERIVATION_PROFILE_VERSION did not bump for this change under the strict rule",
        "bumping DERIVATION_PROFILE_VERSION alone turns the version test red",
        "DERIVATION_PROFILE_VERSION exists precisely so a change cannot happen silently",
        "a manifest carrying profile_version 1 is refused 7/7",
    ):
        assert not STANDING_VERSION_CLAIM.search(silent), silent


#: A PRESENT-TENSE claim that some ``x-datacompany-*`` annotation is read by no engine code, in the
#: two spellings the register actually uses. Past-tense forms -- "was read by no code", "was
#: unread when this change was made" -- are deliberately NOT matched: an entry recording what
#: its own change found is stating a fact about a change, and a fact about a change cannot rot.
#: THE NAME AND THE CLAIM ARE SEPARATED BY A WINDOW, not required to be adjacent. Written
#: adjacent -- ``<name>\s+is\s+read by no code`` -- this pattern did not match the very sentence
#: it was built for, because the register says "x-datacompany-composition-point IS IN THAT SET and is
#: still read by no code". The gate passed its own defect and was found only by mutating the
#: ground truth rather than the prose. ``[^.]`` keeps the window inside one sentence.
PRESENT_TENSE_UNREAD_CLAIM = re.compile(
    r"`?(?P<name>x-datacompany-[a-z-]+)`?[^.]{0,80}?\b(?:is|are)\s+(?:still\s+)?read by no code"
    r"|no code[^.]{0,40}?\breads\s+`?(?P<name2>x-datacompany-[a-z-]+)`?"
)


def test_the_register_never_calls_an_annotation_unread_that_the_engine_reads() -> None:
    """Register prose claiming an annotation is unread must agree with the engine.

    THE DEFECT THIS CLOSES, which is the same shape as the ``stays at 1`` family one field over.
    Two entries asserted in the present tense that ``x-datacompany-composition-point`` "is still read
    by no code in either language", one of them citing a committed fixture control by name as the
    proof. Both were true when written. Implementing section 6.4 gave the annotation two readers
    and renamed that control, and nothing anywhere went red: the citation sweep in
    ``tests/test_extension_vocabulary.py`` reads only the meta-schema, ``EXTENSIONS.md`` and the
    released ``.ts`` sources, and the corpus sweep in this module matches ``file:line`` only. A
    governance artifact could name a fixture case that no longer exists, and assert a property of
    the engine that had stopped being true, with every gate green.

    GROUND TRUTH IS DERIVED, NOT LISTED. ``DECLARATIVE_ONLY`` is the set of vocabulary names no
    engine code reads, and it is itself bound to the engine by
    ``test_the_declarative_only_set_matches_what_the_engine_actually_reads``, which scans the
    canonical sources for member access. So this rule reduces to: the register may call an
    annotation unread exactly when the engine really does not read it. It needs no maintenance
    and it TIGHTENS on its own -- the day the last declarative-only name gets a reader, the set
    empties and any surviving present-tense claim in the register is red.

    SCOPE, stated rather than implied: this binds the annotation-readership sub-class only. The
    general "a register ``evidence`` field may name an artifact that does not exist" gap is NOT
    closed here, and a naive path-existence rule is the wrong instrument for it -- measured over
    this register, 21 of 49 cited paths do not resolve, in four legitimate classes: DataCompany
    corpus paths, forward citations to artifacts a sibling branch owns, language-relative
    shorthand (``src/rendering.ts``), and -- the one that matters -- deliberate references to
    files a change DELETED ("Replaces tests/test_fnd002_task4_blocked.py, which asserted the
    blocker"). That last is the historical form this repository has just decided to protect, so
    a rule forbidding it would be tuned until it was vacuous.
    """
    # Imported lazily: that module walks every committed schema at import time, and this is the
    # only test here that needs it.
    from test_extension_vocabulary import DECLARATIVE_ONLY, meta_schema

    unread_by_the_engine = frozenset(DECLARATIVE_ONLY)
    document = load(DECISIONS)

    offenders = [
        (match.group("name") or match.group("name2"), match.group(0))
        for text in _register_strings(document)
        for match in PRESENT_TENSE_UNREAD_CLAIM.finditer(text)
    ]
    wrong = [(name, quote) for name, quote in offenders if name not in unread_by_the_engine]
    assert wrong == [], (
        "the register says an annotation is read by no code, and the engine reads it. Say what "
        f"the change found, not what the vocabulary is today: {wrong}"
    )

    # Non-vacuity, both halves. The register currently makes NO present-tense claim of this
    # kind, so `offenders` is empty and the rule above holds over nothing -- which is exactly
    # the shape that must not be mistaken for a measurement.
    assert _register_strings is not None
    texts = list(_register_strings(document))
    assert sum("read by no code" in text for text in texts) >= 2, (
        "no register text discusses annotation readership at all; this gate has stopped "
        "discriminating"
    )

    # The detector must fire on a present-tense claim...
    for fires in (
        # THE REAL SENTENCE, restored verbatim from before the correction. It is first because
        # the adjacent-only spelling of this pattern matched every probe below and NOT this one
        # -- the name and the claim are eleven words apart -- so a gate built for this defect
        # would have shipped unable to see it.
        "x-datacompany-composition-point is IN that set and is still read by no code in either "
        "language -- recognising a name is not implementing it",
        "x-datacompany-composition-point is still read by no code in either language",
        "`x-datacompany-composition-point` is read by no code",
        "no code in either language reads x-datacompany-composition-point",
        "section 6.4 records that x-datacompany-composition-point is read by no code",
    ):
        assert PRESENT_TENSE_UNREAD_CLAIM.search(fires), fires
    # ...and stay silent on the past-tense record an entry is entitled to keep, which is the
    # whole distinction and the only thing separating this from a keyword ban.
    for silent in (
        # The corrected sentences, verbatim, so the two forms are pinned against each other.
        "x-datacompany-composition-point was IN that set and, WHEN THIS CHANGE WAS MADE, was read "
        "by no code in either language -- recognising a name is not implementing it",
        "x-datacompany-composition-point was read by no code in either language, and had to be "
        "given an implementation or retired",
        "`x-datacompany-composition-point` was read by no code in either language",
        "the annotation now has two readers",
    ):
        assert not PRESENT_TENSE_UNREAD_CLAIM.search(silent), silent

    # THE GROUND-TRUTH HALF NEEDS ITS OWN CONTROL, and this is the second hole mutation found
    # here. Because the corrected register makes NO present-tense claim, the rule above holds
    # over an empty population, so widening `unread_by_the_engine` to the WHOLE vocabulary --
    # which permits every possible claim -- was green against the entire suite. An allowlist
    # that has quietly grown to "everything" is indistinguishable from no allowlist at all.
    vocabulary = set(meta_schema()["$defs"]["vocabulary"]["enum"])
    assert len(vocabulary) >= 7, sorted(vocabulary)
    # It is the engine-derived set, re-asserted against the import rather than against whatever
    # local expression happens to be above.
    assert unread_by_the_engine == frozenset(DECLARATIVE_ONLY), sorted(unread_by_the_engine)
    # ...and it is a STRICT subset, so it can never mean "any claim is permitted". This holds
    # before and after section 6.4's closure: today it is one name of seven, afterwards none.
    assert unread_by_the_engine < vocabulary, sorted(unread_by_the_engine)
    assert unread_by_the_engine <= vocabulary, sorted(unread_by_the_engine - vocabulary)


#: The defect ids ``config/foundation-decisions.json`` is expected to carry OPEN.
#:
#: An equality, not a floor and not a blanket emptiness. Empty was the value from D9's closure
#: on 2026-08-03 until 2026-08-04; ``EXT-4.5-residual`` is the ``repr``-versus-canonical
#: rendering divergence, which EXTENSIONS.md section 4.5's closure explicitly does NOT cover and
#: which no gate in this repository can currently detect -- see that entry's own
#: ``what_it_breaks``.
EXPECTED_OPEN_DEFECTS = frozenset({"EXT-4.5-residual"})


def test_every_recorded_defect_is_either_open_or_resolved_and_never_just_deleted() -> None:
    """A defect that vanishes from the register is indistinguishable from one that was fixed.

    D3 (option B) and D8 (the whole-member order key) closed on 2026-07-30; D4 closed on
    2026-07-31 as REFUTED. All three moved to ``resolved_defects`` rather than being deleted,
    because a refuted defect and a forgotten one look identical once the entry is gone.

    Both halves are asserted, because each failure mode is real and they are different: the
    register carried D4 as open for a day after ``rc#16`` had already refuted it, and it never
    carried D9 at all -- D9 lived only in ``EXTENSIONS.md`` prose while being the mechanism a
    closed defect's evidence depends on. A resolved entry must carry
    ``status``/``taken``/``rejected``/``evidence``; an entry that says only "CLOSED" is the
    prose-only assertion this repository keeps finding.
    """
    register = load(DECISIONS)
    open_defects = {defect["id"] for defect in register["open_defects"]}
    resolved = {defect["id"]: defect for defect in register.get("resolved_defects", [])}

    assert {"D3", "D4", "D8", "D9"} <= set(resolved), sorted(resolved)

    # `open_defects` is compared to the set of ids the register is EXPECTED to carry open --
    # not asserted empty. The key still cannot be deleted (the shape check below), an empty
    # register is still assertable and was simply the expected value until 2026-08-04, and a
    # newly discovered defect is now a REVIEWED event: this line goes red, and someone updates
    # it deliberately.
    #
    # The blanket `== set()` it replaces was right about its reason and wrong about its
    # instrument. Its stated reason -- "an empty list and a deleted key are different facts,
    # and the second would make the whole register unfalsifiable" -- is defended by the shape
    # assertion, not by emptiness. What emptiness ADDED was a rule that recording any open
    # defect at all requires editing this file, which is usually not owned by whoever found the
    # defect; two agents hit it in one day, and the second was carrying a real finding it could
    # not file. A gate that blocks a legitimate change is the mirror of one that cannot fire.
    assert open_defects == EXPECTED_OPEN_DEFECTS, {
        "unexpected": sorted(open_defects - EXPECTED_OPEN_DEFECTS),
        "missing": sorted(EXPECTED_OPEN_DEFECTS - open_defects),
    }
    # THE KEY ITSELF, separately from its contents: an absent `open_defects` and an empty one
    # are different facts, and only this line can tell them apart -- `{... for ... in
    # register["open_defects"]}` over a missing key raises, but over a deleted key that some
    # future `.get("open_defects", [])` papered over it would silently be empty.
    assert "open_defects" in register, sorted(register)
    assert isinstance(register["open_defects"], list), type(register["open_defects"])
    assert not (open_defects & set(resolved)), "a defect is recorded as both open and resolved"

    # Every open entry carries the shape a reader needs to act on it, derived from D9's -- the
    # last real one, at 46062b1 -- rather than invented. An open defect that states no
    # mechanism and nothing it is blocked on is a label, not a record.
    for identifier in sorted(open_defects):
        defect = next(d for d in register["open_defects"] if d["id"] == identifier)
        assert defect["status"].startswith("OPEN"), identifier
        for field in ("title", "mechanism", "what_it_breaks", "options", "blocked_on"):
            assert defect.get(field), f"{identifier} records no {field}"

    for identifier, defect in resolved.items():
        assert defect["status"].startswith("CLOSED"), identifier
        assert defect.get("taken"), f"{identifier} records no decision"
        assert defect.get("rejected"), f"{identifier} records no rejected alternative"
        assert defect.get("evidence"), f"{identifier} names no evidence that it is closed"

    # A defect the register calls REFUTED must say what remains true, so a withdrawal cannot
    # quietly widen into "the whole area is fine". D4's schema-annotation half still is not.
    refuted = [d for d in resolved.values() if "REFUTED" in d["status"]]
    assert refuted, "no refuted defect found; this control has stopped discriminating"
    for defect in refuted:
        assert defect.get("as_recorded"), f"{defect['id']} does not quote what it refutes"
        assert defect.get("what_remains_true_and_is_narrower"), (
            f"{defect['id']} refutes a defect without stating what survives the refutation"
        )


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_every_fixture_names_a_released_schema_this_corpus_owns(kind: str) -> None:
    for path in fixtures(kind):
        ref = load(path)["schema_ref"]
        base = ref.partition("#")[0]
        assert base in FIXTURE_TARGETS, (
            f"{path.name} targets {base}, which this corpus does not own"
        )


def test_every_schema_this_corpus_owns_has_both_a_valid_and_an_invalid_fixture() -> None:
    """A schema exercised only in one direction is half-gated.

    Wave 1's finding was a shipped "valid" example that was itself invalid. The mirror of
    that -- a schema with no invalid fixture at all -- cannot be caught by replaying valid
    fixtures, however many there are. ``typed-refs:1`` shipped in exactly that state: four
    released ``$defs`` and not one instance of any of them anywhere.
    """
    seen: dict[str, set[str]] = {base: set() for base in FIXTURE_TARGETS}
    for kind in ("valid", "invalid"):
        for path in fixtures(kind):
            seen[load(path)["schema_ref"].partition("#")[0]].add(kind)
    missing = {
        base: sorted({"valid", "invalid"} - kinds) for base, kinds in seen.items() if len(kinds) < 2
    }
    assert missing == {}, missing


def test_every_typed_ref_is_instantiated_in_both_directions() -> None:
    """Per-``$def`` coverage, which the per-DOCUMENT check above cannot see.

    ``typed-refs:1`` is a ``$defs`` library: one valid and one invalid fixture against any
    single definition satisfies the document-level rule while three of the four released
    reference types stay uninstantiated. This counts them.
    """
    definitions = set(canonical_schemas()[TYPED_REFS]["$defs"])
    assert len(definitions) == 4, sorted(definitions)
    seen: dict[str, set[str]] = {name: set() for name in definitions}
    for kind in ("valid", "invalid"):
        for path in fixtures(kind):
            base, _, fragment = load(path)["schema_ref"].partition("#")
            if base == TYPED_REFS:
                seen[fragment.removeprefix("/$defs/")].add(kind)
    missing = {
        name: sorted({"valid", "invalid"} - kinds) for name, kinds in seen.items() if len(kinds) < 2
    }
    assert missing == {}, missing


# ================================================================ 3. falsifiability ===


def test_the_scope_conditional_rejects_a_nullable_tenant_and_accepts_its_absence() -> None:
    """IMP-DEC-FND002-001, with its false-positive control.

    The rejection alone would also be satisfied by a schema that rejected the whole global
    fixture for an unrelated reason. The control is the same instance without the mutated
    member.
    """
    clean = instance_of("valid", "context-global-scoped-minimal")
    assert validate_instance(clean, CONTEXT) == []

    nulled = {**clean, "resource_tenant_id": None}
    assert ("/", "unevaluatedProperties") in schema_failure_codes(nulled, CONTEXT) or (
        "/resource_tenant_id",
        "type",
    ) in schema_failure_codes(nulled, CONTEXT)
    assert validate_instance(nulled, CONTEXT) != []

    populated = {**clean, "resource_tenant_id": "11111111-1111-4111-8111-111111111111"}
    assert validate_instance(populated, CONTEXT) != [], (
        "a global-scoped context accepted a resource tenant; the released "
        "resource_scope_conditional is not composed"
    )


def test_the_context_interval_rule_is_evaluated_and_can_go_either_way() -> None:
    """The cross-field rule, both directions, including the D0 fractional-second case."""
    clean = instance_of("valid", "context-tenant-scoped-complete")
    assert validate_instance(clean, CONTEXT) == []

    for bad_expiry in (clean["requested_at"], "2026-07-30T09:59:59Z"):
        assert validate_instance({**clean, "expires_at": bad_expiry}, CONTEXT) != []

    # The control that D0 got wrong in BOTH directions: a valid fractional interval must
    # still pass, and its inversion must still fail.
    fractional = {
        **clean,
        "requested_at": "2026-07-30T10:00:00Z",
        "expires_at": "2026-07-30T10:00:00.5Z",
    }
    assert validate_instance(fractional, CONTEXT) == []
    inverted = {
        **clean,
        "requested_at": "2026-07-30T10:00:00.5Z",
        "expires_at": "2026-07-30T10:00:00Z",
    }
    assert validate_instance(inverted, CONTEXT) != []


def test_the_sort_uniqueness_rule_catches_what_unique_items_cannot() -> None:
    """The whole reason ``unique_by`` exists, demonstrated rather than asserted."""
    clean = instance_of("valid", "page-request-first-page")
    assert validate_instance(clean, f"{PAGE}#/$defs/page_request") == []

    duplicated = {
        **clean,
        "sort": [
            {"field": "published_at", "direction": "ascending"},
            {"field": "published_at", "direction": "descending"},
        ],
    }
    # uniqueItems does NOT catch it: the two objects genuinely differ.
    assert schema_failure_codes(duplicated, f"{PAGE}#/$defs/page_request") == []
    # The cross-field rule does.
    failures = validate_instance(duplicated, f"{PAGE}#/$defs/page_request")
    assert any("one_sort_key_per_field" in failure for failure in failures), failures


def test_the_page_envelope_refuses_a_total_but_accepts_the_members_it_releases() -> None:
    """IMP-DEC-FND002-016 with its control: the refusal is about ``total``, not about the
    envelope being unusable."""
    clean = instance_of("valid", "page-response-with-continuation")
    assert validate_instance(clean, f"{PAGE}#/$defs/page_response") == []
    assert validate_instance({**clean, "total": 10}, f"{PAGE}#/$defs/page_response") != []
    # ...and next_cursor: null is refused too, while an ABSENT next_cursor is fine.
    assert validate_instance({**clean, "next_cursor": None}, f"{PAGE}#/$defs/page_response") != []
    ended = {key: value for key, value in clean.items() if key != "next_cursor"}
    assert validate_instance(ended, f"{PAGE}#/$defs/page_response") == []


def test_problem_details_refuses_a_disclosing_member_and_a_success_status() -> None:
    clean = instance_of("valid", "problem-capability-unavailable")
    assert validate_instance(clean, PROBLEM) == []
    assert validate_instance({**clean, "resource_tenant_id": "x"}, PROBLEM) != []
    assert validate_instance({**clean, "status": 200}, PROBLEM) != []
    # Control: a different legitimate error status is still accepted, so the refusal above
    # is about the success range and not about `status` being unusable.
    assert validate_instance({**clean, "status": 429}, PROBLEM) == []


def test_a_capability_cannot_report_itself_available_off_a_broken_chain() -> None:
    clean = instance_of("valid", "capability-available-and-qualified")
    assert validate_instance(clean, CAPABILITY) == []
    for link in ("installed", "enabled", "qualified"):
        broken = {**clean, link: False}
        assert validate_instance(broken, CAPABILITY) != [], (
            f"available:true survived {link}:false, so the silent-substitution guard is not "
            "structural"
        )
    # And the reason conditional, both directions.
    assert validate_instance({**clean, "unavailable_reason": "unhealthy"}, CAPABILITY) != []
    unavailable = {**clean, "available": False}
    assert validate_instance(unavailable, CAPABILITY) != []
    assert validate_instance({**unavailable, "unavailable_reason": "unhealthy"}, CAPABILITY) == []


def test_the_run_manifest_acyclicity_rule_is_evaluated_and_has_a_control() -> None:
    clean = instance_of("valid", "run-manifest-all-nine-groups")
    assert validate_instance(clean, MANIFEST) == []

    output_pin = clean["outputs"]["artifact_refs"][0]["artifact_ref"]
    cyclic = json.loads(json.dumps(clean))
    cyclic["inputs"]["input_refs"] = [output_pin]
    # The schema layer accepts it -- a pin is a pin.
    assert schema_failure_codes(cyclic, MANIFEST) == []
    failures = validate_instance(cyclic, MANIFEST)
    assert any("a_run_output_is_not_also_its_own_input" in f for f in failures), failures


def test_the_run_manifest_hash_gate_is_falsifiable_in_both_directions() -> None:
    """An excluded pointer must NOT move the digest and an included one MUST."""
    fixture = load(FIXTURE_ROOT / "hash" / "run-manifest-all-nine-groups.json")
    profile = derive_hash_profile(MANIFEST)
    assert compute_content_hash(fixture["instance"], MANIFEST) == fixture["expected_content_hash"]

    excluded = json.loads(json.dumps(fixture["instance"]))
    excluded["aggregate_version"] = 4096
    excluded["content_hash"] = "sha256:" + "e" * 64
    excluded["run_ref"]["resolved_at"] = "2031-01-01T00:00:00Z"
    assert compute_content_hash(excluded, MANIFEST) == fixture["expected_content_hash"]

    included = json.loads(json.dumps(fixture["instance"]))
    included["method"]["seed"] = 1
    assert compute_content_hash(included, MANIFEST) != fixture["expected_content_hash"]

    # ...and the gate cannot be satisfied by a tampered profile: breaking an exclusion is
    # refused by the derivation check before any digest is produced.
    leaky = derive_hash_profile(MANIFEST)
    leaky["excluded_pointers"] = [
        entry for entry in leaky["excluded_pointers"] if entry["pointer"] != "/run_ref/resolved_at"
    ]
    with pytest.raises(HashProfileError):
        compute_content_hash(excluded, MANIFEST, profile=leaky)
    assert profile != leaky


def test_the_set_like_array_order_really_is_applied_to_the_run_manifest() -> None:
    """A set-like array reorder must NOT change the digest; an ordered one MUST.

    This is the one property that separates the two declarations, and without it every
    ``x-datacompany-array`` entry in the run manifest could be `ordered` and no fixture would
    notice.
    """
    fixture = load(FIXTURE_ROOT / "hash" / "run-manifest-all-nine-groups.json")
    base = fixture["instance"]
    digest = fixture["expected_content_hash"]

    two_params = json.loads(json.dumps(base))
    reversed_params = json.loads(json.dumps(base))
    reversed_params["inputs"]["parameters"] = list(reversed(two_params["inputs"]["parameters"]))
    assert reversed_params["inputs"]["parameters"] != two_params["inputs"]["parameters"]
    assert compute_content_hash(reversed_params, MANIFEST) == digest, (
        "/inputs/parameters is declared set-like, so member order must not reach the digest"
    )

    # D8, closed 2026-07-30. /method/packages is a set of SCALARS, which the manifest
    # vocabulary could not express until `order_key_pointer` admitted the whole-member
    # pointer. Reordering it used to change the digest -- two services holding the same
    # packages in two orders computed two different content hashes.
    reordered_packages = json.loads(json.dumps(base))
    reordered_packages["method"]["packages"] = list(reversed(base["method"]["packages"]))
    assert reordered_packages["method"]["packages"] != base["method"]["packages"], (
        "the reversal was a no-op, so this proves nothing about ordering"
    )
    assert compute_content_hash(reordered_packages, MANIFEST) == digest, (
        "/method/packages is declared set-like since D8, so member order must not reach the digest"
    )

    # The discriminating control: a set is order-insensitive, not content-insensitive. A
    # hash view that simply dropped the array would satisfy the assertion above.
    changed_packages = json.loads(json.dumps(base))
    changed_packages["method"]["packages"] = [
        *base["method"]["packages"][:-1],
        "a-package-that-was-not-there",
    ]
    assert compute_content_hash(changed_packages, MANIFEST) != digest, (
        "changing a package MEMBER did not change the digest, so /method/packages is not "
        "reaching the hash view at all"
    )


def test_the_generated_bindings_match_the_released_schemas() -> None:
    """The drift gate, exercised in-process as well as from CI."""
    from research_contracts.tooling.generate_types import main as generate

    assert generate(["--check"]) == 0


# ============================================================= 4. open defect D8 ===


def test_d8_a_set_like_array_of_scalars_is_now_declarable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D8 CLOSED 2026-07-30: the whole-member order key.

    Before this, ``hash_view_pointer`` required a leading ``/`` and ``minLength: 2``, so
    neither ``"/"`` nor RFC 6901's whole-document ``""`` was a legal ``order_key`` entry --
    and there was no third spelling of "the member itself". A set of scalars could not be
    declared at all, so seven released arrays that are semantically sets shipped ``ordered``
    with member order unguarded.

    ``order_key_pointer`` now admits ``""`` and ``hash_view._pointer_at`` resolves it to the
    member. This asserts the capability *and* that it actually sorts, which is the part that
    closes the two-orders-two-hashes divergence: a declaration that validated but did not
    reorder would look identical here without fixing anything.
    """
    import research_contracts.canonical.registry as registry_module

    probe_id = "urn:datacompany:d8-scalar-set-probe:1"
    probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": probe_id,
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "x-datacompany-array": {"kind": "set", "order_key": [""]},
            }
        },
    }
    schemas = {**canonical_schemas(), probe_id: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    profile = derive_hash_profile(probe_id)
    forward = build_hash_view({"tags": ["b", "a"]}, profile)
    backward = build_hash_view({"tags": ["a", "b"]}, profile)
    assert forward == backward, "the scalar set did not sort, so D8 is not actually closed"
    assert forward["tags"] == ["a", "b"], forward


def test_d8_the_whole_member_pointer_is_not_admitted_where_it_has_no_meaning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``""`` is legal in an ``order_key`` and nowhere else.

    ``order_key_pointer`` is deliberately a SEPARATE definition rather than a widening of
    ``hash_view_pointer``: widening the latter would have let ``""`` appear in
    ``included_pointers`` and ``excluded_pointers``, where "the whole instance" is not a
    path the hash view can include or exclude. This is the control that keeps the two
    languages apart -- without it, the fix could have been made by loosening one pattern and
    nobody would have noticed the blast radius.
    """
    profile_schema = canonical_schemas()["urn:datacompany:canonical-hash-profile:1"]
    validator = CanonicalValidator(
        profile_schema, registry=schema_registry(), format_checker=FormatChecker()
    )
    # Derived rather than hand-rolled: a hand-built profile missing a required member would
    # make every rejection below pass for the wrong reason.
    base = derive_hash_profile("urn:datacompany:run-manifest:1")
    assert not list(validator.iter_errors(base)), "the control profile must validate"

    for member in ("included_pointers", "opaque_pointers"):
        bad = {**base, member: [*base[member], ""]}
        assert list(validator.iter_errors(bad)), f'"" was accepted in {member}'
    bad_excluded = {
        **base,
        "excluded_pointers": [*base["excluded_pointers"], {"pointer": "", "reason": "signature"}],
    }
    assert list(validator.iter_errors(bad_excluded)), '"" was accepted in excluded_pointers'

    # ...and it IS accepted where it belongs.
    ok = {
        **base,
        "arrays": [*base["arrays"], {"pointer": "/tags", "kind": "set", "order_key": [""]}],
    }
    assert not list(validator.iter_errors(ok)), '"" was rejected in an order_key'


def test_d8_is_recorded_as_resolved_with_what_it_rejected() -> None:
    register = load(DECISIONS)
    resolved = {d["id"]: d for d in register.get("resolved_defects", [])}
    assert "D8" in resolved, sorted(resolved)
    assert resolved["D8"]["status"].startswith("CLOSED")
    assert resolved["D8"].get("rejected"), "D8 records no rejected alternative"
    assert "D8" not in {d["id"] for d in register["open_defects"]}


# ================================== 5. D4's residue, and the D9 it left load-bearing ===


def test_d4_the_schema_annotation_route_into_an_opaque_subtree_is_still_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4 was refuted, but only at the width it was written. This is what survived.

    ``rc#16`` proved an ``arrays``-only PROFILE EXTENSION declares a collection inside an
    opaque subtree without adding a declared child. It never tested the other route, and the
    other route is still shut: reaching ``/value/tags`` from a schema requires a ``properties``
    chain, ``hash_profile._Walker`` puts every ``properties`` name into ``included_pointers``,
    and a declared child beats opacity. Asserted here so the refutation cannot widen by
    retelling into "an opaque subtree with an array is fine".
    """
    import research_contracts.canonical.registry as registry_module

    probe_id = "urn:datacompany:d4-annotation-route-probe:1"
    probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": probe_id,
        "type": "object",
        "properties": {
            "value": {
                "type": "object",
                "x-datacompany-hash-opaque": True,
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "x-datacompany-array": {"kind": "set", "order_key": [""]},
                    }
                },
            }
        },
    }
    schemas = {**canonical_schemas(), probe_id: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)

    profile = derive_hash_profile(probe_id)
    # The mechanism, not just the symptom: the annotation put the child in included_pointers.
    assert "/value/tags" in profile["included_pointers"], profile["included_pointers"]
    assert profile["opaque_pointers"] == ["/value"], profile["opaque_pointers"]

    with pytest.raises(UndeclaredPathError) as raised:
        build_hash_view({"value": {"tags": ["b", "a"], "other": 1}}, profile)
    assert "/value/other" in str(raised.value), str(raised.value)

    # The control: the SAME subtree with no undeclared sibling hashes fine, so the raise is
    # about opacity having been destroyed, not about the probe being malformed.
    assert build_hash_view({"value": {"tags": ["b", "a"]}}, profile)["value"]["tags"] == [
        "a",
        "b",
    ]


def test_d9_the_runtime_route_still_works_and_the_schema_route_now_matches_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D9 CLOSED 2026-08-03. Rewritten as its own docstring instructed, not deleted.

    This test used to be titled "a runtime profile extension declares what no schema
    annotation can" and to pin D9 as OPEN: the two routes disagreed and only one was
    reachable from a committed schema. It carried its own rewrite instruction --
    "**This test pins a DEFECT, so closing D9 must make it red** ... rewrite this test to
    assert the rejection and move D9 to ``resolved_defects``; do not delete the assertion to
    make it pass."

    The prediction in that instruction was WRONG about the mechanism, and that is worth
    keeping. It expected D9 to close through the register's option (c) -- tightening
    ``validate_profile_against_schema`` to reject extras -- so that the call below would
    start raising. Option (c) turned out to be already enforced and a no-op (see the D9
    register entry's ``correction_option_c_was_a_no_op``). D9 closed instead by making the
    SCHEMA route reach the same manifest, so the runtime route keeps working unchanged and
    this call still succeeds.

    So the assertion that has to survive is no longer "the merge is accepted" on its own --
    which is now unremarkable -- but that the two routes AGREE. That is asserted here against
    the released envelope, and byte-for-byte in
    ``tests/test_declaration_only_annotation.py``.
    """
    reference = "urn:datacompany:bitemporal-assertion:1"
    base = derive_hash_profile(reference)
    assert base["opaque_pointers"] == ["/value"], base["opaque_pointers"]
    assert not any(entry["pointer"] == "/value/tags" for entry in base["arrays"])

    merged = merge_profile_extensions(
        base, {"arrays": [{"pointer": "/value/tags", "kind": "ordered"}]}
    )
    assert any(entry["pointer"] == "/value/tags" for entry in merged["arrays"])

    # The defect itself: the checker does not notice the extra declaration.
    validate_profile_against_schema(merged, reference)

    instance = {
        "assertion_id": "11111111-1111-4111-8111-111111111111",
        "assertion_version_id": "22222222-2222-4222-8222-222222222222",
        "subject_ref": {
            "owner_context": "probe",
            "entity_type": "probe_subject",
            "entity_id": "33333333-3333-4333-8333-333333333333",
            "resource_scope": "global",
        },
        "assertion_type": "probe_assertion",
        "value": {"tags": ["b", "a"], "other": 1},
        "valid_from": "2026-01-01T00:00:00Z",
        "recorded_at": "2026-01-01T00:00:00Z",
        "basis_refs": [],
    }
    view = build_hash_view(instance, merged)
    # Opacity intact: the undeclared sibling survived and the ordered array kept its order.
    assert view["value"] == {"tags": ["b", "a"], "other": 1}, view["value"]

    # The discriminating control. Without the extension the same instance raises, so the
    # extension is what carried it -- otherwise this test would pass against an engine that
    # ignored `arrays` entirely.
    with pytest.raises(UndeclaredArrayError):
        build_hash_view(instance, base)

    # ...and the half that closing D9 added: the SCHEMA route now reaches the same manifest,
    # so the runtime route is no longer the only one. An annotated mirror of the released
    # envelope must derive exactly what the merge produced.
    import json as _json_module

    mirror = _json_module.loads(_json_module.dumps(canonical_schemas()[reference]))
    value = mirror["$defs"]["assertion_fields"]["properties"]["value"]
    assert value["x-datacompany-hash-opaque"] is True, value
    value["properties"] = {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "x-datacompany-hash-declaration-only": True,
            "x-datacompany-array": {"kind": "ordered"},
        }
    }
    import research_contracts.canonical.registry as registry_module

    schemas = {**canonical_schemas(), reference: mirror}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    schema_route = derive_hash_profile(reference)
    assert schema_route == merged, "the schema route and the runtime route disagree"


def test_d9_is_recorded_as_resolved_with_what_it_rejected_and_what_it_measured() -> None:
    """D9 CLOSED 2026-08-03 by ``x-datacompany-hash-declaration-only`` (vocabulary 1.2).

    This test used to pin D9 as OPEN, and the test above it instructed its own rewrite --
    "when that day comes, rewrite this test to assert the rejection and move D9 to
    ``resolved_defects``; do not delete the assertion to make it pass". Rewritten, not
    deleted.

    An open defect that names no mechanism is a worry; a CLOSED one that names no
    measurement is a claim. D9's closure is an EQUALITY between two routes -- the schema
    route must derive a manifest byte-identical to the runtime-merged one -- so the entry has
    to carry what was measured and what was rejected, not only a status.
    """
    register = load(DECISIONS)
    resolved = {defect["id"]: defect for defect in register.get("resolved_defects", [])}
    assert "D9" in resolved, sorted(resolved)
    entry = resolved["D9"]
    assert entry["status"].startswith("CLOSED"), entry["status"]
    for member in ("taken", "rejected", "evidence", "hash_impact"):
        assert entry.get(member), f"D9 records no {member}"
    # The register named option (c) as "the smallest, and what #16 implicitly assumed". It
    # was already enforced and would have changed nothing, which is WHY the durable route was
    # taken -- so that correction has to survive in the record rather than leaving a
    # superseded options list readable as an untried alternative.
    assert entry.get("correction_option_c_was_a_no_op"), "D9 records no correction for (c)"
    assert "D9" not in {defect["id"] for defect in register["open_defects"]}


def test_no_released_array_is_an_ordered_collection_of_scalars() -> None:
    """The D8 exposure, measured from the corpus rather than listed by hand.

    A named list would have stayed green as the corpus grew; this recomputes it. It also
    corrects the register, which named FIVE arrays: it counted ``pack_refs`` (an alias for
    ``release_ref_list``, so not a seventh declaration) and missed ``use_modes`` and
    ``data_classes`` entirely. The real exposure was seven declarations.
    """
    scalars = {"string", "integer", "number", "boolean"}
    schemas = canonical_schemas()

    def resolve(node: Any, base: str) -> tuple[Any, str]:
        seen = 0
        while isinstance(node, dict) and "$ref" in node and seen < 10:
            node, base = resolve_ref(node["$ref"], base)
            seen += 1
        return node, base

    def is_scalar(items: Any, base: str) -> bool:
        items, base = resolve(items, base)
        if not isinstance(items, dict):
            return False
        if items.get("type") in scalars:
            return True
        if items.get("type") in ("object", "array"):
            return False
        if "enum" in items:
            return all(not isinstance(v, (dict, list)) for v in items["enum"])
        return "const" in items

    offenders: list[str] = []
    declarations = 0

    def walk(node: Any, schema_id: str, path: str) -> None:
        nonlocal declarations
        if isinstance(node, dict):
            annotation = node.get("x-datacompany-array")
            if isinstance(annotation, dict):
                declarations += 1
                if annotation.get("kind") == "ordered" and is_scalar(
                    node.get("items", {}), schema_id
                ):
                    offenders.append(f"{schema_id}{path}")
            for key, value in node.items():
                walk(value, schema_id, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, schema_id, f"{path}/{index}")

    for schema_id, document in sorted(schemas.items()):
        walk(document, schema_id, "")

    # Non-vacuity: an empty sweep would make the assertion below trivially true.
    assert declarations >= 10, f"only {declarations} array declarations found"

    # An EQUALITY against the recorded exceptions, not the empty list. The original assertion
    # read "their member order is unguarded and two orders hash differently", which is a defect
    # for a SET and the desired property for a SEQUENCE -- and until FND-002 task 4 the corpus
    # happened to hold only sets, so the heuristic and the rule agreed. A section path and a
    # bbox are sequences: sorting either changes what it addresses. IMP-DEC-FND002-032 records
    # both of them with the citation each is transcribed from, and the equality keeps the whole
    # gate: an ordered scalar array that is NOT recorded still turns this red, and a recorded
    # one that stops being declared turns it red from the other side.
    expected = expected_ordered_scalar_sequences()
    assert offenders == expected, {
        "declared but not recorded as a sequence": sorted(set(offenders) - set(expected)),
        "recorded as a sequence but no longer declared": sorted(set(expected) - set(offenders)),
    }


def expected_ordered_scalar_sequences() -> list[str]:
    """The ordered scalar arrays IMP-DEC-FND002-032 records as genuine sequences."""
    register = load(DECISIONS)
    entry = next(d for d in register["decisions"] if d["id"] == "IMP-DEC-FND002-032")
    recorded = entry["ordered_scalar_arrays_that_are_sequences"]
    assert recorded, "IMP-DEC-FND002-032 records no exception, so the equality is a decoy"
    return sorted(recorded)


def test_the_ordered_scalar_sweep_still_fires_on_an_unrecorded_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The RED half of the narrowing above, on a corpus the gate cannot have been tuned to.

    Narrowing an assertion from ``== []`` to ``== <recorded set>`` is exactly the move that
    turns a gate into a rubber stamp, so the narrowing is proven not to have done that: a
    schema declaring an ordered array of scalars that IMP-DEC-FND002-032 does not record is
    still found, and the same schema declaring it ``set`` is not.
    """
    import sys

    this_module = sys.modules[__name__]

    def probe(kind: str) -> dict[str, Any]:
        declaration: dict[str, Any] = {"kind": kind}
        if kind == "set":
            declaration["order_key"] = [""]
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:datacompany:ordered-scalar-probe:1",
            "type": "object",
            "properties": {
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "x-datacompany-array": declaration,
                }
            },
        }

    for kind, expected_extra in (("ordered", True), ("set", False)):
        document = probe(kind)
        schemas = {**canonical_schemas(), document["$id"]: document}
        # The sweep reads THIS module's `canonical_schemas` binding, so patching the registry
        # module would leave it reading the real corpus and the probe would prove nothing.
        monkeypatch.setattr(this_module, "canonical_schemas", lambda s=schemas: s)
        if expected_extra:
            with pytest.raises(AssertionError) as raised:
                test_no_released_array_is_an_ordered_collection_of_scalars()
            assert "urn:datacompany:ordered-scalar-probe:1/properties/labels" in str(raised.value)
        else:
            test_no_released_array_is_an_ordered_collection_of_scalars()


def test_the_schema_root_is_the_parent_of_the_canonical_tier() -> None:
    """Guards the relocation property the emptiness check depends on."""
    assert SCHEMA_ROOT.name == "schemas"
    for directory in foundation_schema_dirs():
        assert directory.parent == SCHEMA_ROOT


def test_a_relocated_canonical_tier_relocates_the_foundation_tiers_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Otherwise the "no schemas" guard is answerable from a tree the caller moved away from."""
    import research_contracts.canonical.registry as registry_module

    empty = tmp_path / "canonical"
    empty.mkdir()
    monkeypatch.setattr(registry_module, "CANONICAL_SCHEMA_DIR", empty)
    assert all(d.parent == tmp_path for d in registry_module.foundation_schema_dirs())


def test_a_cross_field_only_fixture_really_is_accepted_by_the_schema_layer() -> None:
    """The premise of the TypeScript suite's measured gap, asserted on the Python side.

    If a fixture marked ``cross_field_only`` were in fact schema-rejectable, the TypeScript
    suite would be asserting a false statement about the port's limitation.
    """
    marked = [path for path in fixtures("invalid") if load(path).get("cross_field_only")]
    assert len(marked) == 5, [p.name for p in marked]
    for path in marked:
        fixture = load(path)
        assert schema_failure_codes(fixture["instance"], fixture["schema_ref"]) == [], path.name
        with pytest.raises(CrossFieldError):
            from research_contracts.canonical import assert_valid_instance

            assert_valid_instance(fixture["instance"], fixture["schema_ref"])


# ============================================== 6. FND-002 task 4: the evidence tier ===
#
# Every rule the evidence tier adds is proven able to REJECT, one member at a time, each with
# a control that isolates what was mutated. The corpus carries the same facts as fixtures;
# these assert them in-process as well, because a fixture proves the corpus is consistent and
# a test proves the RULE is what does the rejecting.

EVIDENCE_CLEAN = "evidence-location-document-selector"

#: Document 16 lines 867-868 name six; implementation-plans/13-hirag-service.md:367 adds
#: ``selection_digest``, implementation-plans/11-ingestion-documents.md:122 adds any object or
#: storage key, and implementation-plans/05-guideline-registry-8814.md:1086-1087 adds the
#: authorization receipt -- NINE, not eight. The ninth was refused all along and cited nowhere,
#: which is an evidence gap rather than a hole: an incidental refusal and an intended one are
#: indistinguishable until one is written down. Parametrised so each is its own red, with its
#: own name in the report: an omnibus assertion would stay green while eight of the nine
#: refusals silently stopped.
RIGHTS_BEARING_MEMBERS = [
    ("current_right", {"decision": "authorized", "valid_until": "2026-08-30T10:00:00Z"}),
    ("actor_or_service_ref", "service:hirag"),
    ("requested_action", "render"),
    ("requested_use_basis", "internal_review"),
    ("expiring_url", "https://example.invalid/o/1?expires=1790000000"),
    ("rendered_bytes", "<rendered bytes are never carried on a location>"),
    ("selection_digest", "sha256:" + "8" * 64),
    ("storage_key", "s3://evidence/2026/07/30/0f2a.pdf"),
    ("evidence_resolution_receipt_ref", {"entity_type": "evidence_resolution_receipt"}),
]


def test_the_clean_evidence_location_validates_which_is_the_control_for_all_of_the_below() -> None:
    """THE FALSE-POSITIVE CONTROL for every rejection in this section.

    Without it, a schema that rejected the whole instance for an unrelated reason would
    satisfy all eight rights-neutrality assertions, the XOR, the discriminator and the depth
    conditional at once.
    """
    assert validate_instance(instance_of("valid", EVIDENCE_CLEAN), LOCATION) == []


@pytest.mark.parametrize(
    ("member", "value"), RIGHTS_BEARING_MEMBERS, ids=[m for m, _ in RIGHTS_BEARING_MEMBERS]
)
def test_the_evidence_location_refuses_each_rights_bearing_member_on_its_own(
    member: str, value: Any
) -> None:
    """Rights-neutrality, falsified one member at a time and for the right reason.

    ``unevaluatedProperties`` is asserted specifically rather than "it failed somehow": a
    rejection under any other keyword would mean the member had been declared and then
    constrained, which is a different contract from one that does not carry it at all.
    """
    clean = instance_of("valid", EVIDENCE_CLEAN)
    assert member not in clean, f"{member} is in the clean instance; this proves nothing"
    codes = schema_failure_codes({**clean, member: value}, LOCATION)
    assert ("/", "unevaluatedProperties") in codes, codes
    assert validate_instance({**clean, member: value}, LOCATION) != []


#: Every member name the two evidence documents' composed closure DECLARES, measured
#: 2026-08-02 by ``composed_member_closure`` below and pinned as an equality.
#:
#: This is what ``unevaluatedProperties: false`` cannot do on its own. That keyword refuses a
#: member NO composed subschema evaluated; it is powerless against one that a composed ``$ref``
#: declares. Measured: adding ``created_by`` to ``identity-ref:1#/$defs/identity_ref_fields``
#: made ``{...location, "created_by": "svc-render-worker"}`` VALID against the location, and
#: the eight named rights refusals -- which only cover members declared ON the record -- all
#: stayed green. The location's ``$comment`` asserts that "no actor reaches this record even
#: through the envelope"; that is a claim about the whole composed member set, so the whole
#: composed member set is what is pinned.
COMPOSED_MEMBERS = {
    LOCATION: [
        "artifact_ref",
        "content_hash",
        "coordinate_manifest_ref",
        "document_version_ref",
        "entity_id",
        "entity_type",
        "evidence_location_id",
        "language",
        "owner_context",
        "quoted_text_digest",
        "resolved_at",
        "resource_scope",
        "resource_tenant_id",
        "schema_ref",
        "selector",
        "selector_schema_ref",
        "selector_type",
        "version_id",
        "version_number",
    ],
    CANDIDATE: [
        "artifact_ref",
        "coordinate_manifest_ref",
        "derivation_provenance_refs",
        "document_version_ref",
        "language",
        "quoted_text_digest",
        "selector",
        "selector_schema_ref",
        "selector_type",
    ],
}

#: Member names that would carry an ACTOR onto a record document 16 lines 867-868 declares
#: rights-neutral. Names, not a concept: the equality pin above is what makes the claim total,
#: and this list is the behavioural half that proves the pin is about a live mechanism.
ACTOR_BEARING_MEMBER_NAMES = [
    "created_by",
    "updated_by",
    "actor_id",
    "actor_ref",
    "authored_by",
    "registered_by",
    "requested_by",
    "resolved_by",
]


def composed_member_closure(schema_ref: str) -> set[str]:
    """Every property name reachable from a document's root ``allOf``, following ``$ref``.

    Resolution goes through the real registry rather than through a local copy, so a member
    added anywhere in the composed graph -- ``identity_ref_fields``, ``pin_fields``,
    ``selector_fields``, any of them -- lands here.
    """
    seen: set[str] = set()

    def walk(node: Any, base: str) -> set[str]:
        if not isinstance(node, dict):
            return set()
        names: set[str] = set()
        ref = node.get("$ref")
        if isinstance(ref, str):
            target = ref if not ref.startswith("#") else f"{base}{ref}"
            if target not in seen:
                seen.add(target)
                resolved, resolved_base = resolve_ref(ref, base)
                names |= walk(resolved, resolved_base)
        if isinstance(node.get("properties"), dict):
            names |= set(node["properties"])
        for keyword in ("allOf", "anyOf", "oneOf"):
            for branch in node.get(keyword, []) or []:
                names |= walk(branch, base)
        for keyword in ("if", "then", "else"):
            if keyword in node:
                names |= walk(node[keyword], base)
        return names

    schema = canonical_schemas()[schema_ref]
    return {name for branch in schema.get("allOf", []) for name in walk(branch, schema_ref)}


@pytest.mark.parametrize("schema_ref", sorted(COMPOSED_MEMBERS), ids=lambda r: r.split(":")[-2])
def test_the_composed_member_set_of_each_evidence_document_is_pinned_exactly(
    schema_ref: str,
) -> None:
    """The location's rights-neutrality ``$comment``, as something that can fail.

    An EQUALITY over the closure, deliberately, rather than a list of forbidden names. The
    ``$comment`` claims something universal -- that no actor reaches this record through the
    envelope -- and a list of names can only ever refuse the names someone thought to write
    down: it catches ``created_by`` and lets ``authored_by`` through. The equality is total
    over the composed graph, so ANY member arriving from ANY composed ``$ref`` is red,
    whatever it is called and whoever added it.

    It is structural, and a structural assertion can pass while the mechanism it describes is
    broken, which is why
    ``test_an_actor_bearing_member_is_refused_on_a_full_valid_instance`` sits beside it: that
    one proves the root really does seal, and this one proves the seal has nothing to let
    through. Neither is sufficient alone.
    """
    assert composed_member_closure(schema_ref) == set(COMPOSED_MEMBERS[schema_ref])


@pytest.mark.parametrize("schema_ref", sorted(COMPOSED_MEMBERS), ids=lambda r: r.split(":")[-2])
@pytest.mark.parametrize("member", ACTOR_BEARING_MEMBER_NAMES)
def test_an_actor_bearing_member_is_refused_on_a_full_valid_instance(
    schema_ref: str, member: str
) -> None:
    """The behavioural half: the root seal is live, on a COMPLETE instance of each document.

    A full valid instance, not a fragment, so the rejection cannot be the record failing for
    some unrelated reason -- the control is that the same instance without the member
    validates. ``unevaluatedProperties`` is asserted specifically: a rejection under any other
    keyword would mean the member had been declared and then constrained, which is a different
    contract from one that does not carry it at all.
    """
    clean = instance_of("valid", SELECTOR_CARRIERS[schema_ref])
    assert validate_instance(clean, schema_ref) == [], schema_ref
    assert member not in clean, f"{member} is in the clean instance; this proves nothing"
    codes = schema_failure_codes({**clean, member: "svc-render-worker"}, schema_ref)
    assert ("/", "unevaluatedProperties") in codes, codes


@pytest.mark.parametrize(
    ("member", "value"),
    [entry for entry in RIGHTS_BEARING_MEMBERS if entry[0] == "selection_digest"],
    ids=["selection_digest"],
)
def test_the_candidate_refuses_the_receipt_only_digest_too(member: str, value: Any) -> None:
    """The same refusal on the OTHER document, which reaches it through a different boundary.

    implementation-plans/13-hirag-service.md:367 addresses the deriving context, so the
    candidate is where that sentence actually bites. The location passing proves nothing here:
    the candidate composes no envelope at all and seals a completely different member set.
    """
    clean = instance_of("valid", "evidence-location-candidate-transcript-selector")
    assert validate_instance(clean, CANDIDATE) == []
    codes = schema_failure_codes({**clean, member: value}, CANDIDATE)
    assert ("/", "unevaluatedProperties") in codes, codes


def test_the_target_ref_alternative_rejects_both_rejects_neither_and_accepts_exactly_one() -> None:
    """Document 16 line 859, all three cases, because two of them are how it is got wrong.

    A schema that merely declared both members optional accepts "neither"; a schema that used
    ``anyOf`` accepts "both". Only the third case is what the citation states.
    """
    clean = instance_of("valid", EVIDENCE_CLEAN)
    artifact = instance_of("valid", "evidence-location-tabular-selector-by-row-index")[
        "artifact_ref"
    ]

    # Exactly one, in each direction: the two committed valid fixtures already carry one each.
    assert validate_instance(clean, LOCATION) == []
    assert "document_version_ref" in clean and "artifact_ref" not in clean

    both = {**clean, "artifact_ref": artifact}
    assert ("/", "oneOf") in schema_failure_codes(both, LOCATION)

    neither = {key: value for key, value in clean.items() if key != "document_version_ref"}
    assert ("/", "oneOf") in schema_failure_codes(neither, LOCATION)


def test_the_discriminator_and_the_selector_union_are_cross_linked() -> None:
    """The one thing a shape-only union does NOT give you, and the reason the guards exist.

    The mismatched instance is well formed on both sides: ``tabular`` is a member of the closed
    kind enum and the body is a valid member of the union. Nothing but the guard relates them,
    and the failure has to land under ``/selector`` -- a rejection at the root would mean
    something else refused it.
    """
    clean = instance_of("valid", EVIDENCE_CLEAN)
    mismatched = {**clean, "selector_type": "tabular"}
    codes = schema_failure_codes(mismatched, LOCATION)
    assert ("/selector", "unevaluatedProperties") in codes, codes
    # ...and the same body under its OWN kind is accepted, so the guard discriminates rather
    # than rejecting the document selector generally.
    assert validate_instance(clean, LOCATION) == []


#: One committed valid instance per declared selector kind, and the two documents that carry a
#: selector. Every body below is read out of a RELEASED fixture rather than written here, so
#: this cannot pass against a union that has drifted from what the corpus actually ships.
SELECTOR_BODY_FIXTURES = {
    "code": "evidence-location-candidate-code-selector",
    "document": "evidence-location-document-selector",
    "media": "evidence-location-media-selector",
    "notebook": "evidence-location-notebook-selector",
    "tabular": "evidence-location-tabular-selector-by-row-index",
    "transcript": "evidence-location-candidate-transcript-selector",
}

#: The two documents that COMPOSE the guards. The guards are declared in locator-selector:1
#: and are inert there: what makes them bite is the ``$ref`` from each of these two roots.
SELECTOR_CARRIERS = {
    LOCATION: EVIDENCE_CLEAN,
    CANDIDATE: "evidence-location-candidate-transcript-selector",
}

#: 2 documents x 6 declared x 5 mismatched bodies. Named so the count is a statement rather
#: than an artefact of however many ids ``parametrize`` happened to generate.
SELECTOR_MISMATCH_PAIRS = [
    (carrier, declared, body)
    for carrier in SELECTOR_CARRIERS
    for declared in SELECTOR_BODY_FIXTURES
    for body in SELECTOR_BODY_FIXTURES
    if declared != body
]


def selector_body(kind: str) -> Any:
    """The released selector body for ``kind``, taken from its committed valid fixture."""
    return json.loads(json.dumps(instance_of("valid", SELECTOR_BODY_FIXTURES[kind])["selector"]))


def test_the_selector_body_map_is_total_over_the_released_kind_enum() -> None:
    """Non-vacuity for the cross-product below: a missing kind would silently shrink it.

    The map is keyed by hand and the enum is released, so the two are asserted equal rather
    than assumed to be. Five of the six kinds had a committed instance and ``notebook`` had
    none, which is exactly the shape of drift this catches: the kind stays declarable, no
    fixture uses it, and every test that iterates over fixtures skips it.
    """
    declared = set(canonical_schemas()[SELECTOR]["$defs"]["selector_kind"]["enum"])
    assert set(SELECTOR_BODY_FIXTURES) == declared, SELECTOR_BODY_FIXTURES
    assert len(SELECTOR_MISMATCH_PAIRS) == 60, len(SELECTOR_MISMATCH_PAIRS)


@pytest.mark.parametrize("carrier", sorted(SELECTOR_CARRIERS), ids=lambda ref: ref.split(":")[-2])
@pytest.mark.parametrize("kind", sorted(SELECTOR_BODY_FIXTURES))
def test_each_selector_kind_is_accepted_on_each_carrier_under_its_own_discriminator(
    carrier: str, kind: str
) -> None:
    """THE FALSE-POSITIVE CONTROL for the 60 rejections below, all twelve of them.

    Without this half, a document that had lost the ``selector_fields`` composition entirely --
    or a body map pointing at nonsense -- would refuse every pairing and satisfy all sixty
    mismatch assertions at once. Every kind must be reachable on every carrier, and the base
    instance is swapped to that kind rather than a per-kind instance being loaded, so the only
    thing varying between the accepted and the refused case is the pairing itself.
    """
    base = instance_of("valid", SELECTOR_CARRIERS[carrier])
    probe = {**base, "selector_type": kind, "selector": selector_body(kind)}
    assert validate_instance(probe, carrier) == [], (carrier, kind)


@pytest.mark.parametrize(
    ("carrier", "declared", "body"),
    SELECTOR_MISMATCH_PAIRS,
    ids=[f"{c.split(':')[-2]}-{d}-carrying-{b}" for c, d, b in SELECTOR_MISMATCH_PAIRS],
)
def test_a_mismatched_selector_body_is_refused_on_both_carriers_for_every_kind(
    carrier: str, declared: str, body: str
) -> None:
    """The composition, not the declaration: all 60 ordered pairs, on BOTH documents.

    ``test_every_declared_selector_kind_is_reachable`` asserts the six guards EXIST inside
    ``locator-selector:1``. That is a statement about a ``$defs`` library, and a ``$defs``
    library constrains nothing: the guards only bite where a root ``allOf`` composes them.
    Measured before this test was written -- deleting any ONE of the twelve
    ``*_selector_guard`` ``$ref``s from the two roots left the whole suite green for eleven of
    them, and with the media guard gone ``selector_type: media`` carrying a full DOCUMENT body
    was ACCEPTED. One behavioural case per guard per carrier is the minimum that cannot say
    that.

    Behavioural rather than structural on purpose. Asserting that the twelve ``$ref``s are
    present would pass while a guard was composed and broken -- a wrong ``const``, a ``then``
    pointing at the wrong body, a lost ``required`` -- and this asserts what the union does.

    The failure must land under ``/selector``: both halves are well formed on their own, the
    declared kind is in the closed enum and the body is a valid member of ``any_selector``, so
    a rejection at ``/`` would mean the root refused it for some other reason and the guard
    never ran.
    """
    base = instance_of("valid", SELECTOR_CARRIERS[carrier])
    probe = {**base, "selector_type": declared, "selector": selector_body(body)}
    codes = schema_failure_codes(probe, carrier)
    assert [code for code in codes if code[0] == "/selector"], codes


@pytest.mark.parametrize("kind", ["code", "document", "media", "notebook", "tabular", "transcript"])
def test_every_declared_selector_kind_is_reachable(kind: str) -> None:
    """A closed enum with an unreachable member is a contract nobody can satisfy.

    Six guards, six bodies: if any pairing were wrong the kind would be declarable and never
    instantiable, and no fixture that did not happen to use it would notice.
    """
    definitions = canonical_schemas()[SELECTOR]["$defs"]
    assert set(definitions["selector_kind"]["enum"]) == {
        "code",
        "document",
        "media",
        "notebook",
        "tabular",
        "transcript",
    }
    assert f"{kind}_selector" in definitions
    guard = definitions[f"{kind}_selector_guard"]
    assert guard["if"]["properties"]["selector_type"]["const"] == kind
    assert guard["then"]["properties"]["selector"]["$ref"] == f"#/$defs/{kind}_selector"


@pytest.mark.parametrize("kind", sorted(SELECTOR_BODY_FIXTURES))
def test_the_required_discriminator_inside_each_guard_is_load_bearing(kind: str) -> None:
    """``required: ["selector_type"]`` inside EVERY ``if``, proven by removing it, per guard.

    ``properties`` says nothing about an ABSENT member, so without the ``required`` the guard's
    ``if`` is vacuously true on any instance that omits the discriminator, and its ``then``
    narrows ``selector`` to a body that instance is not. The released form ignores such an
    instance entirely and lets ``selector_fields``' own ``required`` report the real fault.

    Parametrised over all six. This test previously read ``document_selector_guard`` alone
    while its name claimed a property of each: deleting ``required: ["selector_type"]`` from
    the other five was invisible to the entire suite. The impact is diagnostic rather than
    structural -- ``selector_fields.required`` still refuses an instance with no discriminator
    at the root -- but a test that names a property of six things and checks one of them is the
    same defect whatever the blast radius.

    The released ``then`` is kept -- it is not rewritten to point somewhere else -- and the
    discriminating body is another kind's, so what is measured is the released ``then``
    narrowing to the released body. The guard's ``$ref``s are relative to
    ``locator-selector:1`` and the probe below is a different document, so they are rebased
    onto that URN; the rebase is applied IDENTICALLY to both probes, which differ only in the
    ``required`` under test, and the rebased target is asserted to be the released body.
    """
    released = canonical_schemas()[SELECTOR]["$defs"][f"{kind}_selector_guard"]

    def rebase(node: Any) -> Any:
        """Rewrite the guard's ``locator-selector:1``-relative ``$ref``s onto that URN.

        Mechanical and total, and applied to the guarded and unguarded copies alike, so it
        cannot be what produces the difference between them.
        """
        if isinstance(node, dict):
            return {
                key: f"{SELECTOR}{value}"
                if key == "$ref" and isinstance(value, str) and value.startswith("#")
                else rebase(value)
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [rebase(item) for item in node]
        return node

    def probe(guard: dict[str, Any]) -> Any:
        return CanonicalValidator(
            {
                "type": "object",
                "properties": {"selector": {"$ref": f"{SELECTOR}#/$defs/any_selector"}},
                "allOf": [guard],
            },
            registry=schema_registry(),
            format_checker=FormatChecker(),
        )

    # A well-formed body of SOME OTHER kind, carrying no discriminator at all. It is a valid
    # member of `any_selector`, so the union alone accepts it and only the `then` can refuse it.
    other = sorted(set(SELECTOR_BODY_FIXTURES) - {kind})[0]
    instance = {"selector": selector_body(other)}
    guarded = rebase(json.loads(json.dumps(released)))
    assert guarded["then"]["properties"]["selector"]["$ref"] == f"{SELECTOR}#/$defs/{kind}_selector"
    unguarded = json.loads(json.dumps(guarded))
    # `pop`, not `del`: if the released guard ever loses this member the BEHAVIOURAL assertions
    # below have to be what reports it. A KeyError raised while building the probe is a broken
    # test, not a red proof, and it would say nothing about what the schema now accepts.
    unguarded["if"].pop("required", None)

    assert list(probe(unguarded).iter_errors(instance)), (
        f"an absent selector_type did NOT satisfy the unguarded `if` of {kind}_selector_guard, "
        "so this probe is not reproducing the vacuity the released `required` exists to rule out"
    )
    assert not list(probe(guarded).iter_errors(instance)), (
        f"the RELEASED {kind}_selector_guard rejected an instance carrying no discriminator at "
        "all, which is what happens when `required: [selector_type]` is dropped from its `if`: "
        "the guard becomes vacuously true and narrows `selector` to a body the instance is not"
    )
    assert released["if"].get("required") == ["selector_type"], released["if"]


def test_the_scope_conditional_fires_inside_a_selector_branch_and_at_depth() -> None:
    """The literal "identical at every nesting depth, without weakening" clause.

    Asserted where it is hardest and therefore where it matters: the record is tabular-kinded
    so a selector guard is actively narrowing ``selector``, and the violation is three composed
    documents down -- evidence-location into typed-refs into pinned-version-ref -- rather than
    at the root. The failure pointer is asserted, not just the fact of failure: a rejection at
    ``/`` would mean the outer boundary refused it and the nested conditional never ran.
    """
    clean = instance_of("valid", "evidence-location-tabular-selector-by-row-index")
    assert validate_instance(clean, LOCATION) == []
    assert clean["selector_type"] == "tabular"
    assert clean["artifact_ref"]["resource_scope"] == "global"

    leaky = json.loads(json.dumps(clean))
    leaky["artifact_ref"]["resource_tenant_id"] = "11111111-1111-4111-8111-111111111111"
    codes = schema_failure_codes(leaky, LOCATION)
    assert ("/artifact_ref", "not") in codes, codes

    # ...and the other direction of the same conditional, also at depth: a tenant-scoped pin
    # with no tenant. Without this the assertion above would also be satisfied by a schema that
    # forbade resource_tenant_id everywhere.
    stripped = json.loads(json.dumps(instance_of("valid", EVIDENCE_CLEAN)))
    assert stripped["document_version_ref"]["resource_scope"] == "tenant"
    del stripped["document_version_ref"]["resource_tenant_id"]
    assert ("/document_version_ref", "required") in schema_failure_codes(stripped, LOCATION)


def test_the_typed_alias_equality_is_evaluated_and_the_schema_layer_cannot_see_it() -> None:
    """IMP-DEC-FND002-034, both halves.

    The schema layer accepting it is not incidental -- it is the whole reason the mapping has to
    be a released rule. Asserting only that the mismatched instance fails would be satisfied by
    a schema that rejected it for an unrelated reason.
    """
    clean = instance_of("valid", EVIDENCE_CLEAN)
    mismatched = {**clean, "evidence_location_id": "e71d9999-9999-4999-8999-999999999999"}
    assert schema_failure_codes(mismatched, LOCATION) == []
    failures = validate_instance(mismatched, LOCATION)
    assert any(
        "evidence_location_id_is_the_typed_alias_of_entity_id" in failure for failure in failures
    ), failures
    # The control: the same instance with the two members agreeing passes BOTH layers.
    assert validate_instance(clean, LOCATION) == []


def test_evidence_location_id_is_required_on_the_location_and_refused_on_the_candidate() -> None:
    """Document 16 line 846 against document 16 line 841, as one assertion.

    These are the two halves of the same sentence and each is a different failure mode: a
    candidate that carried the ID would be indistinguishable from a registered location, and a
    location that omitted it would have no typed alias for its own identity.
    """
    location = instance_of("valid", EVIDENCE_CLEAN)
    without_id = {k: v for k, v in location.items() if k != "evidence_location_id"}
    assert ("/", "required") in schema_failure_codes(without_id, LOCATION)

    candidate = instance_of("valid", "evidence-location-candidate-transcript-selector")
    assert "evidence_location_id" not in candidate
    with_id = {**candidate, "evidence_location_id": location["evidence_location_id"]}
    assert ("/", "unevaluatedProperties") in schema_failure_codes(with_id, CANDIDATE)


def test_the_evidence_location_removes_its_own_content_hash_from_its_own_hash_view() -> None:
    """IMP-DEC-FND002-033's found_by, as an executable assertion.

    ``pin_fields`` declares ``content_hash`` as a PINNED TARGET's hash, which stays inside the
    enclosing view; composed at a record root the same member is the record's OWN hash. The
    first draft of this schema left it included, so computing the record's content hash
    depended on the value it produced. Both directions are asserted, because an exclusion that
    dropped the member from the view entirely would satisfy the first half alone.
    """
    profile = derive_hash_profile(LOCATION)
    excluded = {entry["pointer"]: entry["reason"] for entry in profile["excluded_pointers"]}
    assert excluded.get("/content_hash") == "own_content_hash", excluded

    clean = instance_of("valid", EVIDENCE_CLEAN)
    digest = compute_content_hash(clean, LOCATION)
    assert compute_content_hash({**clean, "content_hash": "sha256:" + "9" * 64}, LOCATION) == digest

    # The discriminating control: an INCLUDED member still moves the digest, so the exclusion
    # above is about this pointer and not about the hash view having stopped reading the record.
    moved = json.loads(json.dumps(clean))
    moved["selector"]["page"] = 13
    assert compute_content_hash(moved, LOCATION) != digest


def test_the_ordered_selector_sequences_really_are_order_sensitive() -> None:
    """IMP-DEC-FND002-032, demonstrated rather than argued.

    The decision claims that sorting a section path or a bbox would change what the selector
    addresses. That is only an argument for ``kind: ordered`` if member order actually reaches
    the digest, which is what this measures.
    """
    clean = instance_of("valid", EVIDENCE_CLEAN)
    digest = compute_content_hash(clean, LOCATION)
    for pointer in ("section_path", "bbox"):
        reordered = json.loads(json.dumps(clean))
        reordered["selector"][pointer] = list(reversed(reordered["selector"][pointer]))
        assert reordered["selector"][pointer] != clean["selector"][pointer], pointer
        assert compute_content_hash(reordered, LOCATION) != digest, (
            f"/selector/{pointer} is declared ordered, so reversing it must change the digest; "
            "if it does not, the declaration is not reaching the hash view"
        )


def test_a_selector_cross_field_rule_would_fire_across_every_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measured engine limit IMP-DEC-FND002-028 is forced by, asserted rather than quoted.

    Rule collection is static over the whole schema tree, so a rule declared in one guard's
    ``then`` is collected once and evaluated for every instance whatever its ``selector_type``.
    This is what makes a per-kind cross-field invariant impossible and the row XOR plain JSON
    Schema. Proven by planting one and watching it fire on the wrong kind.
    """
    import research_contracts.canonical.registry as registry_module
    import research_contracts.canonical.structural as structural_module

    probe_id = "urn:datacompany:per-branch-rule-probe:1"
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": probe_id,
        "type": "object",
        "allOf": [
            {
                "if": {
                    "required": ["selector_type"],
                    "properties": {"selector_type": {"const": "document"}},
                },
                "then": {
                    "x-datacompany-cross-field": [
                        {
                            "rule": "equal",
                            "name": "a_rule_that_only_looks_like_it_belongs_to_one_branch",
                            "scope": "relative",
                            "left": "/selector/page",
                            "right": "/selector/page",
                        }
                    ]
                },
            }
        ],
    }
    schemas = {**canonical_schemas(), probe_id: document}
    try:
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
        structural_module._collect.cache_clear()
        from research_contracts.canonical import check_cross_field_rules

        tabular = {"selector_type": "tabular", "selector": {"sheet_or_table_id": "s"}}
        failures = check_cross_field_rules(tabular, probe_id)
        assert any(
            "a_rule_that_only_looks_like_it_belongs_to_one_branch" in failure
            for failure in failures
        ), (
            "the branch rule did NOT fire on a tabular instance, so this engine limit no longer "
            "holds and IMP-DEC-FND002-028's premise has to be re-derived"
        )
    finally:
        structural_module._collect.cache_clear()


def test_the_generated_python_binding_actually_imports() -> None:
    """``--check`` compares the committed file to the GENERATOR, never to the interpreter.

    Those are different questions, and the gap between them shipped a broken binding. The
    generator emits each type where it was first REQUESTED, which is fine for a ``class``
    (PEP 649 defers every member annotation on 3.14) and a NameError for an alias, whose
    right-hand side is evaluated at import. No released alias had ever
    named another generated type, so the walk order happened to be a valid evaluation order
    -- until ``AnySelector = DocumentSelector | ...``, which was emitted eleven definitions
    before the six it unions and raised ``NameError: name 'DocumentSelector' is not defined``
    while ``--check`` reported no drift.

    Nothing else in this repository would have caught it at the time: ``ruff check`` ran over
    ``src scripts tests`` and never over ``generated/``, and no test imported the module. Both
    checkers are now scoped to ``generated`` as well, which is a second, independent reader of
    that file -- but neither ``ruff`` nor ``ty`` executes it, so this stays the one assertion
    that the committed binding IMPORTS.
    """
    module = import_generated_python()  # THIS is the assertion; a NameError fails it here.

    # Non-vacuity: the module has to actually contain the union whose ordering is at issue,
    # or an empty generated file would satisfy the import above.
    assert "AnySelector" in module.__all__, module.__all__
    assert "EvidenceLocationVersion" in module.__all__, module.__all__


def test_the_generated_alias_order_is_derived_rather_than_the_walk_order() -> None:
    """The mechanism behind the import above, asserted directly and proven falsifiable.

    Asserting only that the module imports would be satisfied by a corpus that happened to be
    in a valid order again. This asserts the PROPERTY -- every alias follows every generated
    name it evaluates -- and that a cycle, which has no valid Python spelling at all, is
    refused rather than emitted in walk order and left to fail at a consumer's import.
    """
    from research_contracts.tooling.errors import ContractError
    from research_contracts.tooling.generate_types import Walker

    walker = Walker()
    walker.run()
    position = {name: index for index, name in enumerate(walker.order)}
    for name in walker.order:
        for dependency in walker.alias_dependencies(name):
            assert position[dependency] < position[name], (
                f"{name} evaluates {dependency}, which is emitted after it"
            )

    # Non-vacuity: at least one alias really does name another generated type, or the loop
    # above ranged over empty dependency sets and proved nothing.
    depending = {name for name in walker.order if walker.alias_dependencies(name)}
    assert "AnySelector" in depending, sorted(depending)

    walker.order = [*walker.order, "AliasLoopLeft", "AliasLoopRight"]
    walker.python["AliasLoopLeft"] = "AliasLoopLeft = AliasLoopRight"
    walker.python["AliasLoopRight"] = "AliasLoopRight = AliasLoopLeft"
    with pytest.raises(ContractError, match="cycle"):
        walker.emission_order()


# ================================ 5. requiredness in the generated bindings ===
#
# `scripts/generate_types.py --check` re-renders the bindings and byte-compares. It catches a
# hand-edit and a stale commit, and it CANNOT catch a rendering that drops a fact, because
# both halves of the comparison come from the same emitter: it is a fixed point over the
# generator, never over the schemas. That is not a hypothetical. One emitter line wrote
# `total=False` on every Python class and `?:` on the TypeScript twin from the SAME composed
# `required` set, marking the Python difference with a trailing `# optional` comment no type
# checker reads. 230 of 339 members were required by the schemas and optional to every Python
# consumer, and `--check` was green throughout.
#
# The three tests below are oracles the gate does not have: the INTERPRETER's answer, the
# OTHER language's answer, and the SCHEMA's own `required` array. None of them calls the
# generator's composition, or it would be the same fixed point again.

GENERATED_PYTHON = ROOT / "generated" / "python" / "foundation_types.py"
GENERATED_TYPESCRIPT = ROOT / "generated" / "typescript" / "foundationTypes.ts"

#: Equality pins, measured 2026-08-03 over the committed bindings. They are the
#: FALSE-POSITIVE CONTROL for every set comparison below: "the two sets match" is
#: satisfied by two empty sets, and a parser that silently matched nothing would report
#: every binding in perfect agreement. Equalities rather than floors, mirroring
#: EXPECTED_FOUNDATION_CHECKS, so a member that disappears is as red as one that appears.
GENERATED_CLASS_COUNT = 50
GENERATED_MEMBER_COUNT = 339
GENERATED_OPTIONAL_COUNT = 109
GENERATED_REQUIRED_COUNT = GENERATED_MEMBER_COUNT - GENERATED_OPTIONAL_COUNT

#: Deliberately tolerant of anything inside the parentheses, ``, total=False`` included. A
#: regex that only matched the correct spelling would fail on the mutation for the WRONG
#: reason — "the text and the module disagree about which classes exist" — and hide the
#: requiredness comparison that is the actual subject. The bad spellings are asserted against
#: by name, in their own assertion, with a message that says what is wrong.
_PY_CLASS = re.compile(r"^class (\w+)\(TypedDict[^)]*\):$")
_PY_MEMBER = re.compile(r"^ {4}(\w+): (.+)$")
_TS_INTERFACE = re.compile(r"^export interface (\w+) \{$")
_TS_MEMBER = re.compile(r"^ {2}(\w+)(\??): (.+);$")


def import_generated_python() -> Any:
    """Execute the committed Python binding and return the module object.

    A fresh module per call: these tests read ``__required_keys__``, which TypedDict computes
    at class creation, so a cached import could serve an earlier run's answer after the file
    on disk had been regenerated.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("foundation_types_import_probe", GENERATED_PYTHON)
    assert spec is not None and spec.loader is not None, GENERATED_PYTHON
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generated_typed_dicts(module: Any) -> dict[str, Any]:
    """Every generated ``TypedDict``, keyed by name. Aliases and NewTypes are excluded."""
    found: dict[str, Any] = {}
    for name in module.__all__:
        candidate = getattr(module, name)
        if isinstance(candidate, type) and hasattr(candidate, "__required_keys__"):
            found[name] = candidate
    return found


def _parse_members(
    text: str, header: re.Pattern[str], member: re.Pattern[str], optional_group: int
) -> dict[str, dict[str, bool]]:
    """``{type name: {member: is_optional}}`` as the committed TEXT spells it.

    The text is a THIRD reading, independent of both the interpreter and the generator. It is
    what caught PEP 563: with ``from __future__ import annotations`` the source said
    ``NotRequired[T]`` on 109 members and the interpreter put all 339 in
    ``__required_keys__``, because a stringified qualifier is opaque to ``TypedDict``. An
    annotation that is written but has no effect is invisible to any test that reads only one
    of the two.
    """
    parsed: dict[str, dict[str, bool]] = {}
    current: dict[str, bool] | None = None
    for line in text.splitlines():
        opened = header.match(line)
        if opened:
            current = {}
            parsed[opened.group(1)] = current
            continue
        if line and not line.startswith(" "):
            current = None
            continue
        found = member.match(line)
        if found is not None and current is not None:
            marker = found.group(optional_group)
            current[found.group(1)] = marker == "?" or marker.startswith("NotRequired[")
    return parsed


def python_source_members() -> dict[str, dict[str, bool]]:
    return _parse_members(GENERATED_PYTHON.read_text(encoding="utf-8"), _PY_CLASS, _PY_MEMBER, 2)


def typescript_source_members() -> dict[str, dict[str, bool]]:
    return _parse_members(
        GENERATED_TYPESCRIPT.read_text(encoding="utf-8"), _TS_INTERFACE, _TS_MEMBER, 2
    )


def test_the_generated_python_binding_states_requiredness_to_the_interpreter() -> None:
    """(a) The interpreter's answer, which is the only one a consumer's type checker sees.

    ``--check`` proves the committed bytes are what the generator emits. It says nothing
    about what those bytes MEAN, and the two diverged twice in one change:

    * ``total=False`` on every class made all 339 members optional while a ``# optional``
      comment carried the real distinction — a comment being a second source of truth for a
      fact the annotation already owns; and
    * ``NotRequired[T]`` under ``from __future__ import annotations`` is a STRING to
      ``TypedDict``, which cannot tell the qualifier from the type and files the member as
      required. All 339 read required again, this time with 109 correct-looking markers in
      the source.

    Reading ``__required_keys__`` catches both. Comparing it to the committed TEXT catches
    the second specifically: an annotation that is written and has no effect.
    """
    module = import_generated_python()
    classes = generated_typed_dicts(module)
    assert len(classes) == GENERATED_CLASS_COUNT, sorted(classes)

    source = python_source_members()
    assert set(source) == set(classes), (
        "the committed text and the imported module disagree about which classes exist: "
        f"text-only {sorted(set(source) - set(classes))}, "
        f"module-only {sorted(set(classes) - set(source))}"
    )

    required_total = 0
    optional_total = 0
    for name, cls in sorted(classes.items()):
        spelled_optional = {member for member, opt in source[name].items() if opt}
        spelled_all = set(source[name])
        interpreter_optional = set(cls.__optional_keys__)
        interpreter_required = set(cls.__required_keys__)

        assert spelled_all == interpreter_optional | interpreter_required, (
            f"{name}: the source lists {sorted(spelled_all)} but the interpreter sees "
            f"{sorted(interpreter_optional | interpreter_required)}"
        )
        assert interpreter_optional == spelled_optional, (
            f"{name}: the source marks {sorted(spelled_optional)} optional, the interpreter "
            f"reports {sorted(interpreter_optional)}. An annotation that is written but has "
            "no effect is the defect this asserts against."
        )
        required_total += len(interpreter_required)
        optional_total += len(interpreter_optional)

    # The false-positive control. Every comparison above is an equality between two sets, and
    # two empty sets are equal; a binding with no members at all would pass the loop.
    assert required_total == GENERATED_REQUIRED_COUNT, required_total
    assert optional_total == GENERATED_OPTIONAL_COUNT, optional_total
    assert required_total + optional_total == GENERATED_MEMBER_COUNT

    # A NAMED class must have a non-empty required set, so "everything is optional" — the
    # exact shape of the original defect — cannot satisfy the totals by some other split.
    assert module.CapabilityStatus.__required_keys__, "CapabilityStatus requires nothing"
    assert "required_for_publication" in module.CapabilityStatus.__required_keys__

    # The two dead spellings must not come back beside the live one. `total=False` makes the
    # annotations unreadable; `# optional` is a second source of truth for the same fact.
    text = GENERATED_PYTHON.read_text(encoding="utf-8")
    assert "total=False" not in text, "total=False makes every NotRequired marker decoration"
    assert "# optional" not in text, "requiredness is stated by the type, not by a comment"
    assert "from __future__ import annotations" not in text, (
        "PEP 563 stringifies NotRequired[T] into something TypedDict cannot recognise, so "
        "every optional member lands in __required_keys__ while the source looks correct"
    )


def test_the_two_generated_bindings_agree_on_which_members_are_optional() -> None:
    """(b) Two independent renderings of one composed ``required`` set must agree.

    The defect was asymmetric — TypeScript encoded requiredness with ``?:`` and Python did
    not — and no test compared the two, so the correct half stood beside the broken half for
    the whole life of the generator. The Python side is read from the INTERPRETER and the
    TypeScript side from its committed text: neither is the generator's own composition, so
    an emitter that drops the fact in one language is red here even if it drops it
    consistently in that language's own tests.
    """
    module = import_generated_python()
    classes = generated_typed_dicts(module)
    interfaces = typescript_source_members()

    assert set(interfaces) == set(classes), (
        "the two languages generate different type sets: "
        f"TypeScript-only {sorted(set(interfaces) - set(classes))}, "
        f"Python-only {sorted(set(classes) - set(interfaces))}"
    )
    assert len(interfaces) == GENERATED_CLASS_COUNT, sorted(interfaces)

    ts_members = 0
    ts_optional = 0
    for name, cls in sorted(classes.items()):
        members = interfaces[name]
        python_optional = set(cls.__optional_keys__)
        typescript_optional = {member for member, opt in members.items() if opt}

        assert set(members) == python_optional | set(cls.__required_keys__), (
            f"{name}: TypeScript declares {sorted(members)}, Python declares "
            f"{sorted(python_optional | set(cls.__required_keys__))}"
        )
        assert typescript_optional == python_optional, (
            f"{name}: TypeScript marks {sorted(typescript_optional)} optional and Python "
            f"reports {sorted(python_optional)}. One binding is weaker than the other, and a "
            "consumer of the weaker one is told less than the schema says."
        )
        ts_members += len(members)
        ts_optional += len(typescript_optional)

    # The false-positive control: an interface parser that matched nothing would report every
    # class in perfect agreement over two empty sets.
    assert ts_members == GENERATED_MEMBER_COUNT, ts_members
    assert ts_optional == GENERATED_OPTIONAL_COUNT, ts_optional


# ---------------------------------------------------------------------------------------
# An INDEPENDENT composer, written for this test file and used by leg (c).
#
# It exists because the alternative is a hand list, and a hand list was measured to be
# exploitable rather than merely incomplete. With three pinned documents covering 38 of 339
# members, the only oracle for the other 47 classes was ``GENERATED_OPTIONAL_COUNT`` — a
# number a developer edits by hand. Weakening one member in the emitter for BOTH languages and
# bumping that count 109 -> 111, exactly as somebody would after what looks like a legitimate
# schema change, left `--check` green, all three legs green and the full suite green, with both
# bindings claiming a member optional that ``research-access-context:1`` still requires.
#
# So REQUIREDNESS is DERIVED here for every class the generator emits, from the released JSON,
# by code that never touches ``Walker``. Importing the generator's composition would rebuild
# the fixed point this whole section exists to escape: the artifact would be compared to the
# thing that produced it, again.
#
# Scope of that independence, stated precisely because "independent derivation" overclaims:
# only the REQUIREDNESS is independent. ``_pascal``, ``_PASCAL_SPLIT`` and ``_derived_name``
# below are character-identical to the generator's ``pascal``, ``_WORD`` and ``type_name``, so
# NAMING is a re-implementation of the same algorithm rather than a second opinion about it. A
# shared naming bug would be invisible to this leg; what limits that is the class-set equality
# against ``module.__all__`` -- a name this derivation invents that the generator does not, or
# the reverse, is red.
#
# THE RULE. A member is unconditionally required if the node, or any branch reached through
# ``allOf``, names it in ``required``. Composition follows ``allOf`` and NOTHING ELSE:
#
#   * ``if``/``then``/``else``/``not`` are conditionals -- a member required only inside one is
#     not required of the type; and
#   * ``oneOf``/``anyOf`` are DISJUNCTIONS -- a member required by one arm is not required by
#     the composed object, because the other arm is an equally legal instance.
#
# The second bullet is load-bearing, not tidiness, and the earlier version of this comment had
# it wrong. A path census of all 100 ``required`` arrays in the corpus finds 30 that are
# constraint-only; 24 sit under a conditional, and SIX sit under ``oneOf`` with no conditional
# anywhere above them:
#
#     evidence-location-candidate:1  allOf/1/oneOf/{0,1}   document_version_ref, artifact_ref
#     evidence-location-version:1    allOf/4/oneOf/{0,1}   document_version_ref, artifact_ref
#     locator-selector:1             $defs/tabular_selector/oneOf/{0,1}   row_id, row_index
#
# Descending ``oneOf`` would pull those six in and the derived total moves 230 -> 236. So the
# rule is "allOf only", not "everything except conditionals": a maintainer who simplified this
# to the latter on the strength of the old comment would silently break the leg.
#
# On this corpus the rule and the generator's ``is_constraint_only`` agree. If a constraint-only
# node ever appears as a real ``allOf`` branch they will disagree, and that disagreement is a
# finding, not a nuisance.
_PASCAL_SPLIT = re.compile(r"[^0-9a-zA-Z]+")


def _pascal(text: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in _PASCAL_SPLIT.split(text) if part)


def _derived_name(schema_id: str, pointer: str | None) -> str:
    """The generated name for a document root or a top-level ``$defs`` entry."""
    if pointer is not None:
        return _pascal(pointer)
    return _pascal(schema_id.removeprefix("urn:datacompany:").rpartition(":")[0])


def _resolve_for_derivation(
    schemas: dict[str, Any], ref: str, base: str
) -> tuple[dict[str, Any], str]:
    """Resolve a ``$ref``. Indexing rather than ``.get`` on purpose: a ref that does not
    resolve must raise here, never compose as an empty contribution that silently weakens
    the derived requiredness and makes the comparison agree for the wrong reason."""
    document, _, fragment = ref.partition("#")
    document = document or base
    if not fragment:
        return schemas[document], document
    prefix = "/$defs/"
    assert fragment.startswith(prefix), f"{base}: unexpected $ref fragment {ref!r}"
    return schemas[document]["$defs"][fragment[len(prefix) :]], document


def _compose_requiredness(
    schemas: dict[str, Any],
    node: dict[str, Any],
    base: str,
    seen: set[tuple[str, str]] | None = None,
) -> tuple[set[str], set[str]]:
    """``(required, properties)`` for one node, composed through ``allOf`` only."""
    seen = set() if seen is None else seen
    required = set(node.get("required") or [])
    properties = set(node.get("properties") or {})
    for branch in node.get("allOf") or []:
        if "$ref" in branch:
            key = (base, branch["$ref"])
            if key in seen:
                continue
            seen.add(key)
            target, target_base = _resolve_for_derivation(schemas, branch["$ref"], base)
            branch_required, branch_properties = _compose_requiredness(
                schemas, target, target_base, seen
            )
        else:
            branch_required, branch_properties = _compose_requiredness(schemas, branch, base, seen)
        required |= branch_required
        properties |= branch_properties
    return required, properties


def derive_requiredness_from_the_schemas() -> dict[
    str, list[tuple[str, frozenset[str], frozenset[str]]]
]:
    """``{generated name: [(source, required, properties), ...]}`` over the whole registry.

    A LIST per name, not a single entry, so an ambiguity is visible instead of being resolved
    by whichever node happened to be visited last. Two names are genuinely ambiguous in the
    corpus (``Command`` and ``Sealed``, each defined in more than one document with different
    members); neither is generated today, and the test asserts that every name it actually
    compares is unambiguous, so a future collision is red rather than silently arbitrary.
    """
    schemas = canonical_schemas()
    derived: dict[str, list[tuple[str, frozenset[str], frozenset[str]]]] = {}
    for schema_id, document in schemas.items():
        nodes: list[tuple[str | None, Any]] = [(None, document)]
        nodes.extend((entry, body) for entry, body in (document.get("$defs") or {}).items())
        for pointer, node in nodes:
            if not isinstance(node, dict):
                continue
            required, properties = _compose_requiredness(schemas, node, schema_id)
            if not properties:
                # No members: an alias, a NewType brand or a pure rule. The generator emits
                # those as aliases rather than classes, and a class is what this compares.
                continue
            source = schema_id if pointer is None else f"{schema_id}#/$defs/{pointer}"
            derived.setdefault(_derived_name(schema_id, pointer), []).append(
                (source, frozenset(required), frozenset(properties))
            )
    return derived


class RegisterPin(NamedTuple):
    """One decision-register entry, and how much of the schema its prose actually claims."""

    decision: str
    schema_id: str
    defs_entry: str
    named_required: int
    required_is_exhaustive: bool
    named_optional: int
    optional_is_exhaustive: bool


#: A member name as the register writes it. Deliberately over-matching -- it also finds
#: ordinary English words -- and the caller intersects the result with the members the schema
#: actually releases, which is what makes the over-match harmless. The same shape the generator
#: uses for ``_GENERATED_NAME``, and for the same reason.
_REGISTER_MEMBER = re.compile(r"[a-z][a-z0-9_]*")


def register_named_members(
    decision: dict[str, Any], released: set[str]
) -> tuple[set[str], set[str]]:
    """``(named required, named optional)`` for one register entry.

    The entry's ``taken`` field states the outcome in prose and splits the two halves on a
    semicolon when it makes both claims ("... all required; issues optional"). The ``title`` is
    read with the required half because two entries name their member only there
    (IMP-DEC-FND002-011's whole subject is in its title).

    Prose is a fragile thing to parse, and that is handled by pinning the COUNT the parse must
    find rather than trusting it: a register edit that removes a member, or a rewording this
    stops understanding, both fail the floor rather than silently narrowing the claim.
    """
    required_clause, _, optional_clause = decision["taken"].partition(";")
    named_required = set(_REGISTER_MEMBER.findall(decision["title"] + " " + required_clause))
    named_optional = set(_REGISTER_MEMBER.findall(optional_clause))
    return named_required & released, named_optional & released


#: The DECISION leg's table. It holds NO member names: the members are parsed out of
#: ``config/foundation-decisions.json`` at run time by :func:`register_named_members`.
#:
#: That is the whole point of this shape. The previous version hand-typed the member sets, and
#: a hand-typed set restating the schema is bypassable in exactly as many edits as it has
#: copies. Measured, three edits and no register edit: drop ``expires_at`` from
#: ``context_fields.required``, move ``"expires_at"`` from the pinned-required set to the
#: pinned-optional set, bump ``GENERATED_OPTIONAL_COUNT`` 109 -> 111, regenerate. ``--check``
#: green, all four legs green, 1224 passed — while IMP-DEC-FND002-002 still read "Twelve
#: members required: ... expires_at" and its rejected alternative still read "an envelope that
#: requires nothing cannot fail closed on ... a missing validity window". ``expires_at`` IS the
#: validity window. The leg claimed in its own docstring to bind the register and never opened
#: the file.
#:
#: Reading the register instead means the bypass now requires editing the recorded decision,
#: which is a reviewable act rather than a silent one.
#:
#: Each entry declares HOW MUCH the register's prose actually claims, because the four entries
#: differ and forcing them into one shape would overstate three of them:
#:
#:   ``named_required``      how many members the entry names as required (a floor on the parse)
#:   ``required_is_exhaustive``  True when the entry enumerates the WHOLE ``required`` array,
#:                           so the schema may be compared to it as an equality
#:   ``named_optional``      how many it names as optional
#:   ``optional_is_exhaustive``  True when those are the whole optional set
REGISTER_PINS: dict[str, RegisterPin] = {
    # "Twelve members required: actor_id, actor_tenant_id, resource_scope, roles, entitlements,
    # purpose, data_classes, policy_version, correlation_id, causation_id, requested_at,
    # expires_at." Rejected: requiring nothing, "because an envelope that requires nothing
    # cannot fail closed on a missing actor or a missing validity window".
    #
    # EXHAUSTIVE: the twelve are exactly the released `required` array, so a member added to or
    # removed from either side is red.
    #
    # The entry's second sentence USED to read "The other eight are operation-dependent" and
    # was NOT asserted, because it was wrong: `context_fields` releases 21 members and requires
    # 12, so nine are optional. Re-measured 2026-08-04 (21/12/9) and CORRECTED in the register
    # rather than left as a note here, because a comment recording a known-false sentence is
    # the prose-versus-executable gap this whole register exists to prevent.
    #
    # The ninth is `resource_tenant_id`, which `stable-identity:1#/$defs/resource_scope_
    # conditional` requires CONDITIONALLY -- so it is not "operation-dependent" either; it is a
    # third category the old sentence had no slot for, and its requiredness belongs to
    # IMP-DEC-FND002-001. The entry now names all nine and says which eight are which, so the
    # optional half is EXHAUSTIVE and equality-checked below. That is the point of correcting
    # it here rather than only fixing the number word: `optional_is_exhaustive=False` meant a
    # member could be added to or removed from the released optional set with the register
    # silent, exactly as `named_optional=0` meant the entry's optional claim was unread.
    #
    # STILL OUTSTANDING, and not fixable from this file: the schema's own `$comment` on
    # `context_fields` enumerates the same eight and omits `resource_tenant_id`. That file is
    # sibling-owned; the correction is reported as a specification, not applied here.
    "ResearchAccessContext": RegisterPin(
        decision="IMP-DEC-FND002-002",
        schema_id=CONTEXT,
        defs_entry="context_fields",
        named_required=12,
        required_is_exhaustive=True,
        named_optional=9,
        optional_is_exhaustive=True,
    ),
    # "code, status, message, retryable, correlation_id all required; issues optional."
    # Rejected: making retryable optional, "because a client that cannot rely on it has to
    # guess retry safety" -- which is exactly what a NotRequired retryable would force.
    # EXHAUSTIVE on both sides: five required, one optional, and that is the whole member set.
    "ProblemDetails": RegisterPin(
        decision="IMP-DEC-FND002-008",
        schema_id=PROBLEM,
        defs_entry="problem_fields",
        named_required=5,
        required_is_exhaustive=True,
        named_optional=1,
        optional_is_exhaustive=True,
    ),
    # "required_for_publication is released as a member and is required" / "boolean, required."
    # Rejected: leaving it optional, "because an absent flag reads as non-blocking, which is
    # the exact direction the four citations exist to prevent".
    #
    # NOT exhaustive, and not forced to be: this entry argues about ONE member. The schema
    # requires six; the register speaks for one of them. Asserting equality here would be
    # asserting something the register does not say.
    "CapabilityStatus": RegisterPin(
        decision="IMP-DEC-FND002-011",
        schema_id=CAPABILITY,
        defs_entry="status_fields",
        named_required=1,
        required_is_exhaustive=False,
        named_optional=0,
        optional_is_exhaustive=False,
    ),
    # "inputs, versions, method, environment and outputs are required; sources, extraction,
    # rights and approvals are optional at the envelope and required by a capability."
    # Rejected: requiring all nine, "because document 13 explicitly makes requiredness
    # capability-declared, and a numerical model run has no extraction stage at all".
    #
    # The required half is NOT exhaustive: the schema requires nine, the five named groups plus
    # four identity members (content_hash, run_manifest_id, run_ref, schema_ref) that this
    # decision is not about. The optional half IS exhaustive -- the four named are the whole
    # optional set.
    "RunManifest": RegisterPin(
        decision="IMP-DEC-FND002-017",
        schema_id=MANIFEST,
        defs_entry="manifest_fields",
        named_required=5,
        required_is_exhaustive=False,
        named_optional=4,
        optional_is_exhaustive=True,
    ),
}


def test_the_generated_requiredness_matches_the_released_schemas() -> None:
    """(c) Every generated class, composed from the released JSON by code of its own.

    (a) and (b) prove the two bindings agree with each other and with their own source text.
    Two renderings can agree and both be wrong — that is what happens when the fact is lost
    upstream of the split — so this leg goes back to the schemas.

    It covers ALL 50 classes and all 339 members, not a hand-picked few. The earlier shape of
    this test pinned three documents and left the other 47 classes guarded only by a count a
    developer edits by hand, and that was measured to be exploitable: weakening one member in
    the emitter for both languages and bumping the count exactly as somebody would after a
    legitimate schema change left every gate in this repository green while both bindings
    contradicted ``research-access-context:1``. A derivation has no such seam — the schema
    side moves only when the schema moves.

    ``_compose_requiredness`` is this file's own, never ``Walker``'s. Reusing the generator's
    composition would compare the artifact to the thing that produced it, which is exactly
    what ``--check`` already does and exactly what this section exists to escape.
    """
    module = import_generated_python()
    classes = generated_typed_dicts(module)
    derived = derive_requiredness_from_the_schemas()

    # Non-vacuity, before any comparison: the derivation has to have found the corpus. An
    # empty or partial derivation would make every equality below trivially true.
    assert len(derived) >= GENERATED_CLASS_COUNT, sorted(derived)
    uncovered = sorted(set(classes) - set(derived))
    assert not uncovered, (
        f"{uncovered} are generated as classes and the derivation produced no schema node for "
        "them, so nothing here checks their requiredness at all"
    )

    schema_required = 0
    schema_optional = 0
    for name, cls in sorted(classes.items()):
        candidates = derived[name]
        distinct = {(required, properties) for _, required, properties in candidates}
        assert len(distinct) == 1, (
            f"{name} is produced by more than one schema node with different members "
            f"({[source for source, _, _ in candidates]}), so which one the binding claims to "
            "be is arbitrary. Give one of them a distinct name."
        )
        source, released_required, released_properties = candidates[0]
        released_optional = released_properties - released_required

        assert set(cls.__required_keys__) == set(released_required), (
            f"{name} ({source}): the schemas require {sorted(released_required)} and the "
            f"binding requires {sorted(cls.__required_keys__)}. Members the schema requires "
            "and the binding does not may be omitted by any consumer with every type checker "
            "agreeing."
        )
        assert set(cls.__optional_keys__) == set(released_optional), (
            f"{name} ({source}): the schemas leave {sorted(released_optional)} optional and "
            f"the binding leaves {sorted(cls.__optional_keys__)}"
        )
        schema_required += len(released_required)
        schema_optional += len(released_optional)

    # The count pins, kept — but they are now a CONTROL over a schema-derived measurement
    # rather than the oracle for 47 classes. Every per-class equality above is an equality
    # between two sets and two empty sets are equal; these totals are what stops a derivation
    # that quietly matched nothing from reporting the whole corpus in agreement.
    assert schema_required == GENERATED_REQUIRED_COUNT, schema_required
    assert schema_optional == GENERATED_OPTIONAL_COUNT, schema_optional
    assert schema_required + schema_optional == GENERATED_MEMBER_COUNT
    assert len(classes) == GENERATED_CLASS_COUNT, sorted(classes)


def test_the_register_cited_requiredness_decisions_are_the_ones_generated() -> None:
    """The DECISION leg: the register's own words, against the schema and the binding.

    Separate from the derivation above on purpose. The derivation proves the binding matches
    the schema; it cannot notice that the SCHEMA changed, because both sides move together. So
    this leg goes one step further out and binds the released ``required`` arrays to what
    ``config/foundation-decisions.json`` records was decided — the file it names, opened and
    parsed, not restated. The earlier version claimed this in its docstring and compared the
    schema to hand-typed strings instead, which made it bypassable in three edits none of which
    touched the register.
    """
    module = import_generated_python()
    schemas = canonical_schemas()
    register = {entry["id"]: entry for entry in load(DECISIONS)["decisions"]}

    # An equality, so deleting a pin is as red as adding one. This was the only iterated
    # collection in the section with no size assertion, and emptying it left the test passing
    # over nothing.
    assert len(REGISTER_PINS) == 4, sorted(REGISTER_PINS)

    for name, pin in sorted(REGISTER_PINS.items()):
        decision = register[pin.decision]
        assert decision["schema"] == pin.schema_id, (
            f"{pin.decision} records a decision about {decision['schema']}, not {pin.schema_id}"
        )

        node = schemas[pin.schema_id]["$defs"][pin.defs_entry]
        released_required = set(node.get("required") or [])
        released_properties = set(node.get("properties") or {})
        released_optional = released_properties - released_required

        named_required, named_optional = register_named_members(decision, released_properties)

        # The floor on the parse. Prose is fragile to read, so the number of members the
        # register is expected to name is pinned: a reword this stops understanding, or a
        # register edit that drops a member, fails HERE rather than silently narrowing the
        # claim to nothing and agreeing with whatever the schema says.
        assert len(named_required) == pin.named_required, (
            f"{pin.decision}: parsed {sorted(named_required)} as required members, expected "
            f"{pin.named_required}. The register's wording changed, or this pin is stale."
        )
        assert len(named_optional) == pin.named_optional, (
            f"{pin.decision}: parsed {sorted(named_optional)} as optional members, expected "
            f"{pin.named_optional}"
        )

        # The register against the SCHEMA.
        demoted = sorted(named_required - released_required)
        assert not demoted, (
            f"{pin.decision} records {demoted} as required and "
            f"{pin.schema_id}#/$defs/{pin.defs_entry} does not require them. The recorded "
            f"reasoning still stands: {decision['rejected']}"
        )
        promoted = sorted(named_optional & released_required)
        assert not promoted, (
            f"{pin.decision} records {promoted} as optional and "
            f"{pin.schema_id}#/$defs/{pin.defs_entry} requires them"
        )
        if pin.required_is_exhaustive:
            assert named_required == released_required, (
                f"{pin.decision} enumerates the whole required set, so it must equal the "
                f"schema's: register {sorted(named_required)} vs schema "
                f"{sorted(released_required)}"
            )
        if pin.optional_is_exhaustive:
            assert named_optional == released_optional, (
                f"{pin.decision} enumerates the whole optional set: register "
                f"{sorted(named_optional)} vs schema {sorted(released_optional)}"
            )

        # The register against the BINDING, which is what a consumer actually programs against.
        cls = getattr(module, name)
        interpreter_required = set(cls.__required_keys__)
        interpreter_optional = set(cls.__optional_keys__)

        missing = sorted(named_required - interpreter_required)
        assert not missing, (
            f"{name}: {missing} are recorded as required by {pin.decision} and are NOT in "
            "__required_keys__. A consumer may omit them and every type checker agrees."
        )
        widened = sorted(named_optional & interpreter_required)
        assert not widened, (
            f"{name}: {widened} are recorded as optional by {pin.decision} and are required by "
            "the binding, which refuses instances the schema accepts."
        )

        # Per-document false-positive control: both sets non-empty, so no assertion above can
        # be satisfied by a class that declares nothing.
        assert interpreter_required, f"{name} requires nothing at all"
        assert interpreter_optional, f"{name} has no optional member at all"

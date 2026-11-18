"""IMP-DEC-FND002-020: a pinned ``schema_ref`` must resolve, or name who owes it.

``stable-identity:1#/$defs/schema_ref`` is a *pattern*. It checks that a value looks like
``urn:datacompany:<name>:<major>`` and nothing more, so the committed corpus could name --- and
did name --- schema documents that exist nowhere and will never be written, and every gate
stayed green. A pin whose ``schema_ref`` names a document nobody owns is a reference that
can never be verified, and it reads identically to one that can.

This suite closes that. Every ``schema_ref`` anywhere in the committed corpus must either
resolve through the released registry or have its base URN on the deferred allowlist in
``config/deferred-schema-owners.json``, which names the bounded context that owes the
document. The allowlist is bound to the corpus in **both** directions, because each failure
mode is real and they are different: an entry no document references has become dead prose,
and an owner that disagrees with the corpus sends a reader to the wrong team.

Two properties of the sweep are load-bearing and are asserted rather than assumed:

* **Scope.** ``fixtures/`` alone was not the corpus. A dangling ref in ``examples/`` was
  invisible, and a ``schema_ref`` ``const`` in a RELEASED schema --- a *stronger* statement
  than any fixture value, because it makes the document a requirement rather than an
  example --- was reachable only through one hand-written helper. All three trees are swept
  now, and both spellings of a pin are collected.
* **Falsifiability in both directions.** Every rule below is extracted as a function of its
  inputs and exercised against synthetic inputs it must REJECT *and* synthetic inputs it must
  ACCEPT. A rule proven only able to fire is indistinguishable from one that always fires.
  SEVERAL rules here are assertions about the real committed corpus, register, ``OWNERS.yaml``
  or released schemas rather than functions of synthetic input --- every ``test_the_..._really_
  ...`` and every non-vacuity pin. For those, falsifiability is shown by mutating the DATA,
  because weakening an assertion that already passes cannot make it fail; a synthetic reject
  case is neither available nor meaningful. That distinction is stated rather than glossed,
  because this module's prose has FOUR times now claimed a property its code did not have,
  and the claim is what a reviewer trusts when they do not re-derive it themselves.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from test_foundation_schemas import MIN_QUOTE, normalise_prose

from research_contracts.canonical import canonical_schemas
from research_contracts.canonical.registry import resolve_pointer

# ``MIN_QUOTE`` is the floor below which a "quotation" is a gesture at one. It is IMPORTED
# from the citation gate rather than restated here: that module answers the identical
# question about the same register, and two floors for one question drift apart -- after
# which one of them is silently wrong.

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "config" / "foundation-decisions.json"
OWNERSHIP = ROOT / "config" / "deferred-schema-owners.json"

#: Every tree the sweep reads. ``fixtures/`` alone left two proven blind spots: a dangling
#: ``schema_ref`` planted under ``examples/`` was never seen, and a ``const`` in a released
#: schema reached the gate only through the one ``_typed_ref_pins`` helper -- which is to
#: say, only for the one document that helper knows about.
CORPUS_ROOTS: tuple[Path, ...] = (ROOT / "fixtures", ROOT / "examples", ROOT / "schemas")

TYPED_REFS = "urn:datacompany:typed-refs:1"


def _governance() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(OWNERSHIP.read_text(encoding="utf-8"))
    return document


#: Schema documents the corpus pins but this repository does not release, and the bounded
#: context that owes each one. GOVERNANCE DATA, so it lives in ``config/`` beside every
#: other governance artefact rather than inside this module: ``OWNERS.yaml`` assigns
#: REPOSITORY-level accountability only (IMP-DEC-001, Python half, 2026-08-08) and names no
#: individual schema, which keeps these the only PER-SCHEMA ownership statements the
#: repository holds, and they were readable only by running pytest.
DEFERRED_SCHEMA_OWNERS: dict[str, str] = _governance()["deferred_schema_owners"]

#: Entries whose owner is assigned from the implementation plans rather than observed in the
#: corpus, because no document states an ``owner_context`` beside them. Listed explicitly so
#: the agreement check below cannot be weakened by quietly adding to this set.
OWNER_NOT_OBSERVED_IN_CORPUS = frozenset(_governance()["owner_not_observed_in_corpus"]["entries"])

#: A second owner the corpus states for a shared document. ``approved_mapping`` versions are
#: pinned by the guideline registry as well as by the broker that owns them; the allowlist
#: names the OWNER, so this records the other observed context rather than contradicting it.
ADDITIONAL_OBSERVED_CONTEXTS: dict[str, frozenset[str]] = {
    reference: frozenset(contexts)
    for reference, contexts in _governance()["additional_observed_contexts"]["entries"].items()
}

#: The counts the ownership register states about ITSELF. There are two of them and they are
#: not the same fact: 18 documents are assigned an owner, and 17 of those owners are compared
#: against a document that states one. The pair was self-consistent only by accident --
#: 18 - 1 excused = 17 -- so the module docstring, the register prose and IMP-DEC-FND002-020's
#: narration each carried whichever of the two the author had in mind.
STATED_COUNTS: dict[str, Any] = _governance()["counts"]

#: The deferred entries that record something OWED rather than a document another context
#: simply owns. Structured, because a context picking the work up reads THIS file -- it is the
#: one that names them as owner -- and the gaps lived only as prose inside a decision register
#: it has no reason to open.
DEFERRED_OBLIGATIONS: dict[str, Any] = _governance()["deferred_obligations"]["entries"]

#: How a count is spelled in prose, so a structured list and the sentence that introduces it
#: cannot disagree in either direction. Used for the register's "FOUR MEASURED GAPS" phrase
#: and for this file's own "eighteen assignments" sentence.
NUMBER_WORDS = {
    1: "ONE",
    2: "TWO",
    3: "THREE",
    4: "FOUR",
    5: "FIVE",
    6: "SIX",
    7: "SEVEN",
    8: "EIGHT",
    9: "NINE",
    10: "TEN",
    11: "ELEVEN",
    12: "TWELVE",
    13: "THIRTEEN",
    14: "FOURTEEN",
    15: "FIFTEEN",
    16: "SIXTEEN",
    17: "SEVENTEEN",
    18: "EIGHTEEN",
    19: "NINETEEN",
    20: "TWENTY",
}


def _decisions() -> dict[str, dict[str, Any]]:
    register = json.loads(DECISIONS.read_text(encoding="utf-8"))
    return {decision["id"]: decision for decision in register["decisions"]}


def _label(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _documents(roots: Sequence[Path]) -> list[tuple[str, Any]]:
    paths = sorted(path for root in roots for path in root.rglob("*.json"))
    assert paths, f"no JSON documents found under {[str(root) for root in roots]}"
    return [(_label(p), json.loads(p.read_text(encoding="utf-8"))) for p in paths]


def _schema_refs(roots: Sequence[Path] = CORPUS_ROOTS) -> dict[str, set[str]]:
    """Every ``schema_ref`` the corpus names, mapped to the files that name it.

    BOTH spellings are collected. ``"schema_ref": "urn:..."`` is an instance naming a
    document; ``"schema_ref": {"const": "urn:..."}`` is a released schema REQUIRING one, and
    the second is the stronger statement of the two.
    """
    found: dict[str, set[str]] = {}

    def walk(node: Any, source: str) -> None:
        if isinstance(node, dict):
            value = node.get("schema_ref")
            if isinstance(value, str):
                found.setdefault(value, set()).add(source)
            elif isinstance(value, dict) and isinstance(value.get("const"), str):
                found.setdefault(value["const"], set()).add(source)
            for child in node.values():
                walk(child, source)
        elif isinstance(node, list):
            for child in node:
                walk(child, source)

    for source, document in _documents(roots):
        walk(document, source)
    return found


def _owners_beside_schema_refs(
    roots: Sequence[Path] = CORPUS_ROOTS,
) -> dict[str, set[str]]:
    """``schema_ref`` -> every ``owner_context`` a document states in the SAME object."""
    observed: dict[str, set[str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            reference = node.get("schema_ref")
            owner = node.get("owner_context")
            if isinstance(reference, str) and isinstance(owner, str):
                observed.setdefault(reference, set()).add(owner)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    for _, document in _documents(roots):
        walk(document)
    return observed


def _resolves(schema_ref: str) -> bool:
    try:
        resolve_pointer(schema_ref)
    except Exception:  # noqa: BLE001 - any failure to resolve is the answer
        return False
    return True


def _unaccounted(
    references: Mapping[str, set[str]], owners: Mapping[str, str]
) -> dict[str, list[str]]:
    """The rule itself, as a function of its inputs, so it can be run on synthetic ones."""
    return {
        reference: sorted(sources)
        for reference, sources in references.items()
        if not _resolves(reference) and reference.partition("#")[0] not in owners
    }


def _disagreements(
    observed: Mapping[str, set[str]],
    owners: Mapping[str, str],
    additional: Mapping[str, frozenset[str]],
    excused: frozenset[str],
) -> tuple[dict[str, dict[str, Any]], int]:
    """Return the owner disagreements and how many entries were actually compared."""
    findings: dict[str, dict[str, Any]] = {}
    checked = 0
    for reference, owner in owners.items():
        contexts = observed.get(reference, set())
        if not contexts:
            assert reference in excused, (
                f"{reference} is excused from the agreement check, but nothing in the corpus "
                "states an owner_context beside it -- so the exemption is not the fact it "
                "claims to be"
            )
            continue
        checked += 1
        permitted = {owner} | additional.get(reference, frozenset())
        if contexts - permitted:
            findings[reference] = {"allowlist": owner, "corpus": sorted(contexts)}
    return findings, checked


def _count_drift(
    stated: Mapping[str, Any], assignments: int, excused: int, prose: Any
) -> dict[str, Any]:
    """The counts rule, as a function of its inputs, so it can be run on synthetic ones."""
    findings: dict[str, Any] = {}
    # The register's own ``status`` sentence spells the count in words. ``prose`` is REQUIRED
    # and its emptiness is a finding, not a skip: this was ``if prose:`` with a ``""``
    # default, so ``status: ""`` and ``status: null`` each disabled the only check the field
    # had and rendered clean -- the identical "an empty value disables its own check in
    # silence" defect this module fixes for ``members`` and ``constraint`` twenty lines apart.
    if not isinstance(prose, str) or not prose.strip():
        findings["prose_is_empty"] = prose
    else:
        # WHOLE WORDS. A substring test reports "one" against "none of these obligations",
        # which is the same false-positive class the member check had to be fixed for.
        def states(word: str) -> bool:
            return re.search(rf"\b{word}\b", prose, re.IGNORECASE) is not None

        expected = NUMBER_WORDS[assignments].lower()
        if not states(expected):
            findings["prose_omits_the_count"] = expected
        wrong = sorted(
            word.lower()
            for value, word in NUMBER_WORDS.items()
            if value != assignments and states(word.lower())
        )
        if wrong:
            findings["prose_states_another_count"] = wrong
    if stated["assignments"] != assignments:
        findings["assignments"] = {"stated": stated["assignments"], "measured": assignments}
    if stated["excused_owner_not_observed_in_corpus"] != excused:
        findings["excused_owner_not_observed_in_corpus"] = {
            "stated": stated["excused_owner_not_observed_in_corpus"],
            "measured": excused,
        }
    compared = assignments - excused
    if stated["compared_against_the_corpus"] != compared:
        findings["compared_against_the_corpus"] = {
            "stated": stated["compared_against_the_corpus"],
            "measured": compared,
        }
    # The identity is stated in prose beside the numbers, so it is checked against the numbers
    # rather than trusted: a stated triple that does not add up is three facts and a fiction.
    if stated["assignments"] != (
        stated["compared_against_the_corpus"] + stated["excused_owner_not_observed_in_corpus"]
    ):
        findings["identity"] = dict(stated)
    return findings


#: The WHOLE SHAPE of the register, pinned at every level. The derived-key rule used to apply
#: only inside ``entries[*]`` and its gaps -- never at the file's own top level, which is where
#: all the prose lived, so twelve prose fields could be replaced with outright falsehoods and
#: two new keys invented, all green. Everything the file may say is now enumerated here, and
#: anything the file says that is not enumerated is a finding.
REGISTER_SHAPE: dict[str, frozenset[str]] = {
    "": frozenset(
        {
            "register_id",
            "decision",
            "status",
            "counts",
            "deferred_schema_owners",
            "owner_not_observed_in_corpus",
            "additional_observed_contexts",
            "deferred_obligations",
        }
    ),
    "counts": frozenset(
        {"assignments", "compared_against_the_corpus", "excused_owner_not_observed_in_corpus"}
    ),
    "owner_not_observed_in_corpus": frozenset({"entries"}),
    "additional_observed_contexts": frozenset({"entries"}),
    "deferred_obligations": frozenset({"entries"}),
}

#: Keys an obligation entry may carry. Every one of them has a rule below, and a key that is
#: NOT here is a finding rather than something the rule walks past. Hand-listing the two
#: fields that were checked is how ``"severity": "cosmetic"`` and a ``corpus_field_list``
#: pointing at ``16:1-2`` both passed.
ENTRY_KEYS = frozenset(
    {
        "owner_context",
        "decision",
        "corpus_field_list",
        "urn_absence_quoted_from_citations",
        "gaps",
    }
)

#: The same rule for a gap object.
GAP_KEYS = frozenset(
    {
        "id",
        "members",
        "constraint",
        "quoted_from_register",
        "quoted_from_blocked_on",
        "register_paraphrase",
    }
)

#: The two gap keys that are OPTIONAL. Everything else in ``GAP_KEYS`` is required, derived by
#: subtraction rather than restated as a second list that can fall out of step with the first.
OPTIONAL_GAP_KEYS = frozenset({"constraint", "register_paraphrase"})

#: Keys of the optional ``register_paraphrase`` note, which records that the register's own
#: wording is not the corpus's. Fidelity to the register is what the quotations prove;
#: fidelity to the CORPUS is a separate claim, and copying a paraphrase into a second file
#: without saying so propagates it.
PARAPHRASE_KEYS = frozenset({"phrase", "attributed_to", "corpus_wording"})

#: Characters that continue a token. Wider than ``\w`` on purpose: the first version used
#: ``[0-9A-Za-z_]``, under which the member ``stable-identity`` matched INSIDE
#: ``stable-identity:1#/$defs/...`` and ``defs`` matched inside ``#/$defs/``, because ``-``,
#: ``/``, ``:`` and ``$`` all read as boundaries. ``#`` was the one still missing, and it was
#: load-bearing: without it ``stable-identity:1`` was a WHOLE TOKEN inside that pointer, and
#: ``resolve_pointer`` returns the document ROOT for a bare document URN -- so the truncation
#: this rule exists to reject both matched and resolved.
IDENTIFIER_CHARACTERS = r"[\w$/:#-]"

#: What counts as inside a word when deciding whether a quotation was cut mid-word. The
#: apostrophe is included because ``receipt's`` is one word: without it, the slice
#: ``"the receipt'"`` ends on a non-word character and reads as aligned.
WORD_CHARACTERS = r"[\w']"

#: A pointer a ``constraint`` must be, not merely resemble. A bare document URN resolves, so
#: "it resolves" alone does not distinguish a pointer from its own prefix.
DEFS_POINTER = "#/$defs/"

#: A pointer into the corpus that something can actually resolve: a MULTI-LINE range. Used for
#: ``corpus_field_list``, where the attack is a REAL citation of the wrong thing -- ``16:891``,
#: the single line about ``decision`` values -- which "must appear among the citations"
#: happily accepts; and for ``register_paraphrase.attributed_to``, which is resolved against
#: real bytes. A fourteen-member field list cannot sit on one line.
CORPUS_RANGE = re.compile(r"^(?P<file>[0-9A-Za-z][\w./-]*\.md):(?P<first>\d+)-(?P<last>\d+)$")


def _names_whole_token(haystack: str, token: str) -> bool:
    """``token`` occurs in ``haystack`` without a token character either side of it.

    ``.`` is deliberately NOT in :data:`IDENTIFIER_CHARACTERS` and is handled separately: it
    continues a token only when another token character follows it, so ``foo`` does not match
    inside ``foo.bar`` while a constraint ending a SENTENCE still matches. Putting ``.`` in
    the class outright made a trailing full stop a token character, which rejected a
    perfectly good citation -- the false-positive direction, which gets a gate tuned until it
    is vacuous.
    """
    pattern = (
        rf"(?<!{IDENTIFIER_CHARACTERS})(?<!{IDENTIFIER_CHARACTERS}\.)"
        rf"{re.escape(token)}"
        rf"(?!{IDENTIFIER_CHARACTERS})(?!\.{IDENTIFIER_CHARACTERS})"
    )
    return re.search(pattern, haystack) is not None


def _splits_a_word(source: str, start: int, end: int) -> bool:
    """True when ``source[start:end]`` begins or ends in the middle of a word.

    ``MIN_QUOTE`` bounds a quotation's LENGTH and nothing else, so four arbitrary 12-character
    slices of one sentence -- ``"An DataCompany e"``, ``"dit stating "``, ``"the receipt'"``,
    ``"s tenant con"`` -- are disjoint, in order, and above the floor. They are not
    quotations. A quotation starts and ends on a word boundary.
    """
    if start >= end:
        # A ZERO-LENGTH span splits nothing, and asking whether it does used to read
        # ``source[end - 1]`` -- which for ``(0, 0)`` is ``source[-1]``, the LAST character of
        # the string, silently answering about the wrong end of the input. Unreachable today
        # behind ``MIN_QUOTE``, and handled anyway for the same reason the ``while True`` was
        # rewritten: a latent hazard is still a hazard, and consistency about that is the
        # point.
        return False
    opens = (
        start > 0
        and re.match(WORD_CHARACTERS, source[start - 1]) is not None
        and re.match(WORD_CHARACTERS, source[start]) is not None
    )
    closes = (
        end < len(source)
        and re.match(WORD_CHARACTERS, source[end]) is not None
        and re.match(WORD_CHARACTERS, source[end - 1]) is not None
    )
    return opens or closes


def _aligned_occurrences(source: str, quotation: str) -> list[int]:
    """Every offset at which ``quotation`` occurs in ``source`` without splitting a word.

    BOUNDED, deliberately. This was a ``while True`` whose only exit was ``if offset < 0:
    return found``, which made the exit condition a mutable guard rather than a property of
    the iteration: disabling that one line -- an ordinary mutation, and one a careless edit
    could make -- did not turn a test red, it HUNG the whole suite forever. A helper whose
    termination depends on a guard that a reviewer might delete is a latent hazard even while
    it is correct, so termination now comes from iterating a finite range of start positions.
    """
    if not quotation:
        # An empty needle matched at every offset and then indexed ``source[end - 1]`` with
        # ``end == offset``, raising for ``offset == 0`` on an empty source. It also is not a
        # quotation, so it has no occurrences.
        return []
    return [
        offset
        for offset in range(len(source) - len(quotation) + 1)
        if source.startswith(quotation, offset)
        and not _splits_a_word(source, offset, offset + len(quotation))
    ]


def _quotation_problems(
    gaps: Sequence[Mapping[str, Any]],
    field: str,
    source: str,
    where: str,
    label: str,
) -> list[str]:
    """Every quotation must appear in ``source``, in order, disjoint, and whole-word.

    The scan is sequential from a cursor rather than a bare ``find`` per gap, which fixes two
    opposite defects at once. A bare ``find`` binds to the FIRST occurrence, so a quotation
    the register legitimately repeats reports a spurious out-of-order failure; and comparing
    raw offsets accepts a quotation NESTED inside the previous one, because a nested fragment
    starts later. Advancing the cursor past the end of each match makes "in order" mean
    "disjoint and in order", which is what quoting four consecutive clauses actually is.
    Leftmost-valid is optimal here: the earliest start gives the earliest end, hence the
    smallest cursor for the next gap.

    What this function CANNOT say is which gap a fragment describes. Length, alignment, order
    and disjointness are all satisfied by an off-by-one SHIFT of four truthful quotations, and
    a share-of-the-sentence floor does not help --- it rewards the scramble, because a shifted
    set covers more of the sentence than the truthful one. Attribution is not expressible
    as a property of a fragment at all, and four rounds of trying produced four defeated
    heuristics; it is an EXACT PIN in
    ``test_the_deferred_obligations_agree_with_the_register`` instead.
    """
    problems: list[str] = []
    cursor = 0
    for gap in gaps:
        # ``.get``, not ``[]``: a MISSING field must produce a finding here rather than raise,
        # because a raise in one gap would abandon the checks for every following gap.
        quotation = gap.get(field)
        if not isinstance(quotation, str) or len(quotation) < MIN_QUOTE:
            # THE FLOOR. Without it the whole scheme reduces to nothing and stays green:
            # replacing all four quotations with "(1)".."(4)" is a set of strings that are
            # all genuinely present, all in order, and say nothing. The property this file
            # claims -- that the structured form cannot drift from the prose -- rested only
            # on how long the strings happened to be.
            problems.append(
                f"{where} {gap.get('id')}: {field} is {quotation!r}, shorter than the "
                f"{MIN_QUOTE}-character floor a quotation has to clear to be one"
            )
            continue
        occurrences = _aligned_occurrences(source, quotation)
        forward = [offset for offset in occurrences if offset >= cursor]
        if not forward:
            if occurrences:
                problems.append(
                    f"{where} {gap.get('id')}: {field} appears in {label} only BEFORE the "
                    "quotation of the preceding gap, or inside it"
                )
            elif quotation in source:
                problems.append(
                    f"{where} {gap.get('id')}: {field} {quotation!r} is a mid-word slice of "
                    f"{label}, not a quotation of it"
                )
            else:
                problems.append(f"{where} {gap.get('id')}: {label} does not contain {quotation!r}")
            continue
        cursor = forward[0] + len(quotation)
    return problems


def _unquoted_remainder(sentence: str, clauses: Sequence[str]) -> list[str]:
    """What is left of ``sentence`` once each clause is removed, in order.

    Extracted so the exhaustiveness rule has synthetic inputs it must ACCEPT and inputs it
    must REJECT, rather than being a lone expression inside an assertion about real data --
    which is how it shipped with an unpinned ``> 40`` and no rejection case.
    """
    remainder = sentence
    for clause in clauses:
        remainder = remainder.replace(clause, "\x00", 1)
    return [part.strip(" ,.;") for part in remainder.split("\x00")]


def _citation_containing(citations: Sequence[str], fragment: str) -> str | None:
    """The single citation a fragment comes from, or ``None`` if it comes from none of them."""
    for citation in citations:
        if fragment and fragment in citation:
            return citation
    return None


def _field_list_problems(
    entry: Mapping[str, Any], citations: Sequence[str], where: str, decision_id: str
) -> list[str]:
    """``corpus_field_list`` must be a real, cited, MULTI-LINE range about a field list.

    Membership in ``citations`` was the whole rule, and ``"" in <str>`` is True -- the
    byte-identical bug this file already names one field down for ``constraint``. Worse than
    the empty string, though, was a genuine citation of the wrong lines: ``16:891`` is cited
    by this very decision and says nothing about the field list, so the "bound to citations"
    design accepted precisely the substantively-wrong pointer it was built to prevent.
    """
    value = entry.get("corpus_field_list")
    if not isinstance(value, str) or len(value) < MIN_QUOTE:
        return [
            f"{where}: corpus_field_list is {value!r}, not a citation clearing the "
            f"{MIN_QUOTE}-character floor"
        ]
    match = CORPUS_RANGE.match(value)
    if match is None or int(match["last"]) <= int(match["first"]):
        return [
            f"{where}: corpus_field_list {value!r} is not a multi-line <file>.md:<first>-<last> "
            "range; a field list of several members cannot sit on one line"
        ]
    # The citation must be ABOUT this range, not merely mention it. ``startswith`` is the
    # structural form of that: a citation in this register opens with the range it cites, so
    # 16:891's citation cannot stand in for 16:873-889's. The earlier test was a raw
    # ``"field list" in citation`` keyword match, which a citation reading "explicitly NOT the
    # field list" satisfies -- a keyword cannot tell an assertion from its negation, and
    # tightening keywords is how a gate gets tuned until it is vacuous.
    if not any(citation.startswith(value) for citation in citations):
        return [
            f"{where}: no citation of {decision_id} opens with {value!r}, so nothing resolves "
            "it against the corpus"
        ]
    return []


def _placeholder_problems(
    entry: Mapping[str, Any],
    citations: Sequence[str],
    where: str,
    decision_id: str,
) -> list[str]:
    """The evidence that the corpus names no URN for this document must assert an absence.

    There WAS a ``urn_is_a_placeholder`` boolean here, derived from ``not _resolves(...)``. It
    is deleted, because that derivation measured the wrong property: ``_resolves`` says "this
    repository does not release it", which is true of all eighteen entries, while the claim
    the field was filed under is "the CORPUS names no URN for it" --- and the corpus does name
    URNs for at least three of the eighteen. A future obligation on one of those would have
    been FORCED by the rule to assert a falsehood. The claim now rests only on the quotation
    below, which is bound, plus the corpus check in
    ``test_the_urn_really_is_absent_from_the_corpus``.
    """
    problems: list[str] = []
    absence = entry.get("urn_absence_quoted_from_citations")
    if not isinstance(absence, str) or len(absence) < MIN_QUOTE:
        problems.append(
            f"{where}: urn_absence_quoted_from_citations is {absence!r}, below the "
            f"{MIN_QUOTE}-character floor, so the URN-absence claim rests on nothing"
        )
        return problems
    citation = _citation_containing(citations, absence)
    if citation is None:
        problems.append(
            f"{where}: urn_absence_quoted_from_citations {absence!r} is not a quotation of "
            f"{decision_id}'s citations"
        )
    elif not re.search(r"\bno urn\b", absence, re.IGNORECASE):
        # The field's ONE job is to evidence an absence. A fragment of a citation that
        # measures where some OTHER URN does appear satisfies "is quoted from the citations"
        # while asserting the opposite of the claim it is filed under.
        problems.append(
            f"{where}: urn_absence_quoted_from_citations {absence!r} is quoted from "
            f"{decision_id} but does not state that no URN exists, which is the only thing "
            "this field is evidence for"
        )
    return problems


def _obligation_drift(
    obligations: Mapping[str, Any],
    decisions: Mapping[str, Mapping[str, Any]],
    owners: Mapping[str, str],
) -> list[str]:
    """Structured deferred obligations must agree with the register prose they quote.

    Both directions matter and they are different failures: a gap edited in the JSON and not
    in the register is a machine-readable claim the decision does not make, and a gap edited
    out of the register leaves the JSON asserting something no decision records any more.
    Quoting VERBATIM and checking the quotations closes both at once; checking that they are
    DISJOINT AND IN ORDER closes the third -- a renumbered or nested fragment that still
    matches somewhere in the paragraph; the ``MIN_QUOTE`` floor and word alignment close the
    fourth, which is quoting so little, or so arbitrarily, that all of the above hold
    vacuously.

    NOTHING HERE CLOSES THE FIFTH, which is WHICH gap a fragment describes. An off-by-one
    shift of four truthful quotations satisfies every rule in this function, and scores HIGHER
    on any share-of-the-sentence measure than the truthful assignment does, so a coverage
    floor rewards the scramble it was meant to catch. That claim is an EXACT PIN in
    ``test_the_deferred_obligations_agree_with_the_register`` and is not a property this
    function can check. This paragraph credited a ``topic`` rule with it until 2026-08-04 --
    the very rule the commit that wrote this sentence had just DELETED for being unable to do
    the job, which is the sixth time this module's prose has claimed a protection its code did
    not have.

    ``MIN_QUOTE`` is imported from ``tests/test_foundation_schemas.py`` rather than restated.
    That module's citation gate answers the identical question -- "is this a quotation or a
    gesture at one" -- and two independently drifting floors for one question is the defect
    this repository keeps finding in other clothes. The coupling is asserted, not assumed:
    see ``test_the_shared_quotation_floor_really_is_shared_and_is_pinned``.
    """
    problems: list[str] = []
    for reference, entry in sorted(obligations.items()):
        where = f"{reference}"
        unknown = sorted(set(entry) - ENTRY_KEYS)
        if unknown:
            problems.append(
                f"{where}: states {unknown}, which no rule checks; add a rule or remove the "
                "field, because an unchecked field beside checked ones reads as checked"
            )
        missing = sorted(ENTRY_KEYS - set(entry))
        if missing:
            problems.append(f"{where}: is missing {missing}")
            continue
        if reference not in owners:
            problems.append(f"{where}: carries an obligation but is not on the allowlist")
            continue
        if entry["owner_context"] != owners[reference]:
            problems.append(
                f"{where}: obligation names owner {entry['owner_context']!r}, allowlist "
                f"names {owners[reference]!r}"
            )
        decision_id = entry["decision"]
        decision = decisions.get(decision_id)
        if decision is None:
            problems.append(f"{where}: cites {decision_id}, which the register does not define")
            continue

        gaps = entry["gaps"]
        rejected = decision.get("rejected", "")
        blocked_on = decision.get("blocked_on", "")
        citations = list(decision.get("citations", []))

        problems += _field_list_problems(entry, citations, where, decision_id)
        problems += _placeholder_problems(entry, citations, where, decision_id)

        if not gaps:
            problems.append(f"{where}: records no gaps, so the deferral states nothing owed")
            continue
        expected_phrase = f"{NUMBER_WORDS[len(gaps)]} MEASURED GAPS"
        if expected_phrase not in rejected:
            problems.append(
                f"{where}: {len(gaps)} gaps are recorded but {decision_id} does not say "
                f"{expected_phrase!r}"
            )

        identifiers = [gap.get("id") for gap in gaps]
        if identifiers != [f"G{index}" for index in range(1, len(gaps) + 1)]:
            problems.append(f"{where}: gap ids are {identifiers}, expected G1..G{len(gaps)}")

        for gap in gaps:
            unknown = sorted(set(gap) - GAP_KEYS)
            if unknown:
                problems.append(f"{where} {gap.get('id')}: states {unknown}, which no rule checks")
            gap_missing = sorted(GAP_KEYS - OPTIONAL_GAP_KEYS - set(gap))
            if gap_missing:
                problems.append(f"{where} {gap.get('id')}: is missing {gap_missing}")

        # The ENTRY-level skip that used to sit here is gone. It was guarded by a second,
        # separate evaluation of the missing-key expression above, so disabling that finding
        # left the skip in place and the entry's quotation checks were abandoned in silence.
        # Every rule below reads through ``.get``, so a missing field is a finding rather than
        # a raise. (An earlier version of this comment claimed no ``continue`` remained
        # anywhere and that ``.get`` was used throughout; both were false -- ``gap['id']``
        # raised on seven lines and a per-gap ``continue`` after an empty ``constraint``
        # skipped that gap's ``register_paraphrase`` validation entirely.)

        problems += _quotation_problems(
            gaps, "quoted_from_register", rejected, where, f"{decision_id}.rejected"
        )
        problems += _quotation_problems(
            gaps, "quoted_from_blocked_on", blocked_on, where, f"{decision_id}.blocked_on"
        )

        for gap in gaps:
            identifier = gap.get("id")
            quotation = gap.get("quoted_from_register") or ""
            members = gap.get("members")
            # An EMPTY member list disables member checking in silence, which is the same
            # class of vacuity as an empty enumeration reporting a clean scan.
            if not isinstance(members, list) or not members:
                problems.append(
                    f"{where} {identifier}: records no members, so nothing says which part of "
                    "the field list the gap is about"
                )
            for member in members or []:
                if not isinstance(member, str) or not member:
                    problems.append(f"{where} {identifier}: records an empty member")
                elif not _names_whole_token(quotation, member):
                    problems.append(
                        f"{where} {identifier}: states member {member!r}, which its own "
                        f"quotation of {decision_id} does not name"
                    )
            if "constraint" in gap:
                constraint = gap["constraint"]
                if not isinstance(constraint, str) or not constraint:
                    problems.append(f"{where} {identifier}: records an empty constraint")
                else:
                    # TWO INDEPENDENT CHECKS AND ONE CONDITIONAL ONE, which is what the code
                    # below actually is. "Appears in the quotation" is satisfied by any prefix
                    # that is a token there, so truncating to ``resource_scope`` was green
                    # until resolution was added; and "it resolves" is satisfied by the BARE
                    # DOCUMENT URN, because ``resolve_pointer`` returns the document root for
                    # one, so truncating at the ``#`` survived resolution too. Neither
                    # subsumes the other, so both run.
                    #
                    # Resolution is ``elif`` on the pointer shape DELIBERATELY: asking whether
                    # a string that names no definition resolves to a definition is not a
                    # second fault, it is the same one restated. An earlier version of this
                    # comment claimed three independent checks and "a constraint wrong in two
                    # ways must say so twice"; that was true of checks 1 and 2 and never of 2
                    # and 3, and the restructure it described was a pure refactor.
                    if not _names_whole_token(quotation, constraint):
                        problems.append(
                            f"{where} {identifier}: states constraint {constraint!r}, which its "
                            f"own quotation of {decision_id} does not mention"
                        )
                    if DEFS_POINTER not in constraint:
                        problems.append(
                            f"{where} {identifier}: constraint {constraint!r} does not contain "
                            f"{DEFS_POINTER!r}, so it names a document rather than the "
                            "definition the gap is measured against"
                        )
                    elif not _resolves(f"urn:datacompany:{constraint}"):
                        problems.append(
                            f"{where} {identifier}: constraint {constraint!r} does not resolve "
                            "to a released schema definition"
                        )
            if "register_paraphrase" in gap:
                problems += _paraphrase_problems(gap, where)
    return problems


def _paraphrase_problems(gap: Mapping[str, Any], where: str) -> list[str]:
    """A note recording that the register's wording is not the corpus's.

    What THIS function binds, and it is not everything: the paraphrased phrase and the
    location it is attributed to must both be IN the gap's own quotation of the register, and
    the corpus wording must NOT be -- a note claiming the two differ while quoting the same
    words back is not a note. ``attributed_to`` must additionally be a resolvable-looking
    ``<file>.md:<first>-<last>`` range rather than any old fragment.

    What it CANNOT bind is whether ``corpus_wording`` is what the corpus actually says, which
    needs the corpus. That half is
    ``test_the_paraphrase_note_matches_the_real_corpus``, which resolves it against real bytes
    where the corpus is checked out and asserts its ABSENCE where it is not, following
    ``test_every_corpus_citation_resolves_to_the_lines_it_claims``. Saying so here rather than
    claiming "every part of it is bound" is the point: the previous wording claimed a
    property this function did not have, and a fabricated ``corpus_wording`` passed.
    """
    problems: list[str] = []
    note = gap.get("register_paraphrase")
    quotation = gap.get("quoted_from_register") or ""
    if not isinstance(note, dict) or set(note) != PARAPHRASE_KEYS:
        return [
            f"{where} {gap.get('id')}: register_paraphrase must have keys {sorted(PARAPHRASE_KEYS)}"
        ]
    for key in ("phrase", "attributed_to"):
        value = note[key]
        if not isinstance(value, str) or len(value) < MIN_QUOTE or value not in quotation:
            problems.append(
                f"{where} {gap.get('id')}: register_paraphrase.{key} {value!r} is not a "
                f"quotation of at least {MIN_QUOTE} characters from this gap's own "
                "quoted_from_register"
            )
    if isinstance(note["attributed_to"], str) and not CORPUS_RANGE.match(note["attributed_to"]):
        problems.append(
            f"{where} {gap.get('id')}: register_paraphrase.attributed_to "
            f"{note['attributed_to']!r} is not a <file>.md:<first>-<last> range, so nothing "
            "can resolve it against the corpus"
        )
    wording = note["corpus_wording"]
    if not isinstance(wording, str) or len(wording) < MIN_QUOTE:
        problems.append(f"{where} {gap.get('id')}: register_paraphrase.corpus_wording is too short")
    elif wording in quotation:
        problems.append(
            f"{where} {gap.get('id')}: register_paraphrase.corpus_wording {wording!r} is the "
            "very text it says the register does not use, so the note records no difference"
        )
    return problems


def _corpus_paraphrase_problems(gap: Mapping[str, Any], corpus: Path, where: str) -> list[str]:
    """Resolve a paraphrase note against REAL corpus bytes, in both directions.

    ``corpus_wording`` has to be there and ``phrase`` has to NOT be, which is the entire claim
    the note makes. Neither half alone is the claim: a note whose corpus wording is real but
    whose paraphrase is ALSO present records a difference that does not exist.
    """
    note = gap["register_paraphrase"]
    match = CORPUS_RANGE.match(note["attributed_to"])
    if match is None:  # pragma: no cover - the structural rule rejects this first
        return [f"{where} {gap['id']}: attributed_to is not a range"]
    path = corpus / match["file"]
    if not path.is_file():
        return [f"{where} {gap['id']}: {match['file']} does not exist in the corpus"]
    lines = path.read_text(encoding="utf-8").splitlines()
    first, last = int(match["first"]), int(match["last"])
    if last > len(lines):
        return [f"{where} {gap['id']}: {note['attributed_to']} is past EOF ({len(lines)})"]
    window = normalise_prose(" ".join(lines[first - 1 : last]))
    problems = []
    if normalise_prose(note["corpus_wording"]) not in window:
        problems.append(
            f"{where} {gap['id']}: corpus_wording {note['corpus_wording']!r} is not what "
            f"{note['attributed_to']} says, so the note is fabricated"
        )
    if normalise_prose(note["phrase"]) in window:
        problems.append(
            f"{where} {gap['id']}: phrase {note['phrase']!r} IS at {note['attributed_to']}, so "
            "there is no paraphrase to record"
        )
    return problems


def _typed_ref_pins() -> dict[str, str]:
    """The ``$defs`` name -> ``schema_ref`` constant ``typed-refs:1`` states as a requirement."""
    document = canonical_schemas()[TYPED_REFS]
    return {
        name: definition["properties"]["schema_ref"]["const"]
        for name, definition in document["$defs"].items()
    }


# ====================================================== the sweep measures a real corpus ===


def test_every_corpus_root_exists_and_contributes_documents() -> None:
    """A root that stopped existing rglobs to ``[]`` in silence and reads as a clean scan."""
    assert len(CORPUS_ROOTS) == 3, CORPUS_ROOTS
    for root in CORPUS_ROOTS:
        assert root.is_dir(), f"{root} is not a directory; the sweep would silently skip it"
        assert _documents([root]), root


def test_the_sweep_finds_exactly_the_corpus_it_is_pinned_to() -> None:
    """EQUALITIES, not floors. A floor cannot catch the drop it exists for: deleting the
    fixture that names ``analysis-run:1`` leaves ``>= 30`` green while the corpus quietly
    stops covering a document somebody is recorded as owing.

    Measured on the committed tree at the time of writing: 47 distinct ``schema_ref``
    values, 29 of which the released registry resolves. FND-002 task 4 moved both numbers:
    the evidence tier releases three documents the corpus already named or now names, and
    its fixtures pin two more documents nobody releases. 46 -> 47 on 2026-08-02, when the
    ninth-prohibition fixture pinned ``evidence-resolution-receipt:1`` -- a document FND-002
    task 4 was scoped to define and DEFERRED (IMP-DEC-FND002-041). It resolves to nothing, so
    it joins the deferred allowlist rather than the released count, which stays at 29.

    47 -> 48 and 29 -> 30 on 2026-09-02, when ``research-event-envelope.v1`` was released and
    pinned its OWN ``$id`` as a ``const``. Both numbers move together, which is the whole
    signature of a released document naming itself: the two evidence-tier export schemas
    deliberately composed the grammar instead, so they moved neither. The envelope is the
    case where the const is the point rather than the symmetry -- a consumer parsing a mixed
    outbox stream reads that field and nothing else to decide which envelope grammar it is
    holding, and an envelope with no version pin is not an envelope. See authoring decision
    (1) in that document's ``$comment``.

    48 -> 49 and 30 -> 31 on 2026-09-03, when ``evidence-snapshot-manifest.v1`` was
    released and likewise pinned its own ``$id`` as a ``const``. Both numbers move
    together again, for the same reason and with the same signature. A snapshot manifest
    is envelope-shaped rather than payload-wrapping: a consumer holding one has to know
    which manifest grammar it is reading BEFORE it can decide whether the members it sees
    are the members that were sealed, and it cannot ask the producer, because the whole
    point is that the producer may be long gone by the time the snapshot is read.

    49 -> 49 and 31 -> 32 on 2026-09-04, when ``approval-attestation.v1`` was
    released. Only the RESOLVING count moves this time, and that asymmetry is
    the interesting part: the urn was ALREADY in the swept corpus, because it sat
    in ``config/deferred-schema-owners.json`` owed by ``fr-control-plane``.
    Releasing it turned a deferred reference into a resolving one and discharged
    the debt -- which is why that allowlist entry had to be removed in the same
    commit, and why the allowlist test failed until it was.

    49 -> 52 and 32 -> 35 on 2026-09-04, when ``FND-003`` task 1 and task 2 released
    ``operation-idempotency-record.v1``, ``durable-job.v1`` and ``job-attempt.v1``.
    Both numbers move by the same three, which is the ordinary signature and the
    opposite of the attestation's: none of these three urns was in the swept corpus
    beforehand, because none was ever deferred to another owner -- the grammar was
    simply never written, while two services kept the tables anyway.

    52 -> 53 and 35 -> 36 on 2026-09-04, when ``application-receipt.v1`` was released
    alongside the twelve event-payload documents. Both move by ONE, not by thirteen,
    and that asymmetry is worth stating because a future reader will otherwise assume
    the sweep missed twelve files. It did not: this sweep keys on a document declaring
    a ``schema_ref`` member, and the twelve payload documents deliberately declare none.
    The envelope owns ``schema_ref`` -- it names the ENVELOPE grammar a consumer parses
    the row with -- and a payload document that also claimed one would give a single
    outbox row two competing self-descriptions. What binds an event type to its payload
    document is the catalogue's schema-URN column, not a member on the payload.
    """
    references = _schema_refs()
    assert len(references) == 53, sorted(references)
    assert sum(1 for reference in references if _resolves(reference)) == 36, sorted(
        reference for reference in references if _resolves(reference)
    )


def test_the_widened_scope_really_reaches_the_released_schemas() -> None:
    """The ``schemas/`` root and the ``const`` spelling both have to be doing work.

    Widening the roots without collecting the ``const`` form would add three directories and
    zero references, which reads exactly like a widening that fired.
    """
    references = _schema_refs()
    schema_file = "schemas/canonical/typed-refs.v1.schema.json"
    for pinned in _typed_ref_pins().values():
        assert schema_file in references.get(pinned, set()), (
            f"{pinned} did not reach the sweep through the released schema that pins it"
        )


# ============================================================== the rules, on the corpus ===


def test_every_pinned_schema_ref_resolves_or_names_the_context_that_owes_it() -> None:
    unaccounted = _unaccounted(_schema_refs(), DEFERRED_SCHEMA_OWNERS)
    assert unaccounted == {}, (
        "these pinned schema_refs resolve to nothing and no context is recorded as owing "
        f"them, so they can never be verified: {unaccounted}"
    )


def test_the_deferred_allowlist_has_no_stale_entries() -> None:
    """An allowlist entry nobody references is a claim about a corpus that moved on."""
    bases = {reference.partition("#")[0] for reference in _schema_refs()}
    stale = sorted(set(DEFERRED_SCHEMA_OWNERS) - bases)
    assert stale == [], f"allowlisted but referenced by nothing in the swept corpus: {stale}"

    resolved_anyway = sorted(entry for entry in DEFERRED_SCHEMA_OWNERS if _resolves(entry))
    assert resolved_anyway == [], (
        "these are recorded as deferred but the registry releases them; move them out of the "
        f"allowlist: {resolved_anyway}"
    )


def test_the_allowlist_is_exactly_the_set_of_unowned_documents() -> None:
    """The two directions above, stated as the single equality they add up to.

    This is what makes the register's count checkable rather than a number somebody typed:
    the allowlist IS the corpus's unowned set, so ``len`` of one is ``len`` of the other.
    """
    unowned = {
        reference.partition("#")[0]
        for reference in _schema_refs()
        if not _resolves(reference.partition("#")[0])
    }
    assert unowned == set(DEFERRED_SCHEMA_OWNERS), {
        "in the corpus only": sorted(unowned - set(DEFERRED_SCHEMA_OWNERS)),
        "on the allowlist only": sorted(set(DEFERRED_SCHEMA_OWNERS) - unowned),
    }


def test_the_register_states_the_number_the_sweep_actually_measures() -> None:
    """IMP-DEC-FND002-020 said 14. The sweep says **18**: 15 over ``fixtures/`` alone, 16 once
    the corpus carried an instance of ``document-version:1``, 17 once FND-002 task 4 released
    ``evidence-location-version:1`` (which LEFT the allowlist, because the registry resolves it
    now) and pinned ``coordinate-manifest:1`` and ``decomposition-block:1`` (which joined it),
    and 18 once the ninth-prohibition fixture pinned ``evidence-resolution-receipt:1`` -- the
    document IMP-DEC-FND002-041 defers.

    THIS COUNT IS THE NUMBER OF ASSIGNMENTS, and it is not the number of assignments the
    agreement check compares. That one is 17, because one entry is excused as unobserved, and
    ``test_each_allowlisted_owner_agrees_with_what_the_corpus_states`` pins it separately.
    Reading either number as the other is how this docstring came to say 17 while the
    assertion below measured 18; ``config/deferred-schema-owners.json`` now states both under
    ``counts``, named for what each one measures.

    A count written in prose drifts the moment a fixture lands. This binds it, so the next
    document added to the deferred set either updates the register or turns this red.
    """
    register = json.loads(DECISIONS.read_text(encoding="utf-8"))
    entry = next(d for d in register["decisions"] if d["id"] == "IMP-DEC-FND002-020")
    recorded = entry["measured_unowned_schema_urns"]
    assert recorded == len(DEFERRED_SCHEMA_OWNERS), recorded
    assert f"{recorded} distinct schema URNs" in entry["rejected"], entry["rejected"]


def test_the_two_counts_this_file_states_are_the_ones_the_sweep_measures() -> None:
    """18 assignments and 17 comparisons are two facts, and they were being used as one.

    ``config/deferred-schema-owners.json`` prose said "eighteen assignments" while this
    module's docstrings said "seventeen" and IMP-DEC-FND002-020's narration still ends at 17;
    the pair happened to be consistent because exactly one entry is excused. Stating both,
    named, and asserting each against a live measurement is what stops the next reader
    reaching for whichever one is nearer.
    """
    drift = _count_drift(
        STATED_COUNTS,
        len(DEFERRED_SCHEMA_OWNERS),
        len(OWNER_NOT_OBSERVED_IN_CORPUS),
        _governance()["status"],
    )
    assert drift == {}, drift

    # ...and the sentence itself is PINNED. Only the number word was bound -- twelve characters
    # of two hundred and fifteen -- so replacing the rest with its own negation ("CLOSED - all
    # eighteen assignments have been accepted ... OWNERS.yaml plus .github/CODEOWNERS now
    # assign accountable owners") kept the word "eighteen", satisfied every check, and
    # contradicted both facts the sentence exists to state. Prose that survives in this file
    # is pinned prose; the alternative was deleting it with the other eleven.
    # Re-pinned 2026-08-08 when IMP-DEC-001 (Python half) made "assign nobody" false. The
    # weakening this pin guards against is now a different sentence with the same shape:
    # "OWNERS.yaml now assigns owners" read as though it discharged the eighteen per-schema
    # obligations. It does not — it assigns the REPOSITORY — and the pinned words
    # "per-schema" and "neither names an owner for any individual schema" are what say so.
    assert _governance()["status"] == (
        "OPEN — no obligation here has been accepted by the named context. OWNERS.yaml "
        "assigns repository-level accountability (IMP-DEC-001, Python half, 2026-08-08) and "
        ".github/CODEOWNERS still assigns nobody, but neither names an owner for any "
        "individual schema, so the seventeen assignments below remain the only per-schema "
        "ownership statements this repository makes. An entry was discharged on 2026-09-04: "
        "`urn:datacompany:approval-attestation:1` was RELEASED, so its deferral (owed by "
        "fr-control-plane) no longer stands. A urn cannot be both deferred and released, and "
        "the resolution sweep fails if it is."
    ), _governance()["status"]
    # The excused count is what makes the two numbers differ at all, so a run in which nothing
    # is excused would make this test pass while measuring the same number twice.
    assert STATED_COUNTS["excused_owner_not_observed_in_corpus"] >= 1, STATED_COUNTS


def test_the_deferred_obligations_agree_with_the_register() -> None:
    """A deferral names an owner; this makes it also state what that owner is owed.

    ``config/deferred-schema-owners.json`` is the file a context arriving at this work reads,
    because it is the one that names it as owner. The four gaps that make
    ``evidence-resolution-receipt:1`` undeliverable were prose inside IMP-DEC-FND002-041, so
    the assignment travelled and the obligation did not.
    """
    problems = _obligation_drift(DEFERRED_OBLIGATIONS, _decisions(), DEFERRED_SCHEMA_OWNERS)
    assert problems == [], "\n".join(problems)

    # Non-vacuity: an empty obligations map, or entries with no gaps, satisfies the rule above
    # by iterating over nothing. The receipt is the entry the register defers, so it is named
    # here rather than counted.
    receipt = "urn:datacompany:evidence-resolution-receipt:1"
    assert receipt in DEFERRED_OBLIGATIONS, sorted(DEFERRED_OBLIGATIONS)
    assert len(DEFERRED_OBLIGATIONS[receipt]["gaps"]) == 4, DEFERRED_OBLIGATIONS[receipt]["gaps"]

    # ===================================================================== THE EXACT PINS ===
    #
    # ATTRIBUTION IS NOT A PROPERTY OF A FRAGMENT, and four rounds of trying to express it as
    # one produced four defeated heuristics: a share-of-the-sentence floor (which REWARDED an
    # off-by-one shift, scoring 0.9875 against the truthful 0.7292), then a per-gap ``topic``
    # (whole-token in both quotations and unique across gaps) which fell to simply re-choosing
    # the topics -- G3 taking "a non-authorized decision" with topic "decision", a whole token
    # in its own register quotation only by accident, leaving the versioned-envelope clause
    # quoted by nobody. Every rule stayed satisfied and the suite stayed green, which is
    # exactly the defect this entry exists to prevent: an obligation telling a context it is
    # blocked on something the decision does not say it is blocked on.
    #
    # So the mapping from gap to clause is PINNED, the way ``members`` already was and the way
    # ``test_the_typed_refs_pins_are_the_four_the_freeze_list_names`` pins its four. A pin
    # cannot be gamed by re-choosing content: any edit to the assignment is a diff here, and a
    # reviewer reads the pin beside the register. The structural rules above still run --- they
    # are what a NEW entry gets before anyone has reviewed it --- but they no longer carry the
    # attribution claim on their own.
    entry = DEFERRED_OBLIGATIONS[receipt]
    pinned = {
        "G1": {
            "members": ["resource_scope", "resource_tenant_id"],
            "constraint": "stable-identity:1#/$defs/resource_scope_conditional",
            "quoted_from_blocked_on": "the receipt's tenant conditional",
            "register_paraphrase": {
                "phrase": "says no schema may weaken",
                "attributed_to": "implementation-plans/00-shared-foundation.md:185-189",
                "corpus_wording": "No schema may replace it with a nullable tenant ID",
            },
        },
        "G2": {
            "members": ["actor_or_service_ref", "destination_or_provider"],
            "quoted_from_blocked_on": (
                "the types of actor_or_service_ref and destination_or_provider"
            ),
        },
        "G3": {
            "members": ["version_id", "version_number", "schema_ref", "content_hash"],
            "quoted_from_blocked_on": "whether it is a versioned envelope",
        },
        "G4": {
            "members": ["failure_code", "problem_ref"],
            "quoted_from_blocked_on": "how a non-authorized decision reports its reason",
        },
    }
    actual = {
        gap["id"]: {key: value for key, value in gap.items() if key in pinned[gap["id"]]}
        for gap in entry["gaps"]
    }
    assert actual == pinned, actual
    # Each gap's ``quoted_from_register`` is pinned by its opening ordinal and its full length,
    # which is what makes truncating one to half a finding rather than a shorter quotation.
    assert {
        gap["id"]: (gap["quoted_from_register"][:3], len(gap["quoted_from_register"]))
        for gap in entry["gaps"]
    } == {
        "G1": ("(1)", 426),
        "G2": ("(2)", 214),
        "G3": ("(3)", 342),
        "G4": ("(4)", 218),
    }, {
        gap["id"]: (gap["quoted_from_register"][:3], len(gap["quoted_from_register"]))
        for gap in entry["gaps"]
    }

    # The four clauses must EXHAUST the sentence, so a clause quoted by NOBODY is a finding.
    # The pins above catch re-pointing and truncation; this is the only thing standing between
    # the register and a decision that GROWS a clause -- the receipt becoming blocked on a
    # fifth thing while this file still records four and says nothing about the fifth.
    #
    # It was a bare ``len(part) > 40``: an unexplained magic number, with no rejection case and
    # no boundary probe, in the same commit that pinned five other floors at their boundary
    # BECAUSE "a floor tested only at 3 characters proves floor > 3". The largest legitimate
    # leftover is 28, so it shipped with twelve characters of slack, and inserting "its
    # retention rule," left a 23-character leftover that sailed under it. The floor is gone:
    # the remainder is PINNED, which needs no threshold and catches an inserted clause of any
    # length at all.
    remainder = _unquoted_remainder(
        _decisions()[entry["decision"]]["blocked_on"],
        [gap["quoted_from_blocked_on"] for gap in entry["gaps"]],
    )
    assert remainder == [
        "An DataCompany edit stating",
        "",
        "",
        "and",
        "A URN would follow from that",
    ], remainder
    # ...and the document really is still unreleased. An obligation recorded against a schema
    # this repository has since shipped is a stale claim, not an obligation.
    assert not _resolves(receipt)


def test_the_register_says_nothing_no_rule_checks() -> None:
    """The derived-key rule, applied to the FILE and not only to ``entries[*]``.

    It used to stop at the obligation entries, and every essay in this register sat above
    that line. Twelve prose fields could each be replaced with an outright falsehood, one
    subtree deleted entirely, and two new keys invented, with the whole suite green -- the
    only bound thing in any of them was a single number word.

    Those fields are now GONE rather than hedged. What survives is data plus one sentence
    whose two claims are both asserted, and this test is what stops an essay coming back: a
    key at any level that no rule checks is a finding, which for prose means it cannot be
    added at all.
    """

    # DUPLICATE KEYS FIRST, on the raw bytes. ``json.loads`` keeps the LAST occurrence and
    # discards the rest in silence, so a register carrying ``"status"`` twice parses to the
    # right value while a human reading the file sees a different one first. Every value rule
    # below runs on the parsed document and therefore cannot see it at all.
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            assert key not in seen, f"duplicate key {key!r} in the register"
            seen[key] = value
        return seen

    json.loads(OWNERSHIP.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)

    document = _governance()
    for path, permitted in REGISTER_SHAPE.items():
        node = document
        for step in filter(None, path.split(".")):
            node = node[step]
        assert set(node) == permitted, {
            "at": path or "<top level>",
            "unchecked": sorted(set(node) - permitted),
            "missing": sorted(permitted - set(node)),
        }
    # Non-vacuity: the shape is only a constraint if it really covers the essay-sized fields.
    assert "purpose" not in document and "derivation" not in document, sorted(document)
    assert set(document["deferred_obligations"]) == {"entries"}, document["deferred_obligations"]


def test_the_registers_own_identity_is_what_it_claims() -> None:
    """``register_id`` and ``decision`` name this file; falsifying either used to be green."""
    document = _governance()
    assert document["register_id"] == "urn:datacompany:deferred-schema-owners:1", document
    assert document["decision"] == "IMP-DEC-FND002-020", document
    # It is a schema URN, so it satisfies the released pattern every other URN here does.
    pattern = resolve_pointer("urn:datacompany:stable-identity:1#/$defs/schema_ref")["pattern"]
    assert re.match(pattern, document["register_id"]), (pattern, document["register_id"])


def test_every_additional_observed_context_really_is_observed() -> None:
    """This map WIDENS the agreement check, so an invented entry is a loosening.

    ``_disagreements`` tolerates any context listed here, and nothing constrained the map's
    keys or values: adding one silently excused a real owner disagreement. Every key must be
    an allowlisted URN and every context must be one the CORPUS states beside that
    ``schema_ref`` --- which is what the field's name already claims and nothing checked.
    """
    observed = _owners_beside_schema_refs()
    assert ADDITIONAL_OBSERVED_CONTEXTS, "nothing here; this rule would measure nothing"
    # The RAW lists, not the frozensets the module builds: ``frozenset`` absorbs a duplicated
    # entry, so ``["guideline-registry", "guideline-registry"]`` was semantically identical and
    # nothing said the register had grown a repeated claim.
    raw = _governance()["additional_observed_contexts"]["entries"]
    for reference, listed in raw.items():
        assert len(listed) == len(set(listed)), (reference, listed)

    for reference, contexts in ADDITIONAL_OBSERVED_CONTEXTS.items():
        assert reference in DEFERRED_SCHEMA_OWNERS, reference
        assert contexts, reference
        unobserved = sorted(contexts - observed.get(reference, set()))
        assert unobserved == [], (
            f"{reference} lists {unobserved} as additionally OBSERVED, but no document in the "
            "corpus states that owner_context beside it"
        )


def test_every_excused_entry_names_the_owner_it_excuses() -> None:
    """The excuse text is the one prose value that survived, so it is bound too.

    An entry is excused from the agreement check because its owner was assigned editorially;
    the justification therefore has to name the owner it is justifying, or it is a sentence
    about nothing that happens to sit beside the right key.
    """
    excuses = _governance()["owner_not_observed_in_corpus"]["entries"]
    assert excuses, "nothing is excused; this rule would measure nothing"
    for reference, text in excuses.items():
        owner = DEFERRED_SCHEMA_OWNERS[reference]
        assert _names_whole_token(text, owner), (reference, owner, text)

    # ...and PINNED, like ``status``. Binding only the owner token left the rest of the
    # sentence free: a Cyrillic homoglyph substituted into it changed the text nobody reads
    # twice and nothing noticed. Prose that survives in this file is pinned prose.
    assert excuses == {
        "urn:datacompany:recommendation-version:1": (
            "Named by fixtures that state no owner_context in the same object; "
            "guideline-registry is assigned from the implementation plans rather than observed."
        )
    }, excuses


def test_schema_ref_really_is_only_a_pattern() -> None:
    """The premise this entire register rests on, asserted for the first time.

    ``stable-identity:1#/$defs/schema_ref`` is a PATTERN --- it checks that a value looks like
    ``urn:datacompany:<name>:<major>`` and nothing more --- and every rule in this module exists
    BECAUSE that is true. Nothing checked it. If a future release gave that ``$def`` an
    ``enum`` or a ``const``, the released schema would resolve pins itself and this file's
    reason for existing would be gone, while
    the suite stayed green.
    """
    definition = resolve_pointer("urn:datacompany:stable-identity:1#/$defs/schema_ref")
    assert "pattern" in definition, definition
    assert not (set(definition) & {"enum", "const"}), (
        "schema_ref now constrains its VALUE, not just its shape; the deferred allowlist's "
        f"stated premise no longer holds: {definition}"
    )
    # ...and the pattern really does admit a URN nobody releases, which is the specific
    # consequence the register describes.
    unreleased = "urn:datacompany:a-document-nobody-owns:1"
    assert re.match(definition["pattern"], unreleased), definition["pattern"]
    assert not _resolves(unreleased)


def test_owners_yaml_really_assigns_nothing_else() -> None:
    """The premise of this whole register, asserted rather than repeated.

    ``config/deferred-schema-owners.json`` says its assignments are "the only concrete
    ownership statements the repository makes about anything" BECAUSE ``OWNERS.yaml`` is
    ``UNASSIGNED`` throughout, and this module's docstrings repeat it. Nothing checked it:
    ``tests/test_draft_governance.py`` reads ``OWNERS.yaml`` as a fixture INPUT and asserts
    things about synthetic copies, so a real assignment landing there would leave every
    statement of this premise false and green. Pre-existing, and fixed here because this
    branch is what leans on it.
    """
    # ``.github/CODEOWNERS`` is the OTHER place this repository could assign ownership, and
    # OWNERS.yaml's own notes name it as the thing that must stay disabled. Reading only
    # OWNERS.yaml while claiming "assigns nobody" left exactly one of the two files checked.
    codeowners = ROOT / ".github" / "CODEOWNERS"
    if codeowners.is_file():
        rules = [
            line
            for line in codeowners.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert rules == [], (
            f".github/CODEOWNERS now carries active rules {rules}; OWNERS.yaml's own note says "
            "no CODEOWNERS rule may be enabled until accountable ownership is assigned"
        )

    # Inverted 2026-08-08 with IMP-DEC-001 (Python half). OWNERS.yaml now assigns
    # REPOSITORY-level accountability, so "assigns nobody" is false and the register
    # says so. What must stay true is the narrower claim the register actually leans
    # on: nothing outside this file names an owner for an INDIVIDUAL schema. A
    # repository owner appearing in OWNERS.yaml does not discharge eighteen per-schema
    # obligations, and must not be allowed to read as though it did.
    owners = yaml.safe_load((ROOT / "OWNERS.yaml").read_text(encoding="utf-8"))
    register = _governance()
    assert "assign nobody" not in register["status"], (
        "OWNERS.yaml assigns repository-level accountability; the register's status must "
        "not still claim otherwise"
    )
    schema_ids = set(register["deferred_schema_owners"])
    owners_text = yaml.safe_dump(owners, sort_keys=False)
    leaked = sorted(schema_id for schema_id in schema_ids if schema_id in owners_text)
    assert leaked == [], (
        f"OWNERS.yaml now names {leaked} directly, so the deferred register is no longer the "
        "only place per-schema ownership is stated; reconcile the two before this register "
        "can keep calling itself the sole source"
    )
    assert all(value != "UNASSIGNED" for value in owners["blocking_decisions"].values()), owners[
        "blocking_decisions"
    ]
    assert owners["deferred_decisions"] == {}, (
        "nothing is deferred as of 2026-09-04, when the npm half of IMP-DEC-001 was ratified "
        "as @nonagentic/research-contracts and REQUIRED_DEFERRED_DECISIONS in "
        "tooling/governance.py was emptied in the same commit. The mapping stays present and "
        "empty rather than deleted: an empty mapping is a claim a reader can check, a missing "
        "key is indistinguishable from one removed to make a gate pass. If a row reappears "
        "here, this register's 'OPEN' status needs re-examining with it"
    )


def test_the_optional_gap_rules_have_at_least_one_live_instance() -> None:
    """A rule with zero live instances is switched off without anyone editing it.

    ``constraint`` and ``register_paraphrase`` are OPTIONAL, and only G1 carries either --- so
    deleting both left the constraint-resolution rule and the whole paraphrase function with
    nothing to run on, and the suite passed. The same pin already exists for ``len(gaps) == 4``
    and for the receipt's presence; these two were the ones nobody had written down.
    """
    gaps = [gap for entry in DEFERRED_OBLIGATIONS.values() for gap in entry["gaps"]]
    assert [gap["id"] for gap in gaps if "constraint" in gap] == ["G1"], gaps
    assert [gap["id"] for gap in gaps if "register_paraphrase" in gap] == ["G1"], gaps


def test_the_shared_quotation_floor_really_is_shared_and_is_pinned() -> None:
    """``MIN_QUOTE`` is a COUPLING to a file a sibling session may be editing right now.

    Three things can go wrong and only one of them was visible. A local rebinding to 12 makes
    the "imported, not restated" claim false while everything passes; a sibling LOWERING it
    silently weakens every quotation rule here, and the reduction tests use three-character
    strings so they prove ``floor > 3`` rather than ``floor == 12``; a sibling RAISING it
    breaks this module in three places with no message saying why.

    So: the import is asserted to exist in this file's own source, the value is pinned, and
    the behaviour is pinned at the boundary rather than far from it.
    """
    import test_foundation_schemas

    source = Path(__file__).read_text(encoding="utf-8")
    assert "from test_foundation_schemas import MIN_QUOTE" in source, (
        "MIN_QUOTE must be IMPORTED from the citation gate, not rebound locally; a local "
        "constant that happens to equal 12 satisfies every other assertion here"
    )
    assert MIN_QUOTE == test_foundation_schemas.MIN_QUOTE
    assert MIN_QUOTE == 12, (
        f"the citation gate's quotation floor moved to {MIN_QUOTE}. That is a decision about "
        "both gates: re-measure the obligation quotations before changing this pin."
    )

    # AT the boundary, both sides. A test that only ever probes 3 characters proves the floor
    # is somewhere above 3 and would not notice it dropping to 4.
    # The probe is word-aligned at exactly MIN_QUOTE so the FLOOR is what is being measured
    # and not the alignment rule; "abcdefgh ijk" is twelve characters ending on a boundary.
    source_text = "abcdefgh ijk lmnopqrs tuv"
    for length, expect_problem in ((MIN_QUOTE - 1, True), (MIN_QUOTE, False)):
        gap = {"id": "G1", "quoted_from_register": source_text[:length]}
        problems = _quotation_problems([gap], "quoted_from_register", source_text, "x", "y")
        assert bool(problems) is expect_problem, (length, problems)

    # ...and normalise_prose is imported from the same module; pin the behaviour this file
    # depends on so a silent change there is red here rather than subtly permissive.
    assert normalise_prose("`No` “schema” may — replace") == "no schema may - replace"


def test_each_allowlisted_owner_agrees_with_what_the_corpus_states() -> None:
    """The allowlist may not drift from the documents that motivate it.

    17 of the 18 assignments are compared here. They are DIFFERENT NUMBERS for different
    facts -- 18 documents are assigned an owner, 17 of those owners are checked against a
    document that states one -- and the two were used interchangeably across this module, the
    ownership register and IMP-DEC-FND002-020 until 2026-08-03.
    """
    disagreements, checked = _disagreements(
        _owners_beside_schema_refs(),
        DEFERRED_SCHEMA_OWNERS,
        ADDITIONAL_OBSERVED_CONTEXTS,
        OWNER_NOT_OBSERVED_IN_CORPUS,
    )
    assert disagreements == {}, disagreements
    # An EQUALITY, not a floor: the loop passes by skipping, so "how many were really
    # compared" is the only thing standing between this test and vacuity, and a floor of 10
    # would stay green while four entries stopped being observable.
    # 17 -> 16 on 2026-09-04, in step with the register's own
    # `compared_against_the_corpus`: `approval-attestation:1` left the allowlist
    # when it was released, and it was one of the entries the corpus named.
    assert checked == 16, f"{checked} allowlist entries were checked against the corpus"
    # ...and the same number DERIVED, which is what makes 17 self-describing rather than a
    # constant somebody typed. Both are asserted: the derivation alone would stay green if an
    # entry were quietly moved into the excused set (18 - 2 = 16 == 16), and the literal alone
    # never says WHY it is one less than the number of assignments.
    assert checked == len(DEFERRED_SCHEMA_OWNERS) - len(OWNER_NOT_OBSERVED_IN_CORPUS), (
        f"{checked} compared, {len(DEFERRED_SCHEMA_OWNERS)} assigned, "
        f"{len(OWNER_NOT_OBSERVED_IN_CORPUS)} excused"
    )


def test_the_unobserved_set_really_is_unobserved() -> None:
    """The escape hatch above must not become a place to hide a disagreement."""
    observed = _owners_beside_schema_refs()
    wrongly_excused = sorted(entry for entry in OWNER_NOT_OBSERVED_IN_CORPUS if observed.get(entry))
    assert wrongly_excused == [], (
        f"these are excused from the agreement check but the corpus does state an owner: "
        f"{wrongly_excused}"
    )
    assert OWNER_NOT_OBSERVED_IN_CORPUS <= set(DEFERRED_SCHEMA_OWNERS)


@pytest.mark.parametrize("reference", sorted(set(_typed_ref_pins().values())))
def test_every_schema_ref_a_typed_ref_pins_is_accounted_for(reference: str) -> None:
    """DERIVED from ``typed-refs:1``, never restated.

    This case list used to be four hand-written URNs beside a helper that already computed
    them. Adding a fifth ``$def`` whose ``const`` named a document nobody owns left the whole
    suite green -- the hardcoded list simply did not include it, so the one rule that was
    supposed to catch exactly that never ran on it.
    """
    assert _resolves(reference) or reference in DEFERRED_SCHEMA_OWNERS, reference


def test_the_typed_refs_pins_are_the_four_the_freeze_list_names() -> None:
    """Derived from the schema, not restated: a fifth ref added without a decision fails."""
    assert _typed_ref_pins() == {
        "document_version_ref": "urn:datacompany:document-version:1",
        "evidence_location_ref": "urn:datacompany:evidence-location-version:1",
        "rights_decision_ref": "urn:datacompany:rights-decision-version:1",
        "artifact_ref": "urn:datacompany:artifact-version:1",
    }, _typed_ref_pins()


# ================================= falsifiability: each rule rejects, and each one accepts ===
#
# The suite had a non-vacuity control (the corpus is non-empty) and no FALSE-POSITIVE
# control. Those answer different questions. Non-vacuity says the gate measured something;
# a false-positive control says the gate is capable of finding nothing, which a rule that
# fires on every input would fail. tests/test_foundation_schemas.py states the convention in
# its module docstring and test_extension_vocabulary.py, test_file_hygiene.py and
# test_d3_relative_scope.py each carry one.


def _assert_findings(problems: Sequence[str], *expected: str) -> None:
    """Every expected fragment must be reported, and NOTHING ELSE may be.

    ``assert [p for p in problems if "X" in p]`` verifies only THAT something was rejected,
    not WHICH rule rejected it: flipping the test's own ``in`` to ``not in`` kept twenty-one
    of these green, because the planted defect also tripped other rules and the filter still
    returned a non-empty list. Requiring the finding set to be exactly the expected one makes
    each rejection case name the rule it is exercising, so a defect that starts being caught
    by a different rule --- or stops being caught by this one --- is visible.
    """
    for fragment in expected:
        assert [problem for problem in problems if fragment in problem], (fragment, list(problems))
    unexpected = [
        problem for problem in problems if not any(fragment in problem for fragment in expected)
    ]
    assert unexpected == [], unexpected


def _write(directory: Path, name: str, document: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _synthetic_clean_corpus(base: Path) -> tuple[Path, ...]:
    """A three-root tree in the committed shape, in which every pin is accounted for.

    ``release-ref:1`` genuinely resolves and ``analysis-run:1`` is genuinely allowlisted, so
    a clean answer here is the gate declining to fire on input it should accept.
    """
    fixtures, examples, schemas = base / "fixtures", base / "examples", base / "schemas"
    _write(
        fixtures / "nested",
        "resolving.json",
        {"instance": {"pin": {"schema_ref": "urn:datacompany:release-ref:1", "depth": 2}}},
    )
    _write(
        examples / "valid",
        "allowlisted.json",
        {"owner_context": "run-registry", "schema_ref": "urn:datacompany:analysis-run:1"},
    )
    _write(
        schemas / "domain",
        "pinning.schema.json",
        {
            "$defs": {
                "ref": {"properties": {"schema_ref": {"const": "urn:datacompany:model-run:1"}}}
            }
        },
    )
    return (fixtures, examples, schemas)


def test_the_gate_finds_nothing_in_a_synthetic_corpus_that_is_clean(tmp_path: Path) -> None:
    """FALSE-POSITIVE CONTROL. Everything below plants a defect and watches the gate fire;
    without this, a rule that returned every reference it saw would satisfy all of them."""
    roots = _synthetic_clean_corpus(tmp_path)
    references = _schema_refs(roots)
    # The control is only a control if it really carried all three roots and both spellings.
    assert set(references) == {
        "urn:datacompany:release-ref:1",
        "urn:datacompany:analysis-run:1",
        "urn:datacompany:model-run:1",
    }, sorted(references)
    assert _unaccounted(references, DEFERRED_SCHEMA_OWNERS) == {}

    disagreements, checked = _disagreements(
        _owners_beside_schema_refs(roots),
        {"urn:datacompany:analysis-run:1": "run-registry"},
        {},
        frozenset(),
    )
    assert disagreements == {}
    assert checked == 1


@pytest.mark.parametrize("root_name", ["fixtures", "examples", "schemas"])
def test_a_dangling_ref_planted_in_any_root_is_found(tmp_path: Path, root_name: str) -> None:
    """The widened scope, proven per root rather than assumed.

    ``examples/`` was outside the sweep entirely, and it holds the shipped
    model-conformance examples -- a document nobody owns could be named there and no gate
    anywhere would have said so.
    """
    roots = _synthetic_clean_corpus(tmp_path)
    dangling = "urn:datacompany:a-document-nobody-owns:1"
    _write(tmp_path / root_name / "planted", "dangling.json", {"schema_ref": dangling})

    unaccounted = _unaccounted(_schema_refs(roots), DEFERRED_SCHEMA_OWNERS)
    assert list(unaccounted) == [dangling], unaccounted
    # ...and it NAMES the offending file, which is the difference between a finding a
    # reviewer can act on and a count.
    assert [
        source.endswith(f"{root_name}/planted/dangling.json") for source in unaccounted[dangling]
    ] == [True], unaccounted


def test_a_dangling_ref_planted_as_a_released_const_is_found(tmp_path: Path) -> None:
    """The ``const`` spelling specifically, which is the stronger of the two statements."""
    roots = _synthetic_clean_corpus(tmp_path)
    dangling = "urn:datacompany:a-document-nobody-owns:1"
    _write(
        tmp_path / "schemas" / "domain",
        "planted.schema.json",
        {"$defs": {"ref": {"properties": {"schema_ref": {"const": dangling}}}}},
    )
    assert list(_unaccounted(_schema_refs(roots), DEFERRED_SCHEMA_OWNERS)) == [dangling]


def test_the_owner_agreement_rule_rejects_a_disagreement_and_accepts_a_match() -> None:
    """Both directions of the rule, on inputs it cannot have been tuned to."""
    owners = {"urn:datacompany:analysis-run:1": "run-registry"}
    matching, checked = _disagreements(
        {"urn:datacompany:analysis-run:1": {"run-registry"}}, owners, {}, frozenset()
    )
    assert matching == {} and checked == 1

    conflicting, checked = _disagreements(
        {"urn:datacompany:analysis-run:1": {"some-other-context"}}, owners, {}, frozenset()
    )
    assert conflicting == {
        "urn:datacompany:analysis-run:1": {
            "allowlist": "run-registry",
            "corpus": ["some-other-context"],
        }
    }
    assert checked == 1

    # ...and a SECOND observed context that the register records is tolerated, while an
    # unrecorded one is not. Without this the additional-contexts map could be deleted and
    # only the committed corpus would notice.
    tolerated, _ = _disagreements(
        {"urn:datacompany:analysis-run:1": {"run-registry", "second-context"}},
        owners,
        {"urn:datacompany:analysis-run:1": frozenset({"second-context"})},
        frozenset(),
    )
    assert tolerated == {}


def test_an_entry_excused_without_grounds_is_refused() -> None:
    """The exemption is a claim about the corpus, so it is checked against one."""
    with pytest.raises(AssertionError, match="the exemption is not the fact it claims to be"):
        _disagreements({}, {"urn:datacompany:analysis-run:1": "run-registry"}, {}, frozenset())


def test_the_counts_rule_accepts_a_consistent_triple_and_rejects_every_way_it_can_break() -> None:
    """FALSE-POSITIVE CONTROL FIRST, then each dimension separately.

    A rule that returned a finding for every input would satisfy the three rejection cases
    below and prove nothing, and one that only ever compared ``assignments`` would satisfy the
    first alone.
    """
    consistent = {
        "assignments": 18,
        "compared_against_the_corpus": 17,
        "excused_owner_not_observed_in_corpus": 1,
    }
    assert _count_drift(consistent, 18, 1, "the eighteen assignments below") == {}

    # The assignments count drifts from the measurement.
    assert "assignments" in _count_drift(consistent, 19, 1, "the eighteen assignments below")
    # An entry is quietly moved into the excused set: the DERIVED comparison count moves too,
    # which is the failure a single hand-typed 17 would not have caught.
    both = _count_drift(consistent, 18, 2, "the eighteen assignments below")
    assert {"excused_owner_not_observed_in_corpus", "compared_against_the_corpus"} <= set(both)
    # A stated triple that does not add up is refused even when it matches the measurement.
    contradictory = {
        "assignments": 18,
        "compared_against_the_corpus": 18,
        "excused_owner_not_observed_in_corpus": 1,
    }
    assert "identity" in _count_drift(contradictory, 18, 1, "the eighteen assignments below")


def _synthetic_obligation_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """A clean obligation, the register entry it quotes, and the allowlist that assigns it."""
    obligations = {
        "urn:datacompany:some-document:1": {
            "owner_context": "run-registry",
            "decision": "IMP-DEC-SYNTH-001",
            "urn_absence_quoted_from_citations": "the corpus names NO URN for it anywhere",
            "corpus_field_list": "99-synthetic-model.md:10-20",
            "gaps": [
                {
                    "id": "G1",
                    "members": ["alpha_member"],
                    "quoted_from_register": "(1) alpha_member is absent from the field list.",
                    "quoted_from_blocked_on": "what the alpha_member member is",
                },
                {
                    "id": "G2",
                    "members": ["beta_member"],
                    "quoted_from_register": "(2) beta_member is a bare name with no shape.",
                    "quoted_from_blocked_on": "the type of the beta_member member",
                },
            ],
        }
    }
    decisions = {
        "IMP-DEC-SYNTH-001": {
            "citations": [
                "99-synthetic-model.md:10-20 — the only field list the corpus gives.",
                "Measured: the corpus names NO URN for it anywhere.",
                "By contrast urn:datacompany:release-ref:1 appears at 99:2575 and 99:2672.",
            ],
            "rejected": (
                "Transcribing it. TWO MEASURED GAPS. "
                "(1) alpha_member is absent from the field list. "
                "(2) beta_member is a bare name with no shape."
            ),
            "blocked_on": (
                "An edit stating what the alpha_member member is and "
                "the type of the beta_member member."
            ),
        }
    }
    return obligations, decisions, {"urn:datacompany:some-document:1": "run-registry"}


def test_the_obligation_rule_finds_nothing_in_a_consistent_pair() -> None:
    """FALSE-POSITIVE CONTROL. Every case below plants a drift and watches the rule fire."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    assert _obligation_drift(obligations, decisions, owners) == []


def test_a_gap_the_register_does_not_state_is_found() -> None:
    """The direction that matters most: a machine-readable claim the decision never made."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    gaps = obligations["urn:datacompany:some-document:1"]["gaps"]
    gaps[1]["quoted_from_register"] = "(2) beta_member must be an identity_ref."
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "does not contain")


def test_a_gap_edited_out_of_the_register_is_found() -> None:
    """The other direction: the prose moves and the structured form keeps asserting it."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    decisions["IMP-DEC-SYNTH-001"]["rejected"] = (
        "Transcribing it. ONE MEASURED GAPS. (1) alpha_member is absent from the field list."
    )
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "does not contain", "does not say 'TWO MEASURED GAPS'")


def test_a_gap_list_that_disagrees_with_the_registers_own_count_is_found() -> None:
    """Deleting a gap from the JSON while every remaining quotation still resolves."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    del obligations["urn:datacompany:some-document:1"]["gaps"][1]
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "does not say 'ONE MEASURED GAPS'")


def test_gaps_renumbered_against_the_registers_order_are_found() -> None:
    """A quotation that still matches SOMEWHERE is not a quotation of the gap it is filed as."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    gaps = obligations["urn:datacompany:some-document:1"]["gaps"]
    gaps[0]["quoted_from_register"], gaps[1]["quoted_from_register"] = (
        gaps[1]["quoted_from_register"],
        gaps[0]["quoted_from_register"],
    )
    problems = _obligation_drift(obligations, decisions, owners)
    # The swap trips the ordering rule AND both member checks, because each gap now quotes the
    # other's subject. All three are named, so the case cannot pass on one of them alone.
    _assert_findings(
        problems,
        "only BEFORE the quotation",
        "states member 'alpha_member'",
        "states member 'beta_member'",
    )


def test_an_obligation_whose_owner_contradicts_the_allowlist_is_found() -> None:
    """The obligation and the assignment live in one file; they may not disagree."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["owner_context"] = "some-other-context"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "allowlist names")


def test_an_obligation_against_a_document_nobody_is_assigned_is_found() -> None:
    """An obligation with no assignment names nobody, which is the failure it exists to fix."""
    obligations, decisions, _ = _synthetic_obligation_inputs()
    problems = _obligation_drift(obligations, decisions, {})
    _assert_findings(problems, "not on the allowlist")


def test_a_supporting_field_absent_from_its_own_quotation_is_found() -> None:
    """No field beside a checked quotation may become unchecked prose."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["members"] = ["gamma_member"]
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "does not name")

    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["constraint"] = (
        "some-other:1#/$defs/x"
    )
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "does not mention", "does not resolve to a released schema")


def test_quotations_below_the_shared_floor_are_refused() -> None:
    """THE REDUCTION THIS GATE ALMOST SHIPPED WITHOUT.

    Replacing all four quotations with ``"(1)".."(4)"``, emptying every ``members`` and
    deleting every ``constraint`` left the real suite green: the strings were all genuinely
    present, all in order, and said nothing. Every property this file claims rested on how
    long the strings happened to be. The floor is the one the citation gate already uses.
    """
    for field in ("quoted_from_register", "quoted_from_blocked_on"):
        obligations, decisions, owners = _synthetic_obligation_inputs()
        gaps = obligations["urn:datacompany:some-document:1"]["gaps"]
        for index, gap in enumerate(gaps, start=1):
            gap[field] = f"({index})"
            decisions["IMP-DEC-SYNTH-001"]["rejected"] += f" ({index})"
            decisions["IMP-DEC-SYNTH-001"]["blocked_on"] += f" ({index})"
        problems = _obligation_drift(obligations, decisions, owners)
        assert [p for p in problems if f"{MIN_QUOTE}-character floor" in p], (field, problems)

    # ...including the EMPTY string on the FIRST gap, which ``str.find`` reports at offset 0
    # and every ordering check therefore accepted.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["quoted_from_blocked_on"] = ""
    problems = _obligation_drift(obligations, decisions, owners)
    assert [p for p in problems if f"{MIN_QUOTE}-character floor" in p], problems


def test_an_empty_members_list_or_constraint_is_refused() -> None:
    """An empty enumeration disables its own check and reads as a clean one."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["members"] = []
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "records no members")

    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["members"] = [""]
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "records an empty member")

    # ``"" in quotation`` is always True, so an empty constraint passed the containment check.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["constraint"] = ""
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "records an empty constraint")


def test_a_field_no_rule_checks_is_refused() -> None:
    """DERIVED, not hand-listed. Two fields were checked by name and the rest walked past."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["severity"] = "cosmetic"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "which no rule checks")

    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["severity"] = "cosmetic"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "which no rule checks")

    obligations, decisions, owners = _synthetic_obligation_inputs()
    del obligations["urn:datacompany:some-document:1"]["corpus_field_list"]
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "is missing")


def test_a_corpus_field_list_the_decision_does_not_cite_is_refused() -> None:
    """It is bound to ``citations`` because that list is what the corpus gate resolves."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["corpus_field_list"] = (
        "99-synthetic-model.md:1-2"
    )
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "opens with")

    # A range some citation merely MENTIONS in passing is not a citation OF that range. The
    # earlier rule was ``value in citation``, so any range named anywhere in the prose counted.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    decisions["IMP-DEC-SYNTH-001"]["citations"].append(
        "99-synthetic-model.md:40-41 - unrelated, but see also 99-synthetic-model.md:50-51."
    )
    obligations["urn:datacompany:some-document:1"]["corpus_field_list"] = (
        "99-synthetic-model.md:50-51"
    )
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "opens with")


def test_an_unsubstantiated_placeholder_claim_is_refused() -> None:
    """The evidence for an absence must assert one.

    "A 12-character substring of the citations" is satisfied by a fragment stating that a URN
    DOES exist, so the field whose sole job is to evidence "this URN names nothing" accepted
    evidence of the opposite. The ``urn_is_a_placeholder`` boolean that sat beside it is
    DELETED rather than repaired: it was derived from ``not _resolves(...)``, which measures
    "this repository does not release it" -- true of all eighteen entries -- and not "the
    corpus names no URN for it", which is what it claimed.
    """
    # A REAL fragment of the decision's own citations, above the floor, asserting that a URN
    # exists -- filed as the evidence that none does.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["urn_absence_quoted_from_citations"] = (
        "urn:datacompany:release-ref:1 appears at 99:2575"
    )
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "does not state that no URN exists")

    # ...and text quoted from nowhere at all is a different finding, not the same one.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["urn_absence_quoted_from_citations"] = (
        "the corpus names NO URN, invented wholesale"
    )
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "is not a quotation of")

    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["urn_absence_quoted_from_citations"] = "short"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "below the")

    # ...and the deleted boolean cannot come back as unchecked prose.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["urn_is_a_placeholder"] = True
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "which no rule checks")


def test_a_corpus_field_list_that_is_not_a_multiline_range_is_refused() -> None:
    """``"" in <str>`` is True, and a REAL citation of the wrong lines is worse than empty.

    The design was "bound to the decision's citations, which the corpus gate resolves". Under
    it, ``16:891`` -- cited by this very decision, and about the four ``decision`` values
    rather than the field list -- was accepted: exactly the substantively-wrong pointer the
    binding existed to prevent.
    """
    for value in ("", "1", ":"):
        obligations, decisions, owners = _synthetic_obligation_inputs()
        obligations["urn:datacompany:some-document:1"]["corpus_field_list"] = value
        problems = _obligation_drift(obligations, decisions, owners)
        _assert_findings(problems, "not a citation clearing the")

    # A SINGLE LINE that is genuinely cited AND genuinely about the field list, so only the
    # range rule can reject it. Without this the range rule was untested: the earlier probe
    # was rejected for not being cited at all, and disabling the range check stayed green.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    decisions["IMP-DEC-SYNTH-001"]["citations"].append(
        "99-synthetic-model.md:14 — the field list member alpha_member sits on this line."
    )
    obligations["urn:datacompany:some-document:1"]["corpus_field_list"] = "99-synthetic-model.md:14"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "is not a multi-line")

    # A multi-line range mentioned INSIDE another citation's prose rather than cited itself.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    decisions["IMP-DEC-SYNTH-001"]["citations"].append(
        "99-synthetic-model.md:30-31 — explicitly NOT the field list; see 99-model.md:60-61."
    )
    obligations["urn:datacompany:some-document:1"]["corpus_field_list"] = "99-model.md:60-61"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "opens with")


def test_an_identical_or_nested_quotation_is_refused() -> None:
    """The ``<=`` case, which a swap of two DISTINCT quotations cannot distinguish from ``<``.

    Two gaps quoting the SAME text, and a gap quoting a fragment NESTED inside the previous
    gap's quotation, both satisfy "each offset is greater than the last" -- the first because
    it is equal, the second because a nested fragment starts later. Only a scan that advances
    past the END of each match rejects them.
    """
    obligations, decisions, owners = _synthetic_obligation_inputs()
    gaps = obligations["urn:datacompany:some-document:1"]["gaps"]
    gaps[1]["quoted_from_register"] = gaps[0]["quoted_from_register"]
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "only BEFORE the quotation", "states member 'beta_member'")

    obligations, decisions, owners = _synthetic_obligation_inputs()
    gaps = obligations["urn:datacompany:some-document:1"]["gaps"]
    # A fragment sitting INSIDE gap 1's quotation, which starts later than gap 1 does.
    gaps[1]["quoted_from_register"] = "alpha_member is absent from"
    gaps[1]["members"] = ["alpha_member"]
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "only BEFORE the quotation")


def test_a_quotation_the_register_legitimately_repeats_is_not_a_false_positive() -> None:
    """The opposite direction of the same scan, so it is not tuned until vacuous.

    A bare ``find`` per gap binds to the FIRST occurrence, so a register that says the same
    clause twice made a correctly ordered pair report a spurious out-of-order failure. This
    is the accept half: the rule must find nothing here.
    """
    obligations, decisions, owners = _synthetic_obligation_inputs()
    decisions["IMP-DEC-SYNTH-001"]["rejected"] = (
        "(1) alpha_member is absent from the field list. "
        "Transcribing it. TWO MEASURED GAPS. "
        "(1) alpha_member is absent from the field list. "
        "(2) beta_member is a bare name with no shape."
    )
    assert _obligation_drift(obligations, decisions, owners) == []


def test_gap_ids_that_are_not_g1_to_gn_are_refused() -> None:
    """Turning this check off left the suite green, so it had no rejection case."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][1]["id"] = "G3"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "expected G1..G2")


def test_an_obligation_with_no_gaps_at_all_is_refused() -> None:
    """A deferral that states nothing owed is the failure this whole block exists to fix."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"] = []
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "records no gaps")


def test_a_constraint_that_does_not_resolve_is_refused() -> None:
    """Appearing in the quotation is satisfied by any prefix that is a token there."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    gap = obligations["urn:datacompany:some-document:1"]["gaps"][0]
    gap["quoted_from_register"] = (
        "(1) alpha_member is absent from the field list, against "
        "stable-identity:1#/$defs/resource_scope_conditional."
    )
    decisions["IMP-DEC-SYNTH-001"]["rejected"] = (
        "Transcribing it. TWO MEASURED GAPS. "
        + gap["quoted_from_register"]
        + " (2) beta_member is a bare name with no shape."
    )
    gap["constraint"] = "stable-identity:1#/$defs/resource_scope_conditional"
    assert _obligation_drift(obligations, decisions, owners) == []

    # THE TRUNCATION THAT RESOLVES, which is the one this rule exists for and the one the
    # first version of this test missed by choosing a truncation that does not.
    # ``resolve_pointer`` returns the document ROOT for a bare document URN, so
    # ``stable-identity:1`` resolves; and until ``#`` joined IDENTIFIER_CHARACTERS it was also
    # a whole token inside the full pointer. Both halves passed and the constraint was gone.
    assert _resolves("urn:datacompany:stable-identity:1"), (
        "the premise of this test: a bare document URN resolves, so 'it resolves' cannot "
        "distinguish a pointer from its own prefix"
    )
    gap["constraint"] = "stable-identity:1"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(
        problems,
        "names a document rather than the definition",
        "which its own quotation of IMP-DEC-SYNTH-001 does not mention",
    )

    # ...and a pointer that LOOKS like a definition but resolves to nothing is the other half.
    gap["constraint"] = "stable-identity:1#/$defs/resource_scope_condition"
    gap["quoted_from_register"] += " stable-identity:1#/$defs/resource_scope_condition"
    decisions["IMP-DEC-SYNTH-001"]["rejected"] = (
        "Transcribing it. TWO MEASURED GAPS. "
        + gap["quoted_from_register"]
        + " (2) beta_member is a bare name with no shape."
    )
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "does not resolve")


def test_a_gap_missing_a_required_field_cannot_render_the_entry_clean() -> None:
    """The hole a `continue` opened, guarded by a SECOND evaluation of the same expression.

    Disabling the missing-key finding left the skip in place, so the entry's quotation checks
    were abandoned and the whole obligation rendered clean: deleting any one of a gap's three
    required fields was a full-suite pass. There is no skip now, and every rule reads through
    ``.get``, so a missing field is a finding from more than one direction.
    """
    for field in ("quoted_from_register", "quoted_from_blocked_on", "members"):
        obligations, decisions, owners = _synthetic_obligation_inputs()
        del obligations["urn:datacompany:some-document:1"]["gaps"][1][field]
        problems = _obligation_drift(obligations, decisions, owners)
        # BOTH the key check and the rule that CONSUMES the field must fire, so the finding
        # cannot depend on the key check alone -- which is what made disabling one of them
        # insufficient. Deleting the register quotation also strips what the member check
        # reads, so that case names three findings rather than two.
        consumers = {
            "quoted_from_register": ("shorter than the", "does not name"),
            "quoted_from_blocked_on": ("shorter than the",),
            "members": ("records no members",),
        }[field]
        _assert_findings(problems, "is missing", *consumers)


def test_blocked_on_quotations_that_reproduce_none_of_the_sentence_are_refused() -> None:
    """``MIN_QUOTE`` bounds each quotation and says nothing about what they add up to.

    ``quoted_from_register`` is backstopped by ``members`` and ``constraint``;
    ``quoted_from_blocked_on`` was backstopped by nothing, so four disjoint, in-order,
    above-floor slices of the sentence satisfied every rule while carrying no meaning.
    Word alignment closes the arbitrary-slice half. The other half --- WHICH gap a clause
    belongs to --- is not a property of the clause and is pinned, not inferred.
    """
    obligations, decisions, owners = _synthetic_obligation_inputs()
    entry = obligations["urn:datacompany:some-document:1"]
    sentence = decisions["IMP-DEC-SYNTH-001"]["blocked_on"]
    # Twelve-character slices cut straight through words.
    entry["gaps"][0]["quoted_from_blocked_on"] = sentence[3:15]
    entry["gaps"][1]["quoted_from_blocked_on"] = sentence[15:27]
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "mid-word slice")

    # ...and a word-aligned slice that is about NOTHING this gap covers is NOT caught here,
    # deliberately. No property of a fragment says which gap it describes; that claim is an
    # EXACT PIN in test_the_deferred_obligations_agree_with_the_register. This test now owns
    # only the arbitrary-slice half, and says so rather than implying it owns attribution.


def test_every_floor_is_pinned_at_its_boundary_not_merely_above_zero() -> None:
    """``<`` versus ``<=`` on five separate floors, none of which was pinned at the edge.

    Every probe used a value far below the floor, so relaxing any of these comparisons stayed
    green: ``corpus_field_list``, ``urn_absence_quoted_from_citations`` and all three
    ``register_paraphrase`` fields. A floor tested only at 3 characters proves ``floor > 3``.
    """
    at, below = "x" * MIN_QUOTE, "x" * (MIN_QUOTE - 1)

    for value, expect_floor in ((below, True), (at, False)):
        obligations, decisions, owners = _synthetic_obligation_inputs()
        obligations["urn:datacompany:some-document:1"]["corpus_field_list"] = value
        problems = _obligation_drift(obligations, decisions, owners)
        hit = [p for p in problems if "not a citation clearing the" in p]
        assert bool(hit) is expect_floor, (value, problems)

        obligations, decisions, owners = _synthetic_obligation_inputs()
        obligations["urn:datacompany:some-document:1"]["urn_absence_quoted_from_citations"] = value
        problems = _obligation_drift(obligations, decisions, owners)
        hit = [p for p in problems if "below the" in p and "floor" in p]
        assert bool(hit) is expect_floor, (value, problems)

    # A baseline note that is entirely valid, so each probe moves exactly one field.
    phrase, location = "the phrase quoted here", "99-synthetic-model.md:20-30"
    wording = "a wholly different corpus wording"
    for key, message in (
        ("phrase", "is not a quotation of at least"),
        ("attributed_to", "is not a quotation of at least"),
        ("corpus_wording", "too short"),
    ):
        for value, expect_floor in ((below, True), (at, False)):
            gap = {
                "id": "G1",
                "quoted_from_register": f"(1) {phrase}, per {location}, and {at} too.",
                "register_paraphrase": {
                    "phrase": phrase,
                    "attributed_to": location,
                    "corpus_wording": wording,
                },
            }
            gap["register_paraphrase"][key] = value
            problems = _paraphrase_problems(gap, "x")
            # Filtered by FIELD as well as message: two of the three share a message, so a
            # filter on the message alone would report the other field's finding as this
            # field's and the probe would pass without moving anything.
            hit = [p for p in problems if message in p and f"register_paraphrase.{key}" in p]
            assert bool(hit) is expect_floor, (key, value, problems)


def test_a_single_line_range_is_not_a_multiline_range() -> None:
    """``last <= first`` versus ``last < first``: ``16:873-873`` is one line, not a range."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    decisions["IMP-DEC-SYNTH-001"]["citations"].append(
        "99-synthetic-model.md:14-14 — the field list, all of it on one line."
    )
    obligations["urn:datacompany:some-document:1"]["corpus_field_list"] = (
        "99-synthetic-model.md:14-14"
    )
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "is not a multi-line")


def test_a_clause_the_decision_grows_leaves_a_remainder_nobody_quoted() -> None:
    """The exhaustiveness rule, on synthetic inputs it must accept and inputs it must reject.

    A decision that GROWS a clause is the one drift the gap-to-clause pins cannot see: every
    pinned clause still matches, in order, at its pinned length. What changes is the text
    BETWEEN them. The rule used to be ``len(part) > 40`` with no probe at either side, so a
    23-character insertion passed while the largest legitimate leftover was 28.
    """
    sentence = (
        "An edit stating the alpha rule, the beta rule, and how gamma reports itself. "
        "A URN would follow."
    )
    clauses = ["the alpha rule", "the beta rule", "how gamma reports itself"]
    accepted = ["An edit stating", "", "and", "A URN would follow"]
    assert _unquoted_remainder(sentence, clauses) == accepted

    # A fourth obligation added to the sentence and to no gap: the remainder grows and the
    # pin moves, at ANY length. Twelve characters would have cleared the old floor.
    for insertion in ("its retention rule, ", "x, "):
        grown = sentence.replace("the beta rule, ", f"the beta rule, {insertion}")
        assert _unquoted_remainder(grown, clauses) != accepted, insertion

    # ...and a clause DELETED from the decision shows up here too, not only in the pins.
    shrunk = sentence.replace("the beta rule, ", "")
    assert _unquoted_remainder(shrunk, clauses) != accepted

    # EACH GAP CONSUMES ONE OCCURRENCE. Removing every occurrence instead of the first makes
    # a clause the decision states TWICE look as though one gap covered both, so the second
    # -- which no gap quotes -- vanishes from the remainder instead of showing up in it.
    repeated = (
        "An edit stating the alpha rule, the beta rule, the alpha rule again, "
        "and how gamma reports itself. A URN would follow."
    )
    left = _unquoted_remainder(repeated, clauses)
    assert any("the alpha rule again" in part for part in left), left


def test_a_fragment_that_begins_mid_word_is_not_a_quotation() -> None:
    """``_splits_a_word``'s ``opens`` half, which had no rejection case.

    Setting ``opens = False`` left all 1267 tests passing, while ``closes = False`` reddened
    two: one clause of the guard was doing no work that anything could see. The discriminating
    input starts mid-word and ends cleanly on a boundary, so only ``opens`` rejects it.
    """
    sentence = "An edit stating what the rest says"
    fragment = "n edit stating what the"
    assert len(fragment) >= MIN_QUOTE
    start = sentence.index(fragment)
    assert start == 1 and sentence[start - 1] == "A", sentence
    assert sentence[start + len(fragment)] == " ", "the END of this fragment is aligned"

    assert _splits_a_word(sentence, start, start + len(fragment)) is True
    assert _aligned_occurrences(sentence, fragment) == []

    # The mirror case, so the guard is shown to reject one side and accept the other rather
    # than simply firing: same fragment with its leading character restored.
    whole = "An edit stating what the"
    assert _splits_a_word(sentence, 0, len(whole)) is False
    assert _aligned_occurrences(sentence, whole) == [0]

    # Driven through the real rule, not only the helper.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    entry = obligations["urn:datacompany:some-document:1"]
    decisions["IMP-DEC-SYNTH-001"]["blocked_on"] = sentence
    entry["gaps"][0]["quoted_from_blocked_on"] = fragment
    problems = _obligation_drift(obligations, decisions, owners)
    assert [p for p in problems if "mid-word slice" in p], problems


def test_an_obligation_citing_a_decision_the_register_does_not_define_is_refused() -> None:
    """``if decision is None`` never fired on real data, so nothing showed it could."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["decision"] = "IMP-DEC-DOES-NOT-EXIST"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "which the register does not define")


def test_the_paraphrase_note_must_record_a_real_difference() -> None:
    """The STRUCTURAL half of the note. The corpus half is the test below this one."""
    obligations, decisions, owners = _synthetic_obligation_inputs()
    gap = obligations["urn:datacompany:some-document:1"]["gaps"][0]
    gap["quoted_from_register"] = (
        "(1) alpha_member is absent from the field list, per 99-synthetic-model.md:10-20."
    )
    decisions["IMP-DEC-SYNTH-001"]["rejected"] = (
        "Transcribing it. TWO MEASURED GAPS. "
        + gap["quoted_from_register"]
        + " (2) beta_member is a bare name with no shape."
    )
    gap["register_paraphrase"] = {
        "phrase": "is absent from the field list",
        "attributed_to": "99-synthetic-model.md:10-20",
        "corpus_wording": "alpha_member is merely undocumented here",
    }
    assert _obligation_drift(obligations, decisions, owners) == []

    # A location nothing could resolve.
    gap["register_paraphrase"]["attributed_to"] = "alpha_member is absent"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "is not a <file>.md")
    gap["register_paraphrase"]["attributed_to"] = "99-synthetic-model.md:10-20"

    # A note whose "corpus wording" is the register's own words records no difference.
    gap["register_paraphrase"]["corpus_wording"] = "is absent from the field list"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "records no difference")

    # Each of the three fields, individually, below its floor -- three separate guards, none
    # of which had its own rejection case because the committed note satisfies all of them.
    for key, message in (
        ("phrase", "is not a quotation of at least"),
        ("attributed_to", "is not a quotation of at least"),
        ("corpus_wording", "too short"),
    ):
        obligations, decisions, owners = _synthetic_obligation_inputs()
        broken = obligations["urn:datacompany:some-document:1"]["gaps"][0]
        broken["quoted_from_register"] = (
            "(1) alpha_member is absent from the field list, per 99-synthetic-model.md:10-20."
        )
        decisions["IMP-DEC-SYNTH-001"]["rejected"] = (
            "Transcribing it. TWO MEASURED GAPS. "
            + broken["quoted_from_register"]
            + " (2) beta_member is a bare name with no shape."
        )
        broken["register_paraphrase"] = {
            "phrase": "is absent from the field list",
            "attributed_to": "99-synthetic-model.md:10-20",
            "corpus_wording": "alpha_member is merely undocumented here",
        }
        broken["register_paraphrase"][key] = "tiny"
        problems = _obligation_drift(obligations, decisions, owners)
        assert [p for p in problems if message in p], (key, problems)

    # A WRONG KEY SET is a different finding from a field below its floor, so it is asserted
    # against a freshly built input: the loop above rebound ``obligations``, which would leave
    # these last two cases mutating an object no longer under test -- a silent pass.
    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["register_paraphrase"] = {
        "phrase": "is absent from the field list"
    }
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "must have keys")

    obligations, decisions, owners = _synthetic_obligation_inputs()
    obligations["urn:datacompany:some-document:1"]["gaps"][0]["register_paraphrase"] = {
        "phrase": "x",
        "attributed_to": "y",
        "corpus_wording": "z",
        "extra": "unchecked",
    }
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "must have keys")


def _synthetic_corpus_note(base: Path) -> tuple[Path, dict[str, Any]]:
    """A one-file corpus and a gap whose paraphrase note is accurate about it."""
    (base / "99-synthetic-model.md").write_text(
        "line one\nNo schema may replace it with a nullable tenant ID,\nline three\n",
        encoding="utf-8",
    )
    gap = {
        "id": "G1",
        "quoted_from_register": (
            "(1) the invariant 99-synthetic-model.md:2-2 says no schema may weaken."
        ),
        "register_paraphrase": {
            "phrase": "says no schema may weaken",
            "attributed_to": "99-synthetic-model.md:2-2",
            "corpus_wording": "No schema may replace it with a nullable tenant ID",
        },
    }
    return base, gap


def test_the_corpus_paraphrase_rule_rejects_a_fabricated_note(tmp_path: Path) -> None:
    """Both halves of the corpus claim, on a synthetic corpus, in both directions.

    ``test_the_paraphrase_note_matches_the_real_corpus`` asserts the committed note is
    accurate, which cannot fail when a check is DELETED -- a passing assertion stays passing.
    Disabling either half of the rule survived the whole suite until this existed.
    """
    corpus, gap = _synthetic_corpus_note(tmp_path)
    assert _corpus_paraphrase_problems(gap, corpus, "x") == []

    # The corpus does not say what the note claims it says.
    fabricated = json.loads(json.dumps(gap))
    fabricated["register_paraphrase"]["corpus_wording"] = "A sentence nobody ever wrote here"
    problems = _corpus_paraphrase_problems(fabricated, corpus, "x")
    _assert_findings(problems, "so the note is fabricated")

    # The corpus DOES use the register's wording, so there is no paraphrase to record.
    no_difference = json.loads(json.dumps(gap))
    no_difference["register_paraphrase"]["phrase"] = "No schema may replace it"
    problems = _corpus_paraphrase_problems(no_difference, corpus, "x")
    _assert_findings(problems, "there is no paraphrase to record")

    # A location that does not resolve at all is named, not silently skipped.
    missing_file = json.loads(json.dumps(gap))
    missing_file["register_paraphrase"]["attributed_to"] = "98-absent.md:2-2"
    assert [
        p for p in _corpus_paraphrase_problems(missing_file, corpus, "x") if "does not exist" in p
    ]

    past_eof = json.loads(json.dumps(gap))
    past_eof["register_paraphrase"]["attributed_to"] = "99-synthetic-model.md:900-901"
    assert [p for p in _corpus_paraphrase_problems(past_eof, corpus, "x") if "past EOF" in p]


def test_the_count_prose_is_asserted_and_not_merely_written() -> None:
    """``config/deferred-schema-owners.json`` said "eighteen assignments" one field above the
    fix for unasserted counts, and flipping it to "seventeen" left the suite green."""
    consistent = {
        "assignments": 18,
        "compared_against_the_corpus": 17,
        "excused_owner_not_observed_in_corpus": 1,
    }
    assert _count_drift(consistent, 18, 1, "the eighteen assignments below") == {}
    # The word for a DIFFERENT count.
    drift = _count_drift(consistent, 18, 1, "the seventeen assignments below")
    assert "prose_omits_the_count" in drift and "prose_states_another_count" in drift
    # A sentence that says both is not a corrected sentence.
    drift = _count_drift(consistent, 18, 1, "the eighteen (formerly seventeen) assignments")
    assert "prose_states_another_count" in drift
    # WHOLE WORDS: "none of these obligations" must not read as the number one.
    assert _count_drift(consistent, 18, 1, "none of these; the eighteen assignments below") == {}

    # AN EMPTY VALUE MUST NOT DISABLE ITS OWN CHECK. This was ``if prose:`` with a ``""``
    # default, so all three of these rendered the register clean.
    for empty in ("", None, "   "):
        assert "prose_is_empty" in _count_drift(consistent, 18, 1, empty), empty


def test_a_member_that_is_only_a_substring_of_a_named_member_is_found() -> None:
    """The mutation that survived the first version of this rule.

    ``tenant_id`` is a substring of ``resource_tenant_id``, so a plain ``in`` accepted a
    structured entry claiming the gap is about a member the quotation never names --- and
    ``resource_scope``/``resource_tenant_id`` is precisely the pair G1 is about, where which
    of the two is present is the whole finding.
    """
    obligations, decisions, owners = _synthetic_obligation_inputs()
    gaps = obligations["urn:datacompany:some-document:1"]["gaps"]
    gaps[0]["quoted_from_register"] = "(1) resource_alpha_member is absent from the field list."
    rejected = decisions["IMP-DEC-SYNTH-001"]["rejected"]
    decisions["IMP-DEC-SYNTH-001"]["rejected"] = rejected.replace(
        "(1) alpha_member is absent from the field list.",
        "(1) resource_alpha_member is absent from the field list.",
    )
    # The member is spelled without the prefix the quotation actually uses.
    assert gaps[0]["members"] == ["alpha_member"]
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "does not name")


def test_the_token_boundary_covers_more_than_the_underscore_case() -> None:
    """The boundary class, exercised directly in both directions.

    ``[0-9A-Za-z_]`` treated ``-``, ``.``, ``/``, ``:`` and ``$`` as boundaries, so
    ``stable-identity`` matched inside ``stable-identity:1#/$defs/...`` and ``defs`` matched
    inside ``#/$defs/``. The accept cases are here too, because a boundary rule that never
    matches is indistinguishable from one that is merely strict.
    """
    pointer = "stable-identity:1#/$defs/resource_scope_conditional"
    # ``stable-identity:1`` is the one that needs ``#`` in the class specifically: every other
    # prefix here is already stopped by ``:``, ``/`` or ``$``. It is also the prefix that
    # RESOLVES -- ``resolve_pointer`` returns the document root for a bare document URN -- so
    # without ``#`` it passed both the token check and the resolution check.
    # ``stable`` is the probe that needs ``-`` in the class specifically; ``identity`` needs
    # it on the other side. Without them each is a whole token inside the compound name.
    for token in (
        "stable-identity",
        "stable-identity:1",
        "defs",
        "resource_scope",
        "identity",
        "stable",
        "scope",
    ):
        assert not _names_whole_token(pointer, token), token
    assert _names_whole_token(pointer, pointer)
    assert _names_whole_token(f"composes {pointer}, which REQUIRES", pointer)
    # A constraint that ends a sentence still matches; a dotted path still does not split.
    assert _names_whole_token(f"against {pointer}.", pointer)
    assert not _names_whole_token("resource_tenant_id is absent", "tenant_id")
    assert not _names_whole_token("foo.bar is a path", "foo")
    assert not _names_whole_token("foo.bar is a path", "bar")
    assert _names_whole_token("the decision member, plus", "decision")

    # The APOSTROPHE is a word character for alignment purposes, and dropping it from
    # WORD_CHARACTERS survived every other test: the slice "the receipt'" ends on ``'``, which
    # without it reads as a clean boundary, and that is precisely the reduction the alignment
    # rule exists to reject.
    sentence = "An DataCompany edit stating the receipt's tenant conditional, and more."
    assert _aligned_occurrences(sentence, "the receipt's tenant") == [sentence.index("the recei")]
    assert _aligned_occurrences(sentence, "the receipt'") == []
    assert _aligned_occurrences(sentence, "s tenant con") == []

    # Degenerate inputs, which used to raise rather than answer.
    assert _aligned_occurrences(sentence, "") == []
    assert _aligned_occurrences("", "") == []
    assert _aligned_occurrences("", "x") == []
    assert _splits_a_word("", 0, 0) is False
    assert _splits_a_word("abc", 1, 1) is False


def test_a_constraint_pointing_at_a_document_fragment_that_is_not_a_defs_pointer_is_refused() -> (
    None
):
    """``DEFS_POINTER`` must be ``#/$defs/`` and not merely ``#``.

    Weakening the constant to ``"#"`` survived, because the only probe was
    ``stable-identity:1`` -- which contains no ``#`` at all, so both the correct constant and
    the weakened one rejected it. The discriminating input is a fragment that HAS a ``#`` but
    does not point at a definition, and which still resolves.
    """
    assert _resolves("urn:datacompany:stable-identity:1#"), (
        "premise: a bare fragment still resolves, so resolution cannot carry this alone"
    )
    obligations, decisions, owners = _synthetic_obligation_inputs()
    gap = obligations["urn:datacompany:some-document:1"]["gaps"][0]
    gap["quoted_from_register"] = (
        "(1) alpha_member is absent from the field list, against stable-identity:1#."
    )
    decisions["IMP-DEC-SYNTH-001"]["rejected"] = (
        "Transcribing it. TWO MEASURED GAPS. "
        + gap["quoted_from_register"]
        + " (2) beta_member is a bare name with no shape."
    )
    gap["constraint"] = "stable-identity:1#"
    problems = _obligation_drift(obligations, decisions, owners)
    _assert_findings(problems, "names a document rather than the definition")

    # ...and the two ways the constant can be WEAKENED rather than deleted. ``"#/"`` and
    # ``"$defs"`` are each satisfied by a pointer that names no definition, so a probe has to
    # carry that exact shape to tell them from ``"#/$defs/"``. Driven through the real rule,
    # both are rejected only while the constant is the full pointer.
    assert DEFS_POINTER == "#/$defs/"
    for weakened in ("stable-identity:1#/properties", "stable-identity:1#$defs"):
        obligations, decisions, owners = _synthetic_obligation_inputs()
        gap = obligations["urn:datacompany:some-document:1"]["gaps"][0]
        gap["quoted_from_register"] = (
            f"(1) alpha_member is absent from the field list, against {weakened}."
        )
        decisions["IMP-DEC-SYNTH-001"]["rejected"] = (
            "Transcribing it. TWO MEASURED GAPS. "
            + gap["quoted_from_register"]
            + " (2) beta_member is a bare name with no shape."
        )
        gap["constraint"] = weakened
        problems = _obligation_drift(obligations, decisions, owners)
        _assert_findings(problems, "names a document rather than the definition")


# ================================================ the governance data really is in config ===


def test_the_ownership_register_is_config_rather_than_test_source() -> None:
    """The eighteen assignments are the only concrete ownership statements this repository
    makes -- ``OWNERS.yaml`` and ``.github/CODEOWNERS`` assign nobody, which
    ``test_owners_yaml_really_assigns_nothing_else`` measures -- and they used to be readable
    only by opening a test module.

    The file is asserted to be the one this suite reads, not merely to exist, so moving the
    data back into Python cannot leave a decorative JSON file behind.
    """
    assert OWNERSHIP.is_file(), OWNERSHIP
    document = _governance()
    assert document["decision"] == "IMP-DEC-FND002-020"
    assert document["deferred_schema_owners"] == DEFERRED_SCHEMA_OWNERS
    # 18 -> 17 on 2026-09-04: `urn:datacompany:approval-attestation:1` was RELEASED,
    # so its deferral was discharged. A urn cannot be both deferred and released
    # — `test_...` two screens up fails if it is — and this count is what makes
    # the discharge deliberate rather than a quiet deletion.
    assert len(DEFERRED_SCHEMA_OWNERS) == 17, sorted(DEFERRED_SCHEMA_OWNERS)
    # Every owner is a legal bounded_context token, so an entry can be acted on rather than
    # merely read: the released pattern is the one an owner_context has to satisfy.
    context = canonical_schemas()["urn:datacompany:stable-identity:1"]["$defs"]["bounded_context"]
    for owner in DEFERRED_SCHEMA_OWNERS.values():
        assert isinstance(owner, str) and owner
        assert len(owner) <= context["maxLength"]

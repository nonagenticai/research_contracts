"""The pre-ADR regulatory denylist, its anti-erosion guard, and its normalized form.

The denylist is the only thing standing between a generic-looking schema change
and a regulatory activation that has no accepted ADR. Silently deleting entries
from the JSON file must therefore be a CI failure, not a quiet policy change:
:data:`REQUIRED_FORBIDDEN_TOKENS` pins the set in code so weakening the policy
requires an explicit, reviewable two-file edit.

:func:`fold_confusables` lives here, next to :func:`normalize_token`, and not in
``regulatory`` where it was written. It was reachable from only ONE of the two
matchers, and the other one was the guarded-activation-discriminator gate:
``forbidden_match`` folded, ``_discriminator_errors`` called the raw
:func:`normalize_token`, and ``normalize_token`` DELETES every non-ASCII
character rather than folding it. ``work_type`` spelled with a fullwidth ``w`` or
a Cyrillic ``o`` therefore normalized to something that matched no guarded name
at all and passed in silence — the exact substitution the module that owned the
folding table already claimed to close. There is now no unfolded normalizer left
to call by accident: every consumer of the denylist's normalized form gets the
ASCII skeleton, because computing it is what :func:`normalize_token` means.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ContractError

#: Pinned pre-ADR forbidden canonical tokens. Do not shrink without the accepted
#: ADR-DATACOMPANY-REGULATORY-MODEL decision; the guard below fails CI if you do.
REQUIRED_FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {
        "regulatory_instrument",
        "regulatory_provision",
        "regulatory_effect",
        "legal_event",
        "legal_status",
        "regulatory_applicability",
        "regulatory_change",
        "normative_citation",
        "consolidation_snapshot",
        "recommendation_regulatory_link",
    }
)

#: Pinned guarded activation discriminators.
REQUIRED_DISCRIMINATORS: frozenset[str] = frozenset({"work_type"})


#: Non-ASCII code points that render as an ASCII letter, keyed by the letter they
#: impersonate. Everything reachable by Unicode compatibility decomposition
#: (fullwidth, mathematical alphanumerics, ligatures) and by stripping combining
#: marks (accented Latin) is handled generically in :func:`fold_confusables`;
#: this table covers the scripts decomposition cannot reach -- Cyrillic, Greek
#: and the stroke/dotless Latin letters -- because those are what an attacker
#: reaches for. Written as code points, not literals, so the table itself does
#: not trip the ambiguous-character lint it exists to defeat.
#:
#: ``w`` had NO entry at all until the discriminator gate was fixed, which mattered
#: more than the other gaps: ``work_type`` is the one pinned entry of
#: :data:`REQUIRED_DISCRIMINATORS`, so the single token this table most has to protect
#: began with the one letter it could not fold. ``f``, ``q`` and ``r`` are still absent,
#: deliberately: no Cyrillic or Greek letter is a convincing homoglyph for them, and
#: guessing entries into a table that decides what CI rejects buys false positives, not
#: coverage.
CONFUSABLE_CODE_POINTS: dict[str, tuple[int, ...]] = {
    "a": (0x0430, 0x0410, 0x03B1, 0x0391, 0x0251),
    "b": (0x0412, 0x0392, 0x0184),
    "c": (0x0441, 0x0421, 0x03F2, 0x216D),
    "d": (0x0501, 0x0111),
    "e": (0x0435, 0x0415, 0x0395, 0x212E),
    "g": (0x0261, 0x0581),
    "h": (0x04BB, 0x043D, 0x041D, 0x0397, 0x04A3),
    "i": (0x0456, 0x0406, 0x0399, 0x03B9, 0x0131, 0x2170),
    "j": (0x0458, 0x0408, 0x03F3, 0x0237),
    "k": (0x043A, 0x041A, 0x03BA, 0x039A),
    "l": (0x04CF, 0x0142, 0x0141, 0x217C),
    "m": (0x043C, 0x041C, 0x039C, 0x217F),
    "n": (0x039D, 0x0578),
    "o": (0x043E, 0x041E, 0x03BF, 0x039F, 0x00F8, 0x00D8, 0x0585),
    "p": (0x0440, 0x0420, 0x03C1, 0x03A1),
    "s": (0x0455, 0x0405, 0x01BD),
    "t": (0x0442, 0x0422, 0x03C4, 0x03A4),
    "u": (0x03C5, 0x057D),
    "v": (0x0475, 0x03BD, 0x2174),
    "w": (0x051D, 0x051C, 0x0461, 0x0460, 0x03C9),
    "x": (0x0445, 0x0425, 0x03C7, 0x03A7, 0x2179),
    "y": (0x0443, 0x0423, 0x03B3, 0x03A5),
    "z": (0x0396, 0x01B6),
}

#: Flattened confusable -> ASCII letter map.
CONFUSABLE_LETTERS: dict[str, str] = {
    chr(code_point): letter
    for letter, code_points in CONFUSABLE_CODE_POINTS.items()
    for code_point in code_points
}


def fold_confusables(value: str) -> str:
    """Fold ``value`` onto its ASCII skeleton.

    Compatibility-decompose (fullwidth and mathematical alphanumerics,
    ligatures), drop combining marks (accented Latin), then map the
    script-confusable letters that decomposition cannot reach. Characters with
    no ASCII skeleton are left alone; the caller treats them as separators.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return "".join(CONFUSABLE_LETTERS.get(character, character) for character in without_marks)


def normalize_token(value: str) -> str:
    """Squash a value to the denylist's declared 'lowercase ASCII alphanumeric' form.

    Confusable-folded FIRST. Without the fold this function does not merely fail to
    recognise a homoglyph, it *deletes* it: ``re.sub(r"[^a-z0-9]", "", ...)`` drops every
    non-ASCII character, so ``work_type`` with a Cyrillic ``o`` squashed to ``wrktype`` and
    matched no guarded discriminator. Folding turns the same input into ``worktype``.
    """
    return re.sub(r"[^a-z0-9]", "", fold_confusables(value).lower())


@dataclass(frozen=True)
class Denylist:
    """A loaded, integrity-checked denylist."""

    source: Path
    forbidden_tokens: tuple[str, ...]
    guarded_discriminators: tuple[str, ...]

    #: ``ordinary_source_document_types_allowed`` from the JSON file.
    #:
    #: **Declared, shape-checked, and enforced NOWHERE.** No gate consults it:
    #: ``regulatory.py`` reads :attr:`normalized_forbidden` and
    #: :attr:`normalized_discriminators` and nothing else, so an ordinary source
    #: document type outside this list is rejected by no check anywhere in the
    #: repository. Read this field as a record of intent, never as a constraint.
    #:
    #: It is deliberately kept rather than deleted. Removing it would be a
    #: substantive narrowing of a pre-ADR policy statement, and
    #: ADR-DATACOMPANY-REGULATORY-MODEL is ``not_accepted`` with IMP-DEC-001
    #: unassigned, so there is nobody to take that decision. The load-time
    #: integrity check below is therefore the only guarantee attached to it: the
    #: key must exist and be a non-empty array of unique non-empty strings.
    #: ``test_the_allowed_source_document_types_policy_is_enforced_nowhere`` pins
    #: the unenforced status, so if the field gains a reader this note goes red
    #: rather than silently becoming false.
    allowed_source_document_types: tuple[str, ...]

    @property
    def normalized_forbidden(self) -> dict[str, str]:
        """Normalized token -> original token, for reporting the declared spelling."""
        return {normalize_token(token): token for token in self.forbidden_tokens}

    @property
    def normalized_discriminators(self) -> frozenset[str]:
        """Normalized discriminator names.

        Everything else in the gate normalizes; comparing discriminators as raw
        strings let ``workType`` and ``WORK_TYPE`` walk straight past the closed
        const/enum requirement.
        """
        return frozenset(normalize_token(name) for name in self.guarded_discriminators)


def _string_list(document: Any, key: str, source: Path) -> tuple[str, ...]:
    values = document.get(key)
    if not isinstance(values, list) or not values:
        raise ContractError(f"{source}: {key!r} must be a non-empty array")
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ContractError(f"{source}: {key!r} must contain only non-empty strings")
    if len(set(values)) != len(values):
        raise ContractError(f"{source}: {key!r} contains duplicate entries")
    return tuple(values)


def load_denylist(source: Path) -> Denylist:
    """Load and integrity-check the denylist."""
    if not source.is_file():
        raise ContractError(f"{source}: required pre-ADR regulatory denylist is missing")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"{source}: {exc}") from exc
    if not isinstance(document, dict):
        raise ContractError(f"{source}: denylist must be a JSON object")

    denylist = Denylist(
        source=source,
        forbidden_tokens=_string_list(document, "forbidden_canonical_tokens", source),
        guarded_discriminators=_string_list(document, "guarded_activation_discriminators", source),
        allowed_source_document_types=_string_list(
            document, "ordinary_source_document_types_allowed", source
        ),
    )
    verify_denylist_integrity(denylist)
    return denylist


def verify_denylist_integrity(denylist: Denylist) -> None:
    """Fail if the shipped denylist has been eroded below the pinned policy."""
    declared = set(denylist.forbidden_tokens)
    missing = sorted(REQUIRED_FORBIDDEN_TOKENS - declared)
    if missing:
        raise ContractError(
            f"{denylist.source}: forbidden_canonical_tokens has been eroded; "
            f"missing pinned pre-ADR tokens: {missing}"
        )
    missing_discriminators = sorted(REQUIRED_DISCRIMINATORS - set(denylist.guarded_discriminators))
    if missing_discriminators:
        raise ContractError(
            f"{denylist.source}: guarded_activation_discriminators has been eroded; "
            f"missing: {missing_discriminators}"
        )
    normalized = {normalize_token(token) for token in denylist.forbidden_tokens}
    if "" in normalized:
        raise ContractError(f"{denylist.source}: a forbidden token normalizes to the empty string")
    if len(normalized) != len(denylist.forbidden_tokens):
        raise ContractError(f"{denylist.source}: two forbidden tokens collide after normalization")

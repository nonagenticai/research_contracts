"""The two engines resolve exactly the RFC 6901 array indices, and nothing else.

``structural._at`` used to resolve an array element with ``node[int(token)]``. ``int`` is a
much wider grammar than RFC 6901 and a wider one than any other language's: it accepts a
sign, surrounding whitespace, PEP 515 underscores and every Unicode decimal digit. The
TypeScript port guarded on ``/^-?\\d+$/u``. So ``"+0"``, ``" 0"``, ``"0_0"`` and the
Arabic-Indic zero U+0660 all resolved to element 0 in Python and to nothing in the port, and
``{"rule": "equal", "left": "/a/+0", "right": "/b"}`` against ``{"a": [5], "b": 5}`` PASSED
in Python while FAILING in TypeScript -- one engine reporting a released rule as holding
where the other reported it violated, on the same instance. The port also wrapped negative
indices around, which Python's ``int`` route reached through ``IndexError`` rather than
through a grammar.

Neither engine's previous behaviour was chosen: both were accidents of the host language.
The grammar both now implement is RFC 6901 section 4 itself --
``array-index = %x30 / ( %x31-39 *(%x30-39) )`` -- which is narrower than either. It also
rejects leading zeros, which neither engine rejected before and which the RFC does not admit.

The parity is asserted from both sides. ``packages/typescript/test/engineDefects.test.ts``
reads the Python pattern AND this module's token table; this reads the port's pattern.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import check_cross_field_rules
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical import structural as structural_module
from research_contracts.canonical.registry import canonical_schemas

ROOT = Path(__file__).resolve().parents[1]
TS_STRUCTURAL = ROOT / "packages" / "typescript" / "src" / "structural.ts"

PROBE_ID = "urn:datacompany:rfc6901-index-probe:1"

#: ``token -> is it an RFC 6901 array-index?``. The four ``False`` rows in the first block
#: are the divergence: Python resolved every one of them to element 0.
#:
#: Read by ``packages/typescript/test/engineDefects.test.ts``, which parses this literal and
#: asserts the same table against the port, so the two cannot drift.
INDEX_TOKENS: dict[str, bool] = {
    # The divergence class: accepted by Python's `int`, rejected by the port's regex.
    "+0": False,
    " 0": False,
    "0_0": False,
    "\u0660": False,  # ARABIC-INDIC DIGIT ZERO
    # Accepted by the port's old regex, rejected by RFC 6901.
    "-0": False,
    "-1": False,
    "00": False,
    "01": False,
    # Neither engine ever accepted these; kept so the grammar is pinned, not just the delta.
    "": False,
    "0.0": False,
    "1e0": False,
    "-": False,  # the RFC 6901 "next element" token, which addresses no existing member
    "a": False,
    # The grammar itself.
    "0": True,
    "1": True,
    "10": True,
    "9007199254740993": True,  # beyond exact double range: still a well-formed index
}


@pytest.fixture
def evaluate(monkeypatch: pytest.MonkeyPatch):
    """Evaluate ``equal /a/<token> /b`` against an instance through the real collector."""

    def _evaluate(candidate: str, instance: Any) -> list[str]:
        probe = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": PROBE_ID,
            "x-datacompany-cross-field": [
                {"rule": "equal", "scope": "relative", "left": f"/a/{candidate}", "right": "/b"}
            ],
        }
        schemas = {**canonical_schemas(), PROBE_ID: probe}
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
        structural_module._collect.cache_clear()
        return check_cross_field_rules(instance, PROBE_ID)

    yield _evaluate
    structural_module._collect.cache_clear()


def test_the_probe_really_evaluates_its_rule(evaluate) -> None:
    """Non-vacuity for the sweep below: a collector that dropped the probe's rule would
    report ``[]`` for every token, which is the "it resolved and the rule held" answer."""
    assert evaluate("0", {"a": [5], "b": 5}) == []
    assert evaluate("0", {"a": [4], "b": 5}) == [
        "equal: /a/0 and /b must both be present and equal"
    ]


def test_the_token_table_really_holds_both_answers() -> None:
    """Non-vacuity: a table that was all-``False`` would make the sweep below a tautology
    over a resolver that resolved nothing at all."""
    assert sum(INDEX_TOKENS.values()) >= 4
    assert sum(not accepted for accepted in INDEX_TOKENS.values()) >= 10


@pytest.mark.parametrize("candidate", sorted(INDEX_TOKENS))
def test_only_an_rfc_6901_array_index_resolves_an_element(candidate: str) -> None:
    """``_at`` is the shared resolver every operand goes through."""
    resolved = structural_module._at({"a": [5, 6]}, f"/a/{candidate}")
    if INDEX_TOKENS[candidate] and int(candidate) < 2:
        assert resolved == [5, 6][int(candidate)], candidate
    else:
        assert resolved is structural_module._MISSING, candidate


@pytest.mark.parametrize("candidate", sorted(INDEX_TOKENS))
def test_the_same_answer_through_a_released_rule(evaluate, candidate: str) -> None:
    """The end-to-end half, and the exact shape the defect was reported in. ``/a/+0`` naming
    element 0 matters only because it changes the reported result of a released rule against
    ``{"a": [5], "b": 5}``, so that is what is asserted."""
    failures = evaluate(candidate, {"a": [5], "b": 5})
    if candidate == "0":
        assert failures == [], candidate  # resolves to element 0, and the rule holds
    else:
        expected = f"equal: /a/{candidate} and /b must both be present and equal"
        assert failures == [expected], candidate


def test_a_well_formed_index_still_resolves_every_element(evaluate) -> None:
    """The false-positive control, and the one that matters most: ``_locations`` builds its
    own pointers with plain decimal indices, so a grammar that was too strict would silently
    stop evaluating every relative rule under ``items``. Each element still resolves."""
    assert evaluate("0", {"a": [7], "b": 7}) == []
    assert evaluate("1", {"a": [7, 8], "b": 8}) == []
    assert evaluate("1", {"a": [7, 8], "b": 7}) == [
        "equal: /a/1 and /b must both be present and equal"
    ]


def test_an_out_of_range_index_is_missing_rather_than_an_error() -> None:
    """A well-formed index past the end is still just an absent location, exactly as the
    ``IndexError`` route made it. The grammar change must not turn that into a raise."""
    assert structural_module._at({"a": [5]}, "/a/1") is structural_module._MISSING
    assert structural_module._at({"a": []}, "/a/0") is structural_module._MISSING


# ================================================================= two-language parity ===


def test_the_typescript_port_implements_the_identical_grammar() -> None:
    """Compare the two patterns as TEXT, not as two hand-written descriptions of one idea.

    Two regexes that are "the same grammar" in prose is how the previous divergence was
    documented -- ``structural.ts`` carried a comment asserting parity with Python's
    ``int(token)`` that was false in both directions. This compares the source of the
    patterns themselves, so a reword on either side cannot claim parity it does not have.
    """
    ts = TS_STRUCTURAL.read_text(encoding="utf-8")
    match = re.search(r"const ARRAY_INDEX = /\^\(\?:([^/]+)\)\$/u;", ts)
    assert match is not None, f"ARRAY_INDEX is not declared in {TS_STRUCTURAL}"
    assert match.group(1) == structural_module._ARRAY_INDEX.pattern, (
        f"{match.group(1)!r} is not Python's {structural_module._ARRAY_INDEX.pattern!r}"
    )
    # Non-vacuity: the extracted body must be a real grammar, not an empty match.
    assert structural_module._ARRAY_INDEX.pattern == "0|[1-9][0-9]*"

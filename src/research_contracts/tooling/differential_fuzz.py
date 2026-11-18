"""P8 -- differential fuzz between the Python and TypeScript canonical engines.

The committed corpus under ``fixtures/canonical-hash/v1/`` proves parity over the inputs
somebody thought to write down. This proves parity over inputs nobody thought of: N randomly
generated instances are canonicalized and digested by BOTH engines, and the run is green only
when every case produces **byte-identical canonical JSON and an identical digest**, or fails
in both engines with the **same error class name**.

Two layers are fuzzed, because the two engines can disagree in either:

``jcs``
    ``canonicalize`` / ``canonical_sha256`` directly -- RFC 8785 member-name ordering, number
    formatting, escaping and surrogate refusal.
``hash_view``
    ``build_hash_view`` under a synthesized released manifest, then ``canonicalize`` --
    exclusions, opaque subtrees, the absent-versus-null rule, declared Unicode normalization,
    and set-like array ordering. The last of these is where the G1 astral-sort divergence
    lived: UTF-8 byte order is Unicode CODE POINT order while a JavaScript string sort is
    UTF-16 CODE UNIT order, and the two disagree for every astral character compared against
    U+E000..U+FFFF.

The obligation names seven categories explicitly, and every one of them has a **targeted**
generator rather than being left to chance -- a category that only turns up statistically is
a category that can silently stop turning up:

===========================  ==============================================================
``non-bmp-keys``             astral member names against U+E000..U+FFFF names
``lone-surrogates``          lone high, lone low and reversed pairs, in names and in values
``negative-zero``            ``-0.0`` in both the released and the RFC-conformance mode
``integers-past-2-53``       exactly 2^53, 2^53+1, 2^63, and beyond, positive and negative
``exponent-boundaries``      the ECMAScript ``1e21`` / ``1e-7`` / ``1e-6`` switch points
``unicode-normalization``    decomposed versus precomposed, under every declared form
``absent-vs-null``           an absent member versus an explicit ``null``, under both rules
===========================  ==============================================================

plus ``structural``, ``string-escapes`` and ``set-like-order-keys``.

REPRODUCIBILITY. Every run is a pure function of ``--seed``, the seed is printed on every
run including the green ones, and a mismatch report leads with the exact replay command. A
fuzz run that cannot be replayed is not evidence.

NON-VACUITY. A run that would generate zero cases -- ``--count 0``, or a count too small to
give every required category at least one case -- exits 2 rather than reporting a green run
over nothing. An empty measurement is not a zero measurement.

PURITY. Every run additionally re-hashes the whole corpus in REVERSE ORDER, and a sample of
cases each ALONE, and requires the identical result for every case. A case's outcome has to
be a property of the case; when it is a property of the batch, the comparator cannot tell a
real divergence from an artifact and the shrinker minimizes towards the artifact. That is
not hypothetical: on Node >= 24 ``JSON.parse`` is not a pure function of its argument -- a
``string-escapes`` case whose member name is the source text ``\\`` poisons V8's member-name
reuse and renames a member of a later case in the same batch. This gate went red on 5 of 200
measured seeds at ``--count 2048`` and then reported a case the two engines agree on; the
purity probes catch 8 of the same 200, three of which the comparator called green.
``packages/typescript/src/json.ts`` no longer delegates to ``JSON.parse``.

FALSIFIABILITY. ``tests/test_differential_fuzz.py`` perturbs the Python engine once per
category (member-name sort order, the 2^53 bound, the exponent switch point, ``-0``
handling, surrogate refusal, the absent-versus-null rule, declared normalization, and the
set-like order-key comparator) and asserts the generated corpus DETECTS each perturbation.
That proves the corpus discriminates, not merely that it runs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Final

from research_contracts.canonical.hash_profile import DERIVATION_PROFILE_VERSION
from research_contracts.canonical.hash_view import build_hash_view
from research_contracts.canonical.jcs import canonicalize

__all__ = [
    "DEFAULT_COUNT",
    "DEFAULT_PURITY_SAMPLE",
    "DEFAULT_SEED",
    "REQUIRED_CATEGORIES",
    "Impurity",
    "Mismatch",
    "check_purity",
    "compare",
    "engine_results",
    "generate_corpus",
    "isolation_sample",
    "main",
    "read_corpus",
    "shrink",
    "synthesize_profile",
    "write_corpus",
]

#: The pinned seed. CI runs this one for a stable regression signal AND a second run seeded
#: from the GitHub run id, so every CI run also covers ground no committed fixture covers.
DEFAULT_SEED: Final = 20260730

DEFAULT_COUNT: Final = 512

#: How many cases are additionally re-hashed ALONE on every run, to prove a case's result is
#: a property of the case rather than of the batch it happened to travel in. The reversed-
#: order probe already covers every case for the cost of one runner invocation; this is the
#: second axis, and it is deliberately small because each sampled case costs a process.
DEFAULT_PURITY_SAMPLE: Final = 8

#: Every category the P8 obligation names, plus the three general ones. Each must produce at
#: least one case or the run is refused: a category silently generating nothing is the same
#: defect as a suite silently discovering no fixtures.
REQUIRED_CATEGORIES: Final[tuple[str, ...]] = (
    "structural",
    "non-bmp-keys",
    "lone-surrogates",
    "negative-zero",
    "integers-past-2-53",
    "exponent-boundaries",
    "unicode-normalization",
    "absent-vs-null",
    "set-like-order-keys",
    "string-escapes",
)

#: Where the compiled TypeScript runner lands. ``packages/typescript/tsconfig.tools.json``
#: keeps ``rootDir`` at the package root, so ``tools/`` and ``src/`` both appear under it.
TS_RUNNER_RELATIVE: Final = Path("packages/typescript/dist-tools/tools/differentialFuzzRunner.js")

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]

# --------------------------------------------------------------------------------------
# Alphabets
# --------------------------------------------------------------------------------------

# Ordinary text, plus the two RFC 6901 tokens that MUST be escaped in a hash-view pointer.
# `~` is escaped before `/` in both engines; a member name carrying both is the only thing
# that can tell a correct implementation from one that escapes in the other order.
_PLAIN: Final = tuple("abcXYZ019 _-./~")

# BMP characters at or above U+E000. These are exactly the ones that sort BEFORE an astral
# character by code point and AFTER it by UTF-16 code unit, so a member-name comparator that
# has silently become code-point order is caught here and nowhere else.
_HIGH_BMP: Final = ("\ue000", "\ue123", "\uf8ff", "\ufb00", "\ufffd", "\uffff")

_LOW_BMP: Final = (
    "\u00e9",
    "\u00fc",
    "\u00df",
    "\u03b1",
    "\u03a9",
    "\u4e2d",
    "\u65e5",
    "\u00a0",
    "\u0301",
)

# Astral (non-BMP) characters: a surrogate PAIR in UTF-16, four bytes in UTF-8.
_ASTRAL: Final = (
    "\U0001d11e",
    "\U0001f600",
    "\U00010348",
    "\U0001f680",
    "\U0010ffff",
)

# Unpaired surrogates. Not valid Unicode; both engines must refuse them, and both must
# refuse a REVERSED pair, which a naive "is the next unit a low surrogate" check accepts.
_LONE_SURROGATES: Final = (
    "\ud800",
    "\udbff",
    "\udc00",
    "\udfff",
    "\udc00\ud800",
)

# The seven short escapes, the remaining C0 controls that become \u00xx, and the two
# characters several JavaScript serializers escape WRONGLY: U+2028 and U+2029 are ORDINARY
# code points to RFC 8785, and escaping them produces different bytes and a different hash.
_ESCAPABLE: Final = (
    "\u0000",
    "\u0001",
    "\u0007",
    "\b",
    "\t",
    "\n",
    "\u000b",
    "\f",
    "\r",
    "\u001f",
    "\u007f",
    '"',
    "\\",
    "/",
    "\u2028",
    "\u2029",
)

#: (precomposed, decomposed-or-compatibility) pairs that are stable across Unicode versions.
#: Deliberately curated rather than random: an exotic code point whose composition changed
#: between the Unicode version in CPython's ``unicodedata`` and the one in Node's ICU would
#: make this gate flap for a reason that is neither engine's defect. The general string
#: alphabets stay broad, and the released profile normalizes nothing, so breadth is not lost.
_NORMALIZATION_PAIRS: Final = (
    ("\u00e9", "e\u0301"),
    ("\u1ec7", "e\u0323\u0302"),
    ("\u00c5", "A\u030a"),
    ("\u212b", "A\u030a"),
    ("\u2126", "\u03a9"),
    ("\ud55c", "\u1112\u1161\u11ab"),
    ("\ufb01", "fi"),
    ("\u2460", "1"),
    ("\uff71", "\u30a2"),
    ("\u01f9", "n\u0300"),
)

_NORMALIZATION_FORMS: Final = ("none", "nfc", "nfd", "nfkc", "nfkd")

# The ECMAScript Number::toString switch points (ECMA-262 6.1.6.1.20), which RFC 8785
# section 3.2.2.3 defers to. `1e21` is the first magnitude rendered in exponent form and
# `1e-7` the first small magnitude; `1e20` and `1e-6` are the last on the fixed-notation
# side. Every one of these is an UNSTABLE binary float under the released policy, so they
# only reach the serializer in the RFC-conformance mode.
_EXPONENT_BOUNDARY_NUMBERS: Final = (
    1e21,
    -1e21,
    1e20,
    9.999999999999999e20,
    1.0000000000000001e21,
    1e-6,
    -1e-6,
    1e-7,
    9.999999999999999e-7,
    1.0000000000000002e-7,
    1e-323,
    5e-324,
    1.7976931348623157e308,
    0.1,
    -0.30000000000000004,
    1234567890.12345,
    1e100,
    1e-100,
)

# 2^53 is the largest magnitude an IEEE-754 double holds exactly. At the bound both engines
# serialize; one past it both must raise UnstableFloatError -- Python because `int` is
# arbitrary precision, TypeScript because `parseCanonicalJson` re-materializes the literal
# as a `bigint` instead of letting `JSON.parse` round it away.
_MAX_EXACT: Final = 2**53
_LARGE_INTEGERS: Final = (
    _MAX_EXACT - 1,
    _MAX_EXACT,
    _MAX_EXACT + 1,
    _MAX_EXACT + 2,
    -_MAX_EXACT,
    -(_MAX_EXACT + 1),
    2**63,
    -(2**63) - 1,
    10**30,
    -(10**30),
)

_EXCLUSION_REASON: Final = "projection_or_cache"

#: A member name no generator emits, declared so an empty object counts as "members
#: enumerated". Declaring a path an instance does not carry is legal and changes no bytes.
_DECLARED_ABSENT: Final = "__declared_absent__"


# --------------------------------------------------------------------------------------
# Hash-view manifest synthesis
# --------------------------------------------------------------------------------------


def _escape(token: str) -> str:
    """RFC 6901 reference-token escaping. ``~`` MUST be escaped before ``/``."""
    return token.replace("~", "~0").replace("/", "~1")


def _array_declaration(
    node: list[Any], pointer: str, rng: random.Random, set_probability: float
) -> dict[str, Any]:
    """Declare an array ordered, or set-like when every member can carry an order key."""
    if node and all(isinstance(item, dict) for item in node):
        common = sorted(set.intersection(*(set(item) for item in node)))
        if common and rng.random() < set_probability:
            return {
                "pointer": pointer,
                "kind": "set",
                "order_key": [f"/{_escape(common[0])}"],
            }
    return {"pointer": pointer, "kind": "ordered"}


def synthesize_profile(value: Any, settings: dict[str, Any]) -> dict[str, Any]:
    """Build a released-shaped hash-view manifest that declares every path in ``value``.

    Deterministic in ``settings["profile_seed"]`` and in ``value``, so the shrinker can
    re-derive a coherent manifest for a shrunk instance instead of carrying a stale one.
    """
    rng = random.Random(settings["profile_seed"])  # noqa: S311 - reproducibility, not secrecy
    included: list[str] = []
    arrays: list[dict[str, Any]] = []
    seen_arrays: set[str] = set()
    object_pointers: list[str] = []

    def walk(node: Any, pointer: str) -> None:
        if isinstance(node, dict):
            if pointer:
                object_pointers.append(pointer)
            if not node and pointer:
                # An EMPTY object still has to be declared: both engines refuse an object
                # whose members are neither enumerated nor covered by an opaque subtree, and
                # "it has no members" is not a third option. A manifest may declare a path
                # that this particular instance does not carry, so a single declared-absent
                # child is the released way to say "this object's members are enumerated".
                # Without it every generated `{}` produced UndeclaredPathError and the case
                # tested the refusal path instead of the rule it was generated for.
                included.append(f"{pointer}/{_escape(_DECLARED_ABSENT)}")
            for name, child in node.items():
                child_pointer = f"{pointer}/{_escape(name)}"
                if child_pointer not in included:
                    included.append(child_pointer)
                walk(child, child_pointer)
        elif isinstance(node, list):
            if pointer not in seen_arrays:
                seen_arrays.add(pointer)
                arrays.append(_array_declaration(node, pointer, rng, settings["set_probability"]))
            for item in node:
                walk(item, f"{pointer}/-")

    walk(value, "")

    excluded_pointers = {
        pointer for pointer in included if rng.random() < settings["exclude_probability"]
    }
    opaque: list[str] = []
    if settings["opaque"] and object_pointers:
        target = rng.choice(object_pointers)
        opaque.append(target)
        prefix = f"{target}/"
        included = [pointer for pointer in included if not pointer.startswith(prefix)]
        excluded_pointers = {
            pointer for pointer in excluded_pointers if not pointer.startswith(prefix)
        }

    return {
        "profile_id": "urn:datacompany:canonical-hash-profile:1",
        # The implemented constant, never a literal. A hardcoded 1 survived the
        # `DERIVATION_PROFILE_VERSION` 1 -> 2 bump in silence, because this generator does
        # not call `derive_hash_profile` and nothing here reads the number back.
        #
        # It was INERT, and saying so matters more than claiming a catch: neither engine's
        # `build_hash_view` reads `profile_version`, and the comparator hands the SAME
        # profile object to both, so a stale 1 could not have produced a divergence or a
        # wrong hash. What it could produce is a fixture-shaped lie -- a generator emitting
        # manifests at a version neither engine implements, which is exactly the state
        # `validate_profile_against_schema` exists to refuse elsewhere. Bound to the constant
        # so the next bump cannot leave it behind either.
        "profile_version": DERIVATION_PROFILE_VERSION,
        "schema_ref": "urn:datacompany:differential-fuzz:1",
        "serialization": "rfc8785",
        "encoding": "utf-8",
        "byte_order_mark": False,
        "digest_algorithm": "sha256",
        "digest_prefix": "sha256:",
        "absent_vs_null": settings["absent_vs_null"],
        "unicode_normalization": settings["unicode_normalization"],
        "timestamp_representation": "rfc3339_utc_z",
        "decimal_representation": "decimal_string",
        "binary_float_policy": "reject",
        "included_pointers": [p for p in included if p not in excluded_pointers],
        "excluded_pointers": [
            {"pointer": pointer, "reason": _EXCLUSION_REASON}
            for pointer in sorted(excluded_pointers)
        ],
        "opaque_pointers": opaque,
        "arrays": arrays,
    }


def _profile_settings(rng: random.Random, **overrides: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "profile_seed": rng.getrandbits(48),
        "absent_vs_null": rng.choice(["distinct", "equivalent"]),
        "unicode_normalization": "none",
        "set_probability": 0.35,
        "exclude_probability": 0.1,
        "opaque": rng.random() < 0.2,
    }
    settings.update(overrides)
    return settings


# --------------------------------------------------------------------------------------
# Value generation
# --------------------------------------------------------------------------------------


def _text(rng: random.Random, alphabets: Sequence[Sequence[str]], maximum: int = 5) -> str:
    pool = [character for alphabet in alphabets for character in alphabet]
    return "".join(rng.choice(pool) for _ in range(rng.randint(0, maximum)))


def _scalar(rng: random.Random, alphabets: Sequence[Sequence[str]], *, floats: bool) -> Any:
    choice = rng.random()
    if choice < 0.3:
        return _text(rng, alphabets)
    if choice < 0.5:
        return rng.randint(-(2**40), 2**40)
    if choice < 0.6:
        return rng.choice([True, False])
    if choice < 0.7:
        return None
    if choice < 0.8 and floats:
        return rng.choice(_EXPONENT_BOUNDARY_NUMBERS)
    if choice < 0.9:
        return rng.choice([0, -0.0, 1.0, 2.0, -1.0])
    return rng.randint(-9, 9)


def _value(
    rng: random.Random,
    alphabets: Sequence[Sequence[str]],
    depth: int,
    *,
    floats: bool = False,
) -> Any:
    if depth <= 0 or rng.random() < 0.45:
        return _scalar(rng, alphabets, floats=floats)
    if rng.random() < 0.5:
        size = rng.randint(0, 4)
        return {
            _text(rng, alphabets): _value(rng, alphabets, depth - 1, floats=floats)
            for _ in range(size)
        }
    size = rng.randint(0, 4)
    return [_value(rng, alphabets, depth - 1, floats=floats) for _ in range(size)]


def _keyed_members(rng: random.Random, alphabets: Sequence[Sequence[str]]) -> list[Any]:
    """Objects that all carry ``k``, so a set-like declaration is well formed."""
    return [
        {
            "k": _text(rng, alphabets, maximum=3),
            "v": _value(rng, alphabets, 1),
        }
        for _ in range(rng.randint(1, 5))
    ]


# --------------------------------------------------------------------------------------
# Category generators
# --------------------------------------------------------------------------------------


def _case(
    case_id: str,
    category: str,
    value: Any,
    *,
    layer: str = "jcs",
    allow_binary_float: bool = False,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case: dict[str, Any] = {
        "case_id": case_id,
        "category": category,
        "layer": layer,
        "allow_binary_float": allow_binary_float,
        "value": value,
        "profile_settings": settings,
        "profile": synthesize_profile(value, settings) if settings is not None else None,
    }
    return case


def _generate_structural(rng: random.Random, case_id: str) -> dict[str, Any]:
    alphabets = (_PLAIN, _LOW_BMP, _HIGH_BMP, _ASTRAL)
    value = _value(rng, alphabets, 3)
    if rng.random() < 0.5:
        return _case(case_id, "structural", value)
    return _case(case_id, "structural", value, layer="hash_view", settings=_profile_settings(rng))


def _generate_non_bmp_keys(rng: random.Random, case_id: str) -> dict[str, Any]:
    """Member names mixing astral characters with U+E000..U+FFFF -- the G1 divergence."""
    names: list[str] = []
    for _ in range(rng.randint(2, 6)):
        head = rng.choice(_ASTRAL + _HIGH_BMP)
        tail = _text(rng, (_PLAIN, _HIGH_BMP, _ASTRAL), maximum=2)
        names.append(head + tail)
    names.append(rng.choice(_HIGH_BMP))
    names.append(rng.choice(_ASTRAL))
    value = {name: index for index, name in enumerate(names)}
    if rng.random() < 0.5:
        return _case(case_id, "non-bmp-keys", value)
    return _case(
        case_id,
        "non-bmp-keys",
        value,
        layer="hash_view",
        settings=_profile_settings(rng, opaque=False, exclude_probability=0.0),
    )


def _generate_lone_surrogates(rng: random.Random, case_id: str) -> dict[str, Any]:
    surrogate = rng.choice(_LONE_SURROGATES)
    placement = rng.randint(0, 3)
    if placement == 0:
        value: Any = surrogate
    elif placement == 1:
        value = {"ok": 1, surrogate: 2}
    elif placement == 2:
        value = ["fine", "a" + surrogate + "b"]
    else:
        value = {"nested": {"deep": [{"s": surrogate}]}}
    if rng.random() < 0.4:
        return _case(
            case_id,
            "lone-surrogates",
            value,
            layer="hash_view",
            settings=_profile_settings(rng, opaque=False, exclude_probability=0.0),
        )
    return _case(case_id, "lone-surrogates", value)


def _generate_negative_zero(rng: random.Random, case_id: str) -> dict[str, Any]:
    """``-0.0`` must render as ``0`` in both engines, in both modes and at every depth."""
    shapes: tuple[Any, ...] = (
        -0.0,
        [-0.0, 0.0, 0, -0],
        {"a": -0.0, "b": 0},
        {"n": [{"z": -0.0}, {"z": 0.0}]},
        [[-0.0]],
        {"mixed": [-0.0, 1.0, -1.0, 0.0]},
    )
    value = rng.choice(shapes)
    mode = rng.randint(0, 2)
    if mode == 0:
        return _case(case_id, "negative-zero", value)
    if mode == 1:
        return _case(case_id, "negative-zero", value, allow_binary_float=True)
    return _case(
        case_id,
        "negative-zero",
        value,
        layer="hash_view",
        settings=_profile_settings(rng, opaque=False, exclude_probability=0.0),
    )


def _generate_large_integers(rng: random.Random, case_id: str) -> dict[str, Any]:
    number = rng.choice(_LARGE_INTEGERS)
    placement = rng.randint(0, 2)
    if placement == 0:
        value: Any = number
    elif placement == 1:
        value = {"n": number, "safe": 42}
    else:
        value = [number, [number], {"deep": number}]
    if rng.random() < 0.4:
        # Under a manifest, an out-of-range integer at an EXCLUDED pointer never reaches the
        # serializer -- in either language. That asymmetry is exactly what json.ts exists for.
        return _case(
            case_id,
            "integers-past-2-53",
            value,
            layer="hash_view",
            settings=_profile_settings(rng, opaque=False, exclude_probability=0.4),
        )
    return _case(case_id, "integers-past-2-53", value)


def _generate_exponent_boundaries(rng: random.Random, case_id: str) -> dict[str, Any]:
    numbers = [rng.choice(_EXPONENT_BOUNDARY_NUMBERS) for _ in range(rng.randint(1, 4))]
    placement = rng.randint(0, 2)
    if placement == 0:
        value: Any = numbers
    elif placement == 1:
        value = {f"n{index}": number for index, number in enumerate(numbers)}
    else:
        value = numbers[0]
    if rng.random() < 0.25:
        # The released policy REJECTS every one of these; that refusal must also agree.
        return _case(case_id, "exponent-boundaries", value)
    return _case(case_id, "exponent-boundaries", value, allow_binary_float=True)


def _generate_normalization(rng: random.Random, case_id: str) -> dict[str, Any]:
    precomposed, decomposed = rng.choice(_NORMALIZATION_PAIRS)
    form = rng.choice(_NORMALIZATION_FORMS)
    value = {
        "pre": precomposed,
        "dec": decomposed,
        "mixed": precomposed + "-" + decomposed,
        # Member NAMES are never normalized by either engine -- only values are. A pair of
        # names differing only by composition must therefore survive as two distinct members.
        precomposed: 1,
        decomposed: 2,
        "nested": [{"s": decomposed}, {"s": precomposed}],
    }
    return _case(
        case_id,
        "unicode-normalization",
        value,
        layer="hash_view",
        settings=_profile_settings(
            rng, unicode_normalization=form, opaque=False, exclude_probability=0.0
        ),
    )


def _generate_absent_vs_null(rng: random.Random, case_id: str) -> dict[str, Any]:
    present = rng.random() < 0.5
    inner: dict[str, Any] = {"kept": 1}
    if present:
        inner["maybe"] = None
    value: Any = {"a": inner, "b": [{"x": None} if present else {}], "c": None if present else 0}
    if rng.random() < 0.3:
        # At the JCS layer there is no absent-versus-null RULE at all: `{"a":null}` and `{}`
        # are simply different documents, and both engines must render both.
        return _case(case_id, "absent-vs-null", value)
    return _case(
        case_id,
        "absent-vs-null",
        value,
        layer="hash_view",
        settings=_profile_settings(
            rng,
            absent_vs_null="distinct" if rng.random() < 0.5 else "equivalent",
            opaque=False,
            exclude_probability=0.0,
        ),
    )


def _generate_set_like(rng: random.Random, case_id: str) -> dict[str, Any]:
    alphabets = (_PLAIN, _HIGH_BMP, _ASTRAL, _LOW_BMP)
    members = _keyed_members(rng, alphabets)
    if rng.random() < 0.3 and members:
        # A deliberate duplicate order key: both engines must raise DuplicateSetMemberError.
        members = [*members, dict(members[0])]
    if rng.random() < 0.15:
        # A member missing the order key: both engines must raise MissingOrderKeyError.
        members = [*members, {"v": 1}]
    value = {"items": members}
    return _case(
        case_id,
        "set-like-order-keys",
        value,
        layer="hash_view",
        settings=_profile_settings(rng, set_probability=1.0, opaque=False, exclude_probability=0.0),
    )


def _generate_string_escapes(rng: random.Random, case_id: str) -> dict[str, Any]:
    alphabets = (_ESCAPABLE, _PLAIN, _LOW_BMP)
    value: Any = {
        _text(rng, alphabets, maximum=4): _text(rng, alphabets, maximum=6)
        for _ in range(rng.randint(1, 4))
    }
    if rng.random() < 0.4:
        value = [_text(rng, alphabets, maximum=8) for _ in range(rng.randint(1, 4))]
    return _case(case_id, "string-escapes", value)


_GENERATORS: Final = {
    "structural": _generate_structural,
    "non-bmp-keys": _generate_non_bmp_keys,
    "lone-surrogates": _generate_lone_surrogates,
    "negative-zero": _generate_negative_zero,
    "integers-past-2-53": _generate_large_integers,
    "exponent-boundaries": _generate_exponent_boundaries,
    "unicode-normalization": _generate_normalization,
    "absent-vs-null": _generate_absent_vs_null,
    "set-like-order-keys": _generate_set_like,
    "string-escapes": _generate_string_escapes,
}


class EmptyCorpusError(ValueError):
    """A run that would measure nothing. Never a pass."""


def generate_corpus(seed: int, count: int) -> list[dict[str, Any]]:
    """Return ``count`` cases, deterministic in ``seed``, covering every required category.

    Raises :class:`EmptyCorpusError` when ``count`` cannot give every required category at
    least one case. A category present in the table but absent from the corpus is a hole
    that renders as a pass, which is the whole defect class this repository exists to close.
    """
    if count < len(REQUIRED_CATEGORIES):
        raise EmptyCorpusError(
            f"--count {count} cannot cover the {len(REQUIRED_CATEGORIES)} required "
            f"categories {list(REQUIRED_CATEGORIES)}; a category that generates nothing "
            "is a silent hole, so the run is refused rather than reported green"
        )
    rng = random.Random(seed)  # noqa: S311 - reproducibility, not secrecy
    cases: list[dict[str, Any]] = []
    for index in range(count):
        category = REQUIRED_CATEGORIES[index % len(REQUIRED_CATEGORIES)]
        cases.append(_GENERATORS[category](rng, f"{category}/{index:05d}"))
    missing = set(REQUIRED_CATEGORIES) - {case["category"] for case in cases}
    if missing:  # pragma: no cover - round-robin makes this unreachable; kept as a tripwire
        raise EmptyCorpusError(f"categories {sorted(missing)} generated no cases")
    return cases


# --------------------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------------------


def _wire_record(case: dict[str, Any]) -> dict[str, Any]:
    """The subset of a case that crosses the language boundary."""
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "layer": case["layer"],
        "allow_binary_float": case["allow_binary_float"],
        "value": case["value"],
        "profile": case["profile"],
    }


def write_corpus(cases: Iterable[dict[str, Any]], path: Path) -> int:
    """Write the corpus as JSONL and return the number of records.

    ``ensure_ascii=True`` is load-bearing: it renders a lone surrogate as ``\\udXXX``, which
    is the only way that fact survives a UTF-8 file. An out-of-range integer is written as
    its exact literal, which ``json.loads`` reads back as an ``int`` and the TypeScript
    ``parseCanonicalJson`` re-materializes as a ``bigint`` -- both engines therefore see the
    same fact instead of one of them seeing a silently rounded double.
    """
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(_wire_record(case), ensure_ascii=True, allow_nan=False))
            handle.write("\n")
            written += 1
    return written


def read_corpus(path: Path) -> list[dict[str, Any]]:
    """Read the corpus back through ``json.loads``, so both engines start from one text."""
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not records:
        raise EmptyCorpusError(f"{path}: corpus is empty")
    return records


# --------------------------------------------------------------------------------------
# The Python side of the differential
# --------------------------------------------------------------------------------------


def _outcome(record: dict[str, Any]) -> dict[str, Any]:
    try:
        if record["layer"] == "hash_view":
            subject = build_hash_view(record["value"], record["profile"])
        else:
            subject = record["value"]
        raw = canonicalize(subject, allow_binary_float=bool(record["allow_binary_float"]))
    except Exception as exc:  # noqa: BLE001 - an unexpected class IS the differential fact
        return {"case_id": record["case_id"], "ok": False, "error": type(exc).__name__}
    return {
        "case_id": record["case_id"],
        "ok": True,
        "canonical_base64": base64.b64encode(raw).decode("ascii"),
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }


def engine_results(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the Python engine over every record. Never raises for a per-case failure."""
    return [_outcome(record) for record in records]


# --------------------------------------------------------------------------------------
# The TypeScript side
# --------------------------------------------------------------------------------------


class TypeScriptRunnerError(RuntimeError):
    """The compiled TypeScript runner is missing, stale, or failed to execute."""


def locate_runner(root: Path) -> Path:
    """Return the built runner, refusing a MISSING or STALE build.

    A stale build silently fuzzes yesterday's TypeScript against today's Python and calls
    the result parity, which is worse than no run at all.
    """
    runner = root / TS_RUNNER_RELATIVE
    build = "npm --prefix packages/typescript run fuzz:build"
    if not runner.is_file():
        raise TypeScriptRunnerError(
            f"{runner} does not exist; build the TypeScript runner first:\n    {build}"
        )
    built_at = runner.stat().st_mtime
    package = root / "packages/typescript"
    newer = [
        source
        for directory in ("src", "tools")
        for source in (package / directory).rglob("*.ts")
        if source.stat().st_mtime > built_at
    ]
    if newer:
        names = ", ".join(sorted(str(path.relative_to(root)) for path in newer))
        raise TypeScriptRunnerError(
            f"{runner} is older than {names}; the fuzz would compare today's Python against "
            f"a stale TypeScript build. Rebuild:\n    {build}"
        )
    return runner


def run_typescript(
    runner: Path, corpus: Path, results: Path, *, node: str = "node"
) -> list[dict[str, Any]]:
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [node, str(runner), str(corpus), str(results)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise TypeScriptRunnerError(
            f"the TypeScript runner exited {completed.returncode}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return [
        json.loads(line)
        for line in results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------------------


class Mismatch:
    """One case on which the two engines disagree."""

    def __init__(self, case_id: str, reason: str, python: Any, typescript: Any) -> None:
        self.case_id = case_id
        self.reason = reason
        self.python = python
        self.typescript = typescript

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Mismatch({self.case_id!r}, {self.reason!r})"


def compare(
    python: Sequence[dict[str, Any]], typescript: Sequence[dict[str, Any]]
) -> list[Mismatch]:
    """Every disagreement between the two result streams, including missing/extra cases."""
    mismatches: list[Mismatch] = []
    by_id = {result["case_id"]: result for result in typescript}
    if len(by_id) != len(typescript):
        mismatches.append(
            Mismatch("<corpus>", "the TypeScript runner emitted duplicate case ids", None, None)
        )
    for expected in python:
        case_id = expected["case_id"]
        actual = by_id.pop(case_id, None)
        if actual is None:
            mismatches.append(
                Mismatch(case_id, "the TypeScript runner produced no result", expected, None)
            )
            continue
        if expected["ok"] != actual["ok"]:
            mismatches.append(
                Mismatch(case_id, "one engine succeeded, the other failed", expected, actual)
            )
            continue
        if not expected["ok"]:
            if expected["error"] != actual["error"]:
                mismatches.append(Mismatch(case_id, "different error class", expected, actual))
            continue
        if expected["canonical_base64"] != actual["canonical_base64"]:
            mismatches.append(Mismatch(case_id, "different canonical JSON bytes", expected, actual))
            continue
        if expected["digest"] != actual["digest"]:
            mismatches.append(Mismatch(case_id, "different content hash", expected, actual))
    for leftover in by_id:
        mismatches.append(
            Mismatch(leftover, "the TypeScript runner produced an unrequested result", None, None)
        )
    return mismatches


# --------------------------------------------------------------------------------------
# Purity
# --------------------------------------------------------------------------------------


class Impurity:
    """One case whose result changed when nothing about the case changed."""

    def __init__(self, case_id: str, probe: str, batch: Any, again: Any) -> None:
        self.case_id = case_id
        self.probe = probe
        self.batch = batch
        self.again = again

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Impurity({self.case_id!r}, {self.probe!r})"


def isolation_sample(cases: Sequence[dict[str, Any]], sample: int) -> list[dict[str, Any]]:
    """``sample`` cases spread evenly across the corpus, first and last included.

    Deterministic on purpose: a purity check that sampled at random would fail on some runs
    and not others for the same seed, and an intermittent gate is one nobody believes.
    """
    if sample <= 0 or not cases:
        return []
    if sample >= len(cases):
        return list(cases)
    if sample == 1:
        return [cases[0]]
    step = (len(cases) - 1) / (sample - 1)
    return [
        cases[index] for index in sorted({round(position * step) for position in range(sample)})
    ]


def check_purity(
    cases: Sequence[dict[str, Any]],
    batch: Sequence[dict[str, Any]],
    run: Any,
    *,
    sample: int = 8,
) -> list[Impurity]:
    """Every way a case's result must NOT depend on the other cases in the run.

    ``run(cases, stem) -> list[result]`` hashes a corpus with the TypeScript engine, writing
    it under ``stem`` so a ``--keep`` run leaves every probe's corpus and result stream on
    disk for inspection rather than one file overwritten N times. Two probes,
    because an engine can leak state along two different axes:

    ``reversed corpus order``
        the whole corpus again, back to front. One extra runner invocation covers EVERY
        case, and any cross-case leak is order-sensitive by construction -- the case that
        poisons and the case that suffers swap places.
    ``the case alone``
        a sample of cases, each in a corpus of its own. Catches a leak that survives
        reordering because it depends on there being other cases at all.

    This exists because the engine really was impure: on Node >= 24 a `JSON.parse` of one
    generated case renamed a member of another case later in the same batch, so the fuzz
    went red on 5 of 200 measured seeds and the shrinker then "minimized" the failure to an
    instance the engines agree on. See `packages/typescript/src/json.ts`.
    """
    findings: list[Impurity] = []
    expected = {result["case_id"]: result for result in batch}

    if len(cases) > 1:
        reordered = {
            result["case_id"]: result for result in run(list(reversed(cases)), "purity-reversed")
        }
        for case in cases:
            case_id = case["case_id"]
            again = reordered.get(case_id)
            if again != expected.get(case_id):
                findings.append(
                    Impurity(case_id, "reversed corpus order", expected.get(case_id), again)
                )

    for position, case in enumerate(isolation_sample(cases, sample)):
        case_id = case["case_id"]
        alone = run([case], f"purity-alone-{position:03d}")
        again = alone[0] if alone else None
        if again != expected.get(case_id):
            findings.append(Impurity(case_id, "the case alone", expected.get(case_id), again))
    return findings


# --------------------------------------------------------------------------------------
# Shrinking
# --------------------------------------------------------------------------------------


def _candidates(value: Any) -> list[Any]:
    """Strictly smaller values to try. Order matters: biggest reductions first."""
    out: list[Any] = []
    if isinstance(value, dict):
        for name in list(value):
            out.append({key: item for key, item in value.items() if key != name})
        out.extend(value.values())
    elif isinstance(value, list):
        for index in range(len(value)):
            out.append([item for position, item in enumerate(value) if position != index])
        out.extend(value)
    elif isinstance(value, str) and value:
        out.append(value[: len(value) // 2])
        out.append(value[1:])
        out.append(value[:-1])
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0:
        out.append(0)
    seen: list[Any] = []
    for candidate in out:
        if candidate is not value:
            seen.append(candidate)
    return seen


def _rebuild(case: dict[str, Any], value: Any, case_id: str) -> dict[str, Any]:
    """A candidate carrying ``value``, a manifest re-derived for it, and a UNIQUE id.

    The id matters. Every candidate in a shrink round is written into one corpus and hashed
    in one subprocess; candidates sharing the generated case's id would collide in the
    comparator's ``case_id`` index and every one of them would read as a mismatch, so the
    shrinker would happily "minimize" to an instance on which the engines actually AGREE.
    That is exactly what the first cross-engine falsification run produced -- the report
    named ``[]`` as the minimal failing value while printing identical digests for it.
    """
    settings = case["profile_settings"]
    return {
        **case,
        "case_id": case_id,
        "value": value,
        "profile": synthesize_profile(value, settings) if settings is not None else None,
    }


def shrink(
    case: dict[str, Any],
    evaluate: Any,
    *,
    max_rounds: int = 40,
    max_candidates: int = 120,
) -> dict[str, Any]:
    """Reduce ``case`` while ``evaluate(cases) -> list[bool]`` still reports a mismatch.

    ``evaluate`` takes a batch so the TypeScript runner is spawned once per round rather
    than once per candidate.
    """
    original_id = case["case_id"]
    current = case
    for round_number in range(max_rounds):
        candidates = [
            _rebuild(current, value, f"{original_id}~shrink~{round_number}~{index}")
            for index, value in enumerate(_candidates(current["value"]))
        ][:max_candidates]
        if not candidates:
            break
        verdicts = evaluate(candidates)
        reduced = next(
            (candidate for candidate, failed in zip(candidates, verdicts, strict=True) if failed),
            None,
        )
        if reduced is None:
            break
        current = reduced
    return {**current, "case_id": original_id}


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def _evidence_location(workspace: Path, kept: bool) -> list[str]:
    """Where the batch-time streams are, and how to keep them if they were thrown away."""
    if kept:
        return [
            f"  batch streams   : {workspace}/corpus.jsonl and {workspace}/typescript.jsonl",
        ]
    return [
        "  batch streams   : NOT KEPT — this run used a temporary directory. Re-run with",
        "                    --keep <dir> to inspect corpus.jsonl and typescript.jsonl, which",
        "                    hold the result the TypeScript engine actually produced in the",
        "                    batch, as opposed to the isolated re-run printed above.",
    ]


def _render(
    case: dict[str, Any],
    python: Any,
    typescript: Any,
    seed: int,
    count: int,
    *,
    reproduced_in_isolation: bool = True,
    batch_python: Any = None,
    batch_typescript: Any = None,
    workspace: Path | None = None,
    kept: bool = False,
) -> str:
    """Render the mismatch report.

    ``python``/``typescript`` are the ISOLATED re-run of the reported case. When that re-run
    does not reproduce the batch disagreement, printing it alone is a self-contradicting
    report -- two identical digests under the heading "the two canonical engines disagree" --
    and it sends whoever is triaging to a case that is fine. That happened: the shrinker
    minimized a real batch failure to an instance the engines agree on, the report printed
    the agreeing re-run, and nothing said the real evidence was in the kept streams. So when
    the re-run disagrees with the batch, the report SAYS SO FIRST, prints the batch-time
    outcome as the evidence, and marks the isolated pair as not being the failure.
    """
    replay = f"./scripts/differential_fuzz.py --seed {seed} --count {count}"
    heading = (
        "DIFFERENTIAL FUZZ MISMATCH — the two canonical engines disagree"
        if reproduced_in_isolation
        else "DIFFERENTIAL FUZZ MISMATCH — REPORTED CASE DOES NOT REPRODUCE ON ITS OWN"
    )
    lines = [
        "",
        "=" * 78,
        heading,
        "=" * 78,
    ]
    if not reproduced_in_isolation:
        lines += [
            "  !! The engines DISAGREED on this case inside the batch and AGREE on it when it",
            "  !! is re-run alone. The disagreement is therefore not a property of the case:",
            "  !! one of the engines is not a pure function of a single case, or the harness",
            "  !! is carrying state between cases. Triage the impurity, not the case.",
            "  !! The batch-time outcome below is the evidence; the isolated pair is NOT.",
            "",
        ]
    lines += [
        f"  seed            : {seed}",
        f"  replay          : {replay}",
        f"  case_id         : {case['case_id']}",
        f"  category        : {case['category']}",
        f"  layer           : {case['layer']}",
        f"  allow_binary_float: {case['allow_binary_float']}",
        "  minimal value   : "
        + json.dumps(case["value"], ensure_ascii=True, allow_nan=False, sort_keys=False),
    ]
    if case["profile"] is not None:
        lines.append(
            "  manifest        : " + json.dumps(case["profile"], ensure_ascii=True, sort_keys=True)
        )
    if reproduced_in_isolation:
        lines.append(f"  python          : {json.dumps(python, ensure_ascii=True)}")
        lines.append(f"  typescript      : {json.dumps(typescript, ensure_ascii=True)}")
    elif batch_python is None and batch_typescript is None:
        lines.append(
            "  batch outcome   : NOT AVAILABLE — the value above was produced by SHRINKING and "
            "the batch never ran it"
        )
    else:
        lines.append(f"  batch python    : {json.dumps(batch_python, ensure_ascii=True)}")
        lines.append(f"  batch typescript: {json.dumps(batch_typescript, ensure_ascii=True)}")
    if not reproduced_in_isolation:
        lines.append(
            f"  re-run python   : {json.dumps(python, ensure_ascii=True)}  (agrees — NOT the failure)"
        )
        lines.append(
            f"  re-run typescript: {json.dumps(typescript, ensure_ascii=True)}  (agrees — NOT the failure)"
        )
        if workspace is not None:
            lines += _evidence_location(workspace, kept)
    lines.append("=" * 78)
    return "\n".join(lines)


def _render_impurity(
    findings: Sequence[Impurity], seed: int, count: int, workspace: Path, kept: bool
) -> str:
    """The report for an engine whose answer depends on what else was in the run."""
    lines = [
        "",
        "=" * 78,
        "DIFFERENTIAL FUZZ IMPURITY — a case's result depends on the rest of the batch",
        "=" * 78,
        f"  seed            : {seed}",
        f"  replay          : ./scripts/differential_fuzz.py --seed {seed} --count {count}",
        f"  affected cases  : {len(findings)}",
        "",
        "  Each case below produced one result inside the full corpus and a DIFFERENT result",
        "  when nothing about the case changed. Until that is fixed no mismatch this run",
        "  reports can be trusted, and shrinking is meaningless: it re-runs candidates in a",
        "  different batch, so it minimizes towards whatever the impurity happens to do.",
        "",
    ]
    for finding in findings[:10]:
        lines += [
            f"  case_id         : {finding.case_id}",
            f"  probe           : {finding.probe}",
            f"    in the batch  : {json.dumps(finding.batch, ensure_ascii=True)}",
            f"    re-measured   : {json.dumps(finding.again, ensure_ascii=True)}",
        ]
    if len(findings) > 10:
        lines.append(f"  ... and {len(findings) - 10} more")
    lines += _evidence_location(workspace, kept)
    lines.append("=" * 78)
    return "\n".join(lines)


def _tally(
    cases: Sequence[dict[str, Any]], results: Sequence[dict[str, Any]]
) -> dict[str, dict[str, int]]:
    """Per-category counts of agreed-bytes versus identically-refused, by error class."""
    table: dict[str, dict[str, int]] = {}
    for case, result in zip(cases, results, strict=True):
        row = table.setdefault(case["category"], {})
        outcome = "agreed bytes" if result["ok"] else result["error"]
        row[outcome] = row.get(outcome, 0) + 1
    return table


def _render_tally(table: dict[str, dict[str, int]]) -> list[str]:
    """Print what was actually measured. A summary that only says "passed" hides a run in
    which an entire category collapsed into one refusal and compared no bytes at all."""
    lines = ["differential fuzz outcomes, by category:"]
    for category in sorted(table):
        parts = ", ".join(
            f"{outcome} x{count}" for outcome, count in sorted(table[category].items())
        )
        lines.append(f"  {category:<22} {parts}")
    return lines


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="differential_fuzz.py",
        description=(
            "P8 differential fuzz: N randomly generated instances canonicalized and hashed "
            "by BOTH the Python and the TypeScript engine, asserting byte-identical "
            "canonical JSON and an identical digest (or the same refusal)."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"PRNG seed; the run is a pure function of it (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"number of generated cases (default: {DEFAULT_COUNT})",
    )
    parser.add_argument(
        "--keep",
        type=Path,
        default=None,
        help="directory to keep corpus.jsonl and typescript.jsonl in, for inspection",
    )
    parser.add_argument(
        "--node", default=os.environ.get("NODE", "node"), help="node executable (default: node)"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository root holding packages/typescript (default: the containing repository)",
    )
    parser.add_argument(
        "--no-shrink",
        action="store_true",
        help="report the raw failing case instead of minimizing it first",
    )
    parser.add_argument(
        "--purity-sample",
        type=int,
        default=DEFAULT_PURITY_SAMPLE,
        help=(
            "how many cases to additionally re-hash ALONE, to prove a case's result does "
            "not depend on the rest of the batch; the whole corpus is always re-hashed in "
            f"reverse order as well (default: {DEFAULT_PURITY_SAMPLE}, 0 for reorder only)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Return 0 on parity, 1 on a disagreement, 2 on a run that would measure nothing."""
    args = _parser().parse_args(argv)

    try:
        cases = generate_corpus(args.seed, args.count)
    except EmptyCorpusError as exc:
        print(f"differential fuzz refused: {exc}", file=sys.stderr)
        return 2

    try:
        runner = locate_runner(args.root)
    except TypeScriptRunnerError as exc:
        print(f"differential fuzz cannot run: {exc}", file=sys.stderr)
        return 2

    with TemporaryDirectory(prefix="differential-fuzz-") as scratch:
        workspace = Path(args.keep) if args.keep else Path(scratch)
        workspace.mkdir(parents=True, exist_ok=True)
        corpus_path = workspace / "corpus.jsonl"
        results_path = workspace / "typescript.jsonl"

        written = write_corpus(cases, corpus_path)
        if written == 0:
            print("differential fuzz refused: the corpus is empty", file=sys.stderr)
            return 2

        try:
            records = read_corpus(corpus_path)
            python = engine_results(records)
            typescript = run_typescript(runner, corpus_path, results_path, node=args.node)
        except (EmptyCorpusError, TypeScriptRunnerError) as exc:
            print(f"differential fuzz cannot run: {exc}", file=sys.stderr)
            return 2

        kept = args.keep is not None

        def hash_with_typescript(
            batch: Sequence[dict[str, Any]], stem: str
        ) -> list[dict[str, Any]]:
            probe_corpus = workspace / f"{stem}.jsonl"
            probe_results = workspace / f"{stem}-typescript.jsonl"
            write_corpus(batch, probe_corpus)
            return run_typescript(runner, probe_corpus, probe_results, node=args.node)

        # Purity BEFORE comparison, and fatal on its own. An engine whose answer depends on
        # the rest of the batch makes every other verdict in this run unattributable: the
        # comparator cannot tell a real divergence from an artifact, and the shrinker -- which
        # re-runs candidates in a DIFFERENT batch -- minimizes towards the artifact and then
        # reports a case the engines agree on. That is exactly what happened before
        # `packages/typescript/src/json.ts` stopped delegating to `JSON.parse`.
        try:
            impurities = check_purity(
                records, typescript, hash_with_typescript, sample=args.purity_sample
            )
        except TypeScriptRunnerError as exc:
            print(f"differential fuzz cannot run: {exc}", file=sys.stderr)
            return 2
        if impurities:
            print(
                _render_impurity(impurities, args.seed, args.count, workspace, kept),
                file=sys.stderr,
            )
            print(
                "differential fuzz FAILED: the TypeScript engine is not a pure function of "
                f"one case — {len(impurities)} of {written} cases changed result when only "
                f"the rest of the batch changed; seed={args.seed}",
                file=sys.stderr,
            )
            return 1

        mismatches = compare(python, typescript)
        if not mismatches:
            tally = _tally(cases, python)
            for line in _render_tally(tally):
                print(line)
            agreed = sum(1 for result in python if result["ok"])
            refused = written - agreed
            # Both arms of the differential must have been exercised. A run in which every
            # case raised would compare error class names and never once compare bytes, and
            # a run in which none raised would never test that the two engines refuse the
            # same inputs. Either shape is a green run that measured half the contract.
            if agreed == 0 or refused == 0:
                print(
                    f"differential fuzz refused: {agreed} cases produced canonical bytes and "
                    f"{refused} were refused; a run that never compares bytes, or never "
                    "compares a refusal, exercises only half the contract",
                    file=sys.stderr,
                )
                return 2
            print(
                f"differential fuzz passed: {written} cases across {len(tally)} categories "
                f"({agreed} byte-identical, {refused} refused identically), seed={args.seed}"
            )
            return 0

        by_id = {case["case_id"]: case for case in cases}
        first = mismatches[0]
        failing = by_id.get(first.case_id)
        if failing is None:
            print(
                f"differential fuzz FAILED: {first.reason} for {first.case_id} (seed={args.seed})",
                file=sys.stderr,
            )
            return 1

        def rerun(case: dict[str, Any], stem: str) -> tuple[Any, Any, bool]:
            """Re-hash one case in both engines. Returns the two outcomes and whether they
            still disagree, so the report can never claim a minimal instance the engines
            actually agree on."""
            probe_corpus = workspace / f"{stem}.jsonl"
            probe_results = workspace / f"{stem}-typescript.jsonl"
            write_corpus([case], probe_corpus)
            probe_python = engine_results(read_corpus(probe_corpus))[0]
            try:
                probe_ts = run_typescript(runner, probe_corpus, probe_results, node=args.node)[0]
            except TypeScriptRunnerError, IndexError:  # pragma: no cover - diagnostics only
                return probe_python, {"error": "the TypeScript runner produced no result"}, True
            return probe_python, probe_ts, bool(compare([probe_python], [probe_ts]))

        # Whether the instance about to be reported is still the one the BATCH ran, which is
        # what makes the batch-time outcome admissible as evidence for it. A shrunk instance
        # is a different value and the batch never saw it.
        reported_is_the_generated_case = True

        if not args.no_shrink:

            def evaluate(batch: Sequence[dict[str, Any]]) -> list[bool]:
                probe_corpus = workspace / "shrink-corpus.jsonl"
                probe_results = workspace / "shrink-typescript.jsonl"
                write_corpus(batch, probe_corpus)
                probe_records = read_corpus(probe_corpus)
                probe_python = engine_results(probe_records)
                try:
                    probe_ts = run_typescript(runner, probe_corpus, probe_results, node=args.node)
                except TypeScriptRunnerError:
                    return [False] * len(batch)
                failed = {mismatch.case_id for mismatch in compare(probe_python, probe_ts)}
                return [candidate["case_id"] in failed for candidate in batch]

            minimized = shrink(failing, evaluate)
            _, _, still_disagrees = rerun(minimized, "minimal-probe")
            reported_is_the_generated_case = not still_disagrees
            # A shrinker is a gate too, and it is the one gate here whose failure LOOKS like
            # a report. If the minimized instance no longer separates the engines, the raw
            # generated case is reported instead of a comfortable-looking lie.
            if still_disagrees:
                failing = minimized
            else:
                print(
                    "differential fuzz: shrinking produced an instance the engines agree on; "
                    "reporting the raw generated case instead",
                    file=sys.stderr,
                )

        minimal_python, minimal_ts, reproduced = rerun(failing, "minimal")

        # The isolated re-run is only evidence when it reproduces. When it does not, the
        # batch-time outcome is the evidence and the report must say which is which -- two
        # identical digests printed under "the two canonical engines disagree" is a report
        # that contradicts its own heading and sends triage to a case that is fine.
        batch_python: Any = None
        batch_typescript: Any = None
        if reported_is_the_generated_case:
            batch_python = next(
                (result for result in python if result["case_id"] == first.case_id), first.python
            )
            batch_typescript = next(
                (result for result in typescript if result["case_id"] == first.case_id),
                first.typescript,
            )
        print(
            _render(
                failing,
                minimal_python,
                minimal_ts,
                args.seed,
                args.count,
                reproduced_in_isolation=reproduced,
                batch_python=batch_python,
                batch_typescript=batch_typescript,
                workspace=workspace,
                kept=kept,
            ),
            file=sys.stderr,
        )
        if reproduced:
            print(
                f"differential fuzz FAILED: {len(mismatches)} of {written} cases disagree "
                f"(first: {first.reason}); seed={args.seed}",
                file=sys.stderr,
            )
        else:
            print(
                f"differential fuzz FAILED: {len(mismatches)} of {written} cases disagree "
                f"(first: {first.reason}); the reported case AGREES when re-run alone, so the "
                "evidence is the batch-time outcome above, NOT the isolated re-run; "
                f"seed={args.seed}",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

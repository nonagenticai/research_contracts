"""Released cross-field rules that JSON Schema 2020-12 cannot express, and the combined
validation entry point that always evaluates them.

JSON Schema has no way to compare two instance locations, so the half-open non-empty
interval rule (document 16 section 3.4), the receipt ownership/tenant equalities
(section 4.2) and the hash-manifest uniqueness/disjointness rules (section 4.3) are
declared in the schema as ``x-datacompany-cross-field`` and evaluated here. The rules stay
schema-driven: this module contains no hardcoded field names.

``validate_instance`` and ``assert_valid_instance`` are the released way to validate a
canonical instance. They pair the JSON Schema layer with these rules, so a consumer doing
the obvious thing cannot silently miss an interval or equality invariant. The bare schema
layer is still reachable as ``validate_schema_only`` for the places that need it.
"""

from __future__ import annotations

import datetime as dt
import re
from functools import cache
from typing import Any, Literal

from .errors import (
    CrossFieldError,
    SchemaValidationError,
    UnstableFloatError,
    UnsupportedTypeError,
)
from .jcs import canonicalize
from .registry import ecma_262_pattern, resolve_pointer, resolve_ref, validate_schema_only
from .rendering import json_text, json_type

__all__ = [
    "assert_valid_instance",
    "check_cross_field_rules",
    "collect_cross_field_rule_sites",
    "collect_cross_field_rules",
    "validate_instance",
]

_MISSING = object()

#: The propositions a cross-field rule can fail to DECIDE, as opposed to fail. Named as a
#: type so a fourth spelling is a type error in both languages rather than a silent third
#: wording of one message.
_Undecidable = Literal["equality", "uniqueness", "disjointness"]

#: The released ``rfc3339_utc_z`` timestamp representation: a UTC instant with the trailing
#: ``Z`` and optional fractional seconds of arbitrary precision. Anchored with ``\Z`` rather
#: than ``$`` because Python's ``$`` also matches before a trailing newline.
_RFC3339_UTC_Z = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z\Z")

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def _identity_marker(value: Any) -> bytes:
    """Return the language-neutral identity of a JSON value.

    RFC 8785 canonical bytes, exactly as ``hash_view`` already uses for the structurally
    identical job of ordering a set-like array. ``repr`` cannot do this job: it is Python
    source syntax that no other language reproduces, and it is dict-insertion-order
    dependent, so ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` -- the same JSON value --
    produced two different markers and were not detected as duplicates.

    ``allow_binary_float`` is on because this is an identity marker, not a hashed input: a
    binary float in an instance must not turn a validation call that returns a list of
    failures into a raised ``UnstableFloatError``. The hash path still rejects it.
    """
    return canonicalize(value, allow_binary_float=True)


def _equal(left: Any, right: Any) -> bool:
    """Return whether two JSON values are the SAME VALUE, language-neutrally.

    ``==`` cannot do this job, for the same reason ``repr`` could not do
    :func:`_identity_marker`'s: it is a Python answer to a question the contract asks about
    JSON. Python's ``bool`` IS an ``int``, so ``True == 1`` and ``0 == False`` are both true
    and the released ``equal`` rule reported ``{"left": true, "right": 1}`` as HOLDING -- two
    different JSON values, one of them a boolean and one a number, declared equal by a
    coercion no other language performs. A port using JavaScript ``===`` rejects that pair;
    one using ``==`` accepts ``"1" == 1``, which Python rejects. Three languages, three
    answers, one released rule.

    RFC 8785 canonical bytes is the comparator the rest of this module already uses --
    ``unique_by``, ``disjoint`` and the rule-dedup marker were all moved to it by D1 -- and
    ``EXTENSIONS.md`` §4.2 already prescribes it: *"A second implementation MUST use RFC 8785
    canonical-byte equality."* The engine simply did not implement what the document
    prescribed, which is the same shape as §7.5's closure: an unimplemented check is not an
    undecided question. The TypeScript port had ALREADY moved (``identityMarker`` in
    ``evaluateAt``), so until this function existed the two engines answered ``equal``
    differently on ``true``/``1`` and ``0``/``false`` -- a live cross-language split, not a
    hypothetical one.

    Measured over the whole corpus before the change: 40 present operand pairs across the
    three released ``equal``/``equal_when_both_present`` sites, ZERO of which the two
    comparators disagree about, under a positive control that does disagree on
    ``true``/``1`` and ``0``/``false``.

    Only ever called on operands :func:`_uncomparable` has already cleared, so it cannot
    raise. That ordering is load-bearing; see :func:`_uncomparable`.
    """
    return _identity_marker(left) == _identity_marker(right)


def _comparable(value: Any) -> bool:
    """Whether ``value`` has RFC 8785 canonical bytes at all.

    ``allow_binary_float=True`` is NOT a blanket permit and reading it as one is what made
    the first version of this closure a regression. It admits a finite non-integral float;
    it does nothing for an ``int`` outside the exact IEEE-754 double range, for ``NaN`` and
    ``±inf``, or for a lone surrogate, all of which still raise -- and all four arrive
    through stdlib ``json.loads`` on its DEFAULT settings, so they are reachable input and
    not exotica.
    """
    try:
        _identity_marker(value)
    except UnstableFloatError, UnsupportedTypeError:
        return False
    return True


def _uncomparable(
    name: str, operands: tuple[tuple[str, Any], ...], role: _Undecidable
) -> list[str]:
    """Failures for the operands that have no canonical bytes, so no equality to decide.

    This exists because the first version of the §4.2 closure turned a documented
    RETURN into a RAISE. ``validate_instance`` deliberately concatenates the schema layer
    and the cross-field layer rather than short-circuiting, precisely so a caller gets every
    failure of a malformed instance at once -- and malformed input was exactly the input that
    began throwing. Measured: ``{"evidence_location_id": 9007199254740993, "entity_id":
    9007199254740993}`` against ``evidence-location-version:1`` returned 16 failures before
    and raised ``UnstableFloatError`` after. :func:`_identity_marker`'s own docstring states
    the invariant that broke -- *a binary float in an instance must not turn a validation call
    that returns a list of failures into a raised* ``UnstableFloatError`` -- and routing
    ``equal`` through it extended an exposure that had previously needed an ARRAY to reach.

    The answer is not "call them unequal". A value with no canonical bytes is a value this
    contract cannot compare, which is a DIFFERENT fact from "these two differ", and §4.1
    already decided the identical question for the identical reason: an interval bound that
    is not a released instant is *a recorded failure, never a comparison*. So this reports
    the offending operand by pointer, left before right, and the equality verdict is not
    reached at all.

    The message names no VALUE, and that is deliberate rather than terse. The two engines'
    exception text for the same input differs already (``nan`` here, ``NaN`` in the port), and
    rendering the value would import the wider ``repr``-versus-canonical divergence this
    module is still carrying. Pointers are byte-identical in both languages.

    ``role`` names the proposition that cannot be decided, exactly as
    :func:`_missing_member_key`'s does. It is the reason ``unique_by`` and ``disjoint`` share
    this helper rather than growing a second spelling: both had the SAME defect for the same
    reason -- an unguarded :func:`_identity_marker` on a member key -- and the first version of
    this closure fixed only ``equal`` and recorded the other two as pre-existing residue. That
    was half a fix. Fixing ``disjoint`` alone would have re-opened the §4.4/§4.5 asymmetry
    §4.5 was closed to remove; fixing BOTH preserves the symmetry and closes the class, which
    is the argument for going further rather than for stopping.

    Measured before extending, so that no committed fixture's asserted text could move:
    10835 evaluations of the five released ``unique_by``/``disjoint`` sites over every JSON
    object in the corpus, ZERO of which raise today -- under a positive control confirming a
    lone surrogate in a member key DOES raise. Every failure this adds is therefore on an
    input that previously crashed, never on one that previously reported.
    """
    return [
        _uncomparable_text(name, pointer, role)
        for pointer, value in operands
        if not _comparable(value)
    ]


def _uncomparable_text(name: str, pointer: str, role: _Undecidable) -> str:
    """The one place the uncomparable-operand message is spelled, in either language."""
    return (
        f"{name}: {pointer} is not a value RFC 8785 can canonicalize, so the {role} "
        "cannot be decided"
    )


def _instant(value: Any) -> tuple[int, str] | None:
    """Return a comparable instant for a released timestamp, or ``None`` if it is not one.

    The result is ``(seconds since the epoch, fractional digits)``. The fraction keeps every
    digit it was given and is compared as a trailing-zero-stripped digit string, which for
    such strings orders identically to the numeric fraction. Neither half is a binary float,
    so no precision is lost and a port to another language reproduces it exactly -- whereas
    rounding to a fixed number of decimals would make two distinct high-precision instants
    compare equal and let an inverted interval through.
    """
    if not isinstance(value, str):
        return None
    match = _RFC3339_UTC_Z.fullmatch(value)
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    try:
        moment = dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.UTC)
    except ValueError:
        return None  # A syntactically well-formed but non-existent date, e.g. month 13.
    seconds = (moment - _EPOCH) // dt.timedelta(seconds=1)
    return seconds, (match.group(7) or "").rstrip("0")


_APPLICATOR_BRANCHES = ("allOf", "anyOf", "oneOf", "then", "else")

#: Keywords whose subschemas apply to a *child* of the current instance location, at a
#: location this engine can derive from the schema plus the instance. A rule reached through
#: one of these is evaluable only if it opts in with ``"scope": "relative"`` (D3, option B);
#: an absolute-scoped rule found here is still a hard failure, never a skip.
#: ``$defs`` is deliberately NOT here: it is a definitions bag with no instance location of
#: its own, so a rule inside one only matters where that def is actually ``$ref``-composed.
_CHILD_MAP_KEYWORDS = ("properties", "patternProperties")
_CHILD_SCHEMA_KEYWORDS = ("items", "additionalProperties")
_CHILD_LIST_KEYWORDS = ("prefixItems",)

#: Keywords with no single well-defined instance location, so ``scope: relative`` cannot
#: rescue them either: ``contains`` applies to *some* unidentified element,
#: ``propertyNames`` applies to a property NAME string rather than to a value, and
#: ``contentSchema`` applies to the DECODED contents of a string -- a document that is not
#: part of this instance at all. A rule under one of these is unevaluable at any scope and
#: fails closed.
_UNLOCATABLE_KEYWORDS = ("contains", "propertyNames", "contentSchema")

#: Members that are not 2020-12 keywords, so a 2020-12 validator reads no subschema there and
#: applies nothing. A rule under one is dropped by the SPEC, not merely by this collector, and
#: dropped in silence twice over -- which is why it fails closed rather than being ignored as
#: an unknown member. See :data:`_BLOCKED_KEYWORD_REASON` for each one's justification.
#: ``definitions`` is deliberately NOT here; see :data:`_DEFINITION_BAG_KEYWORDS`.
_LEGACY_SCHEMA_KEYWORDS = ("additionalItems",)

#: Applicators this collector does not descend into, whose subschema takes ONE schema.
#: ``dependentSchemas`` takes a map and is handled beside them.
#:
#: A rule declared under any of these used to be dropped in SILENCE: the collector simply
#: never visited the node, so ``check_cross_field_rules`` reported no failures at all while
#: the schema read as enforced. That is the vacuity class this repository keeps finding, and
#: it is strictly worse than either alternative, because it is invisible. Failing closed
#: turns it into an authoring error that names itself.
#:
#: ``not`` and ``dependentSchemas`` are genuinely in-place applicators and COULD be collected
#: branches; ``if`` is evaluated in place too, and ``unevaluatedProperties``/
#: ``unevaluatedItems`` address child locations that depend on annotation results this engine
#: does not compute. Adding any of them to :data:`_APPLICATOR_BRANCHES` (or to the
#: child-keyword walk) is a behaviour EXPANSION -- it would start evaluating rules that are
#: not evaluated today -- and needs a decision. Failing closed is the conservative, reversible
#: half of that decision, and it costs nothing today: no released schema declares a rule under
#: any of the five (``tests/test_cross_field_uncollected_keywords.py`` recomputes that from
#: the corpus rather than asserting it).
#:
#: ``unevaluatedItems`` was MISSING from this tuple until it was added here, while its direct
#: sibling in the same ``unevaluated`` vocabulary was present. It shares the justification
#: word for word, and the omission was the silent drop this whole family exists to eliminate:
#: a rule under it collected zero sites, reported zero failures against an instance the same
#: rule flags under ``allOf``, and raised nothing, so the schema read as enforced. Nothing
#: released was affected -- ``unevaluatedItems`` appears nowhere in the repository -- which is
#: recomputed rather than asserted by the sweep in the test module named above.
_UNCOLLECTED_SCHEMA_KEYWORDS = ("if", "not", "unevaluatedProperties", "unevaluatedItems")
_UNCOLLECTED_MAP_KEYWORDS = ("dependentSchemas",)

#: Members that hold a BAG of subschemas at no instance location: 2020-12's ``$defs`` and the
#: pre-2020 ``definitions`` that a ``$ref`` can still target as a plain JSON Pointer.
#:
#: These are deliberately NOT blocked, and the reason is structural rather than a judgement
#: call: a subschema in a bag is not *applied* anywhere until something ``$ref``s it, and
#: where something does, this collector reaches the rule through that ``$ref`` with no
#: keyword blocking it. Blocking the bag would make a rule inside a ``$def`` raise even when
#: it IS composed, because the walk reaches the same node by both routes -- so a reusable
#: subschema carrying a rule would become undeclarable. An UNREFERENCED bag entry is not a
#: dropped constraint either: JSON Schema applies nothing there for exactly the same reason,
#: so there is no enforcement to lose. That is a different situation from an applicator, whose
#: subschema IS applied at an instance location while its rule vanishes.
#:
#: The residual exposure is an unreferenced bag entry whose rule an author believes is live.
#: It is bounded by measurement, not by argument: every ``$defs`` entry at any depth is swept
#: as its own root by ``tests/test_cross_field_uncollected_keywords.py``, so a malformed or
#: misplaced rule in one is red there, and the same module recomputes that no released schema
#: uses ``definitions`` at all.
_DEFINITION_BAG_KEYWORDS = ("$defs", "definitions")

#: 2020-12 core applicators this collector resolves (``$ref``) and does not (``$dynamicRef``).
#: ``$dynamicRef`` cannot be resolved statically -- its target depends on the dynamic scope of
#: the validation that reaches it -- so a rule at a dynamic target would be unreachable here.
#: It is not blocked because its VALUE is a URI string, not a subschema, so there is no node
#: to fail closed at; the exposure is instead pinned by measurement, as above: no released
#: schema uses ``$dynamicRef`` or ``$dynamicAnchor``, and the sweep is red the day one does.
_REFERENCE_KEYWORDS = ("$ref",)
_UNRESOLVED_REFERENCE_KEYWORDS = ("$dynamicRef",)

_UNCOLLECTED_REASON = (
    "an applicator this engine does not collect cross-field rules from. A rule declared "
    "there is silently dropped -- it reports no failure against any instance while the "
    "schema reads as enforced -- so it fails closed instead. Declare the rule at the root "
    "of the composed schema, or under one of "
    f"{'/'.join(_APPLICATOR_BRANCHES)}, which this engine collects."
)

#: Why each blocked keyword blocks, keyed by the keyword itself so the diagnostic names it.
_BLOCKED_KEYWORD_REASON: dict[str, str] = {
    "contains": (
        "a keyword with no single instance location -- it applies to some unidentified "
        "element -- so no rule scope can evaluate it."
    ),
    "propertyNames": (
        "a keyword with no single instance location -- it applies to a property NAME string "
        "rather than to a value -- so no rule scope can evaluate it."
    ),
    "contentSchema": (
        "a keyword with no single instance location -- it applies to the DECODED contents of "
        "a string, a document this instance does not contain and this engine never "
        "materialises -- so no rule scope can evaluate it. 2020-12's content vocabulary is "
        "annotation-only besides, so a validator asserts nothing there either."
    ),
    "additionalItems": (
        "not a 2020-12 keyword at all. 2019-09 used it for the elements past a tuple; 2020-12 "
        "replaced that pairing with prefixItems plus items, and a 2020-12 validator reads no "
        "subschema here, so the rule is dropped by the specification and not merely by this "
        "engine. Move it under items."
    ),
    "items": (
        "an ARRAY-valued 'items', which is the 2019-09 tuple form. 2020-12 requires 'items' "
        "to be a single schema and spells the tuple as prefixItems, so a 2020-12 validator "
        "reads no subschema in this array and the rule is dropped by the specification. Move "
        "it under prefixItems."
    ),
    **dict.fromkeys(
        (*_UNCOLLECTED_SCHEMA_KEYWORDS, *_UNCOLLECTED_MAP_KEYWORDS), _UNCOLLECTED_REASON
    ),
}

#: The released rule scopes. ``absolute`` is the default and the meaning every rule released
#: before D3 carries: operands resolve against the instance root. ``relative`` resolves them
#: against the location the rule was reached at, which at a document root is the same thing.
_SCOPE_ABSOLUTE = "absolute"
_SCOPE_RELATIVE = "relative"


#: RFC 6901 section 4: ``array-index = %x30 / ( %x31-39 *(%x30-39) )``. Exactly ``0``, or a
#: non-zero digit followed by ASCII digits. Nothing else is an array index.
#:
#: This used to be ``int(token)``, which is a much wider grammar than RFC 6901 and a wider
#: one than any other language's: ``int`` accepts a sign, surrounding whitespace, PEP 515
#: underscores and EVERY Unicode decimal digit, so ``"+0"``, ``" 0"``, ``"0_0"`` and the
#: Arabic-Indic zero U+0660 all resolved to element 0 in Python while the TypeScript port's
#: ``/^-?\d+$/u`` rejected all four -- one engine reporting a rule as HOLDING where the other
#: reported it as VIOLATED, on the same instance and the same released rule. Both engines now
#: implement the RFC grammar, which is narrower than either previous behaviour: it also
#: rejects leading zeros (``"00"``) and the negative indices the port used to wrap around,
#: neither of which RFC 6901 admits and neither of which any released rule uses.
_ARRAY_INDEX = re.compile(r"0|[1-9][0-9]*")


def _at(instance: Any, pointer: str) -> Any:
    node = instance
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return _MISSING
            node = node[token]
        elif isinstance(node, list):
            if _ARRAY_INDEX.fullmatch(token) is None:
                return _MISSING
            index = int(token)
            if index >= len(node):
                return _MISSING
            node = node[index]
        else:
            return _MISSING
    return node


def _member_key(member: Any, key_pointer: str | None) -> Any:
    """Return the comparison value of a collection member under an optional key pointer."""
    return member if key_pointer is None else _at(member, key_pointer)


#: One derivable step from a parent instance location to the child locations a subschema
#: applies at. A step is a *plan*, not a location: ``("items", 0)`` names every element of
#: whatever array is found there, so a step expands against a real instance to zero, one or
#: many concrete pointers.
_Step = tuple[Any, ...]


def _escape(token: str) -> str:
    """Encode a raw member name as an RFC 6901 reference token."""
    return token.replace("~", "~0").replace("/", "~1")


def _locations(instance: Any, steps: tuple[_Step, ...]) -> list[str]:
    """Expand a collected step plan into the concrete instance pointers it addresses.

    A step that addresses nothing in *this* instance contributes no location, so the rule is
    simply not evaluated there -- which is the same thing JSON Schema does with the subschema
    the rule was declared under. An absent ``properties`` member means the subschema never
    applied, so there is no location at which the rule could have an opinion; that is not the
    fail-open case the interval and uniqueness rules guard against, where the rule DOES apply
    and its named target is missing.
    """
    bases = [""]
    for step in steps:
        move = step[0]
        nxt: list[str] = []
        for base in bases:
            node = instance if base == "" else _at(instance, base)
            if node is _MISSING:
                continue
            if move == "key":
                if isinstance(node, dict) and step[1] in node:
                    nxt.append(f"{base}/{_escape(step[1])}")
            elif move == "index":
                if isinstance(node, list) and step[1] < len(node):
                    nxt.append(f"{base}/{step[1]}")
            elif move == "items":
                if isinstance(node, list):
                    nxt.extend(f"{base}/{index}" for index in range(step[1], len(node)))
            elif move == "pattern":
                if isinstance(node, dict):
                    matches = ecma_262_pattern(step[1])
                    nxt.extend(f"{base}/{_escape(k)}" for k in node if matches.search(k))
            elif move == "additional":
                if isinstance(node, dict):
                    named, patterns = step[1], step[2]
                    compiled = [ecma_262_pattern(p) for p in patterns]
                    nxt.extend(
                        f"{base}/{_escape(k)}"
                        for k in node
                        if k not in named and not any(rx.search(k) for rx in compiled)
                    )
        bases = nxt
        if not bases:
            break
    return bases


#: The operands each operator indexes directly, as required/optional member names. This is
#: the executable half of the same contract ``schemas/meta`` states declaratively;
#: ``tests/test_extension_vocabulary.py`` asserts the two agree in both directions, so the
#: table cannot drift away from the meta-schema without a red test.
_OPERANDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "half_open_interval": (frozenset({"from", "to"}), frozenset()),
    "equal": (frozenset({"left", "right"}), frozenset()),
    "equal_when_both_present": (frozenset({"left", "right"}), frozenset()),
    "unique_by": (frozenset({"at"}), frozenset({"key"})),
    "disjoint": (frozenset({"left", "right"}), frozenset({"left_key", "right_key"})),
}

#: Members every rule may carry regardless of operator.
_COMMON_MEMBERS = frozenset({"rule", "name", "scope", "$comment"})

#: The lexical form of an operand pointer, mirroring the meta-schema's ``instance_pointer``.
_POINTER = re.compile(r"(/([^/~]|~[01])*)+\Z")


def _declared_rules(schema: dict[str, Any], schema_ref: str) -> list[dict[str, Any]]:
    """Return a node's declared rules, refusing any declaration that is not well formed.

    Before this existed, neither engine validated the ANNOTATIONS themselves, and the two
    languages failed *differently* on every malformed shape: a bare string was iterated
    character by character into an ``AttributeError`` in Python and silently produced NO
    RULES in TypeScript, a missing operand raised ``KeyError`` out of the failure-collection
    path, and an empty array was a no-op indistinguishable from a rule deleted by mistake.
    A silent no-op on a *rule declaration* is the vacuity class this repository keeps
    finding: the contract reads as enforced and enforces nothing.

    This is not new normative semantics. ``schemas/meta/datacompany-extension-vocabulary.v1``
    already rejects every shape below, and does so under a falsification-proven gate; what
    was missing was the engines consulting it. The checks are re-stated here rather than run
    through a JSON Schema validator so that the TypeScript port can reproduce them without
    shipping one, and ``tests/test_extension_vocabulary.py`` asserts the two agree.
    """
    declared = schema.get("x-datacompany-cross-field")
    if declared is None:
        return []
    where = f"{schema_ref}: x-datacompany-cross-field"
    if not isinstance(declared, list):
        raise CrossFieldError(
            f"{where} must be an array of rule objects, not a JSON {json_type(declared)}. A "
            "non-array declaration is not a rule this engine can evaluate."
        )
    if not declared:
        raise CrossFieldError(
            f"{where} is empty. An empty rule list is indistinguishable from a rule deleted "
            "by mistake, so it is rejected rather than treated as 'no rules'."
        )
    for index, rule in enumerate(declared):
        _validate_rule(rule, f"{where}/{index}")
    return declared


def _validate_rule(rule: Any, where: str) -> None:
    """Raise ``CrossFieldError`` unless ``rule`` is a well-formed rule object."""
    if not isinstance(rule, dict):
        raise CrossFieldError(f"{where} is not a rule object, but a JSON {json_type(rule)}.")
    kind = rule.get("rule")
    if kind not in _OPERANDS:
        raise CrossFieldError(
            f"{where} declares rule {json_text(kind)}, which is not a released cross-field "
            f"operator ({', '.join(sorted(_OPERANDS))})."
        )
    scope = rule.get("scope", _SCOPE_ABSOLUTE)
    if scope not in (_SCOPE_ABSOLUTE, _SCOPE_RELATIVE):
        raise CrossFieldError(
            f"{where} declares scope {json_text(scope)}; the released scopes are "
            f"{json_text(_SCOPE_ABSOLUTE)} and {json_text(_SCOPE_RELATIVE)}."
        )
    name = rule.get("name")
    if "name" in rule and (not isinstance(name, str) or not name):
        raise CrossFieldError(f"{where} declares a name that is not a non-empty string.")
    required, optional = _OPERANDS[kind]
    missing = sorted(required - rule.keys())
    if missing:
        raise CrossFieldError(
            f"{where} is a {json_text(kind)} rule missing the operand(s) "
            f"{', '.join(missing)}, which the evaluator indexes directly."
        )
    unknown = sorted(rule.keys() - _COMMON_MEMBERS - required - optional)
    if unknown:
        raise CrossFieldError(
            f"{where} carries {', '.join(unknown)}, which {json_text(kind)} does not read. "
            "An operand belonging to a different operator is silently ignored, so it is "
            "rejected here."
        )
    for member in sorted(required | (optional & rule.keys())):
        operand = rule.get(member)
        if not isinstance(operand, str) or len(operand) < 2 or not _POINTER.fullmatch(operand):
            raise CrossFieldError(
                f"{where} operand {member}={json_text(operand)} is not an RFC 6901 pointer "
                "of the released form (a non-empty sequence of '/'-prefixed reference "
                "tokens)."
            )


@cache
def _collect(schema_ref: str) -> tuple[tuple[dict[str, Any], tuple[_Step, ...]], ...]:
    sites: list[tuple[dict[str, Any], tuple[_Step, ...]]] = []
    seen: set[tuple[bytes, tuple[_Step, ...]]] = set()

    def walk(
        schema: Any,
        refs: frozenset[str],
        base_id: str,
        steps: tuple[_Step, ...],
        *,
        blocked: str | None,
    ) -> None:
        if not isinstance(schema, dict):
            return
        base_id = schema.get("$id", base_id)
        for rule in _declared_rules(schema, schema_ref):
            scope = rule.get("scope", _SCOPE_ABSOLUTE)
            label = rule.get("name", rule.get("rule"))
            if blocked is not None:
                raise CrossFieldError(
                    f"{schema_ref}: released cross-field rule {label!r} is declared under "
                    f"{blocked!r}, {_BLOCKED_KEYWORD_REASON[blocked]}"
                )
            if steps and scope != _SCOPE_RELATIVE:
                raise CrossFieldError(
                    f"{schema_ref}: released cross-field rule "
                    f"{label!r} is declared below a child "
                    "keyword, but released rule pointers are instance-root-absolute, so "
                    "this engine cannot evaluate it. Declare the rule at the root of the "
                    "composed schema with absolute pointers instead, or declare it "
                    '"scope": "relative" to resolve its operands against the location it '
                    "is reached at."
                )
            marker = (_identity_marker(rule), steps)
            if marker not in seen:
                seen.add(marker)
                sites.append((rule, steps))
        ref = schema.get("$ref")
        if isinstance(ref, str):
            target, target_base = resolve_ref(ref, base_id)
            absolute = f"{target_base}{ref}" if ref.startswith("#") else ref
            if absolute not in refs:
                walk(target, refs | {absolute}, target_base, steps, blocked=blocked)
        for branch in _APPLICATOR_BRANCHES:
            node = schema.get(branch)
            if isinstance(node, list):
                for subschema in node:
                    walk(subschema, refs, base_id, steps, blocked=blocked)
            elif isinstance(node, dict):
                walk(node, refs, base_id, steps, blocked=blocked)

        # Each child keyword below moves the instance location, so it extends the step plan.
        named = schema.get("properties")
        if isinstance(named, dict):
            for member, subschema in named.items():
                walk(subschema, refs, base_id, (*steps, ("key", member)), blocked=blocked)
        patterned = schema.get("patternProperties")
        if isinstance(patterned, dict):
            for pattern, subschema in patterned.items():
                walk(subschema, refs, base_id, (*steps, ("pattern", pattern)), blocked=blocked)
        prefix = schema.get("prefixItems")
        if isinstance(prefix, list):
            for index, subschema in enumerate(prefix):
                walk(subschema, refs, base_id, (*steps, ("index", index)), blocked=blocked)
        rest = schema.get("items")
        if isinstance(rest, dict):
            start = len(prefix) if isinstance(prefix, list) else 0
            walk(rest, refs, base_id, (*steps, ("items", start)), blocked=blocked)
        elif isinstance(rest, list):
            # The 2019-09 tuple form. A 2020-12 validator applies nothing here, so a rule
            # inside is dropped by the specification; blocked rather than ignored.
            for subschema in rest:
                walk(subschema, refs, base_id, steps, blocked=blocked or "items")
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            step: _Step = (
                "additional",
                tuple(named) if isinstance(named, dict) else (),
                tuple(patterned) if isinstance(patterned, dict) else (),
            )
            walk(extra, refs, base_id, (*steps, step), blocked=blocked)
        # Every keyword below blocks the rules beneath it. The outermost blocking keyword
        # wins, so the diagnostic names the one an author would have to move the rule out of
        # first rather than an inner keyword they never wrote.
        for keyword in (
            *_UNLOCATABLE_KEYWORDS,
            *_LEGACY_SCHEMA_KEYWORDS,
            *_UNCOLLECTED_SCHEMA_KEYWORDS,
        ):
            node = schema.get(keyword)
            if isinstance(node, dict):
                walk(node, refs, base_id, steps, blocked=blocked or keyword)
        for keyword in _UNCOLLECTED_MAP_KEYWORDS:
            node = schema.get(keyword)
            if isinstance(node, dict):
                for subschema in node.values():
                    walk(subschema, refs, base_id, steps, blocked=blocked or keyword)

    base, _, _ = schema_ref.partition("#")
    walk(resolve_pointer(schema_ref), frozenset({schema_ref}), base, (), blocked=None)
    return tuple(sites)


def collect_cross_field_rule_sites(schema_ref: str) -> list[tuple[dict[str, Any], tuple[Any, ...]]]:
    """Return every evaluable rule reachable from ``schema_ref``, paired with its step plan.

    A rule declared at the composed root carries an empty plan and is evaluated once against
    the instance root. A ``"scope": "relative"`` rule reached through a child keyword carries
    the plan that locates it, and is evaluated once per instance location that plan addresses
    -- once per array element under ``items``, once per matching member under
    ``patternProperties``, and so on.
    """
    return [(rule, steps) for rule, steps in _collect(schema_ref)]


def collect_cross_field_rules(schema_ref: str) -> list[dict[str, Any]]:
    """Collect every distinct evaluable ``x-datacompany-cross-field`` rule under ``schema_ref``.

    A rule's operand pointers are RFC 6901 pointers resolved against a base, and ``scope``
    chooses the base (D3, option B):

    * ``absolute`` -- the default, and the meaning of every rule released before D3 -- binds
      them to the *instance root*. Such a rule is only evaluable where it is reached without
      changing the instance location: at the composed root, through ``$ref``, and through the
      in-place applicators (``allOf``/``anyOf``/``oneOf``/``then``/``else``). Reached below a
      child keyword it would silently assert a proposition about the wrong object, so the
      collector raises ``CrossFieldError`` instead.
    * ``relative`` binds them to the location the rule was reached at. At a document root the
      two readings coincide, which is why adding ``scope`` left every released rule's meaning
      unchanged; below a child keyword the rule is evaluated once per addressed location.

    Neither reading is available under ``contains``, ``propertyNames`` or ``contentSchema``,
    which have no single instance location; a rule there fails closed at any scope. A rule
    under ``if``, ``not``, ``dependentSchemas``, ``unevaluatedProperties`` or
    ``unevaluatedItems`` fails closed too, for the different reason that this collector does
    not descend into them: it would otherwise be dropped in silence. A rule under
    ``additionalItems`` or an array-valued ``items`` fails closed for a third reason -- those
    are not 2020-12 keywords, so the specification itself applies nothing there. See
    :data:`_UNCOLLECTED_SCHEMA_KEYWORDS`, :data:`_UNLOCATABLE_KEYWORDS` and
    :data:`_LEGACY_SCHEMA_KEYWORDS`; ``$defs``/``definitions`` are the deliberate
    non-blocking case and are justified at :data:`_DEFINITION_BAG_KEYWORDS`.

    This returns the distinct rules. Use :func:`collect_cross_field_rule_sites` when the
    locations matter, and note that one rule reached at several locations is one entry here
    and several sites there.
    """
    distinct: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    for rule, _ in _collect(schema_ref):
        marker = _identity_marker(rule)
        if marker not in seen:
            seen.add(marker)
            distinct.append(rule)
    return distinct


def check_cross_field_rules(instance: Any, schema_ref: str) -> list[str]:
    """Return the failures of every released cross-field rule declared by ``schema_ref``."""
    failures: list[str] = []
    for rule, steps in _collect(schema_ref):
        for base in _locations(instance, steps):
            failures.extend(_evaluate(instance, rule, base))
    return failures


def _evaluate(instance: Any, rule: dict[str, Any], base: str) -> list[str]:
    """Evaluate one rule at one instance location.

    Every operand pointer is rendered into the failure text joined to ``base``, so a rule at
    the instance root (``base == ""``) produces exactly the text it produced before D3 --
    the released fixtures pin that text through ``expected_error_contains`` -- and the same
    rule at a nested location names the full absolute path it actually looked at, which is
    what makes N failures under ``items`` distinguishable from each other.
    """
    kind = rule.get("rule")
    name = rule.get("name", kind)
    if kind == "half_open_interval":
        return _check_half_open_interval(instance, rule, name, base)
    if kind == "equal":
        left_at, right_at = f"{base}{rule['left']}", f"{base}{rule['right']}"
        left, right = _at(instance, left_at), _at(instance, right_at)
        if left is _MISSING or right is _MISSING:
            return [f"{name}: {left_at} and {right_at} must both be present and equal"]
        uncomparable = _uncomparable(name, ((left_at, left), (right_at, right)), "equality")
        if uncomparable:
            return uncomparable
        if not _equal(left, right):
            return [f"{name}: {left_at} and {right_at} must both be present and equal"]
        return []
    if kind == "equal_when_both_present":
        left_at, right_at = f"{base}{rule['left']}", f"{base}{rule['right']}"
        left, right = _at(instance, left_at), _at(instance, right_at)
        if left is _MISSING or right is _MISSING:
            return []
        uncomparable = _uncomparable(name, ((left_at, left), (right_at, right)), "equality")
        if uncomparable:
            return uncomparable
        if not _equal(left, right):
            return [f"{name}: {left_at} and {right_at} must be equal when both present"]
        return []
    if kind == "unique_by":
        return _check_unique_by(instance, rule, name, base)
    if kind == "disjoint":
        return _check_disjoint(instance, rule, name, base)
    raise CrossFieldError(f"unknown released cross-field rule {json_text(kind)}")


def _check_half_open_interval(
    instance: Any, rule: dict[str, Any], name: str, base: str = ""
) -> list[str]:
    """``[from, to)`` must be non-empty, with an omitted ``to`` meaning positive infinity.

    Bounds are compared as parsed instants, never as raw strings. The released
    ``rfc3339_utc_z`` representation permits fractional seconds, and ``'.'`` (0x2E) sorts
    before ``'Z'`` (0x5A), so a lexicographic ``>`` rejected the valid interval
    ``[…T00:00:00Z, …T00:00:00.5Z)`` and *accepted* the inverted
    ``[…T00:00:00.5Z, …T00:00:00Z)``. On the flagship non-empty-interval invariant, that
    second half is a fail-open gate.

    A bound that is not a released timestamp is a recorded failure, never a comparison:
    ``end > start`` between a ``str`` and an ``int`` raised a ``TypeError`` that escaped the
    failure collector entirely, and comparing two arbitrary strings silently answered a
    question about instants with an answer about alphabetical order.
    """
    from_at, to_at = f"{base}{rule['from']}", f"{base}{rule['to']}"
    start = _at(instance, from_at)
    end = _at(instance, to_at)
    if start is _MISSING:
        return [f"{name}: {from_at} is required to bound the interval"]
    # Checked before the omitted-upper-bound shortcut: an explicit null lower bound is
    # invalid whether or not an upper bound happens to be present.
    if start is None:
        return [f"{name}: null is not a released encoding for an interval bound"]
    lower = _instant(start)
    if end is _MISSING:
        # An omitted upper bound means positive infinity, but the lower bound still has to
        # be a released instant for the interval to mean anything at all.
        return _unparseable(name, ((from_at, start, lower),))
    if end is None:
        return [f"{name}: null is not a released encoding for an interval bound"]

    upper = _instant(end)
    unparseable = _unparseable(name, ((from_at, start, lower), (to_at, end, upper)))
    if unparseable or lower is None or upper is None:
        return unparseable
    if upper <= lower:
        return [
            f"{name}: interval [{start}, {end}) is empty or inverted; a half-open "
            "interval must be non-empty"
        ]
    return []


def _unparseable(
    name: str, bounds: tuple[tuple[str, Any, tuple[int, str] | None], ...]
) -> list[str]:
    return [
        f"{name}: {pointer} is {value!r}, which is not a released rfc3339_utc_z instant, so "
        "the interval cannot be compared"
        for pointer, value, parsed in bounds
        if parsed is None
    ]


def _check_unique_by(instance: Any, rule: dict[str, Any], name: str, base: str = "") -> list[str]:
    """No two members of the array at ``at`` may share a value at the member key.

    ``uniqueItems`` cannot express this: two declarations for the same pointer that differ
    in any other member are distinct objects and pass it.
    """
    at = f"{base}{rule['at']}"
    members = _at(instance, at)
    if not isinstance(members, list):
        # Fail loudly. Returning [] here made a missing, null or non-list target read as
        # "the uniqueness rule holds", and check_cross_field_rules is a public,
        # schema-independent entry point, so nothing else was checking.
        return [_absent_target(name, at, members)]
    key_pointer = rule.get("key")
    seen: dict[bytes, int] = {}
    failures: list[str] = []
    for index, member in enumerate(members):
        value = _member_key(member, key_pointer)
        if value is _MISSING:
            failures.append(_missing_member_key(name, at, index, "uniqueness", key_pointer))
            continue
        if not _comparable(value):
            failures.append(_uncomparable_text(name, f"{at}/{index}", "uniqueness"))
            continue
        marker = _identity_marker(value)
        if marker in seen:
            failures.append(
                f"{name}: {at}/{seen[marker]} and {at}/{index} both declare "
                f"{value!r}; a pointer may be declared at most once"
            )
            continue
        seen[marker] = index
    return failures


def _missing_member_key(
    name: str,
    at: str,
    index: int,
    role: Literal["uniqueness", "disjointness"],
    key_pointer: str | None,
) -> str:
    """Name a member of a set-like array that does not carry the key the rule compares by.

    Shared by ``unique_by`` and ``disjoint`` so the two cannot drift apart again: they used
    to disagree about whether this is a fact worth reporting at all (§4.5), and the way that
    asymmetry survived was that each spelled its own answer in its own branch.

    ``role`` is the only thing that differs -- ``uniqueness`` or ``disjointness`` -- and it
    keeps ``unique_by``'s released message byte-identical to what it was. An earlier version
    of this docstring said committed fixtures pin that text through
    ``expected_error_contains``. They do NOT: 80 fixture files use ``expected_error_contains``
    and none of them contains ``does not carry the uniqueness key``. It was pinned by nothing
    at all until ``fixtures/canonical-cross-field/v1/operator-vectors.json`` existed, which is
    a reason to keep that vector rather than a reason to have been relaxed about the edit --
    and citing a pin that is not there as grounds for rejecting an alternative is exactly the
    class of claim this repository keeps having to re-measure.

    ``role`` is a ``Literal`` rather than a ``str`` so that a third role word is a type error
    in BOTH languages. The port's parameter is a union of the same two strings; leaving this
    side ``str`` meant ``ty`` could not see what ``tsc`` would.

    ``key_pointer`` is always a declared pointer STRING here and never ``None``: a member can
    only fail to carry a key that was named, because ``_member_key`` with no pointer returns
    the member itself and is never ``_MISSING``. It is still rendered through ``or ""`` rather
    than interpolated straight, and the port spells the same fallback ``?? ''``, because that
    is load-bearing for parity rather than cosmetic: a bare interpolation of the absent case
    is ``None`` in Python and ``undefined`` in the port, for the same failure of the same
    rule. A correctness property should not rest on an input being unreachable.
    """
    return f"{name}: {at}/{index} does not carry the {role} key {key_pointer or ''}"


def _absent_target(name: str, pointer: str, value: Any) -> str:
    rendered = "absent" if value is _MISSING else f"{value!r}"
    return (
        f"{name}: {pointer} is {rendered}, not an array, so the rule cannot be evaluated; a "
        "released cross-field rule names a location that must be there"
    )


def _check_disjoint(instance: Any, rule: dict[str, Any], name: str, base: str = "") -> list[str]:
    """The two named arrays may not share a value; each side may name a member key.

    A member that does not carry its side's declared key is a **reported failure**, exactly
    as in ``unique_by`` step 2, and this is the whole of what ``EXTENSIONS.md`` §4.5 recorded
    as open. It used to be a silent SKIP on both sides: a right member of ``{"nope": 1}``
    under ``right_key: "/p"`` produced no failure at all, so "the two sets are disjoint"
    could be true by vacuity, one member at a time -- while the structurally identical
    question in ``unique_by`` was answered loudly.

    Nothing normative had to be invented to pick a side. ``hash_view`` already decided the
    same question for the same shape of data, fail-closed, in released code: it raises
    ``MissingOrderKeyError`` because *every member of a set-like array must carry its whole
    released order key, and an absent key is not the same fact as a shared one*. Skipping in
    silence is the fail-open direction, and a set-membership test that silently drops the
    members it cannot read is not a set-membership test.

    A member whose key is missing contributes NO value to the comparison either -- it has
    none to contribute -- so the left set is built from the members that do carry the key,
    which is what it was before. The change is that the ones that do not are now named.

    Blast radius, measured before the change: 23 array pairs and 466 members over every
    committed fixture and released rule, ZERO of which lack their key; positive control 23/23
    (planting ``{"nope": 1}`` into a real corpus instance is seen).
    """
    left_at, right_at = f"{base}{rule['left']}", f"{base}{rule['right']}"
    left = _at(instance, left_at)
    right = _at(instance, right_at)
    # Same fail-open as unique_by: a missing or non-list side made "the two sets are
    # disjoint" true by vacuity rather than by evidence.
    absent = [
        _absent_target(name, pointer, value)
        for pointer, value in ((left_at, left), (right_at, right))
        if not isinstance(value, list)
    ]
    if absent:
        return absent
    failures: list[str] = []
    left_key, right_key = rule.get("left_key"), rule.get("right_key")
    left_values: set[bytes] = set()
    for index, member in enumerate(left):
        value = _member_key(member, left_key)
        if value is _MISSING:
            failures.append(_missing_member_key(name, left_at, index, "disjointness", left_key))
            continue
        if not _comparable(value):
            failures.append(_uncomparable_text(name, f"{left_at}/{index}", "disjointness"))
            continue
        left_values.add(_identity_marker(value))
    for index, member in enumerate(right):
        value = _member_key(member, right_key)
        if value is _MISSING:
            failures.append(_missing_member_key(name, right_at, index, "disjointness", right_key))
            continue
        if not _comparable(value):
            failures.append(_uncomparable_text(name, f"{right_at}/{index}", "disjointness"))
            continue
        if _identity_marker(value) in left_values:
            failures.append(
                f"{name}: {value!r} appears in both {left_at} and "
                f"{right_at}/{index}; the two sets must be disjoint"
            )
    return failures


def validate_instance(instance: Any, schema_ref: str) -> list[str]:
    """Return every released failure of ``instance`` against ``schema_ref``.

    This is the safe default and the one to reach for: it is the JSON Schema layer *plus*
    the released ``x-datacompany-cross-field`` rules that JSON Schema cannot express. Validating
    with the schema layer alone accepts objects the released contract rejects.
    """
    return validate_schema_only(instance, schema_ref) + check_cross_field_rules(
        instance, schema_ref
    )


def assert_valid_instance(instance: Any, schema_ref: str) -> None:
    """Raise on the first released failure of ``instance`` against ``schema_ref``.

    Schema failures raise ``SchemaValidationError`` and cross-field failures raise
    ``CrossFieldError``, so a caller can still tell the two layers apart.
    """
    errors = validate_schema_only(instance, schema_ref)
    if errors:
        raise SchemaValidationError(
            f"instance does not validate against {schema_ref}: " + "; ".join(errors)
        )
    failures = check_cross_field_rules(instance, schema_ref)
    if failures:
        raise CrossFieldError(
            f"instance violates released cross-field rules of {schema_ref}: " + "; ".join(failures)
        )

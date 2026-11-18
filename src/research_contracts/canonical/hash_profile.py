"""Derivation and validation of the released hash-view manifest (``canonical-hash-profile.v1``).

The manifest is not hand-maintained prose: it is derived from the schema annotations
(``x-datacompany-hash-excluded``, ``x-datacompany-hash-exclusion-reason``, ``x-datacompany-array``,
``x-datacompany-hash-opaque``, ``x-datacompany-hash-declaration-only``) by
walking the fully composed schema. A released manifest committed alongside a schema is
therefore checkable against the schema itself, which is what makes "adding or changing a
path, normalization rule or collection kind is a schema compatibility change" enforceable.

Pointers use RFC 6901 syntax with ``-`` as the array-element token, for example
``/pack_refs/-/resolved_at``.
"""

from __future__ import annotations

from functools import cache
from typing import Any, Final

from .errors import (
    CanonicalError,
    HashProfileError,
    SchemaValidationError,
    UnknownExclusionError,
)
from .jcs import canonicalize
from .registry import resolve_pointer, resolve_ref
from .rendering import json_text, json_type
from .structural import validate_instance

__all__ = [
    "DERIVATION_PROFILE_VERSION",
    "EXTENSIBLE_PROFILE_KEYS",
    "HASH_PROFILE_SCHEMA_REF",
    "derive_hash_profile",
    "exclusion_reasons",
    "merge_profile_extensions",
    "validate_hash_profile",
    "validate_profile_against_schema",
]

HASH_PROFILE_SCHEMA_REF = "urn:datacompany:canonical-hash-profile:1"

#: The version of the derivation rules **this engine implements**.
#:
#: ``profile_version`` names the rule set that produced a manifest, not a free label on it.
#: A manifest declaring some other version was produced by rules this engine does not
#: implement, so this engine's derivation is not evidence about it either way and the only
#: honest answer is to refuse it.
#:
#: Pinned in code, deliberately, exactly like ``denylist.REQUIRED_FORBIDDEN_TOKENS``.
#: ``EXTENSIONS.md`` §5.2 prescribes "change both together with a ``profile_version`` bump"
#: as the remedy for the inconsistent exclusion cascade, and before this constant existed
#: that bump was enforced in neither direction: ``validate_profile_against_schema`` built
#: the expected value FROM the supplied one, so a manifest could claim any version at all,
#: and no committed manifest was bound to the rules that derived it. With the version pinned
#: here, a manifest that bumps unilaterally is rejected on the spot, and bumping the rules
#: means editing this line — which immediately fails every committed manifest still carrying
#: the old number. The bump becomes one reviewable change touching code and every manifest
#: together, which is what §5.2 asks for and what prose alone could never enforce.
#:
#: **1 -> 2 on 2026-08-04, and this is the constant's first real test.** §5.2's exclusion
#: cascade filtered ``arrays`` by EXACT match while filtering ``included_pointers`` and
#: ``opaque_pointers`` by prefix, so an array nested under an excluded subtree survived in
#: the manifest; the derivation now filters all three by prefix. The observable delta on the
#: committed corpus is ZERO -- measured, with a positive control, in
#: :mod:`tests.test_canonical_hash` -- and that is deliberately NOT a reason to leave the
#: number alone. A version that only moves when the bytes move is a version nobody can rely
#: on: ``profile_version`` names the RULE SET, and the rule set changed. Leaving it at 1
#: would have hollowed the constant out on the first occasion it was asked to do its job,
#: and would have left a manifest derived under the old cascade indistinguishable from one
#: derived under the new.
DERIVATION_PROFILE_VERSION: Final[int] = 2


@cache
def exclusion_reasons() -> frozenset[str]:
    """The released closed set of hash-exclusion reasons, read from the schema itself.

    Deliberately a cached function and not a module-level constant. As a constant this was a
    filesystem read executed as an import side effect, so any fault in resolving the schema
    directory turned ``import research_contracts.canonical`` itself into a traceback, far
    from the code that could explain it.
    """
    return frozenset(resolve_pointer(f"{HASH_PROFILE_SCHEMA_REF}#/$defs/exclusion_reason")["enum"])


def _canonical_order(value: Any) -> bytes:
    """A language-neutral, member-order-independent sort key for a manifest entry."""
    return canonicalize(value, allow_binary_float=True)


_APPLICATOR_BRANCHES = ("allOf", "anyOf", "oneOf", "then", "else")

#: The only manifest members a domain schema may contribute to at the envelope's declared
#: composition point. Everything else -- exclusions, opaque subtrees, and every
#: serialization/digest rule -- is a property of the released envelope, not of a consumer.
EXTENSIBLE_PROFILE_KEYS: frozenset[str] = frozenset({"included_pointers", "arrays"})


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


#: The name every annotation in this vocabulary starts with. A member outside this prefix
#: belongs to somebody else and is not this engine's business: document 16 section 2.5
#: requires unknown extension values to be PRESERVED, and they are - nothing here strips
#: anything. What :func:`_require_released_annotations` refuses is a name INSIDE the
#: namespace this document owns, at authoring time, which is the only place preservation and
#: enforcement do not collide.
_ANNOTATION_PREFIX = "x-datacompany-"

#: The released ``x-datacompany-*`` names, re-stated from
#: ``schemas/meta/datacompany-extension-vocabulary.v1.schema.json`` ``#/$defs/vocabulary``.
#:
#: Re-stated rather than read at runtime, and both halves of that are deliberate. Decision F
#: set the precedent for the "rather than read": the meta-schema is a JSON Schema document
#: and the TypeScript port would have to ship a validator to consult it as one, so the rules
#: are restated in both engines and ``tests/test_extension_vocabulary.py`` asserts the
#: restatement matches the declaration IN BOTH DIRECTIONS. Reading the ENUM out of the
#: document at runtime - the way :func:`exclusion_reasons` reads the released reason set -
#: is additionally not available here: ``registry`` deliberately keeps ``schemas/meta/``
#: out of the released registry, because it is the authoring-time gate over those documents
#: and not a released payload contract, and the wheel that ships ``schemas/`` would have to
#: start shipping it too.
#:
#: ``x-datacompany-composition-point`` was in this set and read by NO code in either language
#: until 2026-08-04. It is now read twice: :func:`_require_released_composition_point`
#: refuses a value that names no ``$defs`` entry of the document, and
#: :func:`merge_profile_extensions` refuses an extension offered to an envelope that
#: declares no composition point at all. ``EXTENSIONS.md`` section 6.4's decision is taken,
#: not deferred.
_VOCABULARY: frozenset[str] = frozenset(
    {
        "x-datacompany-array",
        "x-datacompany-composition-point",
        "x-datacompany-cross-field",
        "x-datacompany-hash-declaration-only",
        "x-datacompany-hash-excluded",
        "x-datacompany-hash-exclusion-reason",
        "x-datacompany-hash-opaque",
    }
)

#: The members an ``x-datacompany-array`` value may carry, re-stated from the meta-schema's
#: ``#/$defs/array_annotation`` (``required`` and ``properties``) under the same drift test.
#:
#: Only the member NAMES are restated. What ``kind`` and ``order_key`` may CONTAIN is
#: ``canonical-hash-profile.v1``'s ``array_declaration`` - the meta-schema ``$ref``s it
#: rather than restating it, and this engine defers to the same document by validating the
#: derived manifest against it in :func:`validate_hash_profile`. Restating the value shapes
#: here would be a third copy of a closed set that already has one source of truth.
#: The three annotations the engines read with an IDENTITY comparison (``is True`` /
#: ``=== true``), which is why the meta-schema gives all three ``const: true``: every other
#: value is a silent no-op that leaves the path exactly as it was. Ordered so the diagnostic
#: names them the way the meta-schema and EXTENSIONS.md section 8 do.
_IDENTITY_COMPARED_FLAGS = (
    "x-datacompany-hash-declaration-only",
    "x-datacompany-hash-excluded",
    "x-datacompany-hash-opaque",
)

_ARRAY_REQUIRED_MEMBERS: frozenset[str] = frozenset({"kind"})
_ARRAY_OPTIONAL_MEMBERS: frozenset[str] = frozenset({"order_key"})


#: The only fragment shape a composition point may carry. Re-stated from the meta-schema's
#: ``#/$defs/composition_point`` pattern, and deliberately only the PREFIX: what may follow
#: it is decided by resolving the pointer against the document, which is a stronger check
#: than the pattern and needs no second copy of it.
_COMPOSITION_POINT_PREFIX = "#/$defs/"


def _require_released_composition_point(
    point: Any, pointer: str, schema_ref: str, base_id: str
) -> None:
    """Refuse a ``x-datacompany-composition-point`` that names nothing (``EXTENSIONS.md`` §6.4).

    Until 2026-08-04 this annotation was read by no code in either language: ``42``, ``null``
    and ``"not-a-pointer"`` were all accepted with no effect whatsoever, and a one-character
    typo in a real pointer was accepted too. §6.4 called that a liability in as many words --
    "it reads as a constraint and is not one" -- because an envelope's declared extension
    point is exactly the kind of thing a consumer reads and trusts.

    Resolution, not a pattern match, is the check. The value is a document-relative JSON
    Schema ``$ref`` fragment, so the honest question is whether it resolves, and
    :func:`resolve_pointer` is the same resolver the derivation walk itself uses. A pattern
    would accept ``#/$defs/domian_extension`` -- the typo hole this closes.

    ``base_id`` rather than ``schema_ref``: the walk carries the ``$id`` of the document the
    node actually belongs to, and a ``$ref`` into another released schema reaches nodes whose
    ``#/$defs/...`` are relative to THAT document. Resolving against the entry point instead
    would diagnose the wrong document.
    """
    if not isinstance(point, str) or not point.startswith(_COMPOSITION_POINT_PREFIX):
        raise HashProfileError(
            f"{schema_ref}: {json_text(pointer)} declares x-datacompany-composition-point as "
            f"{json_text(point)}. A composition point names the $defs entry at which a domain "
            f"schema attaches, so it must be a document-relative pointer beginning "
            f"{json_text(_COMPOSITION_POINT_PREFIX)}. Anything else names nothing and leaves "
            "the envelope with no stated extension point at all."
        )
    try:
        resolve_pointer(f"{base_id}{point}")
    except SchemaValidationError as exc:
        # The resolver's own message is deliberately NOT interpolated. `registry` renders its
        # diagnostics with `!r` in Python and with bare interpolation in the port, so
        # embedding it here would make this refusal differ between the two engines for the
        # same schema -- the exact divergence §9 item 13 exists to forbid. Everything the
        # author needs is already named: the schema, the node, the value and the document.
        raise HashProfileError(
            f"{schema_ref}: {json_text(pointer)} declares the composition point "
            f"{json_text(point)}, which resolves to no $defs entry of {base_id}. The "
            "annotation is the envelope's own statement of where a consumer may attach, so a "
            "name that resolves to nothing invites a domain schema to extend a point that "
            "does not exist."
        ) from exc


def _require_released_annotations(
    schema: dict[str, Any], pointer: str, schema_ref: str, base_id: str
) -> None:
    """Refuse the authoring-path fail-opens of ``EXTENSIONS.md`` sections 7.1-7.4.

    Every shape below produced a WEAKER canonical hash view with no error anywhere: the
    derivation read the annotations it recognised, ignored the rest, and returned a manifest
    that looked exactly like a manifest for a schema that had never carried them. Section 7.5
    closed the same class on the cross-field side and this is the same closure, by the same
    method and with no new normative semantics:
    ``schemas/meta/datacompany-extension-vocabulary.v1.schema.json`` already rejected all four,
    under a gate proven falsifiable one mutation at a time; what was missing was the engines
    consulting it.

    * **7.1** - an unregistered name in the ``x-datacompany-`` namespace. ``x-datacompany-hash-exclude``
      is one letter short of an exclusion, is a valid JSON Schema member, survives every
      round trip and is read by nothing, so the path it was meant to remove stays in the
      hash view.
    * **7.2** - ``x-datacompany-hash-exclusion-reason`` with no ``x-datacompany-hash-excluded``
      beside it. The reason is read only inside the flag's branch, so deleting the flag and
      leaving the reason silently re-admits a signature to the hash view. Only this
      direction is refused here: the flag WITHOUT a reason already fails closed, as
      ``UnknownExclusionError`` against the released closed reason set.
    * **7.3** - a non-object ``x-datacompany-array``. ``"set"``, ``["set"]`` and ``true`` all
      derived ``arrays: []``, and the lost declaration only resurfaces as
      ``UndeclaredArrayError`` if some instance happens to carry that array - so an OPTIONAL
      array can lose its collection semantics indefinitely with no gate going red.
    * **7.4** - an ``x-datacompany-array`` carrying its own ``pointer``. The derivation merges
      the declaration into ``{"pointer": <derived>, **declaration}``, annotation last, so a
      ``pointer`` member re-targets the declaration at an unrelated path and the resulting
      entry is still a VALID ``array_declaration`` - nothing downstream can notice.

    Two further per-node rules of the same meta-schema are enforced here, for the same
    reason and by the same route. Neither is one of the four numbered defects; both are rows
    of the section 8 table that the engine simply did not consult.

    * ``const: true`` on all three identity-compared flags. ``x-datacompany-hash-excluded:
      false`` beside a valid reason derived an EMPTY ``excluded_pointers`` and left the
      member in the hash view - the same outcome as section 7.2, reached by writing the flag
      wrongly instead of by deleting it. Closing it needs no change to any ``is True`` read:
      this function already runs before anything is read off the node, so the identity
      comparisons below stay byte-identical and simply never see a non-``true`` value.
    * ``declaration_only_pairing``'s ``x-datacompany-hash-excluded`` half. The
      ``x-datacompany-hash-opaque`` half is deliberately NOT here: it belongs with the composed
      walk in :func:`_require_declaration_only_inside_an_opaque_subtree`, which is where the
      placement rules live, and refusing it in two places with two messages would be the
      divergence this closure exists to remove.

    Scope, stated rather than implied: this runs on the nodes the DERIVATION WALK reaches,
    which is what it can speak about. A malformed annotation under ``if``, ``contains`` or an
    unreferenced ``$defs`` entry is not reached here and is not claimed to be. The
    corpus-wide obligation is a different gate with a different reach -
    ``tests/test_extension_vocabulary.py`` applies the meta-schema to every annotated node of
    every committed schema, lexically, and pins the node count as an equality.
    """
    names = [name for name in schema if name.startswith(_ANNOTATION_PREFIX)]
    if not names:
        return

    unregistered = sorted(name for name in names if name not in _VOCABULARY)
    if unregistered:
        raise HashProfileError(
            f"{schema_ref}: {json_text(pointer)} carries {json_text(unregistered)}, which is "
            f"not a released x-datacompany-* annotation. The released vocabulary is "
            f"{json_text(sorted(_VOCABULARY))}. A name outside it is preserved on round trip "
            "and read by nothing, so the hash view is derived as though the annotation had "
            "never been written."
        )

    # BEFORE the pairing check below, so that `x-datacompany-hash-excluded: false` beside a
    # valid reason is diagnosed as the no-op flag it is rather than as a pairing fault.
    for flag in _IDENTITY_COMPARED_FLAGS:
        if flag in schema and schema[flag] is not True:
            raise HashProfileError(
                f"{schema_ref}: {json_text(pointer)} declares {flag} as "
                f"{json_text(schema[flag])}. All three of "
                f"{json_text(sorted(_IDENTITY_COMPARED_FLAGS))} are read with an identity "
                "comparison, so every value but the literal true is a silent no-op that "
                "leaves the path exactly as it was: false beside a valid exclusion reason "
                "hashes the member it reads as excluding. Write true, or omit the "
                "annotation."
            )

    if "x-datacompany-hash-declaration-only" in schema and "x-datacompany-hash-excluded" in schema:
        raise HashProfileError(
            f"{schema_ref}: {json_text(pointer)} carries x-datacompany-hash-declaration-only AND "
            "x-datacompany-hash-excluded. They are contradictory acts on one pointer: an "
            "exclusion REMOVES a path and records the removal in excluded_pointers with a "
            "released reason, while declaration-only asserts there is no path there to "
            "remove. Keep whichever one is meant."
        )

    if (
        "x-datacompany-hash-exclusion-reason" in schema
        and "x-datacompany-hash-excluded" not in schema
    ):
        raise HashProfileError(
            f"{schema_ref}: {json_text(pointer)} carries x-datacompany-hash-exclusion-reason with "
            "no x-datacompany-hash-excluded beside it. The reason is read only inside the flag's "
            "branch, so on its own it excludes nothing: the path stays in the hash view and "
            "excluded_pointers records no exclusion. Add x-datacompany-hash-excluded: true, or "
            "delete the reason."
        )

    if "x-datacompany-array" in schema:
        _require_released_array_declaration(schema["x-datacompany-array"], pointer, schema_ref)

    if "x-datacompany-composition-point" in schema:
        _require_released_composition_point(
            schema["x-datacompany-composition-point"], pointer, schema_ref, base_id
        )


def _require_released_array_declaration(declaration: Any, pointer: str, schema_ref: str) -> None:
    """The ``x-datacompany-array`` half of :func:`_require_released_annotations` (7.3, 7.4)."""
    where = f"{schema_ref}: x-datacompany-array at {json_text(pointer)}"
    if not isinstance(declaration, dict):
        raise HashProfileError(
            f"{where} is a JSON {json_type(declaration)}, not an object. A non-object "
            "declaration is dropped at derivation, so the array keeps undeclared collection "
            "semantics until some instance happens to carry it, and an optional array that "
            "no instance carries loses them indefinitely with no gate going red."
        )
    # An f-string rather than `set(declaration)`: a JSON object's member names ARE strings,
    # but `isinstance(x, dict)` narrows to `dict[Unknown, Unknown]`, and sorting `object` is
    # a real diagnosis about the call rather than noise to silence with a cast.
    members = {f"{name}" for name in declaration}
    unknown = sorted(members - _ARRAY_REQUIRED_MEMBERS - _ARRAY_OPTIONAL_MEMBERS)
    if unknown:
        raise HashProfileError(
            f"{where} carries {json_text(unknown)}; a released array declaration carries "
            f"{json_text(sorted(_ARRAY_REQUIRED_MEMBERS | _ARRAY_OPTIONAL_MEMBERS))} only. "
            "The declaration is merged into the manifest entry AFTER the derived pointer, so "
            "a pointer member re-targets the declaration at an unrelated path and the entry "
            "that reaches the manifest is still a valid array_declaration."
        )
    missing = sorted(_ARRAY_REQUIRED_MEMBERS - members)
    if missing:
        raise HashProfileError(
            f"{where} declares no {', '.join(missing)}. An array declaration that names no "
            "collection kind declares nothing, and canonical-hash-profile.v1 closes the set "
            "of kinds it may name."
        )


class _Walker:
    """Collects hash-view pointers from a composed schema."""

    def __init__(self, schema_ref: str) -> None:
        self.schema_ref = schema_ref
        self.included: set[str] = set()
        self.excluded: dict[str, str] = {}
        self.arrays: dict[str, dict[str, Any]] = {}
        self.opaque: set[str] = set()
        #: Pointers whose schema node exists only to CARRY an annotation (D9). Collected
        #: here and subtracted in :func:`derive_hash_profile`, deliberately not suppressed
        #: inline at the ``properties`` loop below. The flag can arrive through a ``$ref``
        #: or through any of ``_APPLICATOR_BRANCHES``, i.e. AFTER the ``properties`` loop
        #: that added the pointer has already run; an inline check would therefore be
        #: composition-order dependent, and a second implementation composing in another
        #: order would derive a different manifest from the same schema.
        self.declaration_only: set[str] = set()
        #: Every pointer at which the walk reaches an ``x-datacompany-composition-point``.
        #:
        #: POINTERS ONLY, never the values, and that is deliberate: at pointer ``""`` a
        #: schema can reach SEVERAL, because ``allOf``/``$ref`` composition does not advance
        #: the pointer. ``run-manifest:1`` is a released example -- it declares
        #: ``#/$defs/manifest_extension`` and composes ``stable-identity:1``, which declares
        #: ``#/$defs/domain_extension``, so both arrive at ``""``. Collecting values would
        #: invite a reader to pick one, and which one is a normative question nobody has
        #: decided. Collecting pointers is enough for the only consumer: the diagnostic in
        #: :func:`merge_profile_extensions`, which reports WHERE the annotation was found
        #: when the root does not carry it.
        self.composition_points: set[str] = set()

    def walk(
        self,
        schema: Any,
        pointer: str,
        seen: frozenset[tuple[str, str]],
        base_id: str,
    ) -> None:
        if isinstance(schema, bool) or not isinstance(schema, dict):
            return
        base_id = schema.get("$id", base_id)

        # Before anything is READ off this node, so that a node's own malformed annotation is
        # diagnosed at the node, rather than after a `$ref` has carried the walk somewhere
        # else and made the diagnostic point at a schema the author did not write.
        #
        # `base_id` is the `$id` of the document this node belongs to, already updated above
        # from the node's own `$id`. `x-datacompany-composition-point` is document-relative, so
        # it is the only correct base to resolve it against.
        _require_released_annotations(schema, pointer, self.schema_ref, base_id)

        ref = schema.get("$ref")
        if isinstance(ref, str):
            target, target_base = resolve_ref(ref, base_id)
            key = (f"{target_base}{ref}" if ref.startswith("#") else ref, pointer)
            if key not in seen:
                self.walk(target, pointer, seen | {key}, target_base)

        if schema.get("x-datacompany-hash-excluded") is True:
            reason = schema.get("x-datacompany-hash-exclusion-reason")
            if reason not in exclusion_reasons():
                raise UnknownExclusionError(
                    f"{pointer}: hash exclusion reason {reason!r} is not in the released set "
                    f"{sorted(exclusion_reasons())}"
                )
            self.excluded[pointer] = reason

        array_declaration = schema.get("x-datacompany-array")
        if array_declaration is not None:
            # An isinstance-against-dict test until section 7.3 closed, and that test WAS the
            # fail-open: a non-object declaration failed it and was DROPPED, in silence.
            # `_require_released_annotations` has already proven, for this same node, that a
            # present declaration is an object carrying only released members - so the
            # isinstance could no longer evaluate FALSE, and a condition that cannot fire
            # reads as defence in depth while being one more line nothing can test.
            #
            # The merge order is unchanged and still puts the annotation LAST. That used to
            # be section 7.4's mechanism, and it stays because the annotation can no longer
            # carry a `pointer`: the shape that made the precedence dangerous is refused at
            # the node.
            self.arrays[pointer] = {"pointer": pointer, **array_declaration}

        if schema.get("x-datacompany-hash-opaque") is True:
            self.opaque.add(pointer)

        if schema.get("x-datacompany-hash-declaration-only") is True:
            self.declaration_only.add(pointer)

        # PRESENCE, matching `_require_released_annotations` above, which has already proven
        # this node's value well formed. `.get(...) is not None` would drop an explicit
        # `null` -- a declared-but-broken point -- from the diagnostic that exists to say
        # where declarations are.
        if "x-datacompany-composition-point" in schema:
            self.composition_points.add(pointer)

        if "items" in schema or "prefixItems" in schema:
            self.included.add(pointer)
            items = schema.get("items")
            if items is not None:
                self.walk(items, f"{pointer}/-", seen, base_id)
            for index, item_schema in enumerate(schema.get("prefixItems") or []):
                self.walk(item_schema, f"{pointer}/{index}", seen, base_id)

        properties = schema.get("properties")
        if isinstance(properties, dict):
            for name, child in properties.items():
                child_pointer = f"{pointer}/{_escape(name)}"
                self.included.add(child_pointer)
                self.walk(child, child_pointer, seen, base_id)

        for branch in _APPLICATOR_BRANCHES:
            node = schema.get(branch)
            if isinstance(node, list):
                for subschema in node:
                    self.walk(subschema, pointer, seen, base_id)
            elif isinstance(node, dict):
                self.walk(node, pointer, seen, base_id)
        # "if" contributes no hash-view path of its own: it only selects a branch. Walking it
        # would import its narrowing "properties" as if they were declared members.


def _at_or_under(pointer: str, prefixes: Any) -> bool:
    """True when ``pointer`` IS one of ``prefixes`` or sits under one of them.

    The released subtree-cascade predicate, named once instead of spelled out three times.
    ``prefixes`` is any container of pointers; ``excluded`` is passed as a ``dict``, whose
    iteration yields its keys.
    """
    return any(pointer == prefix or pointer.startswith(f"{prefix}/") for prefix in prefixes)


def _require_declaration_only_is_legally_placed(walker: _Walker, schema_ref: str) -> None:
    """Reject ``x-datacompany-hash-declaration-only`` anywhere it does not mean anything.

    The annotation says "this node is reached only to carry an annotation; it declares no
    hashed path". That is a coherent statement exactly once: **strictly inside** an
    ``x-datacompany-hash-opaque`` subtree, where the members are hashed as they arrive and the
    subtree's opacity is destroyed by any declared descendant. Outside one, suppressing a
    pointer removes its member from the hash view entirely -- which is what
    ``x-datacompany-hash-excluded`` already does, with a released closed reason set behind it and
    an ``excluded_pointers`` entry recording the act in the manifest. A second spelling of
    "remove this path" that records nothing and needs no reason is a fail-open the manifest
    could not even show, so it is refused here rather than left to convention.

    Two independent conditions, because "strictly under some opaque ancestor" alone was
    **walk-past-able one level deeper**. A node carrying BOTH annotations satisfies the
    ancestor test whenever it happens to sit inside another opaque subtree, so
    ``/value`` opaque with ``/value/inner`` opaque-and-flagged was accepted -- which is
    exactly the bypass the ancestor test exists to prevent, merely relocated. The flag and
    ``x-datacompany-hash-opaque`` are therefore refused on ONE NODE unconditionally, and that is
    also what the meta-schema's ``declaration_only_pairing`` forbids per node, so the two
    gates now agree instead of only appearing to.

    This guard reads the RAW walk, and only the raw walk: it is a statement about where the
    annotation may be WRITTEN, not about what survives any cascade. The separate
    "declare none or declare all" rule is in
    :func:`_require_declaration_only_does_not_collide_with_a_declared_member`, which
    deliberately runs LATER, against the derived set.

    The second check spells "strictly under" as ``startswith(f"{opaque}/")`` rather than
    :func:`_at_or_under`, and that strictness is now REDUNDANT rather than load-bearing:
    the only pointer that could be *at* an opaque pointer is one carrying both
    annotations, and the pair check above has already refused it. Measured, not assumed --
    relaxing it to ``_at_or_under`` produces an identical outcome across all 64
    arrangements of the two annotations over three nested nodes, so a mutation of this
    line alone cannot go red. It is kept because it states the rule the documentation
    states, and because it keeps this guard correct on its own terms if the pair check is
    ever narrowed.
    """
    both = sorted(walker.declaration_only & walker.opaque)
    if both:
        raise HashProfileError(
            f"{schema_ref}: {json_text(both)} carries x-datacompany-hash-declaration-only AND "
            "x-datacompany-hash-opaque on one node. They are incompatible acts on one pointer: "
            "x-datacompany-hash-opaque declares a subtree whose members are hashed as they "
            "arrive, and declaration-only says this pointer is not a hashed path at all. "
            "Allowing the pair would also make the placement rule below satisfiable by the "
            "node itself, so any author could suppress any pointer anywhere by writing "
            "x-datacompany-hash-opaque beside the flag. Mark the ENCLOSING payload opaque and "
            "leave the flag on the node that only carries annotations."
        )

    misplaced = sorted(
        pointer
        for pointer in walker.declaration_only
        if not any(pointer.startswith(f"{opaque}/") for opaque in walker.opaque)
    )
    if misplaced:
        raise HashProfileError(
            f"{schema_ref}: x-datacompany-hash-declaration-only at {json_text(misplaced)} is not strictly "
            "inside an x-datacompany-hash-opaque subtree. The annotation exists so that an array "
            "inside an opaque subtree can carry its released collection declaration without "
            "its pointer becoming a declared member and revoking the subtree's opacity; "
            "outside an opaque subtree it would silently remove a member from the hash view, "
            "which is x-datacompany-hash-excluded's job and carries a released reason and an "
            "excluded_pointers entry. Mark the enclosing payload x-datacompany-hash-opaque, or "
            "exclude the member with x-datacompany-hash-excluded and a reason."
        )


def _require_declaration_only_does_not_collide_with_a_declared_member(
    walker: _Walker, included: list[str], schema_ref: str
) -> None:
    """Refuse an opaque subtree that both declares a member and carries the flag.

    "Declare none or declare all, and say which" -- the released rule on
    ``bitemporal-assertion:1`` ``/value``. A subtree that mixes the two is the one shape this
    annotation can express and the engine cannot honour: the surviving declared sibling
    revokes the opacity in ``hash_view._build_object``, and the declaration-only member --
    which is deliberately NOT in ``included_pointers`` -- then raises ``UndeclaredPathError``
    at hash time, far from the schema that caused it. Diagnosed here instead, where the
    author can be told which two annotations disagree.

    **``included`` is the DERIVED list, after the exclusion cascade, and that is the whole
    correctness of this function.** It read ``walker.included`` -- the raw walk -- and so
    counted an EXCLUDED member as a declaration that revokes opacity. ``hash_view`` says the
    opposite in as many words: "Opacity is revoked by a DECLARED MEMBER and by nothing else.
    An EXCLUSION is the opposite act." The cost was not theoretical: it refused the exact
    shape the two annotations exist for -- the signed opaque payload of
    ``tests/test_hash_view_opaque_exclusion.py``, ``/value`` opaque with ``/value/sig``
    excluded, plus one array -- while the runtime escape hatch hashed it correctly. D9 was
    therefore NOT closed for the motivating case until this ran against the derived set.

    Grouped by each flag's NEAREST opaque ancestor, not by every opaque ancestor it has.
    Opaque subtrees nest, and the outer one's opacity is legitimately revoked by the inner
    one's own root: given ``/value`` and ``/value/nested`` both opaque with the flag at
    ``/value/nested/tags``, ``/value/nested`` IS a declared member of ``/value`` and the
    shape is sound. Checking every ancestor would refuse it.

    FOUND BY MUTATION, then closed. This loop also carried
    ``and not _at_or_under(pointer, walker.opaque - {opaque})`` -- "ignore a declared pointer
    that lies inside some OTHER opaque subtree". It looked like the clause that made nested
    subtrees work and it was a defect twice over: it made the "group by the OUTERMOST
    ancestor" mutation unobservable, and it SUPPRESSED A REAL REFUSAL -- ``/value`` opaque
    with the flag at ``/value/tags`` and a nested opaque ``/value/nested`` beside it is
    broken, because ``/value/nested`` revokes ``/value``'s opacity. Nearest-ancestor grouping
    alone is what makes nesting legal, because the inner root is never strictly under itself.
    """
    for opaque, suppressed in sorted(_by_nearest_opaque(walker).items()):
        # No declaration-only filter here: `included` has already had it applied, along with
        # the exclusion cascade. Re-applying either would hide which set actually decides.
        declared = [pointer for pointer in included if pointer.startswith(f"{opaque}/")]
        if declared:
            raise HashProfileError(
                f"{schema_ref}: the opaque subtree {json_text(opaque)} both declares members "
                f"{json_text(declared)} and carries x-datacompany-hash-declaration-only at "
                f"{json_text(sorted(suppressed))}. "
                "A declared member revokes the subtree's opacity, after which every member "
                "must be declared -- and a declaration-only pointer deliberately is not one, "
                "so it would raise UndeclaredPathError at hash time. Declare NONE of the "
                "subtree's members and use x-datacompany-hash-declaration-only to carry the "
                "array declarations -- marking the OUTERMOST node of each properties chain "
                "is enough, because the suppression cascades to everything beneath it -- or "
                "declare ALL of them as ordinary properties, in which case x-datacompany-array "
                "works without this annotation. An EXCLUDED member is not a declared one and "
                "does not appear here: an exclusion removes a path, it does not declare one."
            )


def _by_nearest_opaque(walker: _Walker) -> dict[str, set[str]]:
    """Group each declaration-only pointer under its LONGEST opaque-ancestor prefix.

    Longest, because opaque subtrees nest and only the innermost one is the subtree whose
    opacity a given flag exists to protect. Every pointer reaching here already has at least
    one opaque ancestor: the placement guard runs first and raises otherwise. The scan
    nevertheless starts from ``""`` rather than asserting that, because ``""`` is the
    document root and grouping a hypothetically-unguarded pointer there degrades to "the
    whole document", which is the conservative reading rather than a crash.
    """
    grouped: dict[str, set[str]] = {}
    for pointer in walker.declaration_only:
        # An explicit scan rather than `max(..., key=len)`: `key=len` makes ``ty`` infer the
        # result as ``Sized``, which is a real diagnosis about the call and not noise to
        # silence with a cast. It also mirrors the TypeScript port line for line.
        nearest = ""
        for opaque in walker.opaque:
            if pointer.startswith(f"{opaque}/") and len(opaque) >= len(nearest):
                nearest = opaque
        if nearest not in grouped:
            grouped[nearest] = set()
        grouped[nearest].add(pointer)
    return grouped


def derive_hash_profile(schema_ref: str) -> dict[str, Any]:
    """Derive the released hash-view manifest for ``schema_ref`` from its own annotations.

    The derived ``profile_version`` is always :data:`DERIVATION_PROFILE_VERSION`. It used to
    be a keyword argument defaulting to ``1``, and no call site in either language ever
    passed it except ``validate_profile_against_schema``, which passed the *supplied*
    manifest's own value straight back in — which is precisely what made the agreement
    check unfalsifiable. A deriver that can be asked to stamp a version whose rules it does
    not implement produces a manifest its own validator must reject, so the knob is gone
    rather than merely unused.
    """
    walker = _Walker(schema_ref)
    base_id, _, _ = schema_ref.partition("#")
    walker.walk(resolve_pointer(schema_ref), "", frozenset(), base_id)

    # Placement is a fact about the SCHEMA, so it is checked against the raw walk and first:
    # a misplaced flag must be diagnosed rather than silently applied by the filters below.
    _require_declaration_only_is_legally_placed(walker, schema_ref)

    excluded_pointers = walker.excluded
    included = sorted(
        pointer
        for pointer in walker.included
        if not _at_or_under(pointer, excluded_pointers)
        # D9: a declaration-only node carries an annotation and declares no hashed path, so
        # neither it NOR anything the walk reached beneath it enters included_pointers. The
        # cascade is by PREFIX, matching the released exclusion cascade above: an array OF
        # OBJECTS at /value/tags also yields /value/tags/-/<member> from the items walk, and
        # an exact-match filter would leave those behind -- which makes /value a declared
        # prefix again and revokes exactly the opacity this annotation exists to preserve.
        and not _at_or_under(pointer, walker.declaration_only)
    )

    # ...and only NOW the "declare none or declare all" rule, against the DERIVED list. It
    # used to read `walker.included`, which counts an EXCLUDED member as a declaration --
    # the opposite of what `hash_view` implements ("Opacity is revoked by a DECLARED MEMBER
    # and by nothing else. An EXCLUSION is the opposite act."). That refused the signed
    # opaque payload the two annotations exist for.
    _require_declaration_only_does_not_collide_with_a_declared_member(walker, included, schema_ref)
    # `arrays` is deliberately NOT filtered by declaration_only. Carrying the collection
    # declaration OUT of a subtree whose paths stay undeclared is the entire purpose of the
    # annotation (D9): `bitemporal-assertion:1` `/value` states that "arrays inside it still
    # require their own ordered/set-like declaration", and `canonical-hash-profile.v1`
    # states that an undeclared array is rejected "including inside an opaque subtree".
    # Filtering here would make both statements unsatisfiable again.
    #
    # It IS filtered by the exclusion cascade, by PREFIX, exactly like `included_pointers`
    # and `opaque_pointers` above -- since profile_version 2, 2026-08-04. Until then this was
    # an EXACT match, which was §5.2's recorded inconsistency: excluding `/sig` dropped
    # `/sig/parts` from `included_pointers` and `/sig/blob` from `opaque_pointers` while
    # LEAVING `{"pointer": "/sig/parts", ...}` in `arrays`. The surviving entry was inert --
    # the excluded subtree is never visited -- but `validate_profile_against_schema` compares
    # `arrays` exactly, so every port that filtered the three consistently (the obvious clean
    # implementation) rejected every manifest this engine produced, and §9 item 6 had to
    # order ports to reproduce the quirk. Both engines now filter consistently and that item
    # was REWRITTEN IN PLACE rather than deleted: the checklist's numbering is load-bearing,
    # since items 8, 11, 12 and 13 are cited by number elsewhere in the document.
    # Measured before changing: no committed schema declares an array at or under an
    # exclusion, so no committed manifest moved -- which proves the change INERT ON THIS
    # CORPUS and is not evidence that it is correct. `profile_version` moved because the RULE
    # moved; see `DERIVATION_PROFILE_VERSION`.
    #
    # The declaration-only cascade above is by prefix for its own, different reason, and the
    # two rules stay independent: "make the filters consistent" is now true of the exclusion
    # cascade and still says nothing about `declaration_only`, which `arrays` must never be
    # filtered by.
    arrays = [
        walker.arrays[pointer]
        for pointer in sorted(walker.arrays)
        if not _at_or_under(pointer, excluded_pointers)
    ]

    profile = {
        "profile_id": HASH_PROFILE_SCHEMA_REF,
        "profile_version": DERIVATION_PROFILE_VERSION,
        "schema_ref": schema_ref,
        "serialization": "rfc8785",
        "encoding": "utf-8",
        "byte_order_mark": False,
        "digest_algorithm": "sha256",
        "digest_prefix": "sha256:",
        "absent_vs_null": "distinct",
        "unicode_normalization": "none",
        "timestamp_representation": "rfc3339_utc_z",
        "decimal_representation": "decimal_string",
        "binary_float_policy": "reject",
        "included_pointers": included,
        "excluded_pointers": [
            {"pointer": pointer, "reason": excluded_pointers[pointer]}
            for pointer in sorted(excluded_pointers)
        ],
        # Filtered by declaration_only as well, and this is NOT a no-op. The comment here
        # used to claim it could only ever be one, reasoning that the placement guard keeps
        # every flag strictly under an opaque pointer. That argument is about ANCESTORS and
        # says nothing about DESCENDANTS: `/value` opaque, `/value/inner` flagged, and
        # `/value/inner/deeper` opaque puts an opaque pointer squarely under a
        # declaration-only one. Listing it would be the manifest asserting a path inside a
        # subtree the same manifest says contributes no paths. Dropping it changes no
        # behaviour -- `hash_view._is_declared_opaque` matches by prefix and the enclosing
        # opaque pointer already covers everything beneath the flag -- which is exactly why
        # it has to be a rule with a test rather than a comment with an argument.
        "opaque_pointers": sorted(
            pointer
            for pointer in walker.opaque
            if not _at_or_under(pointer, excluded_pointers)
            and not _at_or_under(pointer, walker.declaration_only)
        ),
        "arrays": arrays,
    }
    validate_hash_profile(profile)
    return profile


def _where_else_a_composition_point_was_found(schema_ref: str) -> str:
    """The clause that makes the non-extensible refusal TRUE about the schema it names.

    ``merge_profile_extensions`` reads the annotation at the document root and nowhere else,
    but the annotation is legal at any depth and the derivation walk shape-checks and
    resolves one wherever it finds it. Two shapes were therefore told "declares no
    x-datacompany-composition-point" when they declare one:

    * a point on a **nested** node -- validated by the walk, then reported as absent;
    * a **domain schema composing an envelope** (``allOf: [{"$ref": <envelope>}]``). The
      envelope's point arrives at pointer ``""``, because ``allOf``/``$ref`` do not advance
      the pointer, but it is not a member of the composing document -- so composing an
      extensible envelope does not make the composing schema extensible. That is a real
      authoring requirement and it is stated here rather than left to be discovered.

    Root-only is the rule, and it is a decision rather than an accident. The alternative --
    "extensible if the walk reaches a point at pointer ``""``" -- is **ambiguous on a
    released schema**: ``run-manifest:1`` declares ``#/$defs/manifest_extension`` and
    composes ``stable-identity:1``, which declares ``#/$defs/domain_extension``, so two
    points arrive at ``""`` and which one a consumer attaches at is a normative question
    nobody has decided. Measured across the corpus, the two rules agree on every released
    schema (6 extensible, 12 not), so the ambiguity buys nothing and costs a decision.

    A walk that raises yields no clause rather than replacing the refusal with an unrelated
    error: this is message enrichment on a path that is already failing, and a schema this
    walk cannot traverse is refused by ``derive_hash_profile`` anyway.
    """
    try:
        walker = _Walker(schema_ref)
        base_id, _, _ = schema_ref.partition("#")
        walker.walk(resolve_pointer(schema_ref), "", frozenset(), base_id)
    except CanonicalError:
        return ""
    if not walker.composition_points:
        return ""
    return (
        f" The derivation walk does reach one at {json_text(sorted(walker.composition_points))}"
        ", which is a different statement: an extension contributes ROOT-relative RFC 6901 "
        "pointers, so the point that governs it is the one this document declares at its own "
        "root. A point reached through composition belongs to the envelope that declares it, "
        "and a schema composing an extensible envelope must declare its OWN."
    )


def merge_profile_extensions(
    profile: dict[str, Any], extensions: dict[str, Any] | None
) -> dict[str, Any]:
    """Merge a domain schema's declared additions into a released envelope manifest.

    A domain schema composes an envelope and declares the shape of its own payload at the
    envelope's composition point. That contributes extra included pointers and extra array
    declarations. Nothing may be removed, and no exclusion may be added this way: an
    exclusion is a property of the released envelope, not of a consumer.

    **Bound to ``x-datacompany-composition-point`` since 2026-08-04** (``EXTENSIONS.md`` §6.4).
    This function implemented the composition-point *concept* and was driven entirely by its
    ``extensions`` argument, never consulting the envelope's declared point -- so every
    released schema was extensible in practice whether or not it said so, and the annotation
    constrained nothing. An envelope that declares no composition point is now
    **non-extensible**, which is a behaviour change for consumers and is meant to be: the
    annotation is the envelope's own statement of whether it invites extension at all, and
    an envelope that never made that statement cannot have it inferred on its behalf.

    What this does NOT claim to check is *where* an extension attaches. The composition point
    names a ``$defs`` entry in SCHEMA space; ``included_pointers`` and ``arrays`` are RFC 6901
    pointers in INSTANCE space, and every released composition point is composed at the
    envelope root, so a declared point induces no constraint on which instance pointers an
    extension may name. Stating that limit is better than a check that looks positional and
    is not: the gate here is presence, and presence is exactly what §6.4 asked to become real.
    """
    if not extensions:
        return profile
    unknown = set(extensions) - EXTENSIBLE_PROFILE_KEYS
    if unknown:
        raise HashProfileError(
            f"a domain extension may only add included_pointers and arrays, not {sorted(unknown)}"
        )
    # BEFORE the composition-point read, and that ordering is the whole reason this call is
    # here rather than left to `validate_hash_profile` at the end: `resolve_pointer` below
    # would raise `SchemaValidationError` for an unreleased `schema_ref`, which is a
    # different exception with a different message than the one this repository already
    # promises for that case (D7).
    _require_released_schema_ref(profile["schema_ref"])
    # No isinstance narrowing: `canonical-hash-profile.v1` constrains `schema_ref` to
    # `^urn:datacompany:[a-z][a-z0-9-]*:[1-9][0-9]*$` and `validate_hash_profile` has already
    # enforced it, so there is no fragment and this resolution is always the document root.
    schema = resolve_pointer(profile["schema_ref"])
    # PRESENCE, not `.get(...) is None`. An explicit `"x-datacompany-composition-point": null` is
    # a declared-but-broken point and must reach the shape message below, which is what
    # derivation does for the same schema; `.get` would report it as "declares none" here and
    # as a malformed value there -- reintroducing, in the two messages, exactly the
    # two-route asymmetry D7 is about. Pinned by
    # `test_an_explicit_null_composition_point_is_malformed_not_absent` in both suites; the
    # distinction survived 23 mutations unasserted before that test existed.
    if "x-datacompany-composition-point" not in schema:
        # THE ROOT OF THIS DOCUMENT, and nowhere else. Named in the message rather than left
        # implicit, because the annotation is legal at any depth -- `_require_released_annotations`
        # shape-checks and RESOLVES one wherever the walk finds it -- so a schema that
        # declares a valid point on a nested node used to be told it "declares no
        # x-datacompany-composition-point", which is false about that schema.
        raise HashProfileError(
            f"{profile['schema_ref']} declares no x-datacompany-composition-point at its document "
            "ROOT, so it is not extensible. A domain schema may contribute included_pointers "
            "and arrays only at an envelope's declared composition point: accepting the "
            "extension would put pointers into a manifest the envelope never invited, and "
            "validate_profile_against_schema would then accept them as released."
            + _where_else_a_composition_point_was_found(profile["schema_ref"])
            + " Declare the composition point at the root of this schema, or drop the "
            "extension."
        )
    # Re-checked here rather than trusted from derivation. A manifest reaching this function
    # need never have been produced by `derive_hash_profile` -- it is public API over any
    # well-formed `canonical-hash-profile.v1` -- so a schema carrying a broken composition
    # point would otherwise be extensible through this route while being underivable through
    # the other. One helper, one message, both routes.
    _require_released_composition_point(
        schema["x-datacompany-composition-point"],
        "",
        profile["schema_ref"],
        profile["schema_ref"],
    )
    merged = dict(profile)
    merged["included_pointers"] = sorted(
        set(profile["included_pointers"]) | set(extensions.get("included_pointers", []))
    )
    declared = {entry["pointer"] for entry in profile["arrays"]}
    # SORTED by pointer, exactly as ``derive_hash_profile`` sorts, rather than appended.
    # Appending made the two D9 routes byte-identical only by ACCIDENT: they agreed on
    # ``bitemporal-assertion:1`` because ``/value/tags`` happens to sort after
    # ``/basis_refs``. An opaque ``/aaa`` with a flagged ``/aaa/tags`` beside a released
    # array at ``/zzz`` derived ``['/aaa/tags', '/zzz']`` and merged ``['/zzz', '/aaa/tags']``
    # -- the same manifest in two byte sequences, and the closure of D9 is stated as a BYTE
    # equality. ``validate_profile_against_schema`` compares ``arrays`` per pointer so it
    # never noticed, which is precisely why one representation had to become canonical here.
    # No committed manifest moves: every one of them is DERIVED, and derivation already
    # sorted. Measured across all 18 released schemas and the whole fixture corpus.
    merged["arrays"] = sorted(
        list(profile["arrays"])
        + [entry for entry in extensions.get("arrays", []) if entry["pointer"] not in declared],
        # By `entry["pointer"]`, which is the only key a merged entry has. Derivation
        # sorts by the WALKER key instead, and the two differ only for the released
        # `x-datacompany-array`-carries-its-own-pointer quirk (EXTENSIONS.md 7.4) that the
        # meta-schema forbids and no committed schema uses. Python sorts strings by code
        # POINT; the port uses `compareCodePoints` for the same reason.
        key=lambda entry: entry["pointer"],
    )
    validate_hash_profile(merged)
    return merged


def validate_hash_profile(profile: Any) -> None:
    """Validate a manifest against ``canonical-hash-profile.v1`` and its closed reason set."""
    errors = validate_instance(profile, HASH_PROFILE_SCHEMA_REF)
    if errors:
        raise HashProfileError(
            f"hash-view manifest is not a valid {HASH_PROFILE_SCHEMA_REF}: " + "; ".join(errors)
        )
    for entry in profile["excluded_pointers"]:
        if entry["reason"] not in exclusion_reasons():
            raise UnknownExclusionError(
                f"{entry['pointer']}: unknown hash exclusion reason {entry['reason']!r}"
            )
    _require_released_schema_ref(profile["schema_ref"])


def _require_released_schema_ref(schema_ref: str) -> None:
    """Fail unless ``schema_ref`` actually resolves to a released schema object.

    .. warning::

       **DISCLOSED CROSS-LANGUAGE DIVERGENCE, in this function's own message text, and it is
       a CLASS rather than one site.** ``EXTENSIONS.md`` §9 item 13 requires the two engines
       to refuse the same input with byte-identical words, and this message does not. Two
       independent causes, both measured on the same forged manifest:

       * the quoting. Python renders ``{schema_ref!r}`` as ``'urn:…'``; the port renders
         ``JSON.stringify`` as ``"urn:…"``.
       * the INTERPOLATED resolver error. ``registry.resolve_pointer`` renders its own
         diagnostics with ``!r`` while ``registry.ts`` renders them bare and unquoted, so
         Python emits ``unknown schema_ref 'urn:…'`` against the port's
         ``unknown schema_ref urn:…``. That is the root cause and it reaches roughly eleven
         sites across both engines, not this one.

       One of those sites diverges STRUCTURALLY rather than by quote style:
       :func:`validate_profile_against_schema` renders a contradicted value through ``!r``
       where the port uses a key-sorted ``stableKey``, so lists and objects differ in shape
       and not merely in punctuation.

       **Nothing can catch any of it.** ``tooling/differential_fuzz`` compares
       ``expected["error"] != actual["error"]`` -- the error CLASS NAME, never the message --
       so the P8 fuzzer is blind to this class by construction, and
       ``fixtures/canonical-annotations/v1/refusals.json``, which is the record that does
       compare message bytes, replays only ``derive_hash_profile`` and
       ``collect_cross_field_rules``. Nothing routes through here.

       Left as residue deliberately, in the shape ``structural.ts``'s opening ``PARITY NOTE``
       established: unifying it means editing ``registry``'s message text, whose blast radius
       is every diagnostic in both engines, and that is a decision of its own rather than a
       detail of §5.2 or §6.4. What is NOT acceptable is leaving it undisclosed while the
       function immediately below refuses to interpolate the same resolver error and calls
       doing so "the exact divergence §9 item 13 exists to forbid" -- a rule stated in one
       docstring and silently broken in its neighbour is worse than either.

    The guard this replaces stated the right rule and checked nothing: it called
    ``schema_registry()``, which takes no argument, never reads the manifest's
    ``schema_ref``, and discards the registry it builds. A manifest naming
    ``urn:datacompany:definitely-not-released:1`` therefore validated cleanly here — through
    ``validate_hash_profile``, which ``canonical/__init__`` exports as public API — and the
    fault surfaced much later inside the hash view builder as an unrelated-looking
    resolution error, if it surfaced at all.

    The resolution goes through ``resolve_pointer``, the SAME call
    :func:`derive_hash_profile` uses, and that is a correction rather than a detail. Asking
    :func:`schema_registry` instead — the obvious reading of the comment being replaced —
    looks equivalent and is not. ``schema_registry`` is ``@lru_cache(maxsize=1)``d over its
    own build, so it can answer about a DIFFERENT enumeration than the deriver just walked,
    and two foundation tests proved it: they register a probe schema by monkeypatching
    ``registry.canonical_schemas``, the deriver sees the probe through ``resolve_pointer``,
    and the already-built registry does not. Importing ``canonical_schemas`` by name here
    would go stale the same way, because the patch replaces the attribute on the registry
    module and not the object this module bound at import. A guard that resolves a manifest
    against a different tree than produced it is an absent measurement answered from
    somewhere else, which is the failure this repository exists to eliminate.

    Resolvability is the whole check, and deliberately the only one.
    ``canonical-hash-profile.v1`` constrains ``schema_ref`` to
    ``^urn:datacompany:[a-z][a-z0-9-]*:[1-9][0-9]*$`` and :func:`validate_hash_profile` has
    already enforced that before calling here, so there is no fragment to resolve and no
    non-object to guard against. Adding an ``isinstance`` branch on top would read as
    defence in depth while being one more condition that can never evaluate true — the same
    shape as the guard being replaced.
    """
    try:
        resolve_pointer(schema_ref)
    except SchemaValidationError as exc:
        raise HashProfileError(
            f"hash-view manifest declares schema_ref {schema_ref!r}, which is not a released "
            "schema. Nothing can resolve it, so the hash view it claims to describe could "
            f"never be built: {exc}"
        ) from exc


def _by_pointer(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["pointer"]: entry for entry in entries}


def validate_profile_against_schema(profile: Any, schema_ref: str) -> None:
    """Reject a manifest that contradicts the annotations of the schema it claims to hash.

    ``validate_hash_profile`` only proves a manifest is *well formed*. A well-formed
    manifest can still delete every exclusion or re-declare a released array, which would
    let two services compute different "canonical" hashes for the same object and would
    destroy DM-AT-28. The schema's own annotations are the authority, so a supplied
    manifest must be exactly the released derivation plus, at most, the domain additions
    ``merge_profile_extensions`` permits: extra included pointers and extra array
    declarations for paths the envelope does not declare.
    """
    validate_hash_profile(profile)
    if profile["schema_ref"] != schema_ref:
        raise HashProfileError(
            f"hash-view manifest declares schema_ref {profile['schema_ref']!r}, "
            f"which is not the hashed object's {schema_ref!r}"
        )
    if profile["profile_version"] != DERIVATION_PROFILE_VERSION:
        raise HashProfileError(
            f"hash-view manifest declares profile_version {profile['profile_version']!r}, but "
            f"this engine implements derivation profile version {DERIVATION_PROFILE_VERSION}. "
            "profile_version names the rule set that produced the manifest, so a manifest "
            "carrying another version cannot be checked against this derivation. Bumping it "
            "means bumping DERIVATION_PROFILE_VERSION and every released manifest in the same "
            "change."
        )
    released = derive_hash_profile(schema_ref)

    for key, released_value in released.items():
        if key in EXTENSIBLE_PROFILE_KEYS:
            continue
        supplied = profile.get(key)
        if isinstance(released_value, list):
            # Ordered by RFC 8785 canonical bytes, not by repr. repr renders an object's
            # members in insertion order, so two manifests that are the same JSON but whose
            # entries were written {"pointer": ..., "reason": ...} and
            # {"reason": ..., "pointer": ...} sorted differently and the second was rejected
            # as contradicting the released annotations. Any JSON round-trip can reorder
            # members, so that is a false rejection of a valid manifest.
            supplied = sorted(supplied or [], key=_canonical_order)
            released_value = sorted(released_value, key=_canonical_order)
        if supplied != released_value:
            raise HashProfileError(
                f"hash-view manifest {key} contradicts the released annotations of "
                f"{schema_ref}: {profile.get(key)!r} is not the derived {released[key]!r}. "
                "Only included_pointers and arrays may be extended, and only by "
                "merge_profile_extensions."
            )

    missing = sorted(set(released["included_pointers"]) - set(profile["included_pointers"]))
    if missing:
        raise HashProfileError(
            f"hash-view manifest drops released included pointers of {schema_ref}: {missing}"
        )

    declared = _by_pointer(profile["arrays"])
    for entry in released["arrays"]:
        if declared.get(entry["pointer"]) != entry:
            raise HashProfileError(
                f"hash-view manifest re-declares or drops the released array "
                f"{entry['pointer']!r} of {schema_ref}: {declared.get(entry['pointer'])!r} "
                f"is not the derived {entry!r}"
            )

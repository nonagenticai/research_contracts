"""Loading and resolution of the released canonical JSON Schema 2020-12 sources."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from functools import cache, lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, validators
from jsonschema.exceptions import ValidationError
from jsonschema.protocols import Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .errors import SchemaValidationError

__all__ = [
    "CANONICAL_SCHEMA_DIR",
    "FOUNDATION_SCHEMA_DIRS",
    "REPOSITORY_ROOT",
    "SCHEMA_ROOT",
    "canonical_schemas",
    "ecma_262_pattern",
    "foundation_schema_dirs",
    "resolve_pointer",
    "resolve_ref",
    "schema_failure_codes",
    "schema_registry",
    "validate_schema_only",
    "validator_for",
]

#: Repository root as seen from a source checkout (``<root>/src/research_contracts/...``).
#: It is meaningless in an installed layout, which is exactly why the schema directory is
#: resolved by :func:`_schema_root` and not from this alone.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _schema_root() -> Path:
    """Return the released schema tree root in either supported layout.

    An installed distribution carries the schemas inside the package itself
    (``research_contracts/schemas``, shipped by the wheel's ``force-include``); a source
    checkout keeps them at the repository root. Resolving only the second is what made the
    installed package unimportable: ``parents[3]`` of
    ``site-packages/research_contracts/canonical/registry.py`` is the interpreter's
    ``lib/python3.x`` directory, the glob over that nonexistent path returned ``[]``
    without an error, and the real fault surfaced much later as an unrelated
    ``unknown schema_ref 'urn:datacompany:canonical-hash-profile:1#/$defs/exclusion_reason'``
    raised from a module-level import side effect.
    """
    packaged = Path(str(resources.files("research_contracts"))) / "schemas"
    if (packaged / "canonical").is_dir():
        return packaged
    return REPOSITORY_ROOT / "schemas"


SCHEMA_ROOT = _schema_root()
CANONICAL_SCHEMA_DIR = SCHEMA_ROOT / "canonical"

#: The FND-002 foundation tiers, released alongside ``canonical/`` and resolved through the
#: SAME registry. They have to share one registry rather than sit in a second one: a
#: foundation schema ``$ref``s the canonical primitives, the cross-field engine and the
#: hash-profile deriver both resolve through :func:`resolve_pointer`, and a second registry
#: would silently answer "unknown schema_ref" for exactly the composed shapes FND-002 exists
#: to release.
#:
#: ``meta/`` is deliberately NOT here. ``schemas/meta/datacompany-extension-vocabulary.v1`` is
#: the authoring-time gate over these documents, not a released payload contract, and
#: ``tests/test_extension_vocabulary.py`` builds its own registry for it.
#:
#: ``events/`` joined the list on 2026-09-02, when ``research-event-envelope.v1`` was
#: authored. The directory had existed, empty but for a ``.gitkeep``, since 2026-07-30. An
#: empty directory is not a tier: this tuple is a CLOSED list and
#: :func:`foundation_schema_dirs` reads only the names in it, so a document dropped into an
#: unlisted directory is invisible to the registry -- it resolves to nothing, and a producer
#: pointing a ``schema_ref`` at it would be naming a document the registry does not have,
#: which is the precise defect the flow-ledger release exists to have repaired.
#:
#: ``jobs/`` joined on 2026-09-04 with ``durable-job.v1`` and ``job-attempt.v1``. That
#: directory had also existed empty since 2026-07-30, while ``evidence_review_service``
#: shipped the whole durable-job subsystem (``ER-M020``) and ran it in production against
#: no released grammar -- the same shape of gap, one tier over.
FOUNDATION_SCHEMA_DIRS = (
    "common",
    "context",
    "profiles",
    "capabilities",
    "manifests",
    "evidence",
    "events",
    "approvals",
    "jobs",
)


def foundation_schema_dirs() -> tuple[Path, ...]:
    """Return the foundation tier directories, in declaration order.

    Derived from :data:`CANONICAL_SCHEMA_DIR`'s parent rather than from :data:`SCHEMA_ROOT`
    directly, so that relocating the canonical tier relocates the WHOLE released tree with
    it. Reading the foundation tiers from a fixed root while the canonical tier was pointed
    somewhere else would let the emptiness guard below be satisfied by schemas the caller
    had just moved away from -- an absent measurement answered from a different tree.
    """
    return tuple(CANONICAL_SCHEMA_DIR.parent / name for name in FOUNDATION_SCHEMA_DIRS)


def _released_schema_files() -> list[Path]:
    """Every released ``*.schema.json``, canonical tier first, then the foundation tiers.

    A foundation tier that does not exist yet is not an error -- the directories are created
    as the FND-002 tasks land. A canonical tier that does not exist IS an error, and an
    existing tier that holds nothing readable is caught by the emptiness check in
    :func:`canonical_schemas`.
    """
    if not CANONICAL_SCHEMA_DIR.is_dir():
        raise SchemaValidationError(
            f"{CANONICAL_SCHEMA_DIR}: the released canonical schema directory does not exist, so "
            "no canonical schema can be resolved. In an installed distribution the schemas ship "
            "inside the package; check that the wheel force-includes schemas/."
        )
    paths = sorted(CANONICAL_SCHEMA_DIR.glob("*.schema.json"))
    for directory in foundation_schema_dirs():
        if directory.is_dir():
            paths.extend(sorted(directory.glob("*.schema.json")))
    return paths


@lru_cache(maxsize=1)
def canonical_schemas() -> dict[str, Any]:
    """Return every released schema keyed by its ``$id``.

    "Canonical" is the historical name and is kept because every call site and several
    monkeypatching tests use it. The contents are the canonical tier **plus** the FND-002
    foundation tiers (:data:`FOUNDATION_SCHEMA_DIRS`); :data:`CANONICAL_SCHEMA_DIR` still
    names the canonical tier alone, and the released-file-set assertions that glob it are
    unaffected.

    An empty result is a failure, never an answer. ``Path.glob`` over a missing or empty
    directory returns ``[]`` silently, so a packaging fault would otherwise present itself
    as "this repository releases no canonical schemas" -- a zero measurement manufactured
    out of an absent one.
    """
    schemas: dict[str, Any] = {}
    origin: dict[str, Path] = {}
    for path in _released_schema_files():
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise SchemaValidationError(f"{path}: non-empty $id is required")
        if schema_id in schemas:
            raise SchemaValidationError(
                f"{path}: duplicate $id {schema_id!r}, also released by {origin[schema_id]}"
            )
        Draft202012Validator.check_schema(schema)
        schemas[schema_id] = schema
        origin[schema_id] = path
    if not schemas:
        raise SchemaValidationError(
            f"{CANONICAL_SCHEMA_DIR}: exists but holds no *.schema.json, so every canonical "
            "reference would fail to resolve. An empty enumeration is not a clean one."
        )
    return schemas


@lru_cache(maxsize=1)
def schema_registry() -> Registry:
    """Return a ``referencing`` registry holding every released canonical schema.

    The root ``$schema`` is dropped from the *registered copy* only, and the dialect is
    pinned explicitly through ``default_specification`` instead. jsonschema re-derives the
    validator class from ``$schema`` every time it follows a ``$ref`` into a document that
    declares one, which silently discarded :data:`CanonicalValidator` and its ECMA-262
    ``pattern`` semantics the moment validation crossed a document boundary -- which is
    every released reference, since the entry schema is a bare ``$ref``. Nothing about the
    dialect changes: 2020-12 is still the specification, it is now stated once rather than
    twice. ``canonical_schemas()`` still returns the released documents untouched.
    """
    registry = Registry()
    for schema_id, schema in canonical_schemas().items():
        contents = {key: value for key, value in schema.items() if key != "$schema"}
        registry = registry.with_resource(
            schema_id, Resource.from_contents(contents, default_specification=DRAFT202012)
        )
    return registry


def _split_ref(schema_ref: str) -> tuple[str, str]:
    base, _, fragment = schema_ref.partition("#")
    return base, fragment


def resolve_ref(schema_ref: str, base_id: str | None = None) -> tuple[Any, str]:
    """Resolve an absolute or document-relative reference.

    Returns the schema object and the ``$id`` of the document it belongs to, so a walker
    can keep resolving further ``#/$defs/...`` references in the right document.
    """
    base, _ = _split_ref(schema_ref)
    resolved_base = base or base_id
    if resolved_base is None:
        raise SchemaValidationError(f"relative reference {schema_ref!r} has no base document")
    absolute = schema_ref if base else f"{resolved_base}{schema_ref}"
    return resolve_pointer(absolute), resolved_base


def resolve_pointer(schema_ref: str) -> Any:
    """Resolve a ``urn:...#/$defs/name`` reference to its schema object."""
    base, fragment = _split_ref(schema_ref)
    schemas = canonical_schemas()
    if base not in schemas:
        raise SchemaValidationError(f"unknown schema_ref {schema_ref!r}")
    node = schemas[base]
    if not fragment:
        return node
    if not fragment.startswith("/"):
        raise SchemaValidationError(f"unsupported non-pointer fragment in {schema_ref!r}")
    for token in fragment.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            raise SchemaValidationError(f"cannot resolve {schema_ref!r} at {token!r}")
        node = node[token]
    return node


#: The line terminators ECMA-262 ``.`` excludes, as a Python character-class body. Python's
#: ``.`` excludes only ``\n``, so the other three are a silent widening.
_ECMA_LINE_TERMINATORS = "\\n\\r\\u2028\\u2029"


@cache
def ecma_262_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a JSON Schema ``pattern`` with ECMA-262 semantics rather than Python's.

    JSON Schema 2020-12 mandates ECMA-262 regular expressions. Python's ``re`` differs in
    two ways, and both of them fail OPEN on the released anchored patterns:

    * ``$`` in ECMA-262 without the ``m`` flag asserts the end of input. Python's ``$`` also
      matches immediately before a trailing ``\\n``, so ``"sha256:<64 hex>\\n"`` matched
      ``^sha256:[0-9a-f]{64}$`` and ``"2026-01-01T00:00:00Z\\n"`` matched the released
      timestamp pattern. Every anchored pattern in ``stable-identity.v1`` and
      ``model-conformance-record.v1`` was affected.
    * ``.`` in ECMA-262 excludes every line terminator (``\\n``, ``\\r``, U+2028, U+2029);
      Python's excludes only ``\\n``, so ``"a\\rb"`` matched ``^\\S(?:.*\\S)?$``.

    A conforming validator in another language rejects exactly those values, so this is a
    two-language divergence in the contract, not a Python implementation detail. The
    translation is textual and deliberately narrow: ``$`` becomes ``\\Z`` and ``.`` becomes
    the ECMA-262 dot class, both only outside a character class and only when unescaped.

    Known residual divergences, none of which any released pattern relies on: Python's
    ``\\d``/``\\w``/``\\s`` are Unicode-aware where ECMA-262's are not (no released pattern
    uses them for a bounded set -- the timestamp, UUID and digest patterns all spell their
    classes out as ``[0-9a-f]``), and ECMA-262 treats ``[]`` as an empty class where Python
    treats ``]`` there as a literal.
    """
    return re.compile(_translate(pattern))


def _class_end(pattern: str, start: int) -> int:
    """Return the index just past the character class that begins at ``start``.

    Character classes are copied through untouched, so the scanner only has to find where
    each one ends. It follows Python's own class grammar (a leading ``]``, optionally after
    ``^``, is a literal member) so that it stays in step with the parser that will compile
    the translated pattern.
    """
    index = start + 1
    if index < len(pattern) and pattern[index] == "^":
        index += 1
    if index < len(pattern) and pattern[index] == "]":
        index += 1
    while index < len(pattern):
        if pattern[index] == "\\":
            index += 2
            continue
        if pattern[index] == "]":
            return index + 1
        index += 1
    return len(pattern)  # Unterminated; re.compile reports it against the original text.


def _translate(pattern: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\":
            out.append(pattern[index : index + 2])
            index += 2
            continue
        if character == "[":
            end = _class_end(pattern, index)
            out.append(pattern[index:end])
            index = end
            continue
        if character == "$":
            out.append(r"\Z")
        elif character == ".":
            out.append(f"[^{_ECMA_LINE_TERMINATORS}]")
        else:
            out.append(character)
        index += 1
    return "".join(out)


def _ecma_pattern_keyword(
    _validator: Any, patrn: str, instance: Any, _schema: Any
) -> Iterator[ValidationError]:
    """``pattern``, evaluated with ECMA-262 semantics. Message text is jsonschema's."""
    if isinstance(instance, str) and ecma_262_pattern(patrn).search(instance) is None:
        yield ValidationError(f"{instance!r} does not match {patrn!r}")


def _ecma_pattern_properties_keyword(
    validator: Any, patterns: dict[str, Any], instance: Any, _schema: Any
) -> Iterator[ValidationError]:
    """``patternProperties``, evaluated with the same ECMA-262 semantics.

    No released canonical schema uses this keyword today; it is overridden anyway so the
    two regex keywords cannot drift apart the moment one does.
    """
    if not isinstance(instance, dict):
        return
    for patrn, subschema in patterns.items():
        compiled = ecma_262_pattern(patrn)
        for name, value in instance.items():
            if compiled.search(name) is not None:
                yield from validator.descend(value, subschema, path=name, schema_path=patrn)


#: ``Draft202012Validator`` with the two regex keywords corrected to ECMA-262 semantics.
CanonicalValidator = validators.extend(
    Draft202012Validator,
    {"pattern": _ecma_pattern_keyword, "patternProperties": _ecma_pattern_properties_keyword},
)


@cache
def validator_for(schema_ref: str) -> Validator:
    """Return a format-checking validator for a released schema or one of its ``$defs``.

    The validator schema is a bare ``$ref`` so that the target keeps its own base URI and
    every relative ``#/$defs/...`` reference inside it still resolves against its own
    document rather than against the wrapper.
    """
    # Fail fast and with a useful message on a typo, before jsonschema lazily resolves.
    if not isinstance(resolve_pointer(schema_ref), dict):
        raise SchemaValidationError(f"{schema_ref!r} does not resolve to a schema object")
    return CanonicalValidator(
        {"$ref": schema_ref}, registry=schema_registry(), format_checker=FormatChecker()
    )


def schema_failure_codes(instance: Any, schema_ref: str) -> list[tuple[str, str]]:
    """Return each JSON Schema failure as a LANGUAGE-NEUTRAL ``(pointer, keyword)`` pair.

    This is the vocabulary defect D2f says is missing. ``validate_schema_only`` renders
    ``jsonschema``'s English message text, which no second implementation reproduces:
    Python says ``"'x' does not match 'y'"`` where Ajv says ``'must match pattern "y"'``, and
    ``"Unevaluated properties are not allowed ('total' was unexpected)"`` where Ajv says
    ``"must NOT have unevaluated properties"`` without naming the member at all. A fixture
    that pins the prose can only ever be replayed by the engine whose prose it pinned.

    Both halves of the pair are defined by the specification rather than by an
    implementation: the pointer is the RFC 6901 instance location, and the keyword is the
    JSON Schema 2020-12 keyword that failed (``required``, ``pattern``, ``enum``, ``not``,
    ``unevaluatedProperties``, ``uniqueItems``, ...). Two conforming validators therefore
    agree on it by construction, not by coincidence.

    The result is sorted and de-duplicated so it is a comparable set rather than an
    order-dependent list -- the order in which a validator visits subschemas is not part of
    any specification.
    """
    validator = validator_for(schema_ref)
    seen = {
        (
            "/" + "/".join(str(part) for part in error.absolute_path),
            str(error.validator),
        )
        for error in validator.iter_errors(instance)
    }
    return sorted(seen)


def validate_schema_only(instance: Any, schema_ref: str) -> list[str]:
    """Return the JSON Schema errors of ``instance`` against ``schema_ref``, and nothing else.

    This is the raw JSON Schema layer. It deliberately does NOT evaluate the released
    ``x-datacompany-cross-field`` rules, because JSON Schema cannot express them, so on its own
    it accepts objects the released contract rejects (an interval that is empty, a receipt
    whose subject is not owned by its consumer). Callers validating a canonical instance
    want ``research_contracts.canonical.validate_instance``, which pairs the two. This
    entry point exists for the places that must reason about the schema layer alone.
    """
    validator = validator_for(schema_ref)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors
    ]

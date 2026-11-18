"""FND-002 done-when: "schema generation passes ... in Python and TypeScript".

Generates typed bindings for the released foundation schemas in **both** languages from
one walk of one registry, so the two cannot describe different contracts. The output is
committed, and ``--check`` re-derives it and refuses any difference, which is what makes the
committed files evidence rather than decoration.

Three properties are load-bearing, and each one exists because its absence is a known
failure mode in this repository:

1. **No silent skip.** Every schema keyword the walker meets is either translated or listed
   in :data:`IGNORED_KEYWORDS` as a constraint that has no type-level meaning. An unknown
   keyword raises. A generator that skipped what it did not understand would emit a type
   that is *weaker than the schema* while reporting success -- which is precisely the
   "generated types contain no weaker local aliases" clause of ``FND-CANONICAL-CONTRACT``.
2. **No weaker local alias.** A ``$ref`` to a released primitive always emits that
   primitive's generated alias. ``content_hash`` is never re-emitted as a bare ``str``; it
   is ``ContentHash``, generated once from ``stable-identity:1``. If it were inlined, a
   consumer could pass any string where the contract requires ``sha256:<64 hex>`` and the
   type checker would agree.
3. **No empty generation.** Generating zero types, or zero types for a schema that exists,
   is an error. ``Path.glob`` over a missing directory returns ``[]`` in silence, and this
   repository has already shipped one gate that read that as health.

The emitted types are structural, not validating: they are what a consumer programs
against. Validation remains the released engine's job in both languages, and the generated
docstring says so at the top of each file so nobody mistakes a ``TypedDict`` for a gate.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..canonical.registry import FOUNDATION_SCHEMA_DIRS, canonical_schemas
from .errors import ContractError
from .paths import REPOSITORY_ROOT

PYTHON_TARGET = REPOSITORY_ROOT / "generated" / "python" / "foundation_types.py"
TYPESCRIPT_TARGET = REPOSITORY_ROOT / "generated" / "typescript" / "foundationTypes.ts"

#: Schemas whose types are generated. The foundation tier plus every canonical document it
#: reaches by ``$ref`` -- the primitives have to be generated or property 2 is unenforceable.
#:
#: ``typed-refs:1`` is canonical-tier by directory and is listed here deliberately: FND-002
#: task 4 released four registered reference types that nothing else ``$ref``s yet, so
#: without this line they generate no type in either language and the drift gate, the
#: TypeScript compile and the parity assertions never touch them at all.
#:
#: ``locator-selector:1`` is deliberately ABSENT, and its absence costs nothing: every shape
#: it releases is reached by ``$ref`` from the two evidence documents below, so all six
#: selector bodies and the union over them are generated anyway. Listing the document root
#: would additionally request its six ``if``/``then`` guards, which are pure constraint and
#: have no type to name -- :meth:`Walker.emit` would reach ``render`` and raise "no type
#: could be derived", which is the correct behaviour for a shape and the wrong question to
#: ask of a rule.
FOUNDATION_SCHEMA_IDS = (
    "urn:datacompany:capability-status:1",
    "urn:datacompany:evidence-location-candidate:1",
    "urn:datacompany:evidence-location-version:1",
    "urn:datacompany:page:1",
    "urn:datacompany:problem-details:1",
    "urn:datacompany:release-ref:1",
    "urn:datacompany:research-access-context:1",
    "urn:datacompany:run-manifest:1",
    "urn:datacompany:typed-refs:1",
)

#: Keywords that constrain values without changing the TYPE a consumer programs against.
#: Listing them is the point: an unlisted keyword raises, so widening the contract with a
#: keyword the generator has never seen cannot silently produce an unchanged type.
IGNORED_KEYWORDS = frozenset(
    {
        "$comment",
        "$id",
        "$schema",
        "additionalProperties",
        "description",
        "else",
        "format",
        "if",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "not",
        "pattern",
        "readOnly",
        "then",
        "title",
        "unevaluatedProperties",
        "uniqueItems",
        "x-datacompany-array",
        "x-datacompany-composition-point",
        "x-datacompany-cross-field",
        "x-datacompany-hash-excluded",
        "x-datacompany-hash-exclusion-reason",
        "x-datacompany-hash-opaque",
    }
)

#: The Python spellings a branded alias is minted over.
_SCALAR_PYTHON = frozenset({"str", "int", "float", "bool"})

SCALARS = {
    "string": ("str", "string"),
    "integer": ("int", "number"),
    "number": ("float", "number"),
    "boolean": ("bool", "boolean"),
}

_WORD = re.compile(r"[^0-9a-zA-Z]+")

#: A generated type name as it appears inside an emitted alias body. Every generated name is
#: PascalCase (:func:`type_name` runs :func:`pascal` over it), so this over-matches -- it also
#: finds ``NewType`` and ``Literal`` -- and the caller intersects the result with the set of
#: names actually generated, which is what makes the over-match harmless.
_GENERATED_NAME = re.compile(r"[A-Z][A-Za-z0-9]*")


def pascal(text: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in _WORD.split(text) if part)


def type_name(schema_id: str, pointer: str | None) -> str:
    """Stable generated name for a document root or one of its ``$defs``."""
    stem = schema_id.removeprefix("urn:datacompany:").rpartition(":")[0]
    return pascal(stem) if pointer is None else pascal(pointer)


#: Keywords that make a schema node describe a SHAPE rather than merely constrain one.
_SHAPE_KEYWORDS = frozenset(
    {"$ref", "allOf", "anyOf", "const", "enum", "items", "oneOf", "properties", "type"}
)


def is_constraint_only(node: dict[str, Any]) -> bool:
    """True for a node that narrows legal values without describing a type.

    The released conditionals are all of this kind: ``resource_scope_conditional`` is an
    ``if``/``then``/``else`` body and ``unavailable_requires_a_reason`` is another. They are
    composed by ``allOf`` exactly like a shape branch is, so the generator has to tell them
    apart or it invents a named type for a rule.
    """
    return not (set(node) & _SHAPE_KEYWORDS)


class Walker:
    """One walk of the registry, emitting both languages from the same traversal."""

    def __init__(self) -> None:
        self.schemas = canonical_schemas()
        self.python: dict[str, str] = {}
        self.typescript: dict[str, str] = {}
        self.order: list[str] = []
        self.pending: list[tuple[str, str | None]] = []
        self.done: set[tuple[str, str | None]] = set()

    # ------------------------------------------------------------------ resolution ---

    def resolve(self, schema_id: str, pointer: str | None) -> dict[str, Any]:
        document = self.schemas.get(schema_id)
        if document is None:
            raise ContractError(f"unknown schema {schema_id!r}; generation cannot proceed")
        if pointer is None:
            return document
        node = document.get("$defs", {}).get(pointer)
        if not isinstance(node, dict):
            raise ContractError(f"{schema_id}#/$defs/{pointer} does not resolve to a schema")
        return node

    def ref_target(self, ref: str, base: str) -> tuple[str, str | None]:
        """Return the (document, $defs name) a ``$ref`` addresses, rejecting anything else."""
        document, _, fragment = ref.partition("#")
        document = document or base
        if not fragment:
            return document, None
        prefix = "/$defs/"
        if not fragment.startswith(prefix) or "/" in fragment[len(prefix) :]:
            raise ContractError(
                f"{base}: $ref {ref!r} addresses something other than a document root or a "
                "top-level $defs entry; the generator refuses to guess a name for it"
            )
        return document, fragment[len(prefix) :]

    def request(self, schema_id: str, pointer: str | None) -> str:
        key = (schema_id, pointer)
        if key not in self.done:
            self.done.add(key)
            self.pending.append(key)
        return type_name(schema_id, pointer)

    # -------------------------------------------------------------------- rendering ---

    def render(self, node: dict[str, Any], base: str, hint: str) -> tuple[str, str]:
        """Return the (Python, TypeScript) expression for ``node``."""
        unknown = (
            set(node)
            - IGNORED_KEYWORDS
            - {
                "$defs",
                "$ref",
                "allOf",
                "anyOf",
                "const",
                "enum",
                "items",
                "oneOf",
                "properties",
                "required",
                "type",
            }
        )
        if unknown:
            raise ContractError(
                f"{base} ({hint}): unhandled schema keyword(s) {sorted(unknown)}. The generator "
                "refuses to emit a type it cannot justify: silently ignoring a keyword produces "
                "a binding weaker than the schema while reporting success."
            )

        if "$ref" in node:
            document, pointer = self.ref_target(node["$ref"], base)
            name = self.request(document, pointer)
            return name, name

        if "enum" in node:
            members = node["enum"]
            if not all(isinstance(m, str) for m in members):
                raise ContractError(f"{base} ({hint}): only string enums are generated")
            rendered = ", ".join(f'"{m}"' for m in sorted(members))
            return f"Literal[{rendered}]", " | ".join(f'"{m}"' for m in sorted(members))

        if "const" in node:
            value = node["const"]
            if isinstance(value, str):
                return f'Literal["{value}"]', f'"{value}"'
            if isinstance(value, bool):
                return f"Literal[{value}]", str(value).lower()
            if isinstance(value, int):
                return f"Literal[{value}]", str(value)
            raise ContractError(f"{base} ({hint}): unsupported const {value!r}")

        for combiner in ("allOf", "anyOf", "oneOf"):
            if combiner in node:
                # An in-place applicator over a set of $refs is a COMPOSITION, and the
                # composed object's members come from all of them. Rendering it as an
                # intersection keeps the composed shape; rendering it as the first branch
                # would drop the rest and produce exactly the "weaker alias" this refuses.
                parts = [
                    self.render(branch, base, f"{hint}/{combiner}[{index}]")
                    for index, branch in enumerate(node[combiner])
                    if set(branch) - IGNORED_KEYWORDS
                ]
                if not parts:
                    # Every branch was pure constraint (an if/then/else conditional). It
                    # narrows values, never the type, so the surrounding object stands.
                    return self.render_object(node, base, hint)
                if "properties" in node:
                    parts.append(self.render_object(node, base, hint))
                joiner_py = " & " if combiner == "allOf" else " | "
                py = joiner_py.join(p for p, _ in parts)
                ts = (" & " if combiner == "allOf" else " | ").join(t for _, t in parts)
                # Python has no intersection type. An allOf composition is emitted as the
                # LAST-resort union of its parts only for anyOf/oneOf; for allOf the Python
                # binding names the parts and lets the consumer inherit from all of them.
                if combiner == "allOf":
                    py = ", ".join(p for p, _ in parts)
                return py, ts

        if "properties" in node or node.get("type") == "object":
            return self.render_object(node, base, hint)

        if node.get("type") == "array":
            items = node.get("items")
            if not isinstance(items, dict):
                # A bare `type: array` with no item schema is a deliberate hole in
                # page:1#/$defs/page_response -- the element schema comes from the composing
                # operation. Unknown is the honest rendering; `Any` would claim more.
                return "list[object]", "unknown[]"
            item_py, item_ts = self.render(items, base, f"{hint}/items")
            return f"list[{item_py}]", f"{item_ts}[]"

        declared = node.get("type")
        if isinstance(declared, str) and declared in SCALARS:
            return SCALARS[declared]
        raise ContractError(
            f"{base} ({hint}): no type could be derived from {sorted(node)}; refusing to guess"
        )

    def render_object(self, node: dict[str, Any], base: str, hint: str) -> tuple[str, str]:
        """Objects are only ever emitted as NAMED types, so a nested one is hoisted."""
        raise ContractError(
            f"{base} ({hint}): an inline object literal has no generated name. Give it a "
            "$defs entry and $ref it, so both languages agree on what the type is called."
        )

    # ------------------------------------------------------------------- generation ---

    def is_definitions_only(self, node: dict[str, Any]) -> bool:
        """True for a document that is a ``$defs`` bag with no instance shape of its own.

        ``page:1`` and ``release-ref:1`` are both of this kind: nothing validates against the
        document root, so there is no root type to name. Every ``$defs`` entry is generated
        instead. Falling through to :meth:`render` here would raise "no type could be
        derived", which is correct behaviour for a shape and wrong for a namespace.
        """
        return "$defs" in node and not (set(node) - IGNORED_KEYWORDS - {"$defs"})

    def emit(self, schema_id: str, pointer: str | None) -> None:
        node = self.resolve(schema_id, pointer)
        if pointer is None and self.is_definitions_only(node):
            for entry in sorted(node["$defs"]):
                self.request(schema_id, entry)
            return
        name = type_name(schema_id, pointer)
        self.order.append(name)

        collected: dict[str, Any] = {}
        required: set[str] = set()
        bases: list[str] = []

        def absorb(current: dict[str, Any], current_base: str) -> None:
            unknown = (
                set(current)
                - IGNORED_KEYWORDS
                - {
                    "$defs",
                    "$ref",
                    "allOf",
                    "anyOf",
                    "const",
                    "enum",
                    "items",
                    "oneOf",
                    "properties",
                    "required",
                    "type",
                }
            )
            if unknown:
                raise ContractError(
                    f"{current_base} ({name}): unhandled schema keyword(s) {sorted(unknown)}"
                )
            required.update(current.get("required") or [])
            # COMPOSED FIRST, LOCAL LAST. An `allOf: [$ref X]` beside a local `properties`
            # entry for a member X also declares is an INTERSECTION, and the generator can
            # emit only one of the two. The local sibling is always the narrowing one --
            # that is the only reason to write it -- so it must win.
            #
            # Collecting local properties first was silently wrong in exactly the direction
            # the module docstring's property 2 forbids: every `typed-refs:1` definition is
            # `allOf[$ref pinned-version-ref:1]` plus `properties.schema_ref.const`, and the
            # composed `schema_ref: SchemaRef` overwrote the const. The four typed refs
            # generated as four byte-identical copies of PinnedVersionRef, so a consumer
            # could pass a DocumentVersionRef where an ArtifactRef is required and both the
            # type checker and the parity gates would agree.
            for branch in current.get("allOf") or []:
                if "$ref" in branch:
                    document, target = self.ref_target(branch["$ref"], current_base)
                    resolved = self.resolve(document, target)
                    # A branch that is PURE CONSTRAINT -- a scope conditional, a
                    # required-iff rule -- narrows which values are legal without adding a
                    # member. It has no type to name and must not be requested as one:
                    # `resource_scope_conditional` and `available_requires_the_full_chain`
                    # are both if/then bodies, and generating a type called
                    # "AvailableRequiresTheFullChain" would be a name for nothing.
                    if is_constraint_only(resolved):
                        continue
                    bases.append(self.request(document, target))
                    absorb(resolved, document)
                else:
                    absorb(branch, current_base)
            for member, subschema in (current.get("properties") or {}).items():
                collected[member] = (subschema, current_base)

        if "properties" in node or node.get("allOf") or node.get("type") == "object":
            absorb(node, schema_id)

        if not collected and not node.get("allOf"):
            python, typescript = self.render(node, schema_id, name)
            if python in _SCALAR_PYTHON:
                # A BRANDED alias, not a bare `X = str`. The FND-CANONICAL-CONTRACT gate
                # requires that "generated types contain no weaker local aliases", and a
                # transparent alias is exactly a weaker one: `ContentHash = str` lets a
                # consumer pass any string where the contract demands sha256:<64 hex> and
                # the type checker agrees. NewType in Python and an intersection brand in
                # TypeScript both make that a type error in the language the consumer is
                # actually writing.
                self.python[name] = f'{name} = NewType("{name}", {python})'
                self.typescript[name] = (
                    f'export type {name} = {typescript} & {{ readonly __brand: "{name}" }};'
                )
            else:
                self.python[name] = f"{name} = {python}"
                self.typescript[name] = f"export type {name} = {typescript};"
            return

        # `total=True` (the default) plus `NotRequired[...]` on the optional members, so the
        # composed `required` set is stated in the TYPE rather than beside it. The previous
        # spelling emitted an unconditional `total=False` and marked the difference with a
        # trailing `# optional` comment, which no type checker reads: 230 of 339 members were
        # required by the schemas and optional to every consumer, while the TypeScript twin
        # generated from this same line encoded it correctly with `?:`. A comment is a SECOND
        # source of truth for a fact the annotation already carries, so it is removed rather
        # than kept alongside.
        py_lines = [f"class {name}(TypedDict):", f'    """{schema_id} — generated."""']
        ts_lines = [f"export interface {name} {{"]
        for member in sorted(collected):
            subschema, member_base = collected[member]
            member_py, member_ts = self.render(subschema, member_base, f"{name}.{member}")
            # NOTE for a future reader: an `allOf` composition renders on the Python side as
            # `A, B` (see `render`, which has no intersection type to emit). No OPTIONAL member
            # renders that way in the corpus today, and if one ever did this would emit
            # `NotRequired[A, B]`, which PEP 649 evaluates at class creation and rejects with
            # `TypeError: NotRequired accepts only a single type`. That is the right failure --
            # loud, at import, caught by `test_the_generated_python_binding_actually_imports` --
            # rather than a silently weaker binding. It is recorded here so it reads as a
            # deliberate strictness rather than an oversight.
            annotation = member_py if member in required else f"NotRequired[{member_py}]"
            py_lines.append(f"    {member}: {annotation}")
            ts_lines.append(f"  {member}{'' if member in required else '?'}: {member_ts};")
        ts_lines.append("}")
        if len(py_lines) == 2:
            py_lines.append("    pass")
        self.python[name] = "\n".join(py_lines)
        self.typescript[name] = "\n".join(ts_lines)

    def run(self) -> None:
        for schema_id in FOUNDATION_SCHEMA_IDS:
            self.request(schema_id, None)
        while self.pending:
            schema_id, pointer = self.pending.pop(0)
            self.emit(schema_id, pointer)
        if not self.order:
            raise ContractError(
                "generation produced zero types. An empty enumeration is not a clean one: "
                "check that the foundation schema directories "
                f"{list(FOUNDATION_SCHEMA_DIRS)} are populated and registered."
            )
        self.order = self.emission_order()

    def emission_order(self) -> list[str]:
        """Order the emitted names so every ALIAS follows the names it evaluates.

        ``emit`` visits the registry breadth-first, which puts a type where it was first
        REQUESTED rather than where it can be evaluated. That is fine for a ``class`` body --
        PEP 649 defers every member annotation on this repository's 3.14 floor, so a class may
        name anything in any order -- and it is a NameError for an alias, whose right-hand
        side is an ordinary expression evaluated at import time.

        The generated module deliberately does NOT carry ``from __future__ import
        annotations``: PEP 563 would stringify ``NotRequired[T]`` into something
        ``TypedDict`` cannot recognise, and every optional member would land in
        ``__required_keys__``. Deferral therefore comes from PEP 649 rather than PEP 563, and
        this ordering stays exactly as necessary as it was.

        The corpus tolerated it until FND-002 task 4 by luck: no released alias had ever
        named another generated type. ``AnySelector = DocumentSelector | ...`` is the first,
        and it was emitted eleven definitions before the six it unions, so the committed
        binding raised ``NameError: name 'DocumentSelector' is not defined`` on import while
        ``--check`` reported no drift and ``ruff check``, then scoped to ``src scripts tests``,
        never looked at ``generated/`` at all. A binding that cannot be imported is weaker than
        the schema it claims, which is the exact failure this module's docstring says it exists
        to prevent. Both checkers are scoped to ``generated`` now, but neither EXECUTES the
        file, so the import assertion in the test suite is still the only thing that would
        catch it.

        The same order is used for TypeScript. TypeScript hoists its type declarations and
        does not need it, but two files generated from one walk that listed their types in
        two different orders would be a difference nothing explains.
        """
        remaining = {name: self.alias_dependencies(name) for name in self.order}
        position = {name: index for index, name in enumerate(self.order)}
        ordered: list[str] = []
        while remaining:
            ready = sorted(
                (name for name, needs in remaining.items() if not needs - set(ordered)),
                key=lambda name: position[name],
            )
            if not ready:
                raise ContractError(
                    "the generated aliases form a cycle and cannot be emitted in any order "
                    f"that evaluates: {sorted(remaining)}. An alias is an expression, not a "
                    "deferred annotation, so a cycle among aliases has no valid Python "
                    "spelling; give one of them a $defs entry with an object shape so it is "
                    "emitted as a class instead."
                )
            for name in ready:
                ordered.append(name)
                del remaining[name]
        return ordered

    def alias_dependencies(self, name: str) -> set[str]:
        """The generated names an alias must be emitted after, or an empty set for a class."""
        body = self.python[name]
        if body.startswith("class "):
            return set()
        generated = set(self.order)
        referenced = set(_GENERATED_NAME.findall(body.partition("=")[2]))
        return (referenced & generated) - {name}


HEADER = (
    "GENERATED FILE — do not edit by hand.\n\n"
    "Regenerate with `python scripts/generate_types.py`; CI runs the same script with\n"
    "`--check` and fails on any difference, so an edit here is reverted by the next gate.\n\n"
    "These are STRUCTURAL bindings, not validators. They say what a consumer programs\n"
    "against; they do not enforce a pattern, an interval, a scope conditional or any\n"
    "released cross-field rule. Validation is `research_contracts.canonical."
    "validate_instance`\nin Python and the canonical package in TypeScript. A value that "
    "type-checks here has\nnot been validated.\n"
)


def ruff_format(source: str) -> str:
    """Return ``source`` as ``ruff format`` would write it.

    The generator formats its own output rather than emitting text that a hook will later
    rewrite. `ruff-format` in .pre-commit-config.yaml matches every Python file, including
    the generated one, so an unformatted emission would be reformatted on commit and the
    `--check` drift gate would then fail against the generator that produced it -- a gate
    permanently red for a reason that has nothing to do with the schemas. Running the same
    formatter here makes the two agree by construction.

    A ruff that is absent or fails is a hard error, never a fallback to the raw text: a
    silent fallback would reintroduce exactly the drift this exists to prevent.
    """
    ruff = shutil.which("ruff")
    if ruff is None:
        raise ContractError(
            "ruff is not on PATH, so the generated bindings cannot be formatted the way the "
            "ruff-format hook will format them. Run `uv sync --all-groups`. Falling back to "
            "unformatted output would leave the --check drift gate permanently red."
        )
    result = subprocess.run(  # noqa: S603
        [ruff, "format", "--no-cache", "--stdin-filename", "foundation_types.py", "-"],
        input=source,
        capture_output=True,
        text=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )
    if result.returncode != 0:
        raise ContractError(
            f"ruff format failed over the generated bindings ({result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout


#: Every ``typing`` name the emitter can put in a body. The import line is DERIVED from the
#: body rather than fixed, because a fixed list is wrong in both directions: it was missing
#: ``NotRequired`` (so requiredness could not be expressed at all, whatever the schemas said),
#: and a name that stops being emitted would leave an unused import behind — an F401 the
#: moment ``generated/`` is brought into ruff's scope, i.e. a gate that fails for a reason
#: that has nothing to do with the schemas.
_TYPING_NAMES = ("Literal", "NewType", "NotRequired", "TypedDict")


def typing_imports(body: str) -> list[str]:
    """The ``typing`` names ``body`` actually uses, as a whole-word match."""
    return [name for name in _TYPING_NAMES if re.search(rf"\b{name}\b", body)]


def render_python(walker: Walker) -> str:
    body = "\n\n\n".join(walker.python[name] for name in walker.order)
    used = typing_imports(body)
    if not used:
        raise ContractError(
            "the generated Python binding uses no typing construct at all, which no non-empty "
            "emission can do: every class is a TypedDict and every scalar alias is a NewType. "
            "An empty enumeration is not a clean one."
        )
    # NO `from __future__ import annotations`, deliberately, and this is load-bearing rather
    # than tidying. PEP 563 stringifies every annotation, and a stringified `NotRequired[T]`
    # is opaque to `TypedDict.__new__`: it cannot tell the qualifier from the type, so it
    # assigns the member to `__required_keys__` regardless. With the future import present,
    # all 339 members read as required to the interpreter and all 109 `NotRequired` markers
    # were decoration -- the same defect as `total=False` plus a `# optional` comment, one
    # layer deeper. PEP 649 (the default on this repository's floor of 3.14) evaluates
    # annotations lazily anyway, so class members may still name a type emitted later; ALIAS
    # bodies are ordinary expressions under both regimes, which is what `emission_order`
    # exists for.
    return ruff_format(
        f'"""{HEADER}"""\n\n'
        f"from typing import {', '.join(used)}\n\n"
        f"__all__ = {sorted(walker.order)!r}\n\n\n"
        f"{body}\n"
    )


def render_typescript(walker: Walker) -> str:
    body = "\n\n".join(walker.typescript[name] for name in walker.order)
    commented = "\n".join(f" * {line}" if line else " *" for line in HEADER.splitlines())
    return f"/**\n{commented}\n */\n\n{body}\n"


def generate() -> dict[Path, str]:
    walker = Walker()
    walker.run()
    return {PYTHON_TARGET: render_python(walker), TYPESCRIPT_TARGET: render_typescript(walker)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-derive the bindings and fail on any difference from the committed files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outputs = generate()
    except ContractError as exc:
        print(exc, file=sys.stderr)
        return 1

    drifted: list[str] = []
    for path, text in outputs.items():
        if args.check:
            if not path.is_file():
                drifted.append(f"{path}: generated binding is missing entirely")
            elif path.read_text(encoding="utf-8") != text:
                drifted.append(f"{path}: committed binding differs from the schemas it claims")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    if drifted:
        for message in drifted:
            print(message, file=sys.stderr)
        print("run `python scripts/generate_types.py` and commit the result", file=sys.stderr)
        return 1
    verb = "match the released schemas" if args.check else "regenerated"
    print(f"foundation type bindings {verb}: {', '.join(str(p.name) for p in outputs)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

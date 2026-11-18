"""Pre-ADR regulatory denylist enforcement.

Three properties this module has to hold, each of which was a proven bypass in
the FND-001 baseline:

* it inspects **every** key and **every** string in a document, not a hand-picked
  list of ``$id``/``title``/``const``/``enum``/``properties`` positions;
* it matches on word boundaries, so ``illegal_event_count`` is not a
  ``legal_event`` activation and ``paralegal_status`` is not a ``legal_status``
  one — a gate that punishes correct authoring teaches workarounds;
* it resolves local ``$ref`` before deciding a guarded activation discriminator
  is open, for the same reason.

A fourth property was a proven bypass found by the adversarial verifier: the
matcher kept only ``isascii() and isalnum()`` characters and treated everything
else as a separator, so a single CYRILLIC SMALL LETTER A (U+0430) substituted
into ``regulatory_effect`` *deleted* a character from the squashed form and the
token no longer matched — while rendering identically to a reviewer.
Confusable folding (``denylist.fold_confusables``) is what closes that.
Zero-width characters were and remain fine: they are separators, and
separators vanish from the squashed form rather than corrupting it.

A fifth property, and the reason the folding table now lives in ``denylist``
rather than here: the fold has to be reachable from **both** matchers. It was
reachable from one. ``forbidden_match`` folded; ``_discriminator_errors`` called
the raw ``normalize_token`` and was therefore blind to precisely the
substitutions this module's own docstring claimed to have closed — ``work_type``
with a fullwidth ``w`` (U+FF57) or a Cyrillic ``o`` (U+043E) raised nothing at
all, while ``work_type``, ``workType``, ``WORK_TYPE`` and ``work-type`` were all
caught. Two matchers agreeing on the token half and disagreeing on the
discriminator half is not a defence, it is a documented door.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .denylist import Denylist, fold_confusables, normalize_token

#: JSON pointer style path for reporting.
Pointer = tuple[str, ...]


def _pointer(path: Pointer) -> str:
    return "/".join(path) or "<root>"


def squash_with_word_starts(value: str) -> tuple[str, frozenset[int]]:
    """Normalize ``value`` and record where each word begins in the squashed form.

    Word boundaries come from non-alphanumeric separators, ``camelCase``
    transitions and letter/digit transitions. Keeping the offsets is what lets
    the matcher require a hit to start at a word boundary instead of anywhere in
    the squashed string.

    ``value`` is confusable-folded first, so a homoglyph contributes its ASCII
    skeleton instead of silently deleting a character from the squashed form.
    """
    value = fold_confusables(value)
    squashed: list[str] = []
    starts: set[int] = set()
    previous: str | None = None
    at_word_start = True

    for character in value:
        if character.isascii() and character.isalnum():
            if previous is not None:
                is_digit = character.isdigit()
                if character.isupper() and previous == "lower":
                    at_word_start = True
                elif is_digit != (previous == "digit"):
                    at_word_start = True
            if at_word_start:
                starts.add(len(squashed))
            squashed.append(character.lower())
            at_word_start = False
            previous = (
                "digit" if character.isdigit() else ("upper" if character.isupper() else "lower")
            )
        else:
            at_word_start = True
            previous = None

    return "".join(squashed), frozenset(starts)


def forbidden_match(value: str, denylist: Denylist) -> str | None:
    """Return the declared spelling of the forbidden token ``value`` activates."""
    if not value:
        return None
    squashed, starts = squash_with_word_starts(value)
    if not squashed:
        return None
    for normalized, declared in denylist.normalized_forbidden.items():
        index = squashed.find(normalized)
        while index != -1:
            if index in starts:
                return declared
            index = squashed.find(normalized, index + 1)
    return None


def iter_document_strings(node: Any, path: Pointer = ()) -> Iterator[tuple[str, Pointer, str]]:
    """Yield every object key and every string leaf in a parsed document.

    ``kind`` is ``"key"`` or ``"value"``. This deliberately covers ``$defs`` keys,
    ``patternProperties`` keys, ``required`` array entries and ``description``
    prose — all four were verified bypasses of the position-specific scan.
    """
    if isinstance(node, dict):
        for key, child in node.items():
            key_text = str(key)
            child_path = (*path, key_text)
            yield "key", child_path, key_text
            yield from iter_document_strings(child, child_path)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from iter_document_strings(child, (*path, str(index)))
    elif isinstance(node, str):
        yield "value", path, node


def _resolve_ref(root: Any, ref: str) -> Any | None:
    """Resolve a local JSON pointer ``$ref`` against ``root``; None if not local."""
    if not ref.startswith("#"):
        return None
    pointer = ref[1:].lstrip("/")
    node: Any = root
    if pointer:
        for raw in pointer.split("/"):
            part = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                return None
    return node


def declared_values(schema: Any, root: Any, seen: frozenset[str] = frozenset()) -> list[str] | None:
    """Return the closed set of string values a subschema admits, or None if open.

    Follows local ``$ref``. An unresolvable or remote ``$ref`` returns None so the
    gate fails closed.
    """
    if not isinstance(schema, dict):
        return None

    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return None
        target = _resolve_ref(root, ref)
        if target is None:
            return None
        return declared_values(target, root, seen | {ref})

    if isinstance(schema.get("const"), str):
        return [schema["const"]]

    enum = schema.get("enum")
    if isinstance(enum, list) and enum and all(isinstance(item, str) for item in enum):
        return enum

    for union_key in ("oneOf", "anyOf"):
        variants = schema.get(union_key)
        if isinstance(variants, list) and variants:
            values: list[str] = []
            for variant in variants:
                resolved = declared_values(variant, root, seen)
                if resolved is None:
                    return None
                values.extend(resolved)
            return values or None

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for variant in all_of:
            resolved = declared_values(variant, root, seen)
            if resolved is not None:
                return resolved

    return None


def _walk_nodes(node: Any, path: Pointer = ()) -> Iterator[tuple[Pointer, Any]]:
    yield path, node
    if isinstance(node, dict):
        for key, child in node.items():
            yield from _walk_nodes(child, (*path, str(key)))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _walk_nodes(child, (*path, str(index)))


def _discriminator_errors(schema: Any, denylist: Denylist) -> list[str]:
    """Every guarded activation discriminator must declare a closed ``const``/``enum``.

    Both sides of the membership test below go through ``normalize_token``, which
    confusable-folds. That is load-bearing and is the fix for a verified bypass: while
    ``forbidden_match`` folded, this path did not, so ``work_type`` spelled with a
    fullwidth ``w`` (U+FF57) or a Cyrillic ``o`` (U+043E) matched no guarded name and the
    property was left wide open — silently, and rendering identically to a reviewer, while
    the four ASCII spellings ``work_type``/``workType``/``WORK_TYPE``/``work-type`` were all
    caught. Do not reintroduce a raw-string comparison here.
    """
    errors: list[str] = []
    guarded = denylist.normalized_discriminators

    for path, node in _walk_nodes(schema):
        if len(path) < 2 or path[-2] not in {"properties", "patternProperties"}:
            continue
        if normalize_token(path[-1]) not in guarded:
            continue
        values = declared_values(node, schema)
        if values is None:
            errors.append(f"{_pointer(path)}: activation discriminator must use closed const/enum")
            continue
        for candidate in values:
            match = forbidden_match(candidate, denylist)
            if match:
                errors.append(f"{_pointer(path)}: forbidden activation value {match!r}")
    return errors


#: The document-root ``$schema`` value is the meta-schema URI, which is not
#: authored content. The skip is deliberately root-scoped: a nested
#: ``{"$defs": {"x": {"$schema": "regulatory_effect"}}}`` used to be skipped at
#: *any* depth and walked straight past the gate.
ROOT_SCHEMA_POINTER: Pointer = ("$schema",)


def document_errors(document: Any, denylist: Denylist) -> list[str]:
    """Enforce the denylist over any parsed JSON/YAML document."""
    errors: list[str] = []
    for kind, path, text in iter_document_strings(document):
        if kind == "value" and path == ROOT_SCHEMA_POINTER:
            continue
        match = forbidden_match(text, denylist)
        if match:
            label = "key" if kind == "key" else "value"
            errors.append(
                f"{_pointer(path)}: forbidden pre-ADR token {match!r} in {label} {text!r}"
            )
    return errors


def regulatory_errors(schema: Any, denylist: Denylist) -> list[str]:
    """Enforce the denylist over a parsed JSON Schema document."""
    return [*document_errors(schema, denylist), *_discriminator_errors(schema, denylist)]


def path_errors(relative_path: Path, denylist: Denylist) -> list[str]:
    """Enforce the denylist over a repository-relative file path.

    ``schemas/events/regulatory-effect.json`` escaped the baseline gate purely on
    the ``.json`` vs ``.schema.json`` suffix; its *name* alone should have been
    disqualifying.
    """
    errors: list[str] = []
    for part in relative_path.parts:
        match = forbidden_match(part, denylist)
        if match:
            errors.append(f"{relative_path.as_posix()}: forbidden pre-ADR token {match!r} in path")
            break
    return errors

"""Contract lint helpers.

Enumeration is the whole game here. Three proven bypasses of the earlier
enumeration, all closed below:

* the schema checks (compile, ``$schema``, ``$id`` uniqueness, guarded
  activation discriminator) were hard-anchored to ``<repo>/schemas``, so an
  ``openapi/plant.schema.json`` could declare draft-07, duplicate the ``$id`` of
  a released schema and open ``work_type`` — all unseen;
* the repo-wide scan ran only the *token* half of the denylist, never the
  discriminator half, so the same schema content as plain ``.json`` — or an
  OpenAPI ``.yaml`` with ``properties.work_type: {type: string}`` — passed;
* the scanned suffixes were a case-sensitive whitelist, so ``.JSON``/``.YAML``
  (the same file to every consumer on case-insensitive macOS), ``.json5``,
  ``.jsonc`` and extensionless documents were all invisible.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .denylist import Denylist, load_denylist
from .errors import ContractError
from .paths import DENYLIST, REPOSITORY_ROOT
from .regulatory import path_errors, regulatory_errors
from .yaml_strict import strict_yaml_load

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

__all__ = [
    "DENYLIST",
    "REPOSITORY_ROOT",
    "ContractError",
    "excluded_directories",
    "gitignored_directory_names",
    "is_schema_document",
    "iter_repository_documents",
    "iter_repository_files",
    "iter_schema_documents",
    "lint_repository",
    "lint_schema_files",
    "load_json",
    "parse_key_values",
    "scan_repository_documents",
]

#: Documents the repository-wide regulatory scan reads. Compared case-folded:
#: ``.JSON`` is the same file to every consumer, and on a case-insensitive
#: filesystem it is literally the same file.
DOCUMENT_SUFFIXES = (".json", ".yaml", ".yml", ".json5", ".jsonc")

#: Suffix that marks an authoritative JSON Schema document, compared case-folded.
SCHEMA_SUFFIX = ".schema.json"

#: Directories the repository-wide scan never descends into, regardless of what any
#: ``.gitignore`` says. This is the floor, not the whole set: :func:`excluded_directories`
#: unions it with the repository's own ignore declarations.
#:
EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        ".worktrees",
        ".pytest_cache",
        # ``compatibility/released/`` is a snapshot of the released schemas, compared
        # by scripts/check_schema_compatibility.py. It deliberately duplicates every
        # $id in schemas/, so it is not candidate content and must not be linted.
        "compatibility",
        ".ruff_cache",
        ".mypy_cache",
        ".ty_cache",
        "__pycache__",
        "node_modules",
    }
)

#: The denylist itself necessarily spells out every forbidden token.
EXCLUDED_DOCUMENTS = frozenset({"config/pre-adr-regulatory-denylist.json"})

#: How much of an extensionless file is read to decide whether it is a document.
SNIFF_BYTES = 65536


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{path}: {exc}") from exc


def load_yaml(path: Path) -> Any:
    """Parse YAML strictly: a duplicate key is a parse failure, not a silent drop.

    PyYAML is last-wins, so ``kind: legal_event`` followed by
    ``kind: research_asset`` hands the denylist a document the first value was
    already deleted from.
    """
    try:
        return strict_yaml_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ContractError(f"{path}: {exc}") from exc


def load_document(path: Path) -> Any:
    """Parse a JSON/YAML-family document.

    ``.json5``/``.jsonc`` are JSON-family contract documents that strict JSON may
    reject; YAML 1.2 is a JSON superset and parses most of them. Whichever way it
    goes, an unparseable document is reported, never skipped.
    """
    if path.suffix.lower() == ".json":
        return load_json(path)
    if path.suffix.lower() in {".json5", ".jsonc"}:
        try:
            return load_json(path)
        except ContractError:
            return load_yaml(path)
    return load_yaml(path)


def is_schema_document(path: Path) -> bool:
    """True for an authoritative ``*.schema.json``, matched case-insensitively."""
    return path.name.lower().endswith(SCHEMA_SUFFIX)


def gitignored_directory_names(root: Path) -> frozenset[str]:
    """Directory names ``root``'s own ``.gitignore`` declares are not repository content.

    Deliberately narrow. Only entries that are unambiguously "a directory of this name, at
    any depth" are read: a line ending in ``/``, not negated, carrying no glob metacharacter
    and no interior separator — which is exactly the shape whose meaning matches the
    name-based pruning ``os.walk`` can do, and exactly how git itself treats such a pattern.
    Anchored and globbed patterns are left alone rather than approximated; approximating
    them would need a real gitignore engine, and a gate that guesses at its own scope is
    worse than one with a stated one.

    This exists because :data:`EXCLUDED_DIRECTORIES` was a hand-maintained duplicate of a
    subset of ``.gitignore`` with nothing binding the two — ``dist/`` and ``coverage/`` were
    ignored by git and walked by this scan. Reading the declaration instead of restating it
    means the next entry added to ``.gitignore`` cannot reintroduce the same inversion.
    """
    try:
        text = (root / ".gitignore").read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return frozenset()
    names: set[str] = set()
    for raw in text.splitlines():
        entry = raw.strip()
        if not entry or entry.startswith("#") or entry.startswith("!"):
            continue
        if not entry.endswith("/"):
            continue
        name = entry[:-1].lstrip("/")
        if not name or "/" in name or set(name) & {"*", "?", "[", "]"}:
            continue
        names.add(name)
    return frozenset(names)


def excluded_directories(root: Path) -> frozenset[str]:
    """The effective pruning set for a walk anchored at ``root``."""
    return EXCLUDED_DIRECTORIES | gitignored_directory_names(root)


def iter_repository_files(root: Path) -> list[Path]:
    """Every file under ``root``, with tool-cache and gitignored directories pruned.

    ``os.walk`` rather than ``rglob("*")`` so the excluded directories are pruned
    instead of walked; ``followlinks=False`` so a symlinked directory cannot make
    the walk loop or wander outside the repository.

    A filesystem walk, NOT ``git ls-files`` — the opposite of the sibling gate in
    ``file_hygiene``, on purpose, because the two have opposite requirements. That gate runs
    as a pre-commit hook whose CI counterpart sees a clean checkout, so an untracked local
    scratch file must not fail it. This gate is an adversarial enumeration: a document
    dropped into the tree and not yet ``git add``ed is exactly what it has to see, and
    reading the index would blind it to the file until the moment it is too late. What the
    two do share is the rule that the repository's own ``.gitignore`` decides what is not
    repository content, which is what :func:`excluded_directories` reads.
    """
    if not root.is_dir():
        return []
    pruned = excluded_directories(root)
    found: list[Path] = []
    walk_errors: list[OSError] = []
    for directory, subdirectories, filenames in os.walk(
        root, followlinks=False, onerror=walk_errors.append
    ):
        subdirectories[:] = sorted(name for name in subdirectories if name not in pruned)
        base = Path(directory)
        for filename in sorted(filenames):
            found.append(base / filename)
    if walk_errors:
        raise ContractError(
            f"{root}: could not enumerate the repository: {walk_errors[0]} — an unreadable "
            "directory is not evidence that nothing illicit is in it"
        )
    return found


def iter_schema_documents(root: Path) -> list[Path]:
    """Every ``*.schema.json`` anywhere under ``root``, not only under ``schemas/``."""
    return [path for path in iter_repository_files(root) if is_schema_document(path)]


def _parses_as_container(text: str) -> bool:
    """True when ``text`` parses as a JSON/YAML mapping or sequence."""
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return isinstance(parsed, (dict, list))


def _sniffs_as_document(path: Path) -> bool:
    """True when an extensionless file really parses as a JSON/YAML container.

    Extensionless files cannot be told apart from arbitrary text by name, so they
    are admitted on content: a mapping or a sequence is a document, anything else
    (prose, a Makefile, a binary) is not. Without this an attacker just drops the
    extension.

    Truncation must never produce a false NEGATIVE, and it used to. The only parse was of
    ``text[:SNIFF_BYTES]``, so a document larger than 64 KiB was cut mid-scalar,
    ``yaml.safe_load`` raised, and the file was declared "not a document" and never scanned
    at all. A 70 KB extensionless file holding
    ``{"properties": {"work_type": {...}}, "pad": "AAA…"}`` was invisible to the gate — the
    precise evasion the paragraph above says this function exists to prevent, reachable by
    appending padding.

    The prefix parse is kept as a fast ACCEPT, which is sound in that direction: a prefix
    that parses as a container is a container. A prefix that fails to parse is evidence
    about the prefix and nothing else, so when the read was actually truncated the full text
    decides. The cost falls only on extensionless files over 64 KiB that are not documents,
    of which a contract repository has approximately none.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return False
    prefix = text[:SNIFF_BYTES]
    if _parses_as_container(prefix):
        return True
    if len(text) == len(prefix):
        return False
    return _parses_as_container(text)


def lint_schema_documents(paths: Iterable[Path], base: Path | None = None) -> list[str]:
    """Compile each schema in ``paths`` and enforce the schema-only invariants.

    ``$id`` uniqueness is decided over the whole set handed in, which is why the
    caller passes every ``*.schema.json`` in the repository rather than only the
    ones under ``schemas/``.
    """
    seen_ids: dict[str, str] = {}
    errors: list[str] = []
    for path in paths:
        label = _display(path, base)
        try:
            schema = load_json(path)
        except ContractError as exc:
            errors.append(f"{label}: unreadable or malformed JSON: {exc}")
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            errors.append(f"{label}: invalid JSON Schema 2020-12: {exc}")
            continue

        if not isinstance(schema, dict):
            errors.append(f"{label}: a JSON Schema document must be a JSON object")
            continue
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{label}: $schema must declare JSON Schema 2020-12")
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            errors.append(f"{label}: non-empty $id is required")
        elif schema_id in seen_ids:
            errors.append(
                f"{label}: duplicate $id {schema_id!r} also used by {seen_ids[schema_id]}"
            )
        else:
            seen_ids[schema_id] = label
    return errors


def _display(path: Path, base: Path | None) -> str:
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return str(path)


def lint_schema_files(schema_root: Path, denylist: Denylist) -> list[str]:
    """Compile every ``*.schema.json`` under ``schema_root`` and enforce the denylist.

    Kept as the standalone contract for a single schema tree. :func:`lint_repository`
    enumerates the *whole* repository instead, because anchoring the schema checks
    to ``schemas/`` was itself a bypass.
    """
    paths = iter_schema_documents(schema_root)
    if not paths:
        return [f"{schema_root}: no *.schema.json files found"]
    errors = lint_schema_documents(paths)
    for path in paths:
        try:
            schema = load_json(path)
        except ContractError:
            continue
        errors.extend(f"{path}: {error}" for error in regulatory_errors(schema, denylist))
    return errors


def iter_repository_documents(document_root: Path) -> list[Path]:
    """Every JSON/YAML-family document under ``document_root``, excluding tool caches.

    Suffixes are compared case-folded, the JSON-family suffixes are included, and
    an extensionless file is admitted when it actually parses as a JSON/YAML
    container. ``.JSON``, ``.YAML``, ``.json5``, ``.jsonc`` and extensionless
    documents were all verified bypasses of the case-sensitive whitelist.
    """
    found: list[Path] = []
    for path in iter_repository_files(document_root):
        relative = path.relative_to(document_root)
        if relative.as_posix() in EXCLUDED_DOCUMENTS:
            continue
        suffix = path.suffix.lower()
        if suffix in DOCUMENT_SUFFIXES:
            found.append(path)
        elif not suffix and _sniffs_as_document(path):
            found.append(path)
    return found


def scan_repository_documents(document_root: Path, denylist: Denylist) -> list[str]:
    """Enforce the denylist over every file name and every document in the repo.

    Two things happen here that used to be split or missing:

    * *every* file name is checked, not only the names of parsed documents — a
      forbidden token in a path is disqualifying whatever the file contains;
    * every document gets the **full** :func:`regulatory_errors` treatment, token
      scan *and* guarded-discriminator check. Running only the token half here is
      what let an OpenAPI ``.yaml`` declare an open ``work_type``.
    """
    errors: list[str] = []
    for path in iter_repository_files(document_root):
        errors.extend(path_errors(path.relative_to(document_root), denylist))

    documents = iter_repository_documents(document_root)
    if not documents:
        errors.append(
            f"{document_root}: no JSON/YAML documents found — an empty scan is not a clean scan"
        )
        return errors

    for path in documents:
        relative = path.relative_to(document_root)
        try:
            document = load_document(path)
        except ContractError as exc:
            errors.append(f"{relative.as_posix()}: unparseable JSON/YAML document: {exc}")
            continue
        errors.extend(
            f"{relative.as_posix()}: {error}" for error in regulatory_errors(document, denylist)
        )
    return errors


def lint_repository(repo_root: Path, denylist_path: Path | None = None) -> list[str]:
    """Run every contract lint anchored at ``repo_root``.

    Schema structural checks run over every ``*.schema.json`` in the repository,
    not only ``schemas/**``; the denylist (tokens *and* guarded discriminators)
    runs over every document. ``schemas/`` must still hold at least one schema —
    an empty authoritative tree is a defect, not a clean scan.
    """
    denylist = load_denylist(denylist_path or DENYLIST)
    schemas_dir = repo_root / "schemas"
    errors: list[str] = []
    if not iter_schema_documents(schemas_dir):
        errors.append(f"{schemas_dir}: no *.schema.json files found")
    errors.extend(lint_schema_documents(iter_schema_documents(repo_root), repo_root))
    errors.extend(scan_repository_documents(repo_root, denylist))
    return list(dict.fromkeys(errors))


def parse_key_values(values: Iterable[str], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key or not item:
            raise ContractError(f"{label} must use non-empty KEY=VALUE entries: {value!r}")
        if key in result:
            raise ContractError(f"{label} contains duplicate key {key!r}")
        result[key] = item
    return result

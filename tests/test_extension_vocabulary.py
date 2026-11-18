"""The ``x-datacompany-*`` extension vocabulary is a gate, not prose.

Document 16 section 2.5 requires a profile or pack extension to "declare their schema,
vocabulary, owner, version, and validation rules". Until this suite existed, the
``x-datacompany-*`` vocabulary declared none of those: it was defined only by what
``canonical/structural.py`` and ``canonical/hash_profile.py`` happened to read, and the
string ``x-datacompany`` appeared in no specification document at all. ``EXTENSIONS.md`` is the
declaration; ``schemas/meta/datacompany-extension-vocabulary.v1.schema.json`` is the executable
half of it, and this file is what makes the executable half actually execute.

Three obligations, in order of what they catch:

1. **Conformance** -- every ``x-datacompany-*``-carrying node of every committed schema
   validates against the meta-schema. This is what a second-language port can target.
2. **Non-vacuity** -- the node count is an equality pin and the corpus is asserted
   non-empty, so relocating or emptying ``schemas/`` turns this red instead of green.
   A suite that measures nothing must not report zero findings as health.
3. **Falsifiability** -- every rule the meta-schema adds is proven able to REJECT, each
   with a passing control that isolates the mutated member. Wave 1's finding was that
   none of the repository's gates had ever been shown to fail; an unfalsified gate is
   indistinguishable from an absent one.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import tempfile
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.protocols import Validator
from referencing import Resource
from referencing.jsonschema import DRAFT202012

from research_contracts.canonical import hash_profile as hash_profile_module
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical import structural as structural_module
from research_contracts.canonical.errors import CanonicalError, CrossFieldError, HashProfileError
from research_contracts.canonical.hash_profile import derive_hash_profile
from research_contracts.canonical.registry import (
    CanonicalValidator,
    schema_registry,
)
from research_contracts.canonical.registry import (
    canonical_schemas as canonical_schemas_for_probe,
)
from research_contracts.canonical.rendering import json_text
from research_contracts.tooling.contract_tools import iter_schema_documents

ROOT = Path(__file__).resolve().parents[1]
META_SCHEMA_PATH = ROOT / "schemas" / "meta" / "datacompany-extension-vocabulary.v1.schema.json"
EXTENSIONS_DOC = ROOT / "EXTENSIONS.md"
CANONICAL_SOURCE_DIR = ROOT / "src" / "research_contracts" / "canonical"

ANNOTATION_PREFIX = "x-datacompany-"

#: Equality pin over the annotated nodes in the committed schemas. Deleting an annotation,
#: adding one, or pointing the walk at an empty tree all move this number, so the suite
#: cannot silently start measuring nothing. Mirrors ``EXPECTED_CHECKS`` in
#: ``tooling/canonical_fixtures.py``.
#:
#: 36 -> 37 when ``inclusion-set-export:1`` was released: its
#: ``/counts/exclusion_reasons`` subtree carries one ``x-datacompany-hash-opaque``, the SECOND
#: released use of that annotation after ``bitemporal-assertion:1`` ``/value``. Measured, not
#: predicted -- the walk counts NODES, not annotations, and one node carrying two annotations
#: would have moved this by one while a reader expecting "one per annotation" wrote two.
#: 37 -> 38 when ``inclusion-set-export:2`` was released. ``:2`` inherits ``:1``'s counts
#: block verbatim, including the one ``x-datacompany-hash-opaque`` at
#: ``/counts/exclusion_reasons``, and ``:1`` stays released beside it — so the annotation
#: exists at TWO nodes now, not one moved. The new member ``items_hash`` carries no
#: annotation at all: it is a plain declared string that must reach the hash view, and
#: annotating it would be the opposite of what it is for.
#: 38 -> 40 when ``review-flow-ledger:1`` was released, and it is TWO because the document
#: adds two annotated NODES of its own, not because it uses two annotations. Its
#: ``/counts_by_stage`` is the first released ``x-datacompany-array`` outside the canonical tier
#: and must be declared or the subtree raises ``UndeclaredArrayError`` at derivation; its
#: ``/counts_by_stage/-/exclusion_reasons`` is a THIRD released ``x-datacompany-hash-opaque``,
#: beside ``:1``'s and ``:2``'s. Its flat ``/counts/exclusion_reasons`` moves nothing: that
#: subtree arrives by ``$ref`` from ``inclusion-set-export:2`` and is annotated in THAT
#: file, which the walk has already counted. Measured against the derived profile, whose
#: ``opaque_pointers`` lists both ``/counts/exclusion_reasons`` and
#: ``/counts_by_stage/-/exclusion_reasons`` -- so the composed document behaves as intended
#: while contributing one of the two nodes.
#:
#: 40 -> 41 when ``evidence-snapshot-manifest:1`` was released, and it is ONE, not two.
#: The document declares ``x-datacompany-array`` on ``/artifacts`` -- a set with a declared
#: order key, which it must have or the subtree raises ``UndeclaredArrayError`` at
#: derivation. Its ``/members`` array moves NOTHING even though it is also a set: that
#: subtree arrives by ``$ref`` from ``pinned-version-ref:1#/$defs/set_of_pins`` and is
#: annotated in THAT file, which the walk has already counted. Composing the released
#: order key rather than respelling one is the whole reason ``member_manifest_hash``
#: means the same thing in every context, and this count is where that shows up.
#: 41 -> 42 when `approval-attestation:1` was released, and it is ONE node:
#: `/approvers`, a set whose order key is `(/subject, /role)`. Doc 13 §10.1
#: requires a verifier to check "each approver subject, role and recorded
#: decision, plus required count and separation of duty" — a set that is not
#: sorted before hashing would give two verifiers two different digests for the
#: same approval, and separation of duty is checked over exactly those two
#: fields.
#:
#: 42 -> 43 on 2026-09-04 when ``durable-job:1`` was released, and it is ONE node:
#: ``/pack_refs``, a set whose order key is the item itself. A job pins the packs in
#: force at enqueue time, and doc 13 §3.2 makes the pinned set part of what a command
#: hash covers -- two writers listing the same packs in a different order must not
#: produce two digests for one job. ``job-attempt:1`` and
#: ``operation-idempotency-record:1`` declare no array at all and moved nothing.
EXPECTED_ANNOTATED_NODES = 43

#: Annotation names that no code in ``src/research_contracts/`` reads. Declarative-only
#: members are legitimate, but each one must be listed here on purpose: an annotation that
#: silently stops being read is a contract that silently stopped being enforced.
#:
#: **EMPTY since 2026-08-04.** ``x-datacompany-composition-point`` was the only member and is now
#: read by ``hash_profile._require_released_composition_point`` and
#: ``hash_profile.merge_profile_extensions`` (``EXTENSIONS.md`` §6.4, implemented rather than
#: retired). An empty set is not a weaker assertion here: the equality below still runs in
#: both directions, and it now says every registered name is read -- which is the strongest
#: form this drift detector can take, and the one a vocabulary whose purpose is enforcement
#: should be in.
DECLARATIVE_ONLY: frozenset[str] = frozenset()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def meta_schema() -> dict[str, Any]:
    return load(META_SCHEMA_PATH)


def meta_validator() -> Validator:
    """A validator for the meta-schema, resolving into the released canonical registry.

    The meta-schema deliberately ``$ref``s ``canonical-hash-profile.v1`` for the closed
    exclusion-reason set and for the array ``kind``/``order_key`` shapes rather than
    restating them, so those cannot drift between the manifest schema and the annotation
    that derives it.

    ``CanonicalValidator``, not the stock ``Draft202012Validator``: JSON Schema mandates
    ECMA-262 regexes, where ``$`` asserts end of input, and Python's ``$`` also matches
    before a trailing newline. A gate whose whole purpose is catching fail-open annotations
    must not itself accept ``"#/$defs/domain_extension\\n"``. ``$schema`` is dropped from
    the *registered copy* for the same reason ``registry.schema_registry`` does it:
    jsonschema re-derives the validator class from ``$schema`` whenever it follows a
    ``$ref`` into a document that declares one, which would silently restore Python
    ``pattern`` semantics the moment validation crossed back into this document.
    """
    schema = meta_schema()
    contents = {key: value for key, value in schema.items() if key != "$schema"}
    registry = schema_registry().with_resource(
        schema["$id"], Resource.from_contents(contents, default_specification=DRAFT202012)
    )
    return CanonicalValidator(schema, registry=registry, format_checker=FormatChecker())


def walk_nodes(node: Any, pointer: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield every JSON object anywhere in ``node``, with its RFC 6901 pointer."""
    if isinstance(node, dict):
        yield pointer, node
        for name, child in node.items():
            token = name.replace("~", "~0").replace("/", "~1")
            yield from walk_nodes(child, f"{pointer}/{token}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from walk_nodes(child, f"{pointer}/{index}")


def is_annotated(node: dict[str, Any]) -> bool:
    return any(name.startswith(ANNOTATION_PREFIX) for name in node)


def annotated_nodes() -> list[tuple[str, str, dict[str, Any]]]:
    """Every ``x-datacompany-*``-carrying object in every committed ``*.schema.json``.

    Enumerated with ``iter_schema_documents``, the same repository-wide walk the contract
    lint uses, so a schema dropped outside ``schemas/`` is still covered. Anchoring to
    ``schemas/`` was itself a proven bypass of the contract lint.
    """
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path in iter_schema_documents(ROOT):
        if path == META_SCHEMA_PATH:
            continue
        label = path.relative_to(ROOT).as_posix()
        for pointer, node in walk_nodes(load(path)):
            if is_annotated(node):
                found.append((label, pointer or "<root>", node))
    return found


ANNOTATED = annotated_nodes()


# ------------------------------------------------------------------ 1. non-vacuity ---


def test_the_repository_actually_contains_schemas_to_check() -> None:
    """An empty corpus is not a clean corpus."""
    assert iter_schema_documents(ROOT), "no *.schema.json found; this suite measured nothing"


def test_the_annotated_node_count_is_pinned() -> None:
    """Equality, not a lower bound: a deleted annotation must be as loud as a bad one."""
    assert len(ANNOTATED) == EXPECTED_ANNOTATED_NODES, [
        f"{label}{pointer}" for label, pointer, _ in ANNOTATED
    ]


def test_every_released_annotation_name_is_registered_in_the_vocabulary() -> None:
    """The committed schemas may not use a name the vocabulary does not declare."""
    declared = set(meta_schema()["$defs"]["vocabulary"]["enum"])
    used = {name for _, _, node in ANNOTATED for name in node if name.startswith(ANNOTATION_PREFIX)}
    assert used <= declared, sorted(used - declared)


# --------------------------------------------------------------- 2. conformance ---


@pytest.mark.parametrize(
    ("label", "pointer", "node"),
    ANNOTATED,
    ids=[f"{label}{pointer}" for label, pointer, _ in ANNOTATED],
)
def test_every_annotated_node_conforms_to_the_meta_schema(
    label: str, pointer: str, node: dict[str, Any]
) -> None:
    errors = sorted(meta_validator().iter_errors(node), key=lambda error: list(error.path))
    assert not errors, [f"{label}{pointer}: {error.message}" for error in errors]


def test_the_meta_schema_itself_compiles() -> None:
    Draft202012Validator.check_schema(meta_schema())


# ------------------------------------------------- 3. the declaration is complete ---


def test_extensions_md_documents_every_registered_name() -> None:
    """Document 16 section 2.5: an extension must declare its vocabulary."""
    text = EXTENSIONS_DOC.read_text(encoding="utf-8")
    missing = [
        name for name in meta_schema()["$defs"]["vocabulary"]["enum"] if f"`{name}`" not in text
    ]
    assert not missing, missing


def test_extensions_md_records_owner_and_version() -> None:
    """Section 2.5 also requires owner and version. Owner is UNASSIGNED and says so."""
    text = EXTENSIONS_DOC.read_text(encoding="utf-8")
    assert "UNASSIGNED" in text
    assert re.search(r"vocabulary version\W+1", text, re.IGNORECASE)


#: A name is READ by the engine when a schema node is indexed by it -- ``schema.get("...")``
#: or ``schema["..."]``. A bare MENTION is not a read.
#:
#: The distinction became load-bearing when the §7.1 closure gave ``hash_profile`` a
#: ``_VOCABULARY`` constant that necessarily lists every registered name, including the one
#: nothing reads. Under the substring test this replaced, that constant alone made
#: ``x-datacompany-composition-point`` look "read" and emptied ``DECLARATIVE_ONLY`` -- i.e. it
#: would have reported EXTENSIONS.md section 6.4 as closed by an engine that still does
#: nothing whatsoever with the annotation. Recognising a name is not implementing it.
MEMBER_ACCESS = re.compile(r'(?:\.get\(|\[)"(x-datacompany-[a-z-]+)"')


def test_the_declarative_only_set_matches_what_the_engine_actually_reads() -> None:
    """Drift detector in both directions.

    An annotation the engine stopped reading is a rule that stopped being enforced with no
    test going red; an annotation newly read but still listed here is a stale declaration.
    ``DECLARATIVE_ONLY`` is EMPTY since 2026-08-04: ``x-datacompany-composition-point`` was its
    only member and gained an implementation (``EXTENSIONS.md`` section 6.4), so the equality
    below now says every registered name is read. This docstring said the opposite -- "read
    by nothing today" -- eight lines under the emptied set, which is the drift the test
    itself exists to catch.
    """
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(CANONICAL_SOURCE_DIR.glob("*.py"))
    )
    read_by_engine = set(MEMBER_ACCESS.findall(source))
    declared = set(meta_schema()["$defs"]["vocabulary"]["enum"])
    # Non-vacuity in the direction the equality below cannot see: a scan that found nothing
    # would make `declared - read_by_engine` the whole vocabulary, which IS red -- but a scan
    # that found one accidental match would not be, so the count is pinned against the
    # declaration rather than against a literal.
    assert read_by_engine <= declared, sorted(read_by_engine - declared)
    assert len(read_by_engine) == len(declared) - len(DECLARATIVE_ONLY), sorted(read_by_engine)
    assert declared - read_by_engine == DECLARATIVE_ONLY


def test_the_operator_set_matches_the_engine_dispatch() -> None:
    """The five operators are the five ``structural.py`` dispatches on, no more, no less."""
    source = (CANONICAL_SOURCE_DIR / "structural.py").read_text(encoding="utf-8")
    dispatched = set(re.findall(r'kind == "([a-z_]+)"', source))
    declared = set(meta_schema()["$defs"]["cross_field_operator"]["enum"])
    assert dispatched == declared


def test_the_exclusion_reason_set_is_referenced_not_restated() -> None:
    """One source of truth for the closed reason set, so the two cannot drift apart."""
    text = META_SCHEMA_PATH.read_text(encoding="utf-8")
    assert "urn:datacompany:canonical-hash-profile:1#/$defs/exclusion_reason" in text
    for reason in load(ROOT / "schemas" / "canonical" / "canonical-hash-profile.v1.schema.json")[
        "$defs"
    ]["exclusion_reason"]["enum"]:
        assert f'"{reason}"' not in text, f"{reason} is restated instead of referenced"


# ------------------------------------------- 3b. citations into the engine source ---
#
# Prose that cites the engine is only as good as the citation. Measured against 46062b1,
# FOURTEEN distinct ``<module>.py:<line>`` citations shipped -- 10 in EXTENSIONS.md, 3 in the
# released meta-schema, 1 in a released TypeScript source. Their first line landed on a BLANK
# line once, on an unrelated ``#:`` comment four times, and on real code nine times -- where
# "real code" still included ``hash_profile.py:105`` pointing at a bare ``self,`` parameter
# and ``:92`` pointing at ``self.excluded = {}`` while claiming to show ``is True``. Line
# numbers in prose rot by construction: three of these were invalidated in a single session by
# adding one ``import`` above them. So they are gone -- a citation names a SYMBOL, which
# survives every edit that does not delete the thing cited and, unlike a line number, is
# checkable.
#
# (An earlier version of this comment said FIFTEEN. That counted the second endpoint of a
# range citation such as ``hash_view.py:162,170`` as a separate reference. Fourteen is the
# distinct-citation count and is what the sweep below measures.)
#
# **The first version of this gate was blind to the one document that motivated it.** Both
# patterns required BACKTICKS, and the released meta-schema writes its citations unbackticked
# inside JSON ``$comment`` strings, so the gate matched 0 of its 13 citations and 29 of
# EXTENSIONS.md's -- while a ``checked >= 12`` floor, satisfied entirely by the other
# document, made it read as measured. In the very commit that added the gate, a rename left a
# dead symbol citation in that meta-schema and the suite stayed green. Backticks are now
# OPTIONAL, every document carries its OWN floor, and a citation is scanned wherever it is
# written -- including the released TypeScript sources, which were not scanned at all and
# which still carried a stale line citation.

#: Backticks optional. The released meta-schema writes citations as bare text inside JSON
#: strings; requiring backticks is what made this gate unable to fire on it.
SOURCE_CITATION = re.compile(r"\b([a-z_]+)\.py:(\d+)")

TS_SOURCE_DIR = ROOT / "packages" / "typescript" / "src"


def _typescript_sources() -> list[Path]:
    """The released TypeScript sources, as ONE definition.

    RECURSIVE. A non-recursive ``glob("*.ts")`` missed any source in a subdirectory of
    ``src/``, and the count equality could not catch that because the count did not move.
    Every other definition of "the TypeScript sources" in this repository is recursive: the
    package lint script and both tsconfigs use ``src/**/*.ts``.

    It is a single function because the sweep and the byte-equality backstop each had their
    own copy of the glob, so fixing one left the other narrow -- and a mutation of the
    backstop's copy alone was invisible to every test. It sits ABOVE the citation patterns
    because ``_ambiguously_named_modules`` now reads the real file names from it rather than
    asking the filesystem a case-insensitive question.
    """
    sources = sorted(TS_SOURCE_DIR.rglob("*.ts"))
    # `Path.rglob` over a missing directory returns [] in silence, which would quietly shrink
    # the sweep back to the two documents it was already blind in.
    assert sources, f"{TS_SOURCE_DIR}: no TypeScript sources found"
    return sources


def _module_path(module: str) -> Path:
    """The ``.py`` file a dotted module name refers to."""
    return CANONICAL_SOURCE_DIR.joinpath(*module.split(".")).with_suffix(".py")


def _canonical_modules() -> list[str]:
    """Every canonical module, DERIVED from the directory rather than listed.

    The module set was a hand-written alternation of six while the package held eight, so
    ``engine`` and ``verification`` were unscanned -- and four live citations sat unread in
    ``verification.ts`` in the same ``Mirrors Python's ...`` idiom as the eight the previous
    round was written to rescue. Widening the TAIL had left the MODULE SET untouched.

    This is the same defect the sibling census in this module already warns about, in a test
    whose own docstring said "derived from the documents rather than a hand-listed table"
    while sitting beside exactly such a table. Deriving it means a ninth module is scanned
    the day it is created.

    RECURSIVE, and this half was the asymmetry left over from the round that made
    ``_typescript_sources`` recursive. ``glob("*.py")`` sees nothing in a SUBPACKAGE, and no
    count anywhere moves when one appears, so ``canonical/spans/resolver.py`` would be
    unscanned on the day it is created -- the exact defect the docstring above describes,
    surviving in the other language. A subpackage module is named as it is CITED, dotted:
    ``spans.resolver.walk``. Pinned synthetically by
    ``test_the_module_sweep_discovers_python_sources_recursively``, because no subpackage
    exists today and a clean corpus therefore cannot tell the two spellings apart.

    THE ROUND TRIP IS ASSERTED, not assumed. ``/`` becomes ``.`` here and ``.`` becomes ``/``
    in :func:`_module_path`, which is not injective if a filename itself contains a dot:
    ``foo.bar.py`` derives the name ``foo.bar`` and maps back to ``foo/bar.py``, a path that
    does not exist. The module would then sit in the regex alternation while resolving to
    nothing -- an unscannable module, silent until something cited it. One ``is_file()`` per
    module makes it loud at construction instead.
    """
    modules = sorted(
        path.relative_to(CANONICAL_SOURCE_DIR).with_suffix("").as_posix().replace("/", ".")
        for path in CANONICAL_SOURCE_DIR.rglob("*.py")
        if path.stem != "__init__"
    )
    unresolvable = [module for module in modules if not _module_path(module).is_file()]
    assert not unresolvable, (
        f"{unresolvable} derive module names that map back to no file; a dot in a filename "
        "makes the name/path round trip lossy"
    )
    return modules


def _typescript_source_names() -> set[str]:
    """Every released TypeScript source, as a set of POSIX paths relative to ``src/``."""
    return {path.relative_to(TS_SOURCE_DIR).as_posix() for path in _typescript_sources()}


def _ambiguously_named_modules() -> set[str]:
    """Canonical modules whose name is spelled IDENTICALLY on the TypeScript side.

    Also derived. ``jcs.ts``, ``errors.ts``, ``structural.ts``, ``registry.ts``, ``engine.ts``,
    ``rendering.ts`` and ``verification.ts`` all exist, so inside a ``.ts`` file ``jcs.x`` may
    be a citation into Python or a reference to the sibling port. ``hash_profile``/``hash_view``
    are ``hashProfile``/``hashView`` there, so naming them is unambiguous.

    MEMBERSHIP IN A SET, not ``Path.is_file()``. ``(TS_SOURCE_DIR / "hashprofile.ts").is_file()``
    answers True on the case-insensitive filesystem every developer here runs and False on
    Linux CI, so a Python module whose name differed from a ``.ts`` name only by case would be
    ambiguous locally and unambiguous in CI -- two different scans of the same tree, with the
    local one green. No stem collides that way today, which is exactly why this could sit here
    unnoticed: it is a divergence a clean corpus cannot expose. A set lookup is
    case-sensitive on every platform. Pinned by
    ``test_the_ambiguous_name_test_is_case_sensitive_on_every_platform``.
    """
    names = _typescript_source_names()
    return {module for module in _canonical_modules() if f"{module.replace('.', '/')}.ts" in names}


#: EVERY extension this repository could plausibly write into prose, not the five the first
#: round happened to need. The list was ``py|ts|js|json|md``, and everything outside it
#: FABRICATES a symbol out of a filename: ``verification.test.tsx`` captured
#: ``verification.test.tsx``, ``engine.pyi`` captured ``engine.pyi``, and ``structural.foo.yml``,
#: ``.yaml``, ``.txt``, ``.toml``, ``.sh``, ``.json5``, ``.jsonc``, ``.mts``, ``.cts``, ``.jsx``,
#: ``.mjs`` and ``.cjs`` each did the same -- measured, all fourteen, against the released
#: patterns. Impact today is nil because no such filename is written anywhere, but the failure
#: mode is that the FIRST ``.tsx`` filename in EXTENSIONS.md turns CI red with a finding about
#: a symbol that was never a citation. A fabricated finding is what gets a gate weakened.
#:
#: ``d`` is in the list for ``verification.test.d.ts``, where the extension is two segments.
#: Every entry is protected by ``\b``, so ``d_something`` and ``shape`` are still ordinary
#: segments -- asserted directly rather than assumed.
_FILE_EXTENSIONS = "py|pyi|ts|tsx|mts|cts|d|js|jsx|mjs|cjs|json|jsonc|json5|md|yml|yaml|toml|txt|sh"

#: A tail SEGMENT may not be a file extension, and the whole tail may not be FOLLOWED by one.
#: Both halves are needed: guarding only the first segment let ``verification.test.ts`` in
#: EXTENSIONS.md capture the symbol ``test.ts``, and guarding only segments would still
#: capture ``verification.test`` out of the same filename. With both, a filename produces no
#: match at all.
_SEGMENT = rf"(?!(?:{_FILE_EXTENSIONS})\b)[A-Za-z_][A-Za-z0-9_]*"
#: Two lookaheads, and both are load-bearing. Without the first, the greedy tail simply
#: BACKTRACKS to a partial segment: ``verification.test.ts`` matched the symbol ``tes``,
#: because ``tes`` is followed by ``t`` rather than by ``.ts``. The first forbids ending
#: mid-identifier; the second forbids ending anywhere in front of a file extension.
#:
#: THE SECOND LOOKAHEAD SPANS THE WHOLE DOTTED RUN, not just the next segment. Written as
#: ``(?!\.(?:py|ts|...)\b)`` it only forbade the extension IMMEDIATELY after the tail, so the
#: greedy tail simply backtracked ONE SEGMENT FURTHER and hid the extension behind the segment
#: it gave up: ``verification.test.d.ts`` captured the symbol ``verification.test`` and
#: ``structural.foo.bar.ts`` captured ``structural.foo``. Same backtracking class as the
#: partial-segment defect above, one segment deeper, and equally a fabricated finding. The
#: run-spanning form has no depth to backtrack to.
_NOT_A_FILENAME = (
    r"(?![A-Za-z0-9_])" rf"(?!(?:\.[A-Za-z_][A-Za-z0-9_]*)*\.(?:{_FILE_EXTENSIONS})\b)"
)

_SYMBOL_TAIL = rf"\.(?P<sym>{_SEGMENT}(?:\.{_SEGMENT})*){_NOT_A_FILENAME}"

#: Inside a ``.ts`` file, an ambiguously-named module's tail must look like a PYTHON name:
#: it starts with a capital (a class) or contains an underscore. TypeScript's camelCase --
#: ``esNumberToString`` -- and ordinary property access on a local ``errors`` variable --
#: ``length``, ``join`` -- are neither.
#:
#: This is deliberately WIDER than the first spelling, which required an underscore and so
#: could not see any CamelCase class at all: all 11 exception classes in ``errors.py``, plus
#: ``registry.CanonicalValidator``. The residue is now exactly the lowercase single-word
#: symbols of the ambiguously-named modules (``jcs.canonicalize``), counted and pinned by
#: ``test_the_ambiguous_arm_residue_is_measured_not_guessed``.
#:
#: THE UNDERSCORE MAY BE IN ANY SEGMENT. ``[A-Za-z0-9]*_`` cannot cross a dot, so the rule
#: read "an underscore in the FIRST tail segment" while the residue measurement it is paired
#: with asks ``"_" not in symbol`` of the WHOLE dotted string. The two disagreed about
#: ``jcs.foo.bar_baz``: the pattern would not see it, the residue count would not report it,
#: so it was invisible to both halves at once. Today's pinned residue of 1 is unaffected --
#: re-measured, no ambiguously-named module has a dotted symbol whose first segment is
#: lowercase and underscore-free -- so this corrects the RULE, not the number.
_PYTHON_SHAPED = r"(?=[A-Z]|[A-Za-z0-9.]*_)"
_AMBIGUOUS_TAIL = rf"\.{_PYTHON_SHAPED}(?P<sym2>{_SEGMENT}(?:\.{_SEGMENT})*){_NOT_A_FILENAME}"


def _alternation(modules: Iterable[str]) -> str:
    """Module names as a regex alternation.

    ESCAPED and LONGEST-FIRST, both because a module name may now contain a dot. Unescaped, the
    dot of a subpackage name ``spans.resolver`` would match any character; and Python's
    alternation is first-match rather than longest-match, so a package that also shipped a
    top-level ``spans.py`` would have ``spans`` win and swallow ``resolver`` into the tail.
    """
    return "|".join(re.escape(module) for module in sorted(modules, key=lambda m: (-len(m), m)))


def _symbol_citation() -> re.Pattern[str]:
    """Documents (prose) may cite ANY canonical module with any tail."""
    return re.compile(r"\b(?P<mod>" + _alternation(_canonical_modules()) + r")" + _SYMBOL_TAIL)


def _ts_symbol_citation() -> re.Pattern[str]:
    """TypeScript sources: unambiguous modules unrestricted, ambiguous ones Python-shaped."""
    ambiguous = _ambiguously_named_modules()
    unambiguous = [m for m in _canonical_modules() if m not in ambiguous]
    return re.compile(
        r"\b(?:(?P<mod>"
        + _alternation(unambiguous)
        + r")"
        + _SYMBOL_TAIL
        + r"|(?P<mod2>"
        + _alternation(ambiguous)
        + r")"
        + _AMBIGUOUS_TAIL
        + r")"
    )


SYMBOL_CITATION = _symbol_citation()
TS_SYMBOL_CITATION = _ts_symbol_citation()

#: Per-document floors, so one document cannot satisfy another's non-vacuity check. The
#: shipped gate had a single total floor and the meta-schema contributed ZERO to it.
#:
#: EXACT counts, not floors with slack. The two prose entries carried five slack each, and
#: five was enough to absorb a real narrowing: pairing the ambiguous-arm pattern with
#: EXTENSIONS.md dropped it 30 -> 28 and stayed green. The ``.ts`` entries were already exact,
#: which is why the equivalent narrowing WAS caught there.
#:
#: Three moved when the sections 7.1-7.4 / 7.6 / 8 closures landed, and moving them is the
#: point of an exact pin: the meta-schema 13 -> 16 (three $comments that asserted the
#: fail-opens as CURRENT engine behaviour were rewritten to name the restatement and the
#: drift test that now enforce each one), EXTENSIONS.md 30 -> 32, and hashProfile.ts 3 -> 5
#: (the two new authoring-time guards cite the symbols they mirror).
#:
#: Two moved again on 2026-08-04, when section 6.4 was implemented rather than retired and
#: section 5.2's exclusion cascade was fixed under ``profile_version`` 2: the meta-schema
#: 16 -> 18 (``composition_point``'s $comment stopped saying "no code reads this" and now
#: names the two symbols that do) and EXTENSIONS.md 32 -> 34 (sections 3.5 and 9 item 14 cite
#: the same two). ``hashProfile.ts`` did not move, which is the pin working: the new guard's
#: doc comment cites its Python mirror in the ``hash_profile.<symbol>`` form the sweep counts
#: only once per distinct symbol.
CITATION_FLOORS = {
    "datacompany-extension-vocabulary.v1.schema.json": 18,
    "EXTENSIONS.md": 34,
    # 5 -> 6: `whereElseACompositionPointWasFound` cites the Python symbol it mirrors, which
    # is the port's own convention for a byte-identical message pair.
    "hashProfile.ts": 6,
    "structural.ts": 7,
    "json.ts": 1,
    "registry.ts": 1,
    "verification.ts": 4,
}

#: An EQUALITY, not a floor: a file appearing is as much a change to what is swept as one
#: disappearing, and a floor cannot catch the first. 11 -> 12 when ``rendering.ts`` landed --
#: the single JSON rendering both engines' message text goes through, extracted so the
#: ``repr``/``typeof``/``ensure_ascii``/lone-surrogate family of divergences has ONE home.
EXPECTED_TS_SOURCES = 12


def _cited_documents() -> list[tuple[str, str, re.Pattern[str]]]:
    """Every artifact that cites the engine, with the text a citation may legally appear in.

    The released TypeScript sources are here because they are RELEASED: a stale
    ``hash_profile.py:127-137`` in ``hashProfile.ts`` is the same defect as one in the
    meta-schema, and it survived an earlier version of this gate purely by not being read.
    """
    documents = [
        (META_SCHEMA_PATH.name, META_SCHEMA_PATH.read_text(encoding="utf-8"), SYMBOL_CITATION),
        (EXTENSIONS_DOC.name, EXTENSIONS_DOC.read_text(encoding="utf-8"), SYMBOL_CITATION),
    ]
    for path in _typescript_sources():
        # WHOLE FILE, not comment lines only. An earlier version kept only lines whose
        # stripped form began with ``//``/``*``/``/*``, which silently dropped every TRAILING
        # comment -- ``const x = 1;  // see hash_profile.py:9999`` was invisible, in a file
        # the sweep had just been extended to cover.
        documents.append((path.name, path.read_text(encoding="utf-8"), TS_SYMBOL_CITATION))
    return documents


def _module_symbols(module: str) -> set[str]:
    """Every top-level and nested definition name in a canonical module, as dotted paths."""
    tree = ast.parse(_module_path(module).read_text(encoding="utf-8"))
    found: set[str] = set()

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                dotted = f"{prefix}{child.name}"
                found.add(dotted)
                visit(child, f"{dotted}.")
            elif isinstance(child, ast.Assign) and not prefix:
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        found.add(target.id)
            elif isinstance(child, ast.AnnAssign) and not prefix:
                # `DERIVATION_PROFILE_VERSION: Final[int] = 1` is an AnnAssign, not an
                # Assign. Omitting it made the gate report a live module constant as
                # resolving to nothing -- a false finding, which is the failure mode that
                # gets a gate weakened rather than fixed.
                if isinstance(child.target, ast.Name):
                    found.add(child.target.id)

    visit(tree, "")
    return found


def _unresolved_citations(name: str, text: str, pattern: re.Pattern[str]) -> list[str]:
    """Every citation in ``text`` naming a symbol its module does not define.

    Extracted so the RESOLVER can be exercised against synthetic text. Every control in this
    module used to target the PATTERN (what is scanned) or the FLOORS (how much); nothing
    targeted the half that actually kills renames, and five separate resolver mutations were
    green against the whole suite -- including one that resolved only the FIRST segment of a
    dotted tail, which ships ``hash_view._ViewBuilder._no_such`` as valid. That is the exact
    defect this repository already corrected once.
    """
    problems: list[str] = []
    for match in pattern.finditer(text):
        groups = match.groupdict()
        module = groups.get("mod") or groups.get("mod2")
        symbol = groups.get("sym") or groups.get("sym2")
        # Both arms always populate one pair; asserting it keeps the types honest and turns a
        # future third arm that forgets its names into a failure rather than a skipped
        # citation.
        assert isinstance(module, str) and isinstance(symbol, str), match.group(0)
        if symbol not in _module_symbols(module):
            problems.append(f"{name}: {module}.{symbol} resolves to nothing")
    return problems


def test_the_citation_patterns_match_unbackticked_text() -> None:
    """The control the shipped gate did not have, and the reason it could not fire.

    Once the corpus is clean, every corpus sweep passes whether or not the patterns can see
    what they are supposed to -- there is nothing left to find either way. That is exactly how
    the first version of this gate shipped: it matched 0 of the released meta-schema's 13
    citations, because that file writes them as bare text inside JSON ``$comment`` strings,
    and a shared floor satisfied by the other document made it read as measured.

    So the discriminating power is asserted DIRECTLY, against synthetic text, one dimension
    per assertion. The first version of this test covered only the dimension that had already
    been fixed (backticks), and four further narrowings each left the whole suite green:
    restricting ``SOURCE_CITATION`` to two modules, dropping nested dotted tails, restricting
    ``TS_SYMBOL_CITATION`` to ``hash_profile`` alone, and zeroing ``CITATION_FLOORS``. Every
    one of those is now a named case below.
    """
    # -- dimension 1: BACKTICKS OPTIONAL. The released meta-schema writes citations bare.
    assert SOURCE_CITATION.search("see hash_profile.py:9999 for the cascade")
    assert SOURCE_CITATION.search("see `hash_profile.py:9999` for the cascade")
    assert SYMBOL_CITATION.search("hash_profile._Walker.walk collects the flag")
    assert SYMBOL_CITATION.search("`hash_profile._Walker.walk` collects the flag")

    # -- dimension 2: SOURCE_CITATION covers EVERY module, not just the two D9 touched.
    # Narrowing it to `hash_profile|hash_view` would re-hide `structural.py:137` and
    # `jcs.py:195`, two of the fourteen citations this gate was built to retire.
    for module in ("hash_profile", "hash_view", "jcs", "structural", "registry", "errors"):
        assert SOURCE_CITATION.search(f"{module}.py:12"), module

    # -- dimension 3: NESTED dotted tails. `hash_view._ViewBuilder._build_object` is the
    # correct spelling of two of the citations this gate already corrected; a pattern that
    # stopped at the first dot would match `_ViewBuilder`, resolve it, and pass.
    nested = SYMBOL_CITATION.search("hash_view._ViewBuilder._build_object decides opacity")
    assert nested is not None
    assert nested.group("sym") == "_ViewBuilder._build_object", nested.group("sym")

    # -- dimension 4: the TypeScript arm reaches the SAME-SPELLED modules, which is where
    # eight unread citations were sitting. Underscore in the tail is the discriminator.
    for probe in (
        "Mirrors Python's structural._OPERANDS",
        "Python's registry.ecma_262_pattern",
        "The port of registry.schema_failure_codes",
        "jcs.es_number_to_string renders the number",
        "structural._LEGACY_SCHEMA_KEYWORDS is restated",
    ):
        assert TS_SYMBOL_CITATION.search(probe), probe
    # ...and it still reaches the unambiguous modules with ANY tail, underscore or not.
    assert TS_SYMBOL_CITATION.search(
        "Mirrors hash_profile._require_declaration_only_is_legally_placed"
    )
    # -- dimension 4b: the AMBIGUOUS arm must keep nested tails too. `_SYMBOL_TAIL` losing
    # them is caught by dimension 3; `_AMBIGUOUS_TAIL` losing them was not, so a rename
    # inside a class of a same-spelled module could go unread.
    nested_ambiguous = TS_SYMBOL_CITATION.search("see structural._Step.name_of_it here")
    assert nested_ambiguous is not None
    assert nested_ambiguous.group("sym2") == "_Step.name_of_it", nested_ambiguous.group("sym2")
    # -- dimension 4c: a CamelCase class in a same-spelled module IS a citation, not code.
    # The underscore-only rule hid all 11 exception classes of `errors.py`, whose own header
    # says the class names are load-bearing for the port.
    assert TS_SYMBOL_CITATION.search("throws errors.UnknownExclusionError on a bad reason")
    assert TS_SYMBOL_CITATION.search("uses registry.CanonicalValidator for ECMA-262")

    # -- dimension 4d: the AMBIGUOUS arm's underscore may be in ANY tail segment, not only the
    # first. `[A-Za-z0-9]*_` cannot cross a dot, so `jcs.foo.bar_baz` was unreadable while the
    # residue measurement -- which asks `"_" not in symbol` of the whole dotted string -- did
    # not report it either. Invisible to both halves at once is the shape of a gap nobody finds.
    deep = TS_SYMBOL_CITATION.search("mirrors jcs.foo.bar_baz here")
    assert deep is not None, "an underscore below the first tail segment is unreadable"
    assert deep.group("sym2") == "foo.bar_baz", deep.group("sym2")
    # ...and the discrimination survives: a tail with no underscore and no capital ANYWHERE is
    # still ordinary TypeScript property access, not a citation.
    assert not TS_SYMBOL_CITATION.search("if (errors.foo.bar) { return; }")

    # -- negative controls, so "matches everything" cannot pass as "matches the right thing".
    assert not SOURCE_CITATION.search("hash_profile.py has the walker")
    assert not SYMBOL_CITATION.search("hash_profile.py has the walker")
    assert not SYMBOL_CITATION.search("structural.ts is the port")
    # The camelCase TypeScript siblings, which are references and not citations into Python.
    assert not TS_SYMBOL_CITATION.search("jcs.esNumberToString renders the number")
    # ...and ordinary code in the .ts files the sweep now reads WHOLE.
    assert not TS_SYMBOL_CITATION.search("if (errors.length > 0) { return errors.join(); }")
    assert not TS_SYMBOL_CITATION.search("registry.get(schemaId)")


#: Every extension that FABRICATED a symbol while ``_FILE_EXTENSIONS`` was ``py|ts|js|json|md``,
#: with the symbol it fabricated. Measured against the released patterns, not imagined: each
#: one was verified to match before the list was widened.
FILENAMES_THAT_FABRICATED_A_SYMBOL = [
    ("verification.test.tsx", "verification.test.tsx"),
    ("verification.test.jsx", "verification.test.jsx"),
    ("verification.test.mts", "verification.test.mts"),
    ("verification.test.cts", "verification.test.cts"),
    ("structural.foo.mjs", "structural.foo.mjs"),
    ("structural.foo.cjs", "structural.foo.cjs"),
    ("structural.foo.yml", "structural.foo.yml"),
    ("structural.foo.yaml", "structural.foo.yaml"),
    ("structural.foo.txt", "structural.foo.txt"),
    ("structural.foo.toml", "structural.foo.toml"),
    ("structural.foo.sh", "structural.foo.sh"),
    ("structural.json5", "structural.json5"),
    ("structural.jsonc", "structural.jsonc"),
    ("engine.pyi", "engine.pyi"),
    # The two-dots class: these DID match, one segment short of the extension, so they
    # fabricated a symbol that looks entirely plausible.
    ("verification.test.d.ts", "verification.test"),
    ("structural.foo.bar.ts", "structural.foo"),
    ("jcs.a.b.py", "jcs.a"),
    ("engine.x.y.md", "engine.x"),
]


@pytest.mark.parametrize(
    ("filename", "fabricated"),
    FILENAMES_THAT_FABRICATED_A_SYMBOL,
    ids=[name for name, _ in FILENAMES_THAT_FABRICATED_A_SYMBOL],
)
def test_no_filename_is_read_as_a_citation(filename: str, fabricated: str) -> None:
    """A FILENAME is not a citation, whatever it is a filename of.

    Two separate narrownesses, both measured against the released patterns before this was
    written, and both zero-impact today only because nobody has yet written such a filename
    down:

    1. ``_FILE_EXTENSIONS`` was ``py|ts|js|json|md``. Fourteen other extensions this
       repository plausibly writes -- ``.tsx`` first among them, since ``verification.test.tsx``
       is the natural name of the test file beside ``verification.ts`` -- each produced a match.
    2. The trailing-extension lookahead spanned ONE segment, so a filename with two dots simply
       let the greedy tail backtrack behind the extension: ``verification.test.d.ts`` fabricated
       the symbol ``verification.test``.

    Both fabricate a finding rather than miss one, which is the loud direction -- but a gate
    that reports a symbol nobody ever cited is a gate that gets weakened, and the first ``.tsx``
    filename written into EXTENSIONS.md would have turned CI red for no defect at all.

    Parametrized so each filename is its own named case: a single loop reports the first
    failure and hides the rest, and these are eighteen independent narrownesses.
    """
    # The fabrication is stated, not just the fix, so this test cannot be satisfied by patterns
    # that match nothing at all: `fabricated` is what the OLD pattern produced.
    assert fabricated  # documentation of the defect, kept beside its own case
    assert not SYMBOL_CITATION.search(filename), (
        f"{filename} is read as a citation of {fabricated!r}"
    )
    assert not TS_SYMBOL_CITATION.search(filename), (
        f"{filename} is read as a citation of {fabricated!r} inside a .ts file"
    )


def test_widening_the_extension_list_did_not_blind_the_patterns() -> None:
    """The false-negative control for the widening, which is the direction that costs.

    Every name added to ``_FILE_EXTENSIONS`` also forbids a tail SEGMENT from being that word,
    so widening far enough would start hiding real citations. Each entry is protected by ``\\b``;
    this is what asserts that the protection actually holds, rather than assuming it.
    """
    # A segment that merely STARTS with an extension name is still a segment.
    for tail in ("d_step", "shape", "mdx_node", "json_text", "tsv_reader", "pyi_stub", "txt_of"):
        assert SYMBOL_CITATION.search(f"structural.{tail} is real"), tail
    # Real citations from this repository, one per module, unchanged by the widening.
    for probe in (
        "hash_view._ViewBuilder._build_object decides opacity",
        "hash_profile.derive_hash_profile walks it",
        "jcs.canonicalize is the entry point",
        "structural._OPERANDS is restated",
        "registry.CanonicalValidator for ECMA-262",
        "rendering.json_text renders it",
    ):
        assert SYMBOL_CITATION.search(probe), probe
    # A citation ending a sentence, where the next character is a period, must still match --
    # the run-spanning lookahead must not read `. See` as the start of a dotted extension.
    ending = SYMBOL_CITATION.search("mirrors structural._OPERANDS. See the port.")
    assert ending is not None
    assert ending.group("sym") == "_OPERANDS", ending.group("sym")


def test_the_typescript_sources_are_read_whole_not_comment_lines_only() -> None:
    """Pins the whole-file read directly, because the corpus cannot pin it.

    The first version kept only lines whose stripped form began with ``//``/``*``/``/*``,
    which dropped every TRAILING comment -- ``const x = 1;  // see hash_profile.py:9999`` was
    invisible in a file the sweep had just been extended to cover. Restoring that filter is
    green against today's corpus, because every real citation happens to sit in a
    leading-position comment; only a synthetic assertion separates the two readings, exactly
    as with the backtick narrowing.

    Byte equality with the file on disk, so any filtering at all is red -- including a filter
    that happens to keep every citation today.
    """
    swept = {name: text for name, text, _ in _cited_documents() if name.endswith(".ts")}
    assert swept, "no TypeScript sources swept"
    for path in _typescript_sources():
        assert swept[path.name] == path.read_text(encoding="utf-8"), path.name

    # ...and the discrimination itself: a trailing comment must be visible to the patterns.
    trailing = "const x = 1;  // see hash_profile.py:9999 and structural.no_such_symbol"
    assert SOURCE_CITATION.search(trailing)
    assert TS_SYMBOL_CITATION.search(trailing)


@contextmanager
def planted_source(directory: Path, filename: str, text: str) -> Generator[Path]:
    """A source file planted in a FRESH directory under ``directory``, removed afterwards.

    A UNIQUE directory per invocation, and this replaced a fixed ``__citation_gate_probe__``
    that two tests created, wrote ``probe.ts`` into, and cleaned up with
    ``probe.unlink(missing_ok=True)`` then ``probe_dir.rmdir()``.

    That cleanup DELETES A REAL FILE. Measured: with
    ``packages/typescript/src/__citation_gate_probe__/probe.ts`` committed, the whole suite
    reported ``160 passed`` and the file and its directory were GONE from the tree afterwards
    -- a test suite silently deleting released source and reporting success. Any OTHER filename
    in that directory was loud instead (5 red, because ``rmdir`` refuses a non-empty directory),
    so the blind spot was exactly the name the tests themselves used. Which is the point: the
    reserved path was a self-inflicted hazard, and a unique directory has no reserved path to
    collide with.

    ``shutil.rmtree`` is safe here for the same reason: it only ever names a directory this
    function just created.
    """
    root = Path(tempfile.mkdtemp(prefix="_citation_gate_probe_", dir=directory))
    probe = root / filename
    try:
        probe.write_text(text, encoding="utf-8")
        yield probe
    finally:
        shutil.rmtree(root, ignore_errors=True)
    assert not root.exists(), root


@contextmanager
def planted_file(path: Path, text: str) -> Generator[Path]:
    """One file planted at an EXACT path, removed afterwards, refusing to overwrite.

    The pre-existence assertion is the whole difference from the reserved-path scheme this
    replaced: a probe that quietly overwrites a real file, and then unlinks it, is a test suite
    that deletes source and reports success. Here the collision is red before anything is
    written.
    """
    assert not path.exists(), f"{path} already exists; this probe refuses to overwrite it"
    try:
        path.write_text(text, encoding="utf-8")
        yield path
    finally:
        path.unlink(missing_ok=True)
    assert not path.exists(), path


def test_the_sweep_discovers_typescript_sources_recursively() -> None:
    """A ``.ts`` source in a SUBDIRECTORY of ``src/`` must be swept.

    ``glob("*.ts")`` missed one entirely, in both the sweep and the byte-equality backstop,
    and the count equality could not catch it because the count did not move. Swapping
    ``rglob`` back for ``glob`` is invisible to a clean corpus -- there is no subdirectory
    today -- so this creates one, asserts the sweep reads it, and removes it again. Every
    other definition of "the TypeScript sources" here is recursive: the package lint script
    and both tsconfigs use ``src/**/*.ts``.
    """
    with planted_source(
        TS_SOURCE_DIR, "probe.ts", "// see hash_profile._no_such_symbol_d94\n"
    ) as probe:
        swept = {name for name, _, _ in _cited_documents()}
        assert probe.name in swept, sorted(swept)
        problems = [
            problem
            for name, text, pattern in _cited_documents()
            if name == probe.name
            for problem in _unresolved_citations(name, text, pattern)
        ]
        assert problems, "a stale citation in a subdirectory was not reported"


def test_the_module_sweep_discovers_python_sources_recursively() -> None:
    """The mirror of the test above, for the half that was still non-recursive.

    ``_canonical_modules`` was ``glob("*.py")`` while ``_typescript_sources`` was ``rglob``, so
    a module in a SUBPACKAGE was cited by nothing and scanned by nothing -- and, exactly as in
    the TypeScript case, no count moves when one appears. Swapping ``rglob`` back for ``glob``
    is invisible to a clean corpus because no subpackage exists, so this creates one.

    A subpackage module is named as prose CITES it: dotted. ``spans.resolver.walk``, not
    ``resolver.walk``.
    """
    with planted_source(
        CANONICAL_SOURCE_DIR, "resolver.py", "def walk() -> None:\n    return None\n"
    ) as probe:
        package = probe.parent.name
        module = f"{package}.resolver"
        assert module in _canonical_modules(), _canonical_modules()

        # It is scanned: a citation into it resolves when the symbol exists...
        pattern = _symbol_citation()
        assert _unresolved_citations("probe", f"{module}.walk is the entry", pattern) == []
        # ...and is REPORTED when it does not, which is what "scanned" has to mean.
        assert _unresolved_citations("probe", f"{module}.no_such_d94", pattern) == [
            f"probe: {module}.no_such_d94 resolves to nothing"
        ]
        # The dotted module name must be matched WHOLE, not have `spans` swallow `resolver`
        # into the tail -- which is what an unescaped, first-match alternation would do.
        match = pattern.search(f"{module}.walk is the entry")
        assert match is not None
        assert (match.group("mod"), match.group("sym")) == (module, "walk"), match.groups()

    # ...and the module set is back to what it was, so the plant cannot leak into another test.
    assert all("." not in module for module in _canonical_modules()), _canonical_modules()


def test_the_ambiguous_name_test_is_case_sensitive_on_every_platform() -> None:
    """``Path.is_file()`` answers a case-INSENSITIVE question on macOS and a case-sensitive
    one on Linux CI, so the ambiguous-module set was platform-divergent.

    Nothing collides by case today, which is why this sat unnoticed: a clean corpus cannot
    expose it, and the divergence would first appear as a local pass and a CI failure (or the
    reverse) with no diff between them. Asserted directly against the real filesystem, so the
    test states which platform it is running on rather than assuming.
    """
    names = _typescript_source_names()
    assert "hashProfile.ts" in names, sorted(names)
    # The set is exact-case; the filesystem may or may not be.
    assert "hashprofile.ts" not in names, sorted(names)
    assert "HASHPROFILE.TS" not in names, sorted(names)

    # The derivation must use the SET. If it went back to `is_file()`, a module named
    # `hashprofile` would be ambiguous here and unambiguous in CI, because only
    # `hashProfile.ts` exists. Planting one at the top level -- where its module name really is
    # the bare `hashprofile` -- proves which question is being asked, on whichever filesystem
    # this happens to run on.
    #
    # `Path.is_file()` is measured beside it rather than described, so the divergence is
    # evidence and not a claim: on macOS the two disagree, on Linux they agree, and the
    # derivation must follow the SET either way.
    assert (TS_SOURCE_DIR / "hashProfile.ts").is_file()
    with planted_file(CANONICAL_SOURCE_DIR / "hashprofile.py", "X = 1\n"):
        assert "hashprofile" in _canonical_modules(), _canonical_modules()
        assert "hashprofile" not in _ambiguously_named_modules(), {
            "ambiguous": sorted(_ambiguously_named_modules()),
            "is_file() answers": (TS_SOURCE_DIR / "hashprofile.ts").is_file(),
        }

    # The false-positive control for the assertion above: a name that really IS shared must
    # still come out ambiguous, so "nothing is ever ambiguous" cannot pass as a fix.
    assert "structural" in _ambiguously_named_modules(), _ambiguously_named_modules()
    assert "hash_profile" not in _ambiguously_named_modules(), _ambiguously_named_modules()


def test_the_released_sweeps_actually_fail_on_a_dirty_corpus() -> None:
    """The emptiness assertions are only exercised when something IS wrong.

    ``assert not problems, problems`` and ``assert not offenders, ...`` never evaluate a
    non-empty list against a clean corpus, so replacing either with a tautology --
    ``assert isinstance(problems, list)`` -- passes the whole suite. The two sweeps are
    therefore invoked here against a DELIBERATELY DIRTY tree and required to raise.

    This is the same lesson as the backtick narrowing and the comment-only filter, for the
    third time: a clean corpus cannot pin a gate's discriminating power, only a synthetic one
    can.
    """
    with planted_source(
        TS_SOURCE_DIR,
        "probe.ts",
        "// see hash_profile._no_such_symbol_d94 at hash_profile.py:9999\n",
    ):
        with pytest.raises(AssertionError):
            test_every_symbol_citation_resolves_in_the_module_it_names()
        with pytest.raises(AssertionError):
            test_no_citation_names_a_source_line_number()
    # ...and with the probe gone both are green again, so the raises above were about the
    # probe and not about some unrelated breakage.
    test_every_symbol_citation_resolves_in_the_module_it_names()
    test_no_citation_names_a_source_line_number()


def test_the_resolver_itself_is_falsifiable() -> None:
    """**The fifth narrowing dimension, and the one with no control until now.**

    Every other control here targets the PATTERN (what is scanned) or the FLOORS (how much).
    Nothing targeted the RESOLVER -- the half that actually kills renames -- and five separate
    resolver mutations were green against the entire suite: turning ``assert not problems``
    into a tautology, a symbol table whose ``__contains__`` always answers True, collecting
    every ``ast.Name`` so any identifier resolves, case-insensitive membership, and resolving
    only the FIRST segment of a dotted tail.

    That last one is not hypothetical: it ships ``hash_view._ViewBuilder._no_such`` as valid,
    which is the exact ``_ViewBuilder`` defect this repository already corrected once, and it
    is what the nested-tail pattern control was added to prevent -- but that control pins the
    pattern's CAPTURE, not the resolver's USE of it.

    Synthetic text, so none of this depends on the corpus being dirty.
    """
    fabricated = "hash_profile.no_such_symbol_d94 does not exist"
    assert _unresolved_citations("probe", fabricated, SYMBOL_CITATION) == [
        "probe: hash_profile.no_such_symbol_d94 resolves to nothing"
    ]
    # ...and the control, so "reports everything" cannot pass as "reports the right thing".
    assert _unresolved_citations("probe", "hash_profile._Walker.walk", SYMBOL_CITATION) == []

    # A nested tail must resolve WHOLE. First-segment-only resolution leaves this green.
    assert _unresolved_citations(
        "probe", "hash_view._ViewBuilder._no_such_d94", SYMBOL_CITATION
    ) == ["probe: hash_view._ViewBuilder._no_such_d94 resolves to nothing"]
    assert (
        _unresolved_citations("probe", "hash_view._ViewBuilder._build_object", SYMBOL_CITATION)
        == []
    )

    # Membership is case-SENSITIVE: Python names are, and a case-insensitive table would
    # accept `hash_profile.DERIVE_HASH_PROFILE` for `derive_hash_profile`.
    assert _unresolved_citations("probe", "hash_profile.DERIVE_HASH_PROFILE", SYMBOL_CITATION)
    assert not _unresolved_citations("probe", "hash_profile.derive_hash_profile", SYMBOL_CITATION)

    # The symbol table holds DEFINITIONS, not every identifier. Collecting every `ast.Name`
    # is the plausible "stop the false finding" fix, and it makes the gate resolve anything.
    symbols = _module_symbols("hash_profile")
    assert "derive_hash_profile" in symbols
    assert "_Walker.walk" in symbols
    assert "walker" not in symbols, "local variables must not resolve"
    assert "schema_ref" not in symbols, "parameter names must not resolve"

    # The membership test must be a real containment check, not a container that answers True
    # to everything -- a symbol table mutated that way makes every citation resolve.
    assert "no_such_symbol_d94" not in symbols
    assert len(symbols) < 500, len(symbols)

    # That the FINDINGS are consumed by a FAILING assertion, rather than merely computed, is
    # pinned separately by
    # ``test_the_released_sweeps_actually_fail_on_a_dirty_corpus``, which invokes the released
    # sweeps against a planted probe.


def test_the_ambiguous_arm_residue_is_measured_not_guessed() -> None:
    """What the TypeScript sweep still cannot see, counted from the package.

    Inside a ``.ts`` file an ambiguously-named module's tail must look like a Python name --
    starts with a capital, or contains an underscore -- because ``jcs.esNumberToString`` and
    ``errors.length`` are not citations. The residue is therefore the LOWERCASE SINGLE-WORD
    symbols of those modules, which a ``.ts`` file could cite and this sweep would not read.

    An earlier docstring called the residue "a Python symbol with no underscore
    (``jcs.canonicalize``)" while the rule then in force required an underscore, which hid the
    entire CamelCase class namespace -- all of ``errors.py``'s exception classes and
    ``registry.CanonicalValidator``. Widening to "capital OR underscore" recovered those; this
    test states what is left, and moves the day it changes.
    """
    invisible = {
        module: sorted(
            symbol
            for symbol in _module_symbols(module)
            if "_" not in symbol and not symbol[:1].isupper()
        )
        for module in sorted(_ambiguously_named_modules())
    }
    total = sum(len(names) for names in invisible.values())
    # Non-vacuity: an empty measurement would make the equality below trivially satisfiable.
    assert invisible, sorted(_ambiguously_named_modules())
    # MEASURED, and the measurement corrected a guess: this was first written as 4 and the
    # package says 1. The whole residue is `jcs.canonicalize` -- one symbol across the SEVEN
    # ambiguously-named modules (`engine`, `errors`, `jcs`, `registry`, `rendering`,
    # `structural`, `verification`; this comment said six until `rendering.ts` landed, and the
    # count is now derived below rather than restated), because every other lowercase name in
    # them carries an underscore. Under the previous underscore-only rule the residue was 12
    # (this one plus all 11 of `errors.py`'s exception classes) plus `registry.CanonicalValidator`.
    assert total == 1, invisible
    # DERIVED, so the prose above cannot drift from the package the way "six" did.
    assert len(_ambiguously_named_modules()) == 7, sorted(_ambiguously_named_modules())
    assert invisible["jcs"] == ["canonicalize"], invisible["jcs"]
    # The CamelCase namespace is NOT in the residue any more -- that is what widening bought.
    assert "CanonicalValidator" not in invisible["registry"], invisible["registry"]
    exception_classes = [name for name in _module_symbols("errors") if name.endswith("Error")]
    assert len(exception_classes) >= 10, exception_classes
    assert not any(name in invisible["errors"] for name in exception_classes)

    # THE TWO HALVES MUST AGREE, symbol by symbol. The rule this counts and the rule the
    # pattern enforces were written separately and diverged: `_PYTHON_SHAPED` asked for an
    # underscore in the FIRST tail segment (`[A-Za-z0-9]*_` cannot cross a dot) while the
    # comprehension above asks `"_" not in symbol` of the WHOLE dotted string, so a symbol like
    # `jcs.foo.bar_baz` was unreadable by the pattern AND unreported by the count -- a gap
    # hidden from both halves at once. Nothing in the package had that shape, so no number moved
    # and neither half was wrong about anything visible.
    #
    # Derived from the real symbol table rather than asserted on examples, so it re-measures the
    # day a symbol of that shape is written.
    disagreements = [
        f"{module}.{symbol}: pattern={matched}, counted_invisible={symbol in invisible[module]}"
        for module in sorted(_ambiguously_named_modules())
        for symbol in sorted(_module_symbols(module))
        if (matched := bool(TS_SYMBOL_CITATION.fullmatch(f"{module}.{symbol}")))
        is (symbol in invisible[module])
    ]
    assert disagreements == [], disagreements
    # Non-vacuity for the loop above: it must really have compared symbols, and both outcomes
    # must occur, or "they agree" would be a statement about an empty or one-sided population.
    considered = [
        symbol
        for module in sorted(_ambiguously_named_modules())
        for symbol in _module_symbols(module)
    ]
    assert len(considered) > 30, len(considered)
    assert total >= 1 and len(considered) > total, (total, len(considered))


def test_no_typescript_source_shadows_an_ambiguous_module_name_with_a_python_shaped_field() -> None:
    """The false-positive direction, stated and pinned rather than hoped away.

    ``errors`` is a live LOCAL VARIABLE in several ``src`` files, and snake_case dotted access
    is this repository's normal style, so ``errors.failure_summary`` would be read as a
    citation and reported as resolving to nothing -- a FABRICATED finding. There is no regex
    that separates "property access on a local named ``errors``" from "citation into
    ``errors.py``"; the discriminator is only the SHAPE of the tail.

    The trade is deliberate and is the safe direction: a fabricated finding is loud and gets
    investigated, where a missed citation is silent. The corpus carries zero of them today and
    this pins that, so the first one is a decision rather than a surprise.

    REDUNDANT WITH ``test_every_symbol_citation_resolves_in_the_module_it_names``, which sweeps
    the same ``.ts`` files as part of a wider set, and kept deliberately: the two make different
    CLAIMS about the same measurement, and this one is the claim that gets contradicted first.
    Redundancy is not the weakness here -- the weakness was that ``assert collisions == []``
    never evaluates a non-empty list against a clean corpus, so replacing it with
    ``assert isinstance(collisions, list)`` passed. The synthetic half below is what closes
    that, and it is the same lesson as the backtick narrowing and the comment-only filter.
    """
    collisions = [
        problem
        for name, text, pattern in _cited_documents()
        if name.endswith(".ts")
        for problem in _unresolved_citations(name, text, pattern)
    ]
    assert collisions == [], collisions

    # The synthetic half: a python-shaped shadow of an ambiguously-named module MUST be
    # reported, or the emptiness above is a statement about a gate that cannot speak.
    shadow = "const errors = collect();\nif (errors.failure_summary) { throw errors.join(); }\n"
    assert _unresolved_citations("shadow.ts", shadow, TS_SYMBOL_CITATION) == [
        "shadow.ts: errors.failure_summary resolves to nothing"
    ]
    # ...and the corresponding non-shadow really is silent, so "reports everything" cannot pass
    # as "reports the right thing".
    assert (
        _unresolved_citations(
            "shadow.ts", "if (errors.length > 0) { return errors.join(); }", TS_SYMBOL_CITATION
        )
        == []
    )


def test_the_citation_floors_are_not_all_zero() -> None:
    """``CITATION_FLOORS`` zeroed left the whole suite green, so the floors need a floor.

    Every entry is a number somebody could quietly reduce to silence a failure; the aggregate
    is asserted here so that reducing one to zero is red on its own, without waiting for a
    citation to rot in that particular file.
    """
    assert all(floor >= 1 for floor in CITATION_FLOORS.values()), CITATION_FLOORS
    assert sum(CITATION_FLOORS.values()) >= 40, CITATION_FLOORS
    assert len(CITATION_FLOORS) >= 6, sorted(CITATION_FLOORS)


def _floor_violations(counts: dict[str, int]) -> list[str]:
    """Every document whose citation count is not EXACTLY its pinned number.

    Extracted so the comparison can be exercised against synthetic counts. It was written as
    ``>=`` with five slack on the two prose entries, and five was enough to absorb a real
    narrowing -- pairing the ambiguous-arm pattern with EXTENSIONS.md dropped it 30 to 28 and
    stayed green, while the ``.ts`` entries, already exact, caught the same narrowing. Once
    every entry is exact, loosening the operator back to ``>=`` is invisible to a clean
    corpus, so the comparison itself needs a control.
    """
    return [
        f"{name}: {counts.get(name, 0)} citations, pinned at {expected}"
        for name, expected in CITATION_FLOORS.items()
        if counts.get(name, 0) != expected
    ]


def test_the_floor_comparison_is_exact_not_a_lower_bound() -> None:
    """The control for the comparison, on synthetic counts.

    A count BELOW the pin and a count ABOVE it must both be violations. Loosening to a lower
    bound with slack -- the spelling this replaced -- passes the whole suite against a clean
    corpus, because nothing has drifted yet.
    """
    exact = dict(CITATION_FLOORS)
    assert _floor_violations(exact) == []
    for name in CITATION_FLOORS:
        assert _floor_violations({**exact, name: CITATION_FLOORS[name] - 1}), name
        assert _floor_violations({**exact, name: CITATION_FLOORS[name] + 1}), name
        assert _floor_violations({**exact, name: CITATION_FLOORS[name] - 5}), name
    # ...and a document vanishing entirely is a violation, not a zero quietly tolerated.
    missing = {k: v for k, v in exact.items() if k != "EXTENSIONS.md"}
    assert _floor_violations(missing)


def test_the_citation_sweep_reads_every_document_it_claims_to() -> None:
    """Non-vacuity, per document, because a shared floor hid a document contributing zero.

    ``CITATION_FLOORS`` names the artifacts whose citation count must not collapse. Emptying
    ``_cited_documents()``, un-backticking one file, or relocating the TypeScript sources all
    move a number here instead of quietly reducing what is scanned.
    """
    counts = {
        name: len(pattern.findall(text)) + len(SOURCE_CITATION.findall(text))
        for name, text, pattern in _cited_documents()
    }
    assert _floor_violations(counts) == [], _floor_violations(counts)
    swept_ts = sorted(name for name in counts if name.endswith(".ts"))
    assert len(swept_ts) == EXPECTED_TS_SOURCES, swept_ts
    assert len(counts) == EXPECTED_TS_SOURCES + 2, sorted(counts)


def test_no_citation_names_a_source_line_number() -> None:
    """The class-killer. A line reference is wrong the moment anything above it moves.

    This is not style. Adding a single ``import`` to ``hash_profile.py`` silently invalidated
    three references in the RELEASED meta-schema ``$comment`` -- prose that ships as an
    artifact and that a second implementation reads as normative. Those three were
    unbackticked, which is exactly why this test could not see them when it was written.
    """
    offenders = [
        f"{name}: {match.group(0)}"
        for name, text, _pattern in _cited_documents()
        for match in SOURCE_CITATION.finditer(text)
    ]
    assert not offenders, "cite a symbol, not a line: " + "; ".join(offenders)


def test_every_symbol_citation_resolves_in_the_module_it_names() -> None:
    """A citation that names nothing is the same defect as one that names the wrong line.

    **Existence only, deliberately, and this is the gate's honest limit.** It proves the named
    symbol is defined in the named module; it cannot prove the symbol is the RIGHT one, so a
    citation moved to a real-but-wrong sibling function stays green. Closing that would mean
    checking prose against behaviour, which no regex can do. What it does close is the class
    that actually occurred: a rename leaving a citation pointing at nothing.

    Derived from the documents AND from the package: both the module set and the
    ambiguous-name set are computed from the filesystem. This docstring previously claimed
    derivation while an alternation of six modules sat beside it and the package held eight,
    so ``engine`` and ``verification`` went unscanned and four live citations in
    ``verification.ts`` were unread.
    """
    problems = [
        problem
        for name, text, pattern in _cited_documents()
        for problem in _unresolved_citations(name, text, pattern)
    ]
    assert not problems, problems


def test_the_three_identity_compared_annotations_really_are_identity_compared() -> None:
    """The claim every one of those citations was making, checked against the source.

    DERIVED from the meta-schema's own ``$comment``s rather than a list written here: any
    annotation whose ``$defs`` entry says it "tests ``is True``" must have exactly that line
    in ``hash_profile.py``. Adding a fourth boolean annotation and forgetting the identity
    comparison makes this red without anybody editing this file.
    """
    schema = meta_schema()
    source = (CANONICAL_SOURCE_DIR / "hash_profile.py").read_text(encoding="utf-8")
    claimed = {
        name.removeprefix("x-datacompany-").replace("-", "_"): name
        for name in schema["$defs"]["vocabulary"]["enum"]
    }
    identity_compared = [
        claimed[key]
        for key, definition in schema["$defs"].items()
        if key in claimed and "is True" in str(definition.get("$comment", ""))
    ]
    # Non-vacuity: hash_excluded, hash_opaque and hash_declaration_only all say it today.
    assert len(identity_compared) == 3, identity_compared
    for annotation in identity_compared:
        expected = f'schema.get("{annotation}") is True'
        assert expected in source, f"{annotation}: the meta-schema claims `{expected}`, absent"


# ------------------------------------------------------------- 4. falsifiability ---
#
# Each case below is a real annotation node with exactly one member mutated. The control
# is the unmutated node, asserted to PASS in the same test, so a case that "rejects" because
# the base node was already broken cannot masquerade as a working rule.

EXCLUDED_NODE: dict[str, Any] = {
    "type": "string",
    "x-datacompany-hash-excluded": True,
    "x-datacompany-hash-exclusion-reason": "signature",
}

ARRAY_NODE: dict[str, Any] = {
    "type": "array",
    "x-datacompany-array": {
        "kind": "set",
        "order_key": ["/owner_context", "/entity_id"],
    },
}

RULE_NODE: dict[str, Any] = {
    "type": "object",
    "x-datacompany-cross-field": [
        {"rule": "half_open_interval", "name": "valid", "from": "/valid_from", "to": "/valid_to"}
    ],
}

OPAQUE_NODE: dict[str, Any] = {"type": "object", "x-datacompany-hash-opaque": True}

#: D9, vocabulary 1.2. The shape a domain writes to declare an array INSIDE an opaque
#: subtree: the flag says the node declares no hashed path, the array declaration beside it
#: still reaches the manifest. See EXTENSIONS.md section 3.6.
DECLARATION_ONLY_NODE: dict[str, Any] = {
    "type": "array",
    "x-datacompany-hash-declaration-only": True,
    "x-datacompany-array": {"kind": "ordered"},
}

COMPOSITION_NODE: dict[str, Any] = {
    "type": "object",
    "x-datacompany-composition-point": "#/$defs/domain_extension",
}

MUTATIONS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    (
        "a misspelled annotation name, which the engine ignores in silence",
        EXCLUDED_NODE,
        {
            "type": "string",
            "x-datacompany-hash-exclude": True,
            "x-datacompany-hash-excluded": True,
            "x-datacompany-hash-exclusion-reason": "signature",
        },
    ),
    (
        "an unregistered annotation in the namespace",
        EXCLUDED_NODE,
        {**EXCLUDED_NODE, "x-datacompany-hash-priority": 3},
    ),
    (
        "hash-excluded: false, an identity-comparison no-op that leaves the path hashed",
        EXCLUDED_NODE,
        {**EXCLUDED_NODE, "x-datacompany-hash-excluded": False},
    ),
    (
        'hash-excluded: "true", the same no-op spelled as a string',
        EXCLUDED_NODE,
        {**EXCLUDED_NODE, "x-datacompany-hash-excluded": "true"},
    ),
    (
        "an exclusion reason with no flag beside it, which the engine discards",
        EXCLUDED_NODE,
        {"type": "string", "x-datacompany-hash-exclusion-reason": "signature"},
    ),
    (
        "an exclusion flag with no reason",
        EXCLUDED_NODE,
        {"type": "string", "x-datacompany-hash-excluded": True},
    ),
    (
        "an exclusion reason outside the released closed set",
        EXCLUDED_NODE,
        {**EXCLUDED_NODE, "x-datacompany-hash-exclusion-reason": "because_i_said_so"},
    ),
    (
        "hash-opaque: false, the same identity-comparison no-op",
        OPAQUE_NODE,
        {"type": "object", "x-datacompany-hash-opaque": False},
    ),
    (
        "x-datacompany-array as a bare string, which the engine drops on the isinstance check",
        ARRAY_NODE,
        {"type": "array", "x-datacompany-array": "set"},
    ),
    (
        "x-datacompany-array carrying its own pointer, which re-targets the declaration",
        ARRAY_NODE,
        {"type": "array", "x-datacompany-array": {"pointer": "/elsewhere", "kind": "ordered"}},
    ),
    (
        "a set-like array with no order_key",
        ARRAY_NODE,
        {"type": "array", "x-datacompany-array": {"kind": "set"}},
    ),
    (
        "an ordered array carrying an order_key",
        ARRAY_NODE,
        {"type": "array", "x-datacompany-array": {"kind": "ordered", "order_key": ["/a"]}},
    ),
    (
        "an unregistered collection kind",
        ARRAY_NODE,
        {"type": "array", "x-datacompany-array": {"kind": "multiset", "order_key": ["/a"]}},
    ),
    (
        "hash-declaration-only: false, the third identity-comparison no-op",
        DECLARATION_ONLY_NODE,
        {**DECLARATION_ONLY_NODE, "x-datacompany-hash-declaration-only": False},
    ),
    (
        "hash-declaration-only beside hash-excluded, two contradictory acts on one pointer",
        DECLARATION_ONLY_NODE,
        {
            **DECLARATION_ONLY_NODE,
            "x-datacompany-hash-excluded": True,
            # A valid reason, deliberately: without it the mutant would be rejected by
            # exclusion_reason_pairing and prove nothing about declaration_only_pairing.
            "x-datacompany-hash-exclusion-reason": "signature",
        },
    ),
    (
        "hash-declaration-only beside hash-opaque, which would make the engine's "
        "strictly-under placement guard satisfiable by the node itself",
        DECLARATION_ONLY_NODE,
        {**DECLARATION_ONLY_NODE, "x-datacompany-hash-opaque": True},
    ),
    (
        "an unregistered cross-field operator",
        RULE_NODE,
        {
            "type": "object",
            "x-datacompany-cross-field": [{"rule": "greater_than", "left": "/a", "right": "/b"}],
        },
    ),
    (
        "half_open_interval missing its `to` operand, which raises a bare KeyError",
        RULE_NODE,
        {
            "type": "object",
            "x-datacompany-cross-field": [{"rule": "half_open_interval", "from": "/valid_from"}],
        },
    ),
    (
        "unique_by missing its `at` operand",
        RULE_NODE,
        {"type": "object", "x-datacompany-cross-field": [{"rule": "unique_by", "key": "/pointer"}]},
    ),
    (
        "disjoint missing its `right` operand",
        RULE_NODE,
        {"type": "object", "x-datacompany-cross-field": [{"rule": "disjoint", "left": "/a"}]},
    ),
    (
        "a rule operand that is not a JSON Pointer",
        RULE_NODE,
        {
            "type": "object",
            "x-datacompany-cross-field": [
                {"rule": "equal", "left": "valid_from", "right": "/valid_to"}
            ],
        },
    ),
    (
        "a rule carrying an operand that belongs to a different operator",
        RULE_NODE,
        {
            "type": "object",
            "x-datacompany-cross-field": [
                {"rule": "equal", "left": "/a", "right": "/b", "order_key": ["/c"]}
            ],
        },
    ),
    (
        "x-datacompany-cross-field as a bare string, which the engine iterates character by "
        "character into an AttributeError",
        RULE_NODE,
        {"type": "object", "x-datacompany-cross-field": "equal"},
    ),
    (
        "an empty rule list, indistinguishable from a rule deleted by mistake",
        RULE_NODE,
        {"type": "object", "x-datacompany-cross-field": []},
    ),
    (
        "a null rule, which the engine turns into an AttributeError",
        RULE_NODE,
        {"type": "object", "x-datacompany-cross-field": [None]},
    ),
    (
        "a composition point that is not a document-relative $defs pointer",
        COMPOSITION_NODE,
        {"type": "object", "x-datacompany-composition-point": "domain_extension"},
    ),
    (
        "a composition point with a trailing newline, which Python's `$` accepts and "
        "ECMA-262's does not (B7)",
        COMPOSITION_NODE,
        {"type": "object", "x-datacompany-composition-point": "#/$defs/domain_extension\n"},
    ),
]


@pytest.mark.parametrize(
    ("description", "control", "mutant"), MUTATIONS, ids=[case[0] for case in MUTATIONS]
)
def test_the_meta_schema_rejects_each_malformed_annotation(
    description: str, control: dict[str, Any], mutant: dict[str, Any]
) -> None:
    """The gate is proven able to fail, one mutation at a time, against a passing control."""
    validator = meta_validator()
    assert not list(validator.iter_errors(control)), (
        f"control for {description!r} does not validate; the rejection below would prove nothing"
    )
    assert list(validator.iter_errors(mutant)), f"NOT REJECTED: {description}"


def test_a_declaration_only_node_that_carries_only_properties_is_accepted() -> None:
    """The false-positive control for the rule that was written, tried and DELETED.

    An earlier ``declaration_only_pairing`` required ``x-datacompany-array`` or
    ``x-datacompany-cross-field`` beside the flag, reasoning that a node "reached only to carry
    annotations" which carries none declares nothing. That rule rejected the *intended*
    shape: because the suppression cascades by prefix, the way to declare a deep array is one
    flag on the OUTERMOST node of the ``properties`` chain -- and that node carries only
    ``properties``. The limit that remains is recorded in EXTENSIONS.md section 8.1 rather
    than replaced by a rule that reads strict and is wrong.

    Without this control, re-adding the rule would turn three mutation cases green and
    nothing would say it had broken a legal schema.
    """
    outermost_of_a_chain = {
        "type": "object",
        "x-datacompany-hash-declaration-only": True,
        "properties": {"tags": {"type": "array", "x-datacompany-array": {"kind": "ordered"}}},
    }
    assert not list(meta_validator().iter_errors(outermost_of_a_chain))


def test_a_node_with_no_datacompany_member_is_not_constrained() -> None:
    """False-positive control: the meta-schema must not reject ordinary JSON Schema."""
    assert not list(meta_validator().iter_errors({"type": "string", "minLength": 1}))


def test_the_ecma_262_validator_choice_is_load_bearing() -> None:
    """Proof that ``CanonicalValidator`` is not decorative here.

    The trailing-newline mutation above only fails because ``pattern`` is evaluated with
    ECMA-262 semantics. Under the stock ``Draft202012Validator`` — Python's ``$``, which
    also matches immediately before a trailing ``\\n`` — the very same annotation
    **validates**. Without this test, swapping the validator back would silently reopen
    B7 inside the gate built to catch that class of defect, and every other check would
    stay green.
    """
    newline_annotation = {
        "type": "object",
        "x-datacompany-composition-point": "#/$defs/domain_extension\n",
    }
    schema = meta_schema()
    contents = {key: value for key, value in schema.items() if key != "$schema"}
    registry = schema_registry().with_resource(
        schema["$id"], Resource.from_contents(contents, default_specification=DRAFT202012)
    )
    permissive = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())

    assert not list(permissive.iter_errors(newline_annotation)), (
        "the stock validator was expected to ACCEPT the trailing newline; if it now rejects "
        "it, this proof is stale and the mutation case no longer isolates ECMA-262 semantics"
    )
    assert list(meta_validator().iter_errors(newline_annotation))


def test_every_committed_annotation_shape_survives_the_mutation_controls() -> None:
    """The mutation controls must be shapes the committed schemas really use.

    A falsifiability suite built on shapes nobody writes proves the gate rejects fiction.
    """
    used_operators = {
        rule["rule"]
        for _, _, node in ANNOTATED
        for rule in node.get("x-datacompany-cross-field", [])
    }
    assert used_operators, "no cross-field rule found in any committed schema"
    assert used_operators <= set(meta_schema()["$defs"]["cross_field_operator"]["enum"])


# ===================================================== decision F: the engines fail closed ===
#
# Until 2026-07-30 neither engine validated the ANNOTATIONS themselves, so a malformed
# `x-datacompany-cross-field` failed DIFFERENTLY in the two languages -- a bare string was
# iterated character by character into an `AttributeError` in Python and produced NO RULES,
# silently, in TypeScript. The meta-schema above already rejected every one of those shapes;
# what was missing was the engines consulting it. `structural._declared_rules` now does, and
# these tests pin that the executable check and the declarative one agree.


def test_the_engine_operand_table_matches_the_meta_schema() -> None:
    """Two sources of one contract, cross-checked in both directions.

    ``structural._OPERANDS`` re-states the per-operator operand contract so that the
    TypeScript port can reproduce it without shipping a JSON Schema validator. That is only
    safe while it cannot drift from ``#/$defs/cross_field_rule``, which is what this asserts:
    the operator set, the REQUIRED operands and the OPTIONAL operands are derived from the
    meta-schema here and compared, so widening either side alone goes red.
    """
    branches = meta_schema()["$defs"]["cross_field_rule"]["allOf"]
    derived: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for branch in branches:
        constraint = branch["if"]["properties"]["rule"]
        operators = constraint.get("enum", [constraint["const"]] if "const" in constraint else [])
        required = frozenset(branch["then"]["required"])
        declared = frozenset(branch["then"]["properties"])
        for operator in operators:
            derived[operator] = (required, declared - required)

    assert derived == structural_module._OPERANDS, (
        "the engine's operand table and the meta-schema's per-operator branches disagree"
    )
    # Non-vacuity: an empty derivation would make the equality above trivially satisfiable
    # by an empty table on both sides.
    assert set(derived) == set(meta_schema()["$defs"]["cross_field_operator"]["enum"])


CROSS_FIELD_MUTANTS = [
    (description, mutant)
    for description, control, mutant in MUTATIONS
    if "x-datacompany-cross-field" in mutant and control is RULE_NODE
]


def test_there_really_are_cross_field_mutants_to_check() -> None:
    """Non-vacuity guard for the parametrised sweep below."""
    assert len(CROSS_FIELD_MUTANTS) >= 5, CROSS_FIELD_MUTANTS


@pytest.mark.parametrize(
    ("description", "mutant"), CROSS_FIELD_MUTANTS, ids=[case[0] for case in CROSS_FIELD_MUTANTS]
)
def test_every_malformed_declaration_the_meta_schema_rejects_also_raises_in_the_engine(
    monkeypatch: pytest.MonkeyPatch, description: str, mutant: dict[str, Any]
) -> None:
    """The engine must fail CLOSED, and with a typed error, on every shape the gate rejects.

    An ``AttributeError`` or a ``KeyError`` escaping the failure-collection path is not a
    diagnosis, and a silently empty rule list is worse: the contract reads as enforced and
    enforces nothing. Both are ruled out by requiring ``CrossFieldError`` specifically.
    """
    probe_id = "urn:datacompany:decision-f-probe:1"
    probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": probe_id,
        **mutant,
    }
    schemas = {**canonical_schemas_for_probe(), probe_id: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        with pytest.raises(CrossFieldError):
            structural_module.collect_cross_field_rules(probe_id)
    finally:
        structural_module._collect.cache_clear()


def test_the_control_declaration_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """False-positive control: the well-formed declaration those mutants derive from passes.

    Without this, an engine that rejected EVERY declaration would satisfy the sweep above.
    """
    probe_id = "urn:datacompany:decision-f-control:1"
    probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": probe_id,
        **RULE_NODE,
    }
    schemas = {**canonical_schemas_for_probe(), probe_id: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        assert len(structural_module.collect_cross_field_rules(probe_id)) == 1
    finally:
        structural_module._collect.cache_clear()


# ============================ the authoring-path fail-opens: 7.1-7.4, and 7.6 ===
#
# Decision F closed EXTENSIONS.md section 7.5 by making both engines CONSULT the meta-schema
# -- restating its rules in code, under a drift test that derives them back OUT of the
# meta-schema and compares in both directions -- rather than by the engine growing a
# validator of its own. Sections 7.1-7.4 are the same class on the DERIVATION side and are
# closed the same way: the meta-schema already rejected every shape below (the MUTATIONS
# table above proves it, one mutation at a time), so nothing normative was invented here
# either. What was missing was `hash_profile` consulting it.


def test_the_engine_vocabulary_matches_the_meta_schema() -> None:
    """Two sources of one contract, cross-checked in both directions (section 7.1).

    ``hash_profile._VOCABULARY`` re-states the closed set of released annotation names so
    that the TypeScript port can reproduce the check without shipping a JSON Schema
    validator. That is only safe while it cannot drift from ``#/$defs/vocabulary``, which is
    what this asserts. Widening either side alone goes red: adding a name to the meta-schema
    without teaching the engine leaves the engine REFUSING a released annotation, and adding
    one to the engine without declaring it leaves an unregistered name accepted -- which is
    section 7.1 itself.
    """
    declared = set(meta_schema()["$defs"]["vocabulary"]["enum"])
    assert declared == set(hash_profile_module._VOCABULARY)
    # Non-vacuity: two empty sets are equal, and an empty vocabulary would make the engine
    # refuse every annotation while this test stayed green.
    assert len(declared) == 7, sorted(declared)


def test_the_engine_array_member_table_matches_the_meta_schema() -> None:
    """The same drift check for ``x-datacompany-array``'s member contract (sections 7.3, 7.4).

    The meta-schema's ``array_annotation`` is ``additionalProperties: false`` with
    ``required: ["kind"]``, and the engine re-states exactly those two facts -- the member
    NAMES, and which of them is required. It deliberately re-states nothing about what
    ``kind`` and ``order_key`` may CONTAIN: the meta-schema ``$ref``s
    ``canonical-hash-profile.v1`` for both, and the engine defers to the same document by
    validating the derived manifest against it, so a third copy would be the drift this test
    exists to prevent.
    """
    annotation = meta_schema()["$defs"]["array_annotation"]
    assert annotation["additionalProperties"] is False, (
        "the engine's member check re-states additionalProperties:false; without it in the "
        "meta-schema the restatement is stricter than the declaration it claims to mirror"
    )
    required = frozenset(annotation["required"])
    declared = frozenset(annotation["properties"])
    assert required == hash_profile_module._ARRAY_REQUIRED_MEMBERS
    assert declared - required == hash_profile_module._ARRAY_OPTIONAL_MEMBERS
    # Non-vacuity, in the direction the two equalities above cannot see.
    assert declared == {"kind", "order_key"}, sorted(declared)


# ------------------------------------------------------------- symptom reproductions ---
#
# Each test below is the defect as EXTENSIONS.md section 7 records it -- the misspelled
# name, the lone reason, the three non-object values, the self-retargeting pointer -- so it
# reads as the thing it closes rather than as an abstract shape.


def derive_probe(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> dict[str, Any]:
    """Register ``body`` as a released schema and derive its manifest."""
    probe_id = "urn:datacompany:authoring-fail-open-probe:1"
    probe = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": probe_id, **body}
    schemas = {**canonical_schemas_for_probe(), probe_id: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    return derive_hash_profile(probe_id)


#: A schema that derives cleanly, and the base every reproduction below mutates ONE member
#: of. A refusal is only attributable to the mutation if the unmutated shape is accepted,
#: which :func:`test_the_derivation_accepts_the_unmutated_probe` asserts separately.
CLEAN_PROBE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "signature": {
            "type": "string",
            "x-datacompany-hash-excluded": True,
            "x-datacompany-hash-exclusion-reason": "signature",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "x-datacompany-array": {"kind": "ordered"},
        },
    },
}


def test_the_derivation_accepts_the_unmutated_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """The false-positive control for every reproduction below.

    An engine that refused EVERY annotated node would satisfy all four of them, so the base
    they mutate is asserted to derive -- and to derive the exclusion and the array
    declaration it declares, not merely to return something.
    """
    profile = derive_probe(monkeypatch, CLEAN_PROBE)
    assert profile["excluded_pointers"] == [{"pointer": "/signature", "reason": "signature"}]
    assert profile["arrays"] == [{"pointer": "/tags", "kind": "ordered"}]


def test_7_1_a_misspelled_annotation_name_no_longer_derives_a_weaker_hash_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``x-datacompany-hash-exclude`` is one letter short, and was read by nothing (section 7.1).

    The symptom, exactly as recorded: it is a valid JSON Schema member, it is preserved on
    round trip, and the path stays in the hash view with no error raised anywhere. The
    reproduction asserts BOTH halves of the old behaviour are gone -- the refusal happens,
    and it names the misspelling rather than some downstream consequence of it.
    """
    mutant = json.loads(json.dumps(CLEAN_PROBE))
    del mutant["properties"]["signature"]["x-datacompany-hash-excluded"]
    mutant["properties"]["signature"]["x-datacompany-hash-exclude"] = True

    with pytest.raises(HashProfileError) as raised:
        derive_probe(monkeypatch, mutant)
    assert '"/signature" carries ["x-datacompany-hash-exclude"]' in str(raised.value)
    assert "is not a released x-datacompany-* annotation" in str(raised.value)


def test_7_2_a_lone_exclusion_reason_no_longer_derives_an_empty_exclusion_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting the flag and leaving the reason re-admitted a signature to the hash view.

    Section 7.2's symptom is not "an error of the wrong kind" -- it is that
    ``excluded_pointers`` derived EMPTY and the signature was hashed. The old outcome is
    asserted to be unreachable by reproducing the exact edit an author makes.
    """
    mutant = json.loads(json.dumps(CLEAN_PROBE))
    del mutant["properties"]["signature"]["x-datacompany-hash-excluded"]

    with pytest.raises(HashProfileError) as raised:
        derive_probe(monkeypatch, mutant)
    assert "x-datacompany-hash-exclusion-reason with no x-datacompany-hash-excluded" in str(
        raised.value
    )


@pytest.mark.parametrize(
    ("rendered", "value"),
    [('"set"', "set"), ('["set"]', ["set"]), ("true", True)],
    ids=["a string", "an array", "a boolean"],
)
def test_7_3_a_non_object_array_declaration_is_no_longer_dropped(
    monkeypatch: pytest.MonkeyPatch, rendered: str, value: Any
) -> None:
    """``"set"``, ``["set"]`` and ``true`` all derived ``arrays: []`` (section 7.3).

    The three values are the three the section names. The defect's sting is in the SECOND
    sentence of the record -- the declaration only resurfaces as ``UndeclaredArrayError`` if
    some instance happens to carry that array, so an OPTIONAL array loses its collection
    semantics indefinitely with no gate going red. Nothing but an authoring-time refusal
    closes that, which is why the reproduction never validates an instance.
    """
    mutant = json.loads(json.dumps(CLEAN_PROBE))
    mutant["properties"]["tags"]["x-datacompany-array"] = value

    with pytest.raises(HashProfileError) as raised:
        derive_probe(monkeypatch, mutant)
    assert 'x-datacompany-array at "/tags" is a JSON' in str(raised.value)
    assert "not an object" in str(raised.value)


def test_7_4_an_array_declaration_may_no_longer_retarget_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``{"pointer": ...}`` overrode the walker's derived location, with no error (7.4).

    The reproduction asserts the refusal AND, through the control above, that a declaration
    without ``pointer`` still reaches the manifest at the pointer the walk derived. The two
    together are what distinguishes closing the defect from deleting the feature.
    """
    mutant = json.loads(json.dumps(CLEAN_PROBE))
    mutant["properties"]["tags"]["x-datacompany-array"] = {
        "pointer": "/elsewhere",
        "kind": "ordered",
    }

    with pytest.raises(HashProfileError) as raised:
        derive_probe(monkeypatch, mutant)
    assert 'x-datacompany-array at "/tags" carries ["pointer"]' in str(raised.value)


def test_7_6_an_unknown_operator_refuses_before_any_failure_can_be_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 7.6, reproduced and decided.

    The recorded symptom: ``[{"rule": "equal", ...}, {"rule": "nope"}]`` validated against an
    instance that VIOLATES the first rule raised, and the already-collected ``equal`` failure
    was lost. Nothing failed open -- but a port that collected the unknown operator into the
    failure list instead of raising would report a different result, and that ambiguity was
    the defect.

    DECIDED: an unknown operator is an AUTHORING fault, not an instance fault, so it is
    refused when the rules are COLLECTED -- before any instance is examined. There is
    therefore no partial failure list to discard, in either engine and for any instance. The
    rejected alternative is the one section 7.6 names: collecting it as a failure beside the
    instance failures, which would let a consumer read an unenforceable rule as an enforced
    one that merely passed this time, and would make the reported result depend on whether
    the instance happened to violate the rules declared before it.

    Both halves are asserted, because the decision is only meaningful with both: the
    refusal does not depend on the instance, and a well-formed sibling rule IS still
    evaluated.
    """
    probe_id = "urn:datacompany:seven-six-probe:1"
    body = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "x-datacompany-cross-field": [
            {"rule": "equal", "name": "owner", "left": "/a", "right": "/b"},
            {"rule": "nope"},
        ],
    }
    probe = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": probe_id, **body}
    schemas = {**canonical_schemas_for_probe(), probe_id: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        # The instance that VIOLATES the first rule -- the one whose failure used to be lost.
        with pytest.raises(CrossFieldError) as violating:
            structural_module.check_cross_field_rules({"a": 1, "b": 2}, probe_id)
        # And an instance that satisfies it, so the refusal is proven not to be a report
        # about this instance at all.
        structural_module._collect.cache_clear()
        with pytest.raises(CrossFieldError) as holding:
            structural_module.check_cross_field_rules({"a": 1, "b": 1}, probe_id)
        assert str(violating.value) == str(holding.value)
        assert 'declares rule "nope"' in str(violating.value)
        assert "owner" not in str(violating.value), (
            "the refusal names the unenforceable rule, not a failure of the enforceable one; "
            "reporting both would be the alternative section 7.6 rejects"
        )
    finally:
        structural_module._collect.cache_clear()


def test_7_6_the_control_two_well_formed_rules_both_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this, an engine that refused every multi-rule declaration would pass above."""
    probe_id = "urn:datacompany:seven-six-control:1"
    probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": probe_id,
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "x-datacompany-cross-field": [
            {"rule": "equal", "name": "owner", "left": "/a", "right": "/b"},
            {"rule": "equal", "name": "tenant", "left": "/a", "right": "/b"},
        ],
    }
    schemas = {**canonical_schemas_for_probe(), probe_id: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        failures = structural_module.check_cross_field_rules({"a": 1, "b": 2}, probe_id)
        assert len(failures) == 2, failures
    finally:
        structural_module._collect.cache_clear()


# ------------------------------------------- the two-engine refusal record ---
#
# EXTENSIONS.md section 9 item 12: "two engines that refuse the same schema with different
# words are a divergence a consumer reading either one cannot reconcile", and it names the
# concrete trap -- `repr` writes `['/a']` where `JSON.stringify` writes `["/a"]`. Decision F
# was MEASURED falling into that trap in seven places: Python rendered `'nope'`, `str`,
# `NoneType` and `list` where the port rendered `"nope"`, `string`, `null` and `object`, for
# the same malformed rule. Both engines now route every rendered value through
# `canonical.rendering` / `src/rendering.ts`, and the file replayed below is what keeps them
# together: the expected `message` was read OUT of the Python engine, and
# `packages/typescript/test/authoringRefusals.test.ts` replays the same file.

REFUSALS = load(ROOT / "fixtures" / "canonical-annotations" / "v1" / "refusals.json")

#: An EQUALITY and a partition. The partition is what stops the file drifting into
#: refusals-only, which an engine that rejected everything would satisfy.
#:
#: These were FLOORS (``>=`` 23 and 4) until 2026-08-04, and the section 6.4 closure is what
#: exposed the cost: adding four refusal cases and repairing one control took the file to 28
#: and 5, and a floor accepts every deletion back down to the pin -- so all four new cases
#: plus one control could have been deleted with both suites still green. That is the same
#: shape as ``CITATION_FLOORS``' own note ("EXACT counts, not floors with slack ... five was
#: enough to absorb a real narrowing"), and this file is the record two engines are compared
#: against, so slack here is slack in the cross-language parity itself. Equalities now: an
#: added case is as reviewable an edit as a deleted one.
EXPECTED_REFUSAL_CASES = 28
EXPECTED_ACCEPTED_CONTROLS = 5


def test_the_refusal_record_measures_something() -> None:
    cases = REFUSALS["cases"]
    refused = [case for case in cases if "message" in case["expect"]]
    accepted = [case for case in cases if case["expect"].get("accepted")]
    assert len(refused) == EXPECTED_REFUSAL_CASES, len(refused)
    assert len(accepted) == EXPECTED_ACCEPTED_CONTROLS, len(accepted)
    assert len(refused) + len(accepted) == len(cases), "a case is neither refused nor accepted"
    # Every section this file claims to cover is actually represented, so deleting the last
    # case of one is red rather than merely smaller.
    assert {case["section"] for case in cases} == {
        "7.1",
        "7.2",
        "7.3",
        "7.4",
        "7.5",
        "7.6",
        # Not numbered defects: three rows of the section 8 table the engine did not
        # consult, closed 2026-08-04, and the D9 guard's own non-ASCII rendering parity.
        # `8.row7` is the composition-point row -- the last row where the meta-schema
        # constrained something the engine did not constrain at all (§6.4).
        "8.row2",
        "8.row7",
        "8.row8",
        "D9",
        "control",
    }


@pytest.mark.parametrize(
    "case", REFUSALS["cases"], ids=[case["name"] for case in REFUSALS["cases"]]
)
def test_the_engine_reproduces_the_recorded_refusal(
    monkeypatch: pytest.MonkeyPatch, case: dict[str, Any]
) -> None:
    """Byte for byte, including the message, because the port is compared against this file."""
    probe = case["probe_schema"]
    schemas = {**canonical_schemas_for_probe(), probe["$id"]: probe}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    expect = case["expect"]

    def run() -> Any:
        if case["entry_point"] == "derive_hash_profile":
            return derive_hash_profile(probe["$id"])
        return structural_module.collect_cross_field_rules(probe["$id"])

    try:
        if expect.get("accepted"):
            result = run()
            if "collected_rules" in expect:
                assert len(result) == expect["collected_rules"], result
            return
        with pytest.raises(CanonicalError) as raised:
            run()
        # The CLASS by name rather than by `pytest.raises(HashProfileError)`: the port has no
        # Python exception hierarchy to match against, so the fixture records the name and
        # both engines compare the same string.
        assert type(raised.value).__name__ == expect["error"]
        assert str(raised.value) == expect["message"]
    finally:
        structural_module._collect.cache_clear()


# ================================ section 8's table cannot outrun the engine ===
#
# Section 8 is a TABLE OF MEASUREMENTS: "does the engine refuse what this file rejects?".
# Prose like that rots silently, and it had. Two rows were wrong at once when this was
# written: the count sentence still said "seven things ... four of them the engine still
# accepts" after D9 added an eighth row, and row 8 claimed "the engine catches the
# hash-opaque pair (as a misplaced flag)" when a node carrying BOTH annotations, itself
# sitting under another opaque pointer, derived cleanly.
#
# So the probes the table claims were run are COMMITTED here, and the table is asserted to
# say what they measure. That is the property that matters and it holds in both directions:
# a row that becomes true without the sentence being updated is red, and a sentence that
# claims more than the engine does is red. Neither can drift alone.
#
# Row 8's hash-opaque half is deliberately the interesting one. It is ACCEPTED by this
# engine today and a sibling change closes it; when that lands, this test goes red until
# section 8's row is corrected, which is exactly the coupling the old prose lacked.

SECTION_8_TABLE_ROW = (
    "| `hash-declaration-only` may not sit beside `hash-excluded` or `hash-opaque` |"
)

#: The two halves of the meta-schema's ``declaration_only_pairing``, as probes. Both put the
#: flagged node STRICTLY inside an opaque subtree, so neither can be refused by the placement
#: guard instead -- which is what makes each a measurement of the pairing rule alone.
ROW_8_PROBES: dict[str, dict[str, Any]] = {
    "hash-excluded": {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "x-datacompany-hash-opaque": True,
                "properties": {
                    "tags": {
                        "type": "array",
                        "x-datacompany-hash-declaration-only": True,
                        "x-datacompany-hash-excluded": True,
                        "x-datacompany-hash-exclusion-reason": "signature",
                        "x-datacompany-array": {"kind": "ordered"},
                    }
                },
            }
        },
    },
    "hash-opaque": {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "x-datacompany-hash-opaque": True,
                "properties": {
                    "inner": {
                        "type": "object",
                        "x-datacompany-hash-opaque": True,
                        "x-datacompany-hash-declaration-only": True,
                        "properties": {
                            "tags": {"type": "array", "x-datacompany-array": {"kind": "ordered"}}
                        },
                    }
                },
            }
        },
    },
}


def _row_8_refusals(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """Measure, per half, whether the engine refuses the pair. True means refused."""
    measured: dict[str, bool] = {}
    for half, body in ROW_8_PROBES.items():
        try:
            derive_probe(monkeypatch, body)
            measured[half] = False
        except HashProfileError:
            measured[half] = True
    return measured


def test_the_row_8_probes_are_not_refused_for_some_other_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The control, and it is the whole validity of the measurement below.

    Each probe differs from a schema that derives cleanly by exactly the paired annotation.
    If the surrounding shape were refused on its own, "refused" would measure nothing about
    the pairing rule, and the table would be pinned against an artefact.
    """
    for half, body in ROW_8_PROBES.items():
        control = json.loads(json.dumps(body))
        node = control["properties"]["payload"]["properties"]
        target = next(iter(node.values()))
        if half == "hash-excluded":
            del target["x-datacompany-hash-excluded"]
            del target["x-datacompany-hash-exclusion-reason"]
        else:
            del target["x-datacompany-hash-opaque"]
        profile = derive_probe(monkeypatch, control)
        assert profile["arrays"], f"{half}: the control derives no array declaration"


def test_section_8_row_8_says_what_the_engine_actually_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The table row and the engine are asserted against each other, not against a literal.

    Both wordings are recognised, so this test does not have to be edited when the behaviour
    changes -- only the TABLE does, which is the point. A row claiming a refusal the engine
    does not make is red; a row claiming an acceptance the engine no longer makes is red.
    """
    measured = _row_8_refusals(monkeypatch)
    row = next(
        line
        for line in EXTENSIONS_DOC.read_text(encoding="utf-8").splitlines()
        if line.startswith(SECTION_8_TABLE_ROW)
    )
    for half, refused in measured.items():
        claimed_refused = f"**Yes** for the `{half}` pair" in row
        claimed_accepted = f"**No** for the `{half}` pair" in row
        assert claimed_refused != claimed_accepted, (
            f"section 8 row 8 states neither Yes nor No for the {half} pair: {row}"
        )
        assert claimed_refused == refused, (
            f"section 8 row 8 claims the {half} pair is "
            f"{'refused' if claimed_refused else 'accepted'}, but the engine "
            f"{'refuses' if refused else 'accepts'} it: {row}"
        )


def test_section_8_counts_the_rows_its_table_actually_has() -> None:
    """The other half of the same rot: "it rejects seven things" after D9 added an eighth.

    DERIVED, not pinned. An earlier version of this test was two independent literal
    assertions -- "the table has 8 rows" and "the prose says eight" -- which is not a
    consistency check at all: deleting a row AND correcting the prose to "seven", which is
    the *correct* edit, was still red, while a gutted row (``| |``) counted as a row and
    passed. Both numbers now come out of the document and are compared to each other, and a
    row only counts if it actually states a rule and a verdict.
    """
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    text = EXTENSIONS_DOC.read_text(encoding="utf-8")

    claimed_word = re.search(r"It rejects \*\*(\w+)\*\* things at authoring time", text)
    assert claimed_word is not None, "section 8 no longer states how many rules it rejects"
    claimed = words[claimed_word.group(1)]

    table = text.split("| Meta-schema rule | Does the ENGINE refuse it? |", 1)[1]
    # CONTIGUOUS rows only. A blanket filter over the rest of the file counts section 10's
    # table too, which would make this measure the document rather than the table.
    rows: list[str] = []
    for line in table.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        if line.startswith("|---"):
            continue
        rows.append(line)
    # A row is a row only if BOTH cells say something. `| |` and a bare `|` used to count,
    # so a table could be gutted row by row and still satisfy the old equality.
    stated = [row for row in rows if len([cell for cell in row.split("|") if cell.strip()]) == 2]

    assert stated == rows, [row[:70] for row in rows if row not in stated]
    assert len(stated) == claimed, (
        f"section 8 says it rejects {claimed} things and its table has {len(stated)} rows"
    )


# ------------------------------- the renderer both engines' message text goes through ---
#
# `canonical.rendering.json_text` and `src/rendering.ts`'s `jsonText` must produce the SAME
# bytes, and the table below is the same table in both languages. Four spellings of one trap
# have now been found here, each invisible to the tests that existed when it landed:
# `repr` versus `JSON.stringify`, Python type names versus `typeof`, `ensure_ascii=True`
# escaping what `JSON.stringify` leaves alone -- and, introduced by the fix for the third, a
# lone surrogate left RAW where ES2019's well-formed `JSON.stringify` escapes it. That last
# one also made the rendering unencodable, so a legitimate refusal could not be printed.

RENDERINGS: list[tuple[str, Any, str]] = [
    ("a plain pointer list", ["/a"], '["/a"]'),
    ("an empty pointer", [""], '[""]'),
    ("a quote and a backslash", ['/q"b\\s'], '["/q\\"b\\\\s"]'),
    ("a tab", ["/t\there"], '["/t\\there"]'),
    ("a DEL, which is not escaped by either engine", ["/d\x7f"], '["/d\x7f"]'),
    ("a NUL, which both escape", ["/n\x00"], '["/n\\u0000"]'),
    ("an accented letter, left alone by both", ["/café"], '["/café"]'),
    ("an astral emoji, left alone by both", ["/e\U0001f600"], '["/e\U0001f600"]'),
    ("an unpaired HIGH surrogate", ["/caf\ud800"], '["/caf\\ud800"]'),
    ("an unpaired LOW surrogate", ["/a\udfff"], '["/a\\udfff"]'),
    ("two unpaired highs in a row", ["/\ud800\ud801"], '["/\\ud800\\ud801"]'),
    # The one input on which the two engines DID disagree, and the reason `json_text`
    # implements ES2019's second well-formedness rule rather than escaping every surrogate:
    # an adjacent high+low pair is one astral character to JavaScript, so it must be one here.
    (
        "an adjacent high+low PAIR, which is one astral character",
        ["/\ud83d\ude00"],
        '["/\U0001f600"]',
    ),
    ("a string, not a list", "nope", '"nope"'),
    ("null", None, "null"),
]


@pytest.mark.parametrize(
    ("description", "value", "expected"), RENDERINGS, ids=[case[0] for case in RENDERINGS]
)
def test_the_renderer_matches_json_stringify(description: str, value: Any, expected: str) -> None:
    """The same table is asserted against ``jsonText`` in the port, with the same literals."""
    assert json_text(value) == expected, description


def test_every_rendering_can_actually_be_written_out() -> None:
    """A message that cannot be encoded is not a diagnostic, it is a second failure.

    ``ensure_ascii=False`` alone left an unpaired surrogate raw, and ``str.encode("utf-8")``
    refuses those -- so printing or logging a legitimate refusal raised ``UnicodeEncodeError``
    far from the schema that caused it. Asserted over the table rather than over one case,
    because the property is about the renderer and not about one input.
    """
    for _description, value, _ in RENDERINGS:
        json_text(value).encode("utf-8")  # must not raise
    # Non-vacuity: the table must actually contain an input that used to fail this.
    assert any(
        any("\ud800" <= character <= "\udfff" for character in item)
        for _, value in ((d, v) for d, v, _ in RENDERINGS)
        for item in (value if isinstance(value, list) else [])
        if isinstance(item, str)
    ), "no unpaired-surrogate input in the table; this test proves nothing"

"""Regression tests for the contract lint gate and the pre-ADR regulatory denylist.

Baseline defects covered here:

* D6  the denylist scanned only ``schemas/**/*.schema.json``; a planted
  ``schemas/events/regulatory-effect.json`` escaped on the file suffix alone.
* D7  deleting nine of ten ``forbidden_canonical_tokens`` left every gate green.
* D8  only ``$id``/``title``/``const``, ``enum`` items and ``properties`` keys were
  inspected; ``$defs`` keys, ``required`` entries, ``patternProperties`` keys and
  ``description`` prose were all verified bypasses.
* D9  guarded activation discriminators were compared as raw strings while
  everything else normalized, so ``workType`` and ``WORK_TYPE`` walked past the
  closed-const/enum requirement.
* D10 a ``$ref`` to a closed local enum was rejected — a gate that punishes
  correct authoring teaches workarounds.
* D11 substring matching flagged ``illegal_event_count`` and ``paralegal_status``.
* D13 ``except (ContractError, Exception)`` swallowed any bug in the gate and
  relabelled it "invalid JSON Schema 2020-12".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import ROOT, run_script

SCRIPT = "lint_contracts.py"
DENYLIST_FILE = ROOT / "config/pre-adr-regulatory-denylist.json"


def schema(schema_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        **extra,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_repo(root: Path, *, name: str = "ok.schema.json", document: Any | None = None) -> Path:
    write_json(root / "schemas" / name, document if document is not None else schema("urn:test:ok"))
    return root


def lint(root: Path, denylist: Path = DENYLIST_FILE):
    return run_script(SCRIPT, "--repo-root", root, "--denylist", denylist)


# --------------------------------------------------------------------------
# The repository itself must lint clean
# --------------------------------------------------------------------------


def test_repository_lints_clean() -> None:
    result = run_script(SCRIPT)
    assert result.returncode == 0, result.stderr


def test_baseline_schema_only_repository_is_accepted(tmp_path: Path) -> None:
    result = lint(make_repo(tmp_path))
    assert result.returncode == 0, result.stderr


def test_duplicate_id_fails(tmp_path: Path) -> None:
    write_json(tmp_path / "schemas/one.schema.json", schema("urn:test:duplicate"))
    write_json(tmp_path / "schemas/two.schema.json", schema("urn:test:duplicate"))
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "duplicate $id" in result.stderr


def test_empty_scan_is_not_a_clean_scan(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir()
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "no *.schema.json files found" in result.stderr


# --------------------------------------------------------------------------
# D6 — scan every JSON/YAML document, not just *.schema.json
# --------------------------------------------------------------------------


def test_plain_json_document_outside_the_schema_suffix_is_scanned(tmp_path: Path) -> None:
    """The exact planted artifact: schemas/events/regulatory-effect.json."""
    make_repo(tmp_path)
    write_json(
        tmp_path / "schemas/events/regulatory-effect.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:test:effect",
            "title": "RegulatoryEffect",
        },
    )
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "regulatory-effect.json" in result.stderr


def test_forbidden_token_in_a_file_name_alone_is_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_json(tmp_path / "event-catalog/legal-event.json", {"kind": "harmless"})
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "in path" in result.stderr


def test_yaml_documents_are_scanned(tmp_path: Path) -> None:
    make_repo(tmp_path)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/pipeline.yaml").write_text(
        "steps:\n  - emits: consolidation_snapshot\n", encoding="utf-8"
    )
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "consolidation_snapshot" in result.stderr


def test_yml_documents_are_scanned(tmp_path: Path) -> None:
    make_repo(tmp_path)
    (tmp_path / "labels.yml").write_text("normative_citation: enabled\n", encoding="utf-8")
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "normative_citation" in result.stderr


def test_unparseable_document_is_reported_not_skipped(tmp_path: Path) -> None:
    make_repo(tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "unparseable JSON/YAML document" in result.stderr


# --------------------------------------------------------------------------
# D7 — denylist erosion must be detected
# --------------------------------------------------------------------------


def test_pinned_denylist_tokens_are_all_present() -> None:
    from research_contracts.tooling.denylist import REQUIRED_FORBIDDEN_TOKENS, load_denylist

    denylist = load_denylist(DENYLIST_FILE)
    assert set(denylist.forbidden_tokens) >= REQUIRED_FORBIDDEN_TOKENS
    assert len(REQUIRED_FORBIDDEN_TOKENS) == 10
    assert denylist.forbidden_tokens
    assert "work_type" in denylist.guarded_discriminators


def test_eroded_denylist_fails_the_gate(tmp_path: Path) -> None:
    eroded = tmp_path / "eroded-denylist.json"
    document = json.loads(DENYLIST_FILE.read_text(encoding="utf-8"))
    document["forbidden_canonical_tokens"] = document["forbidden_canonical_tokens"][:1]
    eroded.write_text(json.dumps(document), encoding="utf-8")

    result = lint(make_repo(tmp_path / "repo"), denylist=eroded)
    assert result.returncode == 1
    assert "has been eroded" in result.stderr


def test_emptied_denylist_fails_the_gate(tmp_path: Path) -> None:
    emptied = tmp_path / "empty-denylist.json"
    document = json.loads(DENYLIST_FILE.read_text(encoding="utf-8"))
    document["forbidden_canonical_tokens"] = []
    emptied.write_text(json.dumps(document), encoding="utf-8")

    result = lint(make_repo(tmp_path / "repo"), denylist=emptied)
    assert result.returncode == 1
    assert "must be a non-empty array" in result.stderr


def test_missing_denylist_fails_the_gate(tmp_path: Path) -> None:
    result = lint(make_repo(tmp_path / "repo"), denylist=tmp_path / "absent.json")
    assert result.returncode == 1
    assert "is missing" in result.stderr


# --------------------------------------------------------------------------
# D8 — every key position and every string is inspected
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "extra"),
    [
        ("$defs key", {"$defs": {"legal_event": {"type": "string"}}}),
        ("required entry", {"required": ["regulatory_instrument"]}),
        ("patternProperties key", {"patternProperties": {"regulatory_provision": {}}}),
        ("description", {"description": "tracks consolidation_snapshot rows"}),
        ("nested description", {"properties": {"x": {"description": "a normative_citation"}}}),
        ("title", {"title": "RegulatoryChange"}),
        ("const", {"properties": {"kind": {"const": "regulatory_applicability"}}}),
        ("enum item", {"properties": {"kind": {"enum": ["Regulatory-Instrument"]}}}),
        ("property key", {"properties": {"regulatory_effect": {"type": "string"}}}),
        ("array item value", {"examples": ["recommendation_regulatory_link"]}),
    ],
)
def test_forbidden_tokens_are_caught_in_every_position(
    tmp_path: Path, label: str, extra: dict[str, Any]
) -> None:
    make_repo(tmp_path, name="bad.schema.json", document=schema("urn:test:bad", **extra))
    result = lint(tmp_path)
    assert result.returncode == 1, f"{label} bypassed the denylist: {result.stdout}"
    assert "forbidden pre-ADR token" in result.stderr


# --------------------------------------------------------------------------
# D9 — guarded activation discriminators normalize like everything else
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["work_type", "workType", "WORK_TYPE", "Work-Type", "worktype"])
def test_open_activation_discriminator_is_rejected_in_every_spelling(
    tmp_path: Path, key: str
) -> None:
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema("urn:test:bad", properties={key: {"type": "string"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 1, f"{key} bypassed the discriminator guard: {result.stdout}"
    assert "activation discriminator must use closed const/enum" in result.stderr


def test_closed_activation_discriminator_is_allowed(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        name="ok.schema.json",
        document=schema(
            "urn:test:ok", properties={"work_type": {"enum": ["screening", "reporting"]}}
        ),
    )
    result = lint(tmp_path)
    assert result.returncode == 0, result.stderr


def test_forbidden_activation_value_is_rejected(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema("urn:test:bad", properties={"work_type": {"enum": ["regulatory_change"]}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "forbidden" in result.stderr


# --------------------------------------------------------------------------
# D10 — local $ref must resolve
# --------------------------------------------------------------------------


def test_ref_to_a_closed_local_enum_is_accepted(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        name="ok.schema.json",
        document=schema(
            "urn:test:ok",
            **{
                "$defs": {"WorkType": {"enum": ["screening", "reporting"]}},
                "properties": {"work_type": {"$ref": "#/$defs/WorkType"}},
            },
        ),
    )
    result = lint(tmp_path)
    assert result.returncode == 0, result.stderr


def test_ref_to_an_open_local_definition_is_still_rejected(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema(
            "urn:test:bad",
            **{
                "$defs": {"WorkType": {"type": "string"}},
                "properties": {"work_type": {"$ref": "#/$defs/WorkType"}},
            },
        ),
    )
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "activation discriminator must use closed const/enum" in result.stderr


def test_remote_ref_fails_closed(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema(
            "urn:test:bad",
            properties={"work_type": {"$ref": "https://example.invalid/work-type.json"}},
        ),
    )
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "activation discriminator must use closed const/enum" in result.stderr


# --------------------------------------------------------------------------
# D11 — word-boundary matching
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["illegal_event_count", "paralegal_status", "paralegalStatus", "illegalEventCount"],
)
def test_words_that_merely_contain_a_forbidden_token_are_allowed(tmp_path: Path, name: str) -> None:
    make_repo(
        tmp_path,
        name="ok.schema.json",
        document=schema("urn:test:ok", properties={name: {"type": "integer"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 0, f"{name} was a false positive: {result.stderr}"


@pytest.mark.parametrize(
    "name",
    [
        "legal_event",
        "legal_event_id",
        "legalEvent",
        "Legal-Event",
        "legalevent",
        "x_legal_event",
        "regulatory_instruments",
        "RegulatoryInstrument",
    ],
)
def test_real_activations_are_still_rejected(tmp_path: Path, name: str) -> None:
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema("urn:test:bad", properties={name: {"type": "string"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 1, f"{name} bypassed the denylist: {result.stdout}"
    assert "forbidden pre-ADR token" in result.stderr


def test_ordinary_document_contract_is_allowed(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        name="document.schema.json",
        document=schema(
            "urn:test:document",
            properties={"entity_type": {"enum": ["research_asset", "document_version"]}},
        ),
    )
    result = lint(tmp_path)
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# D13 — a bug in the gate must not be relabelled a contract violation
# --------------------------------------------------------------------------


def test_invalid_json_and_invalid_schema_are_reported_distinctly(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir(parents=True)
    (tmp_path / "schemas/broken.schema.json").write_text("{ not json", encoding="utf-8")
    write_json(tmp_path / "schemas/bad.schema.json", {"type": 17})
    result = lint(tmp_path)
    assert result.returncode == 1
    assert "unreadable or malformed JSON" in result.stderr
    assert "invalid JSON Schema 2020-12" in result.stderr


def test_unexpected_errors_are_not_relabelled_as_invalid_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bug in the gate must surface, not be reported as a schema defect."""
    from research_contracts.tooling import contract_tools
    from research_contracts.tooling.denylist import load_denylist

    write_json(tmp_path / "schemas/ok.schema.json", schema("urn:test:ok"))

    def explode(_path: Path) -> Any:
        raise RuntimeError("gate bug")

    monkeypatch.setattr(contract_tools, "load_json", explode)
    with pytest.raises(RuntimeError, match="gate bug"):
        contract_tools.lint_schema_files(tmp_path / "schemas", load_denylist(DENYLIST_FILE))


# --------------------------------------------------------------------------
# V2 — the guarded-discriminator check must run repo-wide, not only on
#      schemas/**/*.schema.json
# --------------------------------------------------------------------------


def test_open_discriminator_in_a_plain_json_document_is_rejected(tmp_path: Path) -> None:
    """The same schema content as ``.json`` used to exit 0.

    ``lint_repository`` ran the token scan repo-wide but the discriminator check
    only under ``schemas/``, so dropping ``.schema`` from the filename removed
    exactly one of the two halves.
    """
    make_repo(tmp_path)
    write_json(
        tmp_path / "openapi/plant.json",
        schema("urn:test:plant", properties={"work_type": {"type": "string"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "activation discriminator must use closed const/enum" in result.stderr
    assert "openapi/plant.json" in result.stderr


def test_open_discriminator_in_an_openapi_yaml_is_rejected(tmp_path: Path) -> None:
    """``openapi/`` is ``.yaml`` by definition, so this hole opens on day one."""
    make_repo(tmp_path)
    (tmp_path / "openapi").mkdir(parents=True, exist_ok=True)
    (tmp_path / "openapi/api.yaml").write_text(
        "openapi: 3.1.0\n"
        "components:\n"
        "  schemas:\n"
        "    Work:\n"
        "      type: object\n"
        "      properties:\n"
        "        work_type:\n"
        "          type: string\n",
        encoding="utf-8",
    )
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "activation discriminator must use closed const/enum" in result.stderr


def test_a_closed_discriminator_outside_schemas_is_still_accepted(tmp_path: Path) -> None:
    """Falsifiable control: the repo-wide check must not punish correct authoring."""
    make_repo(tmp_path)
    write_json(
        tmp_path / "openapi/plant.json",
        schema("urn:test:plant", properties={"work_type": {"enum": ["screening"]}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# V3 — a *.schema.json outside schemas/ gets the full schema treatment
# --------------------------------------------------------------------------


def test_schema_outside_the_schemas_tree_must_declare_2020_12(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_json(
        tmp_path / "openapi/plant.schema.json",
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$id": "urn:test:plant",
            "type": "object",
        },
    )
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "$schema must declare JSON Schema 2020-12" in result.stderr


def test_schema_outside_the_schemas_tree_cannot_duplicate_a_real_id(tmp_path: Path) -> None:
    """The sharpest form: shadow the conformance-record ``$id`` from ``openapi/``."""
    real_id = "urn:nonagentic:contracts:model-conformance-record:v1"
    write_json(tmp_path / "schemas/canonical/record.schema.json", schema(real_id))
    write_json(tmp_path / "openapi/plant.schema.json", schema(real_id))
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "duplicate $id" in result.stderr


def test_schema_outside_the_schemas_tree_must_have_an_id(tmp_path: Path) -> None:
    make_repo(tmp_path)
    write_json(
        tmp_path / "openapi/plant.schema.json",
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
    )
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "non-empty $id is required" in result.stderr


# --------------------------------------------------------------------------
# V8 — non-ASCII homoglyphs must not delete a character from the squashed form
# --------------------------------------------------------------------------


#: Spellings that render identically to the pinned tokens for a human reviewer.
#: Written as escapes so the intent is legible and the test file does not itself
#: carry ambiguous characters.
HOMOGLYPH_ACTIVATIONS = [
    ("cyrillic a", "regul\u0430tory_effect"),
    ("cyrillic e", "l\u0435gal_event"),
    ("cyrillic o", "cons\u043elidation_snapshot"),
    ("greek omicron", "regulat\u03bfry_change"),
    ("fullwidth L", "\uff2cegal_status"),
    ("mathematical bold l", "\U0001d425egal_event"),
    ("accented latin a", "regul\u00e1tory_provision"),
    ("dotless i", "normat\u0131ve_citation"),
]


@pytest.mark.parametrize(("label", "name"), HOMOGLYPH_ACTIVATIONS)
def test_homoglyph_spellings_are_still_forbidden(tmp_path: Path, label: str, name: str) -> None:
    """Renders identically to a reviewer; used to exit 0.

    ``squash_with_word_starts`` kept only ``isascii() and isalnum()`` characters
    and treated everything else as a *separator*, so a CYRILLIC SMALL LETTER A
    deleted a character from the squashed form rather than contributing one.
    """
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema("urn:test:bad", properties={name: {"type": "string"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 1, f"{label} bypassed the denylist: {result.stdout}"
    assert "forbidden pre-ADR token" in result.stderr


#: The same substitution class, aimed at the guarded ACTIVATION DISCRIMINATOR instead of
#: at a forbidden token. ``HOMOGLYPH_ACTIVATIONS`` above only ever exercised the token
#: half, and the two halves did not agree: ``forbidden_match`` folded confusables while
#: ``_discriminator_errors`` called the raw ``normalize_token``, which DELETES non-ASCII
#: characters instead of folding them. All four ASCII spellings of ``work_type`` raised,
#: all three of these raised NOTHING, and the difference is invisible to a reviewer.
#:
#: Written as escapes, like ``HOMOGLYPH_ACTIVATIONS``: the intent stays legible and the
#: test file does not itself carry the ambiguous characters it is about.
HOMOGLYPH_DISCRIMINATORS = [
    ("fullwidth w", "\uff57ork_type"),
    ("cyrillic o", "w\u043erk_type"),
    ("cyrillic we", "\u051dork_type"),
]

#: Control spellings for the same test: plain ASCII, already caught before the fix. They
#: are re-asserted here so the parametrisation proves the discriminator path itself works,
#: not merely that something in the lint fires.
ASCII_DISCRIMINATORS = [
    ("snake case", "work_type"),
    ("camel case", "workType"),
    ("screaming snake", "WORK_TYPE"),
    ("kebab case", "work-type"),
]


@pytest.mark.parametrize(("label", "name"), [*ASCII_DISCRIMINATORS, *HOMOGLYPH_DISCRIMINATORS])
def test_a_homoglyph_spelled_discriminator_must_still_be_closed(
    tmp_path: Path, label: str, name: str
) -> None:
    """An open ``work_type`` must be red however it is spelled.

    Reproduced against the shipped denylist before the fix: ``work_type``, ``workType``,
    ``WORK_TYPE`` and ``work-type`` all raised "activation discriminator must use closed
    const/enum"; the three homoglyph spellings raised nothing at all. The gate that folds
    confusables and the gate that decides whether a discriminator is guarded were two
    different normalizers, and only one of them folded.
    """
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema("urn:test:bad", properties={name: {"type": "string"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 1, f"{label} bypassed the discriminator gate: {result.stdout}"
    assert "activation discriminator must use closed const/enum" in result.stderr


@pytest.mark.parametrize(("label", "name"), HOMOGLYPH_DISCRIMINATORS)
def test_a_homoglyph_spelled_discriminator_with_a_closed_enum_is_accepted(
    tmp_path: Path, label: str, name: str
) -> None:
    """False-positive control: folding decides WHICH names are guarded, not that they fail.

    Without this, a fix that simply errored on every non-ASCII property name would pass the
    test above while rejecting correct authoring — the shape this repository's own docstring
    calls "a gate that punishes correct authoring teaches workarounds".
    """
    make_repo(
        tmp_path,
        name="ok.schema.json",
        document=schema("urn:test:ok", properties={name: {"enum": ["article", "dataset"]}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 0, f"{label} became a false positive: {result.stderr}"


@pytest.mark.parametrize(
    "name", ["publication_type", "network_type", "workflow_type_id", "doc_type"]
)
def test_an_unrelated_property_name_is_not_a_guarded_discriminator(
    tmp_path: Path, name: str
) -> None:
    """The other false-positive control: an open string on a name that is not guarded."""
    make_repo(
        tmp_path,
        name="ok.schema.json",
        document=schema("urn:test:ok", properties={name: {"type": "string"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 0, f"{name} became a false positive: {result.stderr}"


def test_zero_width_separators_are_still_caught(tmp_path: Path) -> None:
    """Regression guard: zero-width handling was already correct, do not break it."""
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema("urn:test:bad", properties={"legal\u200b_event": {"type": "string"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "forbidden pre-ADR token" in result.stderr


@pytest.mark.parametrize("name", ["illegal_event_count", "paralegal_status", "paralegalStatus"])
def test_confusable_folding_does_not_create_false_positives(tmp_path: Path, name: str) -> None:
    make_repo(
        tmp_path,
        name="ok.schema.json",
        document=schema("urn:test:ok", properties={name: {"type": "integer"}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 0, f"{name} became a false positive: {result.stderr}"


# --------------------------------------------------------------------------
# V9 — the scanned-suffix list was a case-sensitive whitelist
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("catalog.JSON", '{"kind": "legal_event"}'),
        ("catalog.Json", '{"kind": "legal_event"}'),
        ("catalog.YAML", "kind: legal_event\n"),
        ("catalog.YML", "kind: legal_event\n"),
        ("catalog.json5", '{"kind": "legal_event"}'),
        ("catalog.jsonc", '{"kind": "legal_event"}'),
        ("catalog", '{"kind": "legal_event"}'),
    ],
)
def test_documents_the_suffix_whitelist_missed_are_scanned(
    tmp_path: Path, filename: str, body: str
) -> None:
    """On case-insensitive macOS ``.JSON`` is the same file to every consumer."""
    make_repo(tmp_path)
    (tmp_path / "event-catalog").mkdir(parents=True, exist_ok=True)
    (tmp_path / "event-catalog" / filename).write_text(body, encoding="utf-8")
    result = lint(tmp_path)
    assert result.returncode == 1, f"{filename} bypassed the scan: {result.stdout}"
    assert "legal_event" in result.stderr


def test_a_forbidden_token_in_any_file_name_is_rejected(tmp_path: Path) -> None:
    """The name check covers every file, not only parsed documents."""
    make_repo(tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/legal-event.md").write_text("harmless prose\n", encoding="utf-8")
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "in path" in result.stderr


def test_ordinary_prose_without_an_extension_is_not_a_document(tmp_path: Path) -> None:
    """Falsifiable control: sniffing must not turn every text file into a document."""
    make_repo(tmp_path)
    (tmp_path / "NOTES").write_text("Just prose about work types and events.\n", encoding="utf-8")
    result = lint(tmp_path)
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# V10 — the $schema skip must be root-scoped
# --------------------------------------------------------------------------


def test_a_nested_schema_value_is_not_skipped(tmp_path: Path) -> None:
    """``{"$defs": {"x": {"$schema": "regulatory_effect"}}}`` used to exit 0."""
    make_repo(
        tmp_path,
        name="bad.schema.json",
        document=schema("urn:test:bad", **{"$defs": {"x": {"$schema": "regulatory_effect"}}}),
    )
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "forbidden pre-ADR token" in result.stderr


def test_the_root_meta_schema_uri_is_still_skipped(tmp_path: Path) -> None:
    """Control: the document-root ``$schema`` is a meta-schema URI, not content."""
    result = lint(make_repo(tmp_path))
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# V11 — a duplicate key in a scanned YAML document destroys information
# --------------------------------------------------------------------------


def test_a_duplicate_yaml_key_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    """PyYAML is last-wins, so the first value never reaches the denylist."""
    make_repo(tmp_path)
    (tmp_path / "catalog.yaml").write_text(
        "kind: legal_event\nkind: research_asset\n", encoding="utf-8"
    )
    result = lint(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "duplicate key" in result.stderr


# --------------------------------------------------------------------------
# V12 — unreadable inputs are diagnosed, not tracebacked
# --------------------------------------------------------------------------


def test_an_unreadable_document_is_diagnosed_not_tracebacked(tmp_path: Path) -> None:
    make_repo(tmp_path)
    unreadable = tmp_path / "locked.json"
    unreadable.write_text('{"kind": "ok"}', encoding="utf-8")
    unreadable.chmod(0o000)
    try:
        result = lint(tmp_path)
    finally:
        unreadable.chmod(0o644)
    assert result.returncode == 1, result.stdout
    assert "Traceback" not in result.stderr, result.stderr
    assert "unparseable JSON/YAML document" in result.stderr


def test_an_unreadable_directory_is_diagnosed_not_tracebacked(tmp_path: Path) -> None:
    """An unreadable directory is not evidence that nothing illicit is in it."""
    make_repo(tmp_path)
    locked = tmp_path / "locked-tree"
    locked.mkdir()
    (locked / "inner.json").write_text('{"kind": "ok"}', encoding="utf-8")
    locked.chmod(0o000)
    try:
        result = lint(tmp_path)
    finally:
        locked.chmod(0o755)
    assert result.returncode == 1, result.stdout
    assert "Traceback" not in result.stderr, result.stderr
    assert "could not enumerate the repository" in result.stderr


# ---------------------------------------------------------------------------
# Declared-but-unenforced policy: pinned, not silently trusted
# ---------------------------------------------------------------------------


def test_the_allowed_source_document_types_policy_is_enforced_nowhere() -> None:
    """``ordinary_source_document_types_allowed`` constrains nothing, and that is pinned.

    The key is loaded and shape-checked by ``load_denylist`` and then read by no
    gate, so an ordinary source document type outside the list is rejected
    nowhere. ``denylist.Denylist.allowed_source_document_types`` says so in its
    own declaration; this test is what stops that note from rotting. If the field
    gains a reader the assertion below goes red and the note must be rewritten,
    rather than the repository quietly acquiring an enforced policy nobody
    recorded — or, worse, keeping a note that claims it has none.
    """
    tooling = ROOT / "src/research_contracts/tooling"
    readers = sorted(
        path.name
        for path in tooling.glob("*.py")
        if path.name != "denylist.py"
        and "allowed_source_document_types" in path.read_text(encoding="utf-8")
    )
    assert readers == [], (
        f"{readers} now read allowed_source_document_types; the policy is no longer "
        "unenforced and the note on Denylist.allowed_source_document_types is stale"
    )

    # False-positive control: the same scan must be able to SEE a real reader,
    # otherwise the empty result above would prove nothing. regulatory.py reads
    # normalized_forbidden, so a scan that cannot find it is vacuous.
    seen = sorted(
        path.name
        for path in tooling.glob("*.py")
        if path.name != "denylist.py" and "normalized_forbidden" in path.read_text(encoding="utf-8")
    )
    assert "regulatory.py" in seen, (
        "the source scan found no reader of normalized_forbidden either, so the "
        "assertion above is vacuous rather than informative"
    )


# --------------------------------------------------------------------------
# V13 — the walk's exclusion set had NO test at all, and had drifted from
#       .gitignore. `.ci-model-root/` is where CI checks out ANOTHER repository.
# --------------------------------------------------------------------------


#: Entries of the real ``.gitignore`` that name a directory at any depth. Parsed rather
#: than retyped: a retyped list is a second copy of the thing whose drift is the defect.
def gitignore_directory_entries() -> set[str]:
    from research_contracts.tooling.contract_tools import gitignored_directory_names

    return set(gitignored_directory_names(ROOT))


def test_the_repository_gitignore_actually_declares_directories() -> None:
    """Non-vacuity control for the two tests below.

    If the parser returned an empty set, the binding test would pass by measuring nothing —
    which is the defect class, not a result.
    """
    entries = gitignore_directory_entries()
    assert len(entries) >= 5, f"parsed only {sorted(entries)} from .gitignore"
    assert ".ci-model-root" in entries
    assert "node_modules" in entries


def test_every_gitignored_directory_is_pruned_by_the_walk() -> None:
    """The binding that did not exist: ``.gitignore`` and the walk's exclusion set.

    ``EXCLUDED_DIRECTORIES`` was a hand-maintained duplicate of a subset of ``.gitignore``
    with nothing holding the two together, and it had drifted: ``.ci-model-root``,
    ``dist`` and ``coverage`` were all ignored by git and walked by this gate.
    """
    from research_contracts.tooling.contract_tools import excluded_directories

    effective = excluded_directories(ROOT)
    missing = sorted(gitignore_directory_entries() - effective)
    assert not missing, f"{missing} are gitignored but the contract-lint walk descends into them"


def test_a_directory_added_to_gitignore_is_pruned(tmp_path: Path) -> None:
    """The pruning is READ from the repository's declaration, not restated in code."""
    make_repo(tmp_path)
    write_json(tmp_path / "vendored/x.schema.json", {"title": "not ours"})
    before = lint(tmp_path)
    assert before.returncode == 1, "the control did not fail; the probe proves nothing"

    (tmp_path / ".gitignore").write_text("vendored/\n", encoding="utf-8")
    after = lint(tmp_path)
    assert after.returncode == 0, f"a gitignored directory was still walked: {after.stderr}"


def test_a_directory_that_is_not_gitignored_is_still_walked(tmp_path: Path) -> None:
    """False-positive control: the pruning must not swallow ordinary directories.

    Written as a pair with the test above so that a fix which pruned everything, or which
    never read ``.gitignore`` at all, cannot pass both.
    """
    make_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("vendored/\n", encoding="utf-8")
    write_json(tmp_path / "openapi/x.schema.json", {"title": "ours"})
    result = lint(tmp_path)
    assert result.returncode == 1, "an ordinary directory stopped being scanned"
    assert "openapi/x.schema.json" in result.stderr


@pytest.mark.parametrize(
    "entry",
    ["!vendored/", "# vendored/", "vendored", "build/*/", "packages/typescript/dist/"],
)
def test_only_unambiguous_directory_entries_are_read(tmp_path: Path, entry: str) -> None:
    """The parser is narrow ON PURPOSE and must not approximate the patterns it skips.

    A negation, a comment, a non-directory entry, a glob and an anchored path all mean
    something a name-based ``os.walk`` prune cannot express. Guessing at them would let a
    ``.gitignore`` line silently widen what the gate declines to look at.
    """
    from research_contracts.tooling.contract_tools import gitignored_directory_names

    (tmp_path / ".gitignore").write_text(f"{entry}\n", encoding="utf-8")
    assert gitignored_directory_names(tmp_path) == frozenset()


def test_the_hardcoded_exclusion_floor_applies_without_a_gitignore(tmp_path: Path) -> None:
    """``EXCLUDED_DIRECTORIES`` is a floor, not a cache of ``.gitignore``.

    A consumer linting a tree with no ``.gitignore`` at all still gets the tool-cache
    pruning, so the walk cannot be widened by deleting a file.
    """
    from research_contracts.tooling.contract_tools import excluded_directories

    assert not (tmp_path / ".gitignore").exists()
    effective = excluded_directories(tmp_path)
    assert {".git", ".venv", "node_modules", "__pycache__"} <= effective

    make_repo(tmp_path)
    write_json(tmp_path / "node_modules/pkg/x.schema.json", {"title": "vendored"})
    result = lint(tmp_path)
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# V14 — an extensionless document larger than the sniff window was invisible
# --------------------------------------------------------------------------


#: Comfortably past ``contract_tools.SNIFF_BYTES`` (65536), so the prefix read is cut
#: mid-scalar and ``yaml.safe_load`` raises on it.
PADDING_BYTES = 70000


def test_a_large_extensionless_document_is_still_scanned(tmp_path: Path) -> None:
    """The evasion the sniffer's own docstring says it exists to prevent.

    Only ``text[:SNIFF_BYTES]`` was parsed. Truncation cut the padding scalar in half,
    ``yaml.safe_load`` raised, ``_sniffs_as_document`` returned False and
    ``iter_repository_documents`` never yielded the file — so an open ``work_type`` in a
    70 KB extensionless document produced no finding at all. Dropping the extension was
    already a known bypass; appending padding restored it.
    """
    make_repo(tmp_path)
    (tmp_path / "catalog").write_text(
        json.dumps({"properties": {"work_type": {"type": "string"}}, "pad": "A" * PADDING_BYTES}),
        encoding="utf-8",
    )
    result = lint(tmp_path)
    assert result.returncode == 1, f"the padded document bypassed the scan: {result.stdout}"
    assert "activation discriminator must use closed const/enum" in result.stderr


def test_a_large_extensionless_forbidden_token_is_still_scanned(tmp_path: Path) -> None:
    """The token half of the same evasion."""
    make_repo(tmp_path)
    (tmp_path / "catalog").write_text(
        json.dumps({"kind": "legal_event", "pad": "A" * PADDING_BYTES}), encoding="utf-8"
    )
    result = lint(tmp_path)
    assert result.returncode == 1, f"the padded document bypassed the scan: {result.stdout}"
    assert "legal_event" in result.stderr


def test_a_large_extensionless_file_that_is_not_a_document_is_not_a_finding(
    tmp_path: Path,
) -> None:
    """False-positive control: the sniffer must still decline prose.

    A fix that simply admitted every extensionless file would pass both tests above while
    dragging arbitrary text into a JSON/YAML parser and reporting it as unparseable.
    """
    make_repo(tmp_path)
    (tmp_path / "LICENSE-NOTICE").write_text(
        "This file is prose about legal matters. " * 3000, encoding="utf-8"
    )
    assert (tmp_path / "LICENSE-NOTICE").stat().st_size > PADDING_BYTES
    result = lint(tmp_path)
    assert result.returncode == 0, result.stderr


def test_a_small_extensionless_non_document_is_still_declined(tmp_path: Path) -> None:
    """The unchanged half: below the sniff window, the prefix IS the whole file."""
    from research_contracts.tooling.contract_tools import _sniffs_as_document

    prose = tmp_path / "Makefile"
    prose.write_text("all:\n\techo hi\n", encoding="utf-8")
    assert _sniffs_as_document(prose) is False

"""Portability and fail-open regressions in the canonical engine.

Every test here was written against a defect that the 446-check source-tree suite could not
see, and every one of them was observed RED against the pre-fix code before being committed.
Three classes are represented:

* **packaging** -- the released schemas are *data the package cannot run without*, and the
  wheel shipped none of them. A source checkout can never notice, because a source checkout
  resolves them from the repository root by accident of layout.
* **fail-open cross-field rules** -- rules that answered "the invariant holds" from an
  absent, null, or untyped input rather than from evidence.
* **Python-only identity and regex semantics** -- ``repr`` and Python's ``$``, both of which
  a second language cannot reproduce, on paths whose whole purpose is a cross-language
  contract.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import ROOT, require_tool

from research_contracts.canonical import (
    SchemaValidationError,
    canonical_schemas,
    check_cross_field_rules,
    compare_pin_to_owner_response,
    derive_hash_profile,
    validate_instance,
    verify_reference,
)
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical import structural as structural_module
from research_contracts.canonical.errors import HashProfileError
from research_contracts.canonical.hash_profile import validate_profile_against_schema
from research_contracts.canonical.verification import COMPARED_FIELDS
from research_contracts.tooling.canonical_fixtures import EXPECTED_CHECKS, pinned_resolver

BITEMPORAL = "urn:datacompany:bitemporal-assertion:1"
HASH_PROFILE = "urn:datacompany:canonical-hash-profile:1"
STABLE_IDENTITY = "urn:datacompany:stable-identity:1"
FIXTURE_ROOT = ROOT / "fixtures" / "canonical-references" / "v1"
SOURCE_SCHEMA_DIR = ROOT / "schemas" / "canonical"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================ B1: the installed package ===
#
# `Path.glob` over a directory that does not exist returns [] with no error, so a wheel
# carrying zero schemas presented itself as a repository that releases zero schemas. The
# only way to catch this is to leave the source tree, so these two tests build and then
# read the artefact rather than the working directory.


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the wheel this repository would actually publish."""
    out = tmp_path_factory.mktemp("wheel")
    result = subprocess.run(
        [require_tool("uv"), "build", "--wheel", "--out-dir", str(out)],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"uv build failed:\n{result.stdout}\n{result.stderr}"
    wheels = sorted(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def test_the_built_wheel_carries_every_released_canonical_schema(built_wheel: Path) -> None:
    """The wheel must ship the schemas, and ship *all* of them.

    Asserted as an equality against the source tree, not as "more than zero": a wheel that
    shipped some of the released schemas would fail exactly the same way, one ``$ref`` later.
    """
    with zipfile.ZipFile(built_wheel) as archive:
        packaged = {
            Path(name).name
            for name in archive.namelist()
            if name.startswith("research_contracts/schemas/canonical/")
            and name.endswith(".schema.json")
        }
    released = {path.name for path in SOURCE_SCHEMA_DIR.glob("*.schema.json")}
    assert released, f"{SOURCE_SCHEMA_DIR} holds no released schemas -- the premise is gone"
    assert packaged == released, (
        f"the wheel ships {len(packaged)} of {len(released)} released canonical schemas; "
        f"missing {sorted(released - packaged)}, unexpected {sorted(packaged - released)}"
    )


def test_the_installed_layout_replays_every_fixture(built_wheel: Path, tmp_path: Path) -> None:
    """Import and run the package from an installed layout, not from ``src/``.

    The wheel is unpacked and placed first on ``sys.path`` in a child interpreter whose
    working directory is outside the repository, which is the layout that ``site-packages``
    produces. The child asserts that the module it imported really is the unpacked one
    before it proves anything else -- otherwise this test could silently re-measure the
    source tree and report a green that means nothing.
    """
    unpacked = tmp_path / "site-packages"
    with zipfile.ZipFile(built_wheel) as archive:
        archive.extractall(unpacked)

    child = tmp_path / "probe.py"
    child.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(unpacked)!r})\n"
        "import research_contracts, research_contracts.canonical as canonical\n"
        "from pathlib import Path\n"
        "located = Path(research_contracts.__file__).resolve().parent\n"
        f"assert located == Path({str(unpacked)!r}).resolve() / 'research_contracts', located\n"
        "from research_contracts.canonical.registry import "
        "CANONICAL_SCHEMA_DIR, canonical_schemas\n"
        "assert CANONICAL_SCHEMA_DIR.resolve().is_relative_to(located), CANONICAL_SCHEMA_DIR\n"
        "print('schemas', len(canonical_schemas()))\n"
        "from research_contracts.tooling.canonical_fixtures import main\n"
        f"sys.exit(main(['--fixtures-root', {str(ROOT / 'fixtures')!r}]))\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(child)],
        cwd=str(tmp_path),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"the installed package cannot replay the released fixtures:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert f"schemas {len(canonical_schemas())}" in result.stdout, result.stdout
    assert f"{EXPECTED_CHECKS} checks" in result.stdout, result.stdout


@pytest.mark.parametrize("populate", [False, True], ids=["missing", "empty"])
def test_an_absent_schema_directory_is_a_failure_not_an_empty_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, populate: bool
) -> None:
    """Zero released schemas is a diagnosis, never a clean result.

    This is the guard that turns the packaging fault into an error at the point it happens,
    rather than into an ``unknown schema_ref`` raised from an unrelated import side effect
    several modules away.
    """
    directory = tmp_path / "canonical"
    if populate:
        directory.mkdir()
        (directory / "not-a-schema.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(registry_module, "CANONICAL_SCHEMA_DIR", directory)
    registry_module.canonical_schemas.cache_clear()
    try:
        with pytest.raises(SchemaValidationError, match="canonical"):
            registry_module.canonical_schemas()
    finally:
        registry_module.canonical_schemas.cache_clear()


# ================================================ D0: the fail-open half-open interval ===
#
# The single invariant the module exists to enforce. Both directions were wrong: the valid
# fractional interval was rejected and the inverted one accepted, because '.' (0x2E) sorts
# before 'Z' (0x5A) and the bounds were compared as raw strings. No committed fixture uses
# fractional seconds, so all 111 checks stayed green over it.


def bitemporal(**overrides: Any) -> dict[str, Any]:
    base = load(FIXTURE_ROOT / "invalid" / "invalid-empty-valid-interval.json")["instance"]
    instance = {**base}
    for key, value in overrides.items():
        if value is ...:
            instance.pop(key, None)
        else:
            instance[key] = value
    return instance


def test_the_released_timestamp_permits_fractional_seconds() -> None:
    """The premise of D0, asserted rather than assumed."""
    pattern = canonical_schemas()[STABLE_IDENTITY]["$defs"]["timestamp"]["pattern"]
    assert "(\\.[0-9]+)?" in pattern
    assert validate_instance("2026-01-01T00:00:00.5Z", f"{STABLE_IDENTITY}#/$defs/timestamp") == []


def test_a_fractional_second_upper_bound_is_a_valid_interval() -> None:
    """``[00:00:00Z, 00:00:00.5Z)`` is half a second long, not empty."""
    instance = bitemporal(valid_from="2026-01-01T00:00:00Z", valid_to="2026-01-01T00:00:00.5Z")
    assert validate_instance(instance, BITEMPORAL) == []


def test_an_inverted_fractional_second_interval_is_rejected() -> None:
    """``[00:00:00.5Z, 00:00:00Z)`` runs backwards. This half was the fail-open one."""
    instance = bitemporal(valid_from="2026-01-01T00:00:00.5Z", valid_to="2026-01-01T00:00:00Z")
    failures = check_cross_field_rules(instance, BITEMPORAL)
    assert any("empty or inverted" in failure for failure in failures), failures


@pytest.mark.parametrize(
    ("lower", "upper", "non_empty"),
    [
        # The two cases a lexicographic compare gets WRONG, in both directions: '.' (0x2E)
        # sorts before 'Z' (0x5A), so a whole second compares as LATER than any fraction of
        # itself. Every other case below a lexicographic compare happens to get right.
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00.5Z", True),
        ("2026-01-01T00:00:00.5Z", "2026-01-01T00:00:00Z", False),
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00.000001Z", True),
        # Sub-second ordering, which a lexicographic compare gets right only by luck.
        ("2026-01-01T00:00:00.1Z", "2026-01-01T00:00:00.2Z", True),
        ("2026-01-01T00:00:00.2Z", "2026-01-01T00:00:00.1Z", False),
        # Differing precision: 0.5 > 0.45 although "45" sorts before "5".
        ("2026-01-01T00:00:00.45Z", "2026-01-01T00:00:00.5Z", True),
        ("2026-01-01T00:00:00.5Z", "2026-01-01T00:00:00.45Z", False),
        # Trailing zeros are the same instant, so the interval is empty.
        ("2026-01-01T00:00:00.5Z", "2026-01-01T00:00:00.500Z", False),
        # A fractional bound must not beat a later whole second.
        ("2026-01-01T00:00:00.9Z", "2026-01-01T00:00:01Z", True),
        ("2026-01-01T00:00:01Z", "2026-01-01T00:00:00.9Z", False),
    ],
)
def test_fractional_bounds_are_ordered_as_instants_not_as_text(
    lower: str, upper: str, non_empty: bool
) -> None:
    failures = check_cross_field_rules(bitemporal(valid_from=lower, valid_to=upper), BITEMPORAL)
    assert (failures == []) is non_empty, failures


# ======================================== D2: a mismatched bound type must not escape ===


@pytest.mark.parametrize(
    ("lower", "upper"),
    [
        (5, "2026-01-01T00:00:00Z"),
        ("2026-01-01T00:00:00Z", 5),
        ("not-a-timestamp", "2026-01-01T00:00:00Z"),
        ("2026-01-01T00:00:00Z", ["2027-01-01T00:00:00Z"]),
        # Syntactically well formed, but no such date exists.
        ("2026-13-01T00:00:00Z", "2027-01-01T00:00:00Z"),
    ],
)
def test_a_bound_that_is_not_an_instant_is_a_recorded_failure_not_a_type_error(
    lower: Any, upper: Any
) -> None:
    """``end > start`` between a ``str`` and an ``int`` raised out of the failure collector.

    ``check_cross_field_rules`` returns failures; it does not raise them. A ``TypeError``
    escaping it is an unhandled crash in every caller, and a JavaScript port would silently
    coerce instead -- a divergence in both directions.
    """
    failures = check_cross_field_rules(bitemporal(valid_from=lower, valid_to=upper), BITEMPORAL)
    assert any("not a released rfc3339_utc_z instant" in failure for failure in failures), failures


def test_an_unparseable_lower_bound_is_caught_even_with_no_upper_bound() -> None:
    """+infinity as the upper bound does not excuse a lower bound that means nothing."""
    failures = check_cross_field_rules(
        bitemporal(valid_from="not-a-timestamp", valid_to=...), BITEMPORAL
    )
    assert any("not a released rfc3339_utc_z instant" in failure for failure in failures), failures


# ================================ D2b: a null lower bound with an absent upper bound ===


def test_a_null_lower_bound_is_rejected_even_when_the_upper_bound_is_absent() -> None:
    """Branch order: ``if end is _MISSING: continue`` returned before the null check.

    An omitted ``valid_to`` means positive infinity, so the shortcut is correct -- but it
    was taken before the lower bound had been looked at, and ``{"valid_from": null}``
    therefore produced zero failures.
    """
    failures = check_cross_field_rules(bitemporal(valid_from=None, valid_to=...), BITEMPORAL)
    assert any("null is not a released encoding" in failure for failure in failures), failures


def test_a_null_lower_bound_is_still_rejected_when_an_upper_bound_is_present() -> None:
    failures = check_cross_field_rules(
        bitemporal(valid_from=None, valid_to="2027-01-01T00:00:00Z"), BITEMPORAL
    )
    assert any("null is not a released encoding" in failure for failure in failures), failures


# ============================ D2c: unique_by and disjoint were fail-open on a non-list ===


@pytest.mark.parametrize(
    "target",
    [..., None, {}, "not-a-list", 7],
    ids=["absent", "null", "object", "string", "number"],
)
def test_unique_by_and_disjoint_fail_loudly_on_a_target_that_is_not_an_array(
    target: Any,
) -> None:
    """``check_cross_field_rules`` is a public, schema-independent entry point.

    With the target absent, ``{}`` or ``null`` both rules returned ``[]`` -- "the members are
    unique" and "the two sets are disjoint" asserted by vacuity rather than by evidence, and
    nothing else was checking.
    """
    profile = derive_hash_profile(STABLE_IDENTITY)
    for key in ("arrays", "excluded_pointers", "included_pointers", "opaque_pointers"):
        if target is ...:
            profile.pop(key, None)
        else:
            profile[key] = target
    failures = check_cross_field_rules(profile, HASH_PROFILE)
    assert failures, "every declared unique_by/disjoint rule passed over a non-array target"
    assert all("not an array" in failure for failure in failures), failures


def test_an_empty_instance_does_not_satisfy_the_hash_profile_cross_field_rules() -> None:
    """The strongest form of the same fail-open: ``{}`` satisfied all four released rules."""
    assert check_cross_field_rules({}, HASH_PROFILE) != []


# ============================================ D1 / B2: repr is not a cross-language id ===

REORDER_SCHEMA_ID = "urn:datacompany:test-member-order:1"
REORDER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": REORDER_SCHEMA_ID,
    "type": "object",
    "x-datacompany-cross-field": [
        {"rule": "unique_by", "name": "unique_keys", "at": "/left", "key": "/pointer"},
        {
            "rule": "disjoint",
            "name": "left_and_right_are_disjoint",
            "left": "/flat_left",
            "right": "/flat_right",
        },
    ],
}


@pytest.fixture
def reorder_schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    schemas = {**canonical_schemas(), REORDER_SCHEMA_ID: REORDER_SCHEMA}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    yield
    structural_module._collect.cache_clear()


def test_unique_by_sees_through_member_insertion_order(reorder_schema: None) -> None:
    """``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` are one JSON value, not two.

    ``repr`` renders a mapping in insertion order and is Python source syntax no other
    language reproduces. Any JSON round-trip can reorder members, so this was a duplicate
    the released uniqueness rule did not see.
    """
    instance = {
        "left": [{"pointer": {"a": 1, "b": 2}}, {"pointer": {"b": 2, "a": 1}}],
        "flat_left": [],
        "flat_right": [],
    }
    failures = check_cross_field_rules(instance, REORDER_SCHEMA_ID)
    assert any("both declare" in failure for failure in failures), failures


def test_disjoint_sees_through_member_insertion_order(reorder_schema: None) -> None:
    instance = {
        "left": [],
        "flat_left": [{"a": 1, "b": 2}],
        "flat_right": [{"b": 2, "a": 1}],
    }
    failures = check_cross_field_rules(instance, REORDER_SCHEMA_ID)
    assert any("must be disjoint" in failure for failure in failures), failures


def test_a_reordered_manifest_entry_is_not_a_contradiction_of_the_released_annotations() -> None:
    """B2, the mirror image: ``sorted(key=repr)`` falsely *rejected* an identical manifest.

    The manifest below is the derived one with the members of each entry written in the
    other order -- the same JSON, which any round-trip through a non-Python serializer can
    produce. It sorted differently from the derived list and was rejected as contradicting
    the schema annotations it was derived from.
    """
    derived = derive_hash_profile(BITEMPORAL)
    assert derived["excluded_pointers"], "the premise is gone: no excluded pointers to reorder"
    reordered = {
        **derived,
        "excluded_pointers": [
            dict(reversed(list(entry.items()))) for entry in derived["excluded_pointers"]
        ],
    }
    assert [list(entry) for entry in reordered["excluded_pointers"]] != [
        list(entry) for entry in derived["excluded_pointers"]
    ], "the entries have one member each; reordering them is a no-op and proves nothing"
    validate_profile_against_schema(reordered, BITEMPORAL)


def test_a_manifest_that_really_contradicts_the_annotations_is_still_rejected() -> None:
    """The false-positive control for the test above: the gate can still fail."""
    derived = derive_hash_profile(BITEMPORAL)
    contradicting = {
        **derived,
        "excluded_pointers": [
            {**entry, "pointer": "/not-a-released-pointer"}
            for entry in derived["excluded_pointers"]
        ],
    }
    with pytest.raises(HashProfileError):
        validate_profile_against_schema(contradicting, BITEMPORAL)


# ========================== D2d: a malformed owner response must still leave a receipt ===


def test_owner_content_that_does_not_validate_produces_a_rejected_receipt() -> None:
    """A broken or hostile owner service must not be able to erase the consumer's audit trail.

    ``compute_content_hash`` raises ``SchemaValidationError`` on content that does not
    validate against the ``schema_ref`` the owner itself declared. That raise escaped
    ``verify_reference``, so **no receipt was written at all** where the contract wants a
    rejected one.
    """
    fixture = load(
        FIXTURE_ROOT / "verification" / "verification-owner-content-does-not-validate.json"
    )
    receipt = verify_reference(
        fixture["pinned_version_ref"],
        resolver=lambda *_: fixture["owner_response"],
        consumer_context=fixture["consumer_context"],
        subject_local_ref=fixture["subject_local_ref"],
        verification_profile_ref=fixture["verification_profile_ref"],
        verified_at="2026-07-30T10:00:05Z",
        receipt_id="bbbbbbbb-0000-4000-8000-000000000004",
    )
    assert receipt["result"] == "rejected"
    assert receipt["failure_code"] == "content_hash_mismatch"


@pytest.mark.parametrize(
    "content",
    [
        # Does not validate against the schema_ref the owner itself declared.
        {"entity_id": "NOT-A-UUID"},
        # Valid shape, but an unstable binary float the hash algorithm refuses.
        {"entity_id": 1.1},
        # Not an object at all.
        "a string",
    ],
    ids=["invalid", "unstable-float", "not-an-object"],
)
def test_uncomputable_owner_content_is_a_rejection_not_an_escaping_exception(
    content: Any,
) -> None:
    """Every internal raise of ``compute_content_hash`` must become a comparison result.

    Asserted through the pin's *own* ``schema_ref`` so the ``content_hash`` branch is really
    reached: a mismatching ``schema_ref`` is compared first and would short-circuit, which
    would make this test pass without ever running the code it is about.
    """
    fixture = load(FIXTURE_ROOT / "verification" / "verification-verified.json")
    pin = fixture["pinned_version_ref"]
    response = {
        **fixture["owner_response"],
        "schema_ref": pin["schema_ref"],
        "canonical_content": content,
    }
    assert compare_pin_to_owner_response(pin, response) == "content_hash_mismatch"


# ================================================== D2e: the resolver gate can now fail ===


def test_the_fixture_resolver_refuses_a_call_that_is_not_the_exact_pin() -> None:
    """The harness resolver was ``lambda *_: fixture["owner_response"]``.

    It discarded both arguments, so it answered any call whatsoever: swapping ``entity_id``
    and ``version_id`` at the call site left all 111 checks green, and the documented
    "resolve by exact entity_id/version_id, never fall back to latest" rule was untested.
    """
    fixture = load(FIXTURE_ROOT / "verification" / "verification-verified.json")
    pin = fixture["pinned_version_ref"]
    assert pin["entity_id"] != pin["version_id"], "the swap must be observable"

    failures: list[str] = []
    resolve = pinned_resolver(fixture, failures, "verification-verified.json")

    assert resolve(pin["entity_id"], pin["version_id"]) == fixture["owner_response"]
    assert failures == []

    # The swap the old resolver could not see.
    assert resolve(pin["version_id"], pin["entity_id"]) is None
    assert len(failures) == 1
    assert "exact" in failures[0] and "never falls back to latest" in failures[0]


def test_the_verification_suite_goes_red_when_the_resolver_is_called_wrongly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P9 falsifiability, applied to the harness itself: break it and watch it fail."""
    from research_contracts.tooling import canonical_fixtures as harness

    real = harness.verify_reference

    def swapped(pin: dict[str, Any], **kwargs: Any) -> Any:
        resolver = kwargs.pop("resolver")
        return real(pin, resolver=lambda a, b: resolver(b, a), **kwargs)

    monkeypatch.setattr(harness, "verify_reference", swapped)
    failures: list[str] = []
    counts: dict[str, int] = {}
    harness.check_references(FIXTURE_ROOT, failures, counts)
    assert counts["references/verification"] > 0, "no verification fixture was replayed at all"
    assert any("exact" in failure for failure in failures), (
        "swapping the resolver's two arguments changed nothing: the harness's owner-resolution "
        f"rule is still a gate that cannot fail. failures={failures}"
    )


def test_the_compared_field_order_is_pinned() -> None:
    """D2e, second half: precedence decides which code a multi-field mismatch reports.

    Nothing pinned the order, so a reordering of ``COMPARED_FIELDS`` -- a refactor with no
    visible consequence -- silently changed the failure code every multi-field mismatch
    reports, and every verification fixture would still have passed.
    """
    assert [field for field, _ in COMPARED_FIELDS] == [
        "owner_context",
        "entity_type",
        "entity_id",
        "version_id",
        "version_number",
        "resource_scope",
        "resource_tenant_id",
        "schema_ref",
        "content_hash",
    ]
    assert len({code for _, code in COMPARED_FIELDS}) == len(COMPARED_FIELDS)


def test_a_multi_field_mismatch_reports_the_first_field_in_the_released_order() -> None:
    fixture = load(FIXTURE_ROOT / "verification" / "verification-verified.json")
    response = {
        **fixture["owner_response"],
        "owner_context": "somebody-else",
        "entity_type": "something-else",
        "version_number": 99,
    }
    assert (
        compare_pin_to_owner_response(fixture["pinned_version_ref"], response)
        == "owner_context_mismatch"
    )


# =========================================== B7: Python's `$` matches before a newline ===


@pytest.mark.parametrize(
    ("schema_ref", "value"),
    [
        (f"{STABLE_IDENTITY}#/$defs/timestamp", "2026-01-01T00:00:00Z\n"),
        (f"{STABLE_IDENTITY}#/$defs/uuid", "acceef8d-4d38-a5e9-dc70-a0613c52b2a8\n"),
        (
            f"{STABLE_IDENTITY}#/$defs/decimal_string",
            "1.5\n",
        ),
    ],
)
def test_an_anchored_pattern_rejects_a_trailing_newline(schema_ref: str, value: str) -> None:
    """JSON Schema mandates ECMA-262, where ``$`` asserts the end of input.

    Python's ``$`` also matches immediately before a trailing ``\\n``, so every anchored
    released pattern was fail-open on exactly one character -- and a conforming validator in
    any other language rejects these values. Python was the non-conformant side.
    """
    assert validate_instance(value, schema_ref) != []
    assert validate_instance(value.rstrip("\n"), schema_ref) == []


def test_a_pinned_reference_content_hash_rejects_a_trailing_newline() -> None:
    """The same defect on ``^sha256:[0-9a-f]{64}$``, the digest the contract is built on."""
    pin = load(FIXTURE_ROOT / "valid" / "global-pinned-ref.json")["instance"]
    assert validate_instance(pin, "urn:datacompany:pinned-version-ref:1") == []
    tampered = {**pin, "content_hash": pin["content_hash"] + "\n"}
    assert validate_instance(tampered, "urn:datacompany:pinned-version-ref:1") != []


def test_the_ecma_dot_excludes_every_line_terminator() -> None:
    """Python's ``.`` excludes only ``\\n``; ECMA-262's excludes four characters."""
    pattern = registry_module.ecma_262_pattern(r"^\S(?:.*\S)?$")
    assert pattern.search("a b") is not None
    for terminator in ("\n", "\r", "\u2028", "\u2029"):
        assert pattern.search(f"a{terminator}b") is None, repr(terminator)


def test_the_ecma_translation_leaves_character_classes_alone() -> None:
    """A ``$`` or ``.`` inside ``[...]`` is a literal and must not be rewritten."""
    assert registry_module.ecma_262_pattern(r"^[.$]+$").search(".$.") is not None
    assert registry_module.ecma_262_pattern(r"^[.$]+$").search(".$.\n") is None
    # An escaped dot is a literal dot, not the ECMA dot class.
    assert registry_module.ecma_262_pattern(r"^a\.b$").search("a.b") is not None
    assert registry_module.ecma_262_pattern(r"^a\.b$").search("axb") is None


def test_every_released_schema_still_compiles_under_ecma_semantics() -> None:
    """The translation is applied to real released patterns, so it must not break one."""
    seen = 0
    for schema in canonical_schemas().values():
        for pattern in walk_patterns(schema):
            registry_module.ecma_262_pattern(pattern)
            seen += 1
    assert seen > 10, f"only {seen} released patterns found; the sweep is measuring nothing"


def walk_patterns(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        pattern = node.get("pattern")
        if isinstance(pattern, str):
            found.append(pattern)
        for value in node.values():
            found.extend(walk_patterns(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(walk_patterns(value))
    return found


# ============================================================== D3 / D4: flagged, open ===


def test_the_singleton_rule_is_evaluable_as_a_composed_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3 closed as option B: the singleton equality now evaluates where it is composed.

    ``pinned-version-ref#/$defs/singleton`` declares ``equal /entity_id /version_id``. Before
    D3 those operands were instance-root-absolute, so composing a pin as a *property* of an
    evidence schema -- which is FND-002 task 4's whole job -- made the collector raise. The
    rule now declares ``"scope": "relative"``, so its operands resolve against the location it
    is reached at, and the composed pin is checked as itself.

    The full semantics live in ``tests/test_d3_relative_scope.py``. What this pins is the
    portability-relevant half: the rule is evaluated against the NESTED object, so the
    failure names ``/pin/...``. A port that resolved the operands against the instance root
    would report a failure naming ``/entity_id`` here, or none at all, and either way would
    be asserting a different proposition under the same rule name.
    """
    singleton = canonical_schemas()["urn:datacompany:pinned-version-ref:1"]["$defs"]["singleton"]
    assert singleton["x-datacompany-cross-field"][0]["left"] == "/entity_id"
    assert singleton["x-datacompany-cross-field"][0]["scope"] == "relative"
    composed_id = "urn:datacompany:test-composed-pin:1"
    composed = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": composed_id,
        "type": "object",
        "properties": {"pin": singleton},
    }
    schemas = {**canonical_schemas(), composed_id: composed}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
    structural_module._collect.cache_clear()
    try:
        assert check_cross_field_rules({"pin": {}}, composed_id) == [
            "equal: /pin/entity_id and /pin/version_id must both be present and equal"
        ]
        # The discriminating control: a pin that holds is silent, so the rule is answering a
        # question about the instance rather than firing on the composition alone.
        identical = "11111111-1111-4111-8111-111111111111"
        assert (
            check_cross_field_rules(
                {"pin": {"entity_id": identical, "version_id": identical}}, composed_id
            )
            == []
        )
    finally:
        structural_module._collect.cache_clear()


# ================================================= P6/P7: the two-language coverage pin ===
#
# `EXPECTED_CHECKS` and the TypeScript port's `DIRECTORY_SUITES` are one number written in
# two places, and the failure mode is specific: two individually-green pull requests can
# turn main red through a count pin with no merge conflict at all. Cross-checking is
# therefore done from BOTH sides. `packages/typescript/test/coverage.test.ts` parses the
# `SUITES` table below; this parses that file, so deleting either mirror is a red test
# rather than a silently one-directional pin.

TS_COVERAGE = ROOT / "packages" / "typescript" / "test" / "coverage.test.ts"


def test_the_typescript_port_pins_the_same_per_suite_counts() -> None:
    """Every Python suite is replayed by the port, at the same count."""
    import re

    from research_contracts.tooling.canonical_fixtures import SUITES

    source = TS_COVERAGE.read_text(encoding="utf-8")
    declared = {
        match.group(1): int(match.group(2))
        for match in re.finditer(
            r"\{\s*name:\s*'([^']+)',\s*directory:\s*\w+,\s*checks:\s*(\d+)\s*\}", source
        )
    }
    numbers = {
        match.group(1): int(match.group(2))
        for match in re.finditer(
            r"const (RFC_NUMBER_VECTORS|RFC_STRUCTURAL_FILES) = (\d+);", source
        )
    }
    # Non-vacuity first: an unparsed file would make every lookup below trivially absent and
    # the loop trivially satisfied.
    assert len(declared) == len(SUITES) - 1, declared
    assert set(numbers) == {"RFC_NUMBER_VECTORS", "RFC_STRUCTURAL_FILES"}, numbers

    for suite in SUITES:
        if suite.name == "hash/rfc8785":
            assert sum(numbers.values()) == suite.minimum, numbers
            continue
        assert declared.get(suite.name) == suite.minimum, (
            f"{suite.name}: Python pins {suite.minimum}, the TypeScript port pins "
            f"{declared.get(suite.name)}. The two are one number in two files."
        )
    assert sum(declared.values()) + sum(numbers.values()) == EXPECTED_CHECKS

"""FND-005: the canonical hash engine must be right, not merely present.

The suite is layered:

* RFC 8785 conformance, against committed vectors whose expected values come from a native
  ECMAScript oracle (``String(n)`` for numbers, default string ``sort`` for property-name
  ordering) rather than from this implementation;
* golden content-hash vectors covering every axis DM-AT-27 and section 4.3 name;
* negative mutation tests for DM-AT-28;
* rejection tests for duplicate set members, undeclared array kinds, unstable binary floats,
  unknown hash exclusions and a supplied hash that does not recompute (DM-AT-29).
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import (
    CanonicalError,
    ContentHashMismatchError,
    DuplicateSetMemberError,
    HashProfileError,
    MissingOrderKeyError,
    UndeclaredArrayError,
    UnknownExclusionError,
    UnstableFloatError,
    UnsupportedTypeError,
    build_hash_view,
    canonical_json_bytes,
    canonical_sha256,
    compute_content_hash,
    derive_hash_profile,
    es_number_to_string,
    merge_profile_extensions,
    stable_integer,
    utf16_sort_key,
    validate_hash_profile,
    validate_instance,
    validate_profile_against_schema,
    verify_content_hash,
)
from research_contracts.canonical.hash_view import UndeclaredPathError

HASH_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "canonical-hash" / "v1"
RFC_DIR = HASH_ROOT / "rfc8785"
VECTOR_DIR = HASH_ROOT / "vectors"
MUTATION_DIR = HASH_ROOT / "mutations"
REJECTED_DIR = HASH_ROOT / "rejected"
MANIFEST_DIR = HASH_ROOT / "manifests"

HASH_PROFILE_SCHEMA = "urn:datacompany:canonical-hash-profile:1"

ERROR_TYPES = {
    "DuplicateSetMemberError": DuplicateSetMemberError,
    "UndeclaredArrayError": UndeclaredArrayError,
    "UnstableFloatError": UnstableFloatError,
    "UnknownExclusionError": UnknownExclusionError,
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def files(directory: Path) -> list[Path]:
    paths = sorted(directory.glob("*.json"))
    assert paths, f"no fixtures found under {directory}"
    return paths


def profile_for(fixture: dict[str, Any]) -> dict[str, Any]:
    return merge_profile_extensions(
        derive_hash_profile(fixture["schema_ref"]), fixture.get("profile_extensions")
    )


def vector(fixture_id: str) -> dict[str, Any]:
    return load(VECTOR_DIR / f"{fixture_id}.json")


def hash_of(fixture: dict[str, Any]) -> str:
    return compute_content_hash(
        fixture["instance"], fixture["schema_ref"], profile=profile_for(fixture)
    )


def set_pointer(document: Any, pointer: str, value: Any) -> None:
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer.lstrip("/").split("/")]
    node = document
    for token in tokens[:-1]:
        node = node[int(token)] if isinstance(node, list) else node[token]
    last = tokens[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


# ================================================================ RFC 8785 conformance ==


def test_rfc8785_number_serialization_matches_the_ecmascript_oracle() -> None:
    fixture = load(RFC_DIR / "number-serialization.json")
    mismatches = []
    for entry in fixture["vectors"]:
        value = struct.unpack(">d", bytes.fromhex(entry["ieee754_hex"]))[0]
        rendered = es_number_to_string(value)
        if rendered != entry["expected"]:
            mismatches.append((entry["ieee754_hex"], entry["expected"], rendered))
    assert mismatches == []
    assert len(fixture["vectors"]) >= 30


def test_rfc8785_structural_sample_is_reproduced_byte_for_byte() -> None:
    fixture = load(RFC_DIR / "structural-sample.json")
    canonical = canonical_json_bytes(json.loads(fixture["source"]), allow_binary_float=True)
    assert canonical.decode("utf-8") == fixture["expected_canonical_json"]
    assert "sha256:" + hashlib.sha256(canonical).hexdigest() == fixture["expected_sha256"]


def test_rfc8785_property_name_ordering_is_reproduced_byte_for_byte() -> None:
    fixture = load(RFC_DIR / "property-name-ordering.json")
    document = json.loads(fixture["source"])
    canonical = canonical_json_bytes(document)
    assert canonical.decode("utf-8") == fixture["expected_canonical_json"]
    assert "sha256:" + hashlib.sha256(canonical).hexdigest() == fixture["expected_sha256"]
    assert sorted(document, key=utf16_sort_key) == fixture["expected_key_order"]


def test_code_point_sorting_would_produce_a_different_and_wrong_result() -> None:
    """json.dumps(sort_keys=True) is NOT RFC 8785: it sorts by code point."""
    fixture = load(RFC_DIR / "property-name-ordering.json")
    document = json.loads(fixture["source"])
    code_point_order = sorted(document)
    assert code_point_order != fixture["expected_key_order"]
    assert (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        != (fixture["expected_canonical_json"])
    )
    # The discriminating pair, stated explicitly.
    astral, bmp = "\U0001f602", "דּ"
    assert utf16_sort_key(astral) < utf16_sort_key(bmp)
    assert astral > bmp  # Python's code-point comparison is the opposite order.


def test_canonical_bytes_are_utf8_without_a_byte_order_mark() -> None:
    canonical = canonical_json_bytes({"€": "\U0001f602"})
    assert not canonical.startswith(b"\xef\xbb\xbf")
    assert canonical.decode("utf-8") == '{"€":"\U0001f602"}'


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (-0.0, "0"), (1, "1"), (2**53, "9007199254740992"), (-2, "-2")],
)
def test_es_number_edge_cases(value: float, expected: str) -> None:
    assert es_number_to_string(value) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_have_no_canonical_form(value: float) -> None:
    assert math.isnan(value) or math.isinf(value)
    with pytest.raises(UnsupportedTypeError):
        canonical_json_bytes(value, allow_binary_float=True)


def test_integers_beyond_the_exact_double_range_are_rejected() -> None:
    with pytest.raises(UnstableFloatError):
        canonical_json_bytes(2**53 + 1)


def test_lone_surrogate_is_rejected() -> None:
    with pytest.raises(UnsupportedTypeError):
        canonical_json_bytes("\ud800")


def test_non_string_object_member_name_is_rejected() -> None:
    with pytest.raises(UnsupportedTypeError):
        canonical_json_bytes({1: "one"})


# ============================================================== golden content hashes ==


@pytest.mark.parametrize("path", files(VECTOR_DIR), ids=lambda p: p.stem)
def test_golden_vector_reproduces_byte_exactly(path: Path) -> None:
    fixture = load(path)
    assert validate_instance(fixture["instance"], fixture["schema_ref"]) == []
    profile = profile_for(fixture)
    view = build_hash_view(fixture["instance"], profile)
    canonical = canonical_json_bytes(view)
    assert canonical.decode("utf-8") == fixture["expected_hash_view_canonical_json"]
    assert canonical_sha256(view) == fixture["expected_content_hash"]
    assert (
        compute_content_hash(fixture["instance"], fixture["schema_ref"], profile=profile)
        == fixture["expected_content_hash"]
    )


def test_every_required_hash_axis_has_a_golden_vector() -> None:
    covered: set[str] = set()
    for path in files(VECTOR_DIR):
        covered.update(load(path)["axis"])
    required = {
        "unicode",
        "key-ordering",
        "decimals",
        "timestamps",
        "absent-vs-null",
        "ordered-arrays",
        "set-like-arrays",
        "nested-pinned-refs",
        "excluded-fields",
    }
    assert required <= covered, f"axes with no golden vector: {sorted(required - covered)}"


def test_excluded_fields_do_not_reach_the_hash_view() -> None:
    fixture = vector("immutable-version-nested-pins")
    view = build_hash_view(fixture["instance"], profile_for(fixture))
    assert "content_hash" not in view
    assert "content_hash_signatures" not in view
    assert "resolved_at" not in view["profile_ref"]
    assert all("resolved_at" not in pin for pin in view["pack_refs"])


def test_nested_target_content_hashes_remain_included() -> None:
    """Section 4.3 step 3: only the subject's OWN content_hash is removed."""
    fixture = vector("immutable-version-nested-pins")
    view = build_hash_view(fixture["instance"], profile_for(fixture))
    assert view["profile_ref"]["content_hash"].startswith("sha256:")
    assert all(pin["content_hash"].startswith("sha256:") for pin in view["pack_refs"])
    assert view["decision_ref"]["content_hash"].startswith("sha256:")


def test_signatures_over_the_content_hash_do_not_change_it() -> None:
    assert hash_of(vector("immutable-version-excluded-signatures")) == hash_of(
        vector("immutable-version-nested-pins")
    )


def test_set_like_array_input_order_does_not_change_the_hash() -> None:
    assert hash_of(vector("set-like-array-input-order-reversed")) == hash_of(
        vector("set-like-array-sorted-by-released-key")
    )


def test_set_like_array_is_sorted_by_its_released_canonical_key() -> None:
    fixture = vector("set-like-array-input-order-reversed")
    view = build_hash_view(fixture["instance"], profile_for(fixture))
    assert [tag["id"] for tag in view["value"]["tags"]] == ["alpha", "mu", "zeta"]


def test_ordered_array_keeps_its_exact_order() -> None:
    fixture = vector("ordered-array-preserves-order")
    view = build_hash_view(fixture["instance"], profile_for(fixture))
    assert view["value"]["steps"] == ["screen", "confirm", "treat"]


def test_absent_and_explicit_null_are_distinct() -> None:
    assert hash_of(vector("absent-vs-explicit-null-absent")) != hash_of(
        vector("absent-vs-explicit-null-explicit")
    )


def test_no_undeclared_unicode_normalization_is_applied() -> None:
    precomposed = vector("unicode-no-undeclared-normalization-precomposed")
    decomposed = vector("unicode-no-undeclared-normalization-decomposed")
    assert precomposed["instance"]["value"]["text"] != decomposed["instance"]["value"]["text"]
    import unicodedata

    assert (
        unicodedata.normalize("NFC", decomposed["instance"]["value"]["text"])
        == precomposed["instance"]["value"]["text"]
    )
    assert hash_of(precomposed) != hash_of(decomposed)


def test_decimals_are_carried_as_strings_in_the_hash_view() -> None:
    fixture = vector("decimal-carried-as-string")
    view = build_hash_view(fixture["instance"], profile_for(fixture))
    assert view["value"]["measurement"] == "0.30000000000000004"
    assert isinstance(view["value"]["measurement"], str)


# ==================================================== DM-AT-28 negative mutation tests ==


@pytest.mark.parametrize("path", files(MUTATION_DIR), ids=lambda p: p.stem)
def test_mutation_changes_or_preserves_the_hash_as_declared(path: Path) -> None:
    case = load(path)
    base = vector(case["base_fixture"])
    original = hash_of(base)
    assert original == base["expected_content_hash"]

    mutated = json.loads(json.dumps(base["instance"]))
    for mutation in case["mutations"]:
        set_pointer(mutated, mutation["pointer"], mutation["value"])
    assert validate_instance(mutated, base["schema_ref"]) == [], (
        f"{case['fixture_id']} must mutate to a still-valid instance"
    )
    mutated_hash = compute_content_hash(mutated, base["schema_ref"], profile=profile_for(base))
    if case["expect"] == "unchanged":
        assert mutated_hash == original, case["rationale"]
    else:
        assert mutated_hash != original, case["rationale"]


def test_every_excluded_field_class_has_an_unchanged_mutation_case() -> None:
    covered = set()
    for path in files(MUTATION_DIR):
        case = load(path)
        if case["expect"] != "unchanged":
            continue
        covered.update(m["pointer"].rsplit("/", 1)[-1] for m in case["mutations"])
    assert {"resolved_at", "aggregate_version", "recorded_until", "content_hash"} <= covered


# ========================================================== rejected hash inputs (7) ===


@pytest.mark.parametrize("path", files(REJECTED_DIR), ids=lambda p: p.stem)
def test_rejected_fixture_fails_with_its_named_error(path: Path) -> None:
    fixture = load(path)
    expected = ERROR_TYPES[fixture["expected_error"]]
    with pytest.raises(expected) as excinfo:
        compute_content_hash(
            fixture["instance"], fixture["schema_ref"], profile=profile_for(fixture)
        )
    assert fixture["expected_message_contains"] in str(excinfo.value)


def test_duplicate_set_like_members_fail() -> None:
    fixture = vector("set-like-array-sorted-by-released-key")
    instance = json.loads(json.dumps(fixture["instance"]))
    instance["value"]["tags"].append({"id": "alpha", "label": "Alpha again"})
    with pytest.raises(DuplicateSetMemberError):
        compute_content_hash(instance, fixture["schema_ref"], profile=profile_for(fixture))


def test_duplicate_pins_in_a_released_set_fail() -> None:
    """The hazard uniqueItems misses: same identity, different excluded observation field."""
    fixture = vector("immutable-version-nested-pins")
    instance = json.loads(json.dumps(fixture["instance"]))
    twin = json.loads(json.dumps(instance["pack_refs"][0]))
    twin["resolved_at"] = "2026-07-30T23:59:59Z"
    instance["pack_refs"].append(twin)
    # The instance is schema-valid: uniqueItems sees two distinct objects.
    assert validate_instance(instance, fixture["schema_ref"]) == []
    with pytest.raises(DuplicateSetMemberError):
        compute_content_hash(instance, fixture["schema_ref"], profile=profile_for(fixture))


def test_an_undeclared_array_kind_fails() -> None:
    fixture = vector("ordered-array-preserves-order")
    profile = profile_for(fixture)
    profile = {**profile, "arrays": [a for a in profile["arrays"] if a["kind"] != "ordered"]}
    with pytest.raises(UndeclaredArrayError):
        compute_content_hash(fixture["instance"], fixture["schema_ref"], profile=profile)


def test_an_unstable_binary_float_fails() -> None:
    fixture = vector("decimal-carried-as-string")
    instance = json.loads(json.dumps(fixture["instance"]))
    instance["value"]["measurement"] = 0.1
    with pytest.raises(UnstableFloatError):
        compute_content_hash(instance, fixture["schema_ref"], profile=profile_for(fixture))
    with pytest.raises(UnstableFloatError):
        canonical_sha256({"measurement": 0.1})


def test_an_undeclared_hash_view_path_fails() -> None:
    fixture = vector("immutable-version-nested-pins")
    instance = json.loads(json.dumps(fixture["instance"]))
    instance["smuggled"] = "value"
    with pytest.raises(UndeclaredPathError):
        build_hash_view(instance, profile_for(fixture))


def test_a_supplied_content_hash_that_does_not_recompute_is_rejected() -> None:
    """DM-AT-29: supplied hashes are never blindly trusted."""
    fixture = vector("immutable-version-nested-pins")
    instance = json.loads(json.dumps(fixture["instance"]))
    instance["content_hash"] = "sha256:" + "b" * 64
    with pytest.raises(ContentHashMismatchError) as excinfo:
        verify_content_hash(instance, fixture["schema_ref"], profile=profile_for(fixture))
    assert "does not recompute" in str(excinfo.value)

    instance["content_hash"] = fixture["expected_content_hash"]
    assert (
        verify_content_hash(instance, fixture["schema_ref"], profile=profile_for(fixture))
        == fixture["expected_content_hash"]
    )


def test_an_absent_content_hash_is_not_silently_accepted() -> None:
    """Fail closed: an ImmutableVersion without content_hash never reaches verification."""
    fixture = vector("immutable-version-nested-pins")
    instance = json.loads(json.dumps(fixture["instance"]))
    del instance["content_hash"]
    with pytest.raises(CanonicalError):
        verify_content_hash(instance, fixture["schema_ref"], profile=profile_for(fixture))


def test_a_verifiable_shape_without_a_supplied_hash_is_rejected_not_defaulted() -> None:
    fixture = vector("stable-identity-excluded-aggregate-version")
    with pytest.raises(ContentHashMismatchError, match="is absent"):
        verify_content_hash(fixture["instance"], fixture["schema_ref"])


# ================================================================ released manifests ===


@pytest.mark.parametrize("path", files(MANIFEST_DIR), ids=lambda p: p.stem)
def test_released_manifest_matches_its_schema_and_the_derivation(path: Path) -> None:
    manifest = load(path)
    assert validate_instance(manifest, HASH_PROFILE_SCHEMA) == []
    validate_hash_profile(manifest)
    assert manifest == derive_hash_profile(manifest["schema_ref"]), (
        "the committed manifest drifted from its schema annotations; adding or changing a "
        "path, normalization rule or collection kind is a schema compatibility change"
    )


def test_every_excluded_pointer_names_a_released_reason() -> None:
    reasons: set[str] = set()
    for path in files(MANIFEST_DIR):
        for entry in load(path)["excluded_pointers"]:
            reasons.add(entry["reason"])
    assert reasons <= {
        "own_content_hash",
        "signature",
        "transport_envelope",
        "resolution_observation",
        "projection_or_cache",
        "aggregate_version",
        "recorded_until",
    }
    assert {
        "own_content_hash",
        "signature",
        "resolution_observation",
        "aggregate_version",
        "recorded_until",
    } <= reasons


def test_an_unknown_hash_exclusion_is_rejected() -> None:
    manifest = load(MANIFEST_DIR / "immutable-version.v1.profile.json")
    manifest["excluded_pointers"] = [
        *manifest["excluded_pointers"],
        {"pointer": "/created_by", "reason": "because_we_felt_like_it"},
    ]
    with pytest.raises(HashProfileError):
        validate_hash_profile(manifest)


def test_a_manifest_for_a_different_schema_is_rejected() -> None:
    fixture = vector("immutable-version-nested-pins")
    other = derive_hash_profile("urn:datacompany:bitemporal-assertion:1")
    with pytest.raises(Exception, match="which is not the hashed object"):
        compute_content_hash(fixture["instance"], fixture["schema_ref"], profile=other)


def test_a_domain_extension_may_not_remove_or_add_an_exclusion() -> None:
    base = derive_hash_profile("urn:datacompany:bitemporal-assertion:1")
    with pytest.raises(HashProfileError):
        merge_profile_extensions(base, {"excluded_pointers": []})


def test_set_like_arrays_declare_an_order_key_and_ordered_arrays_do_not() -> None:
    for path in files(MANIFEST_DIR):
        for entry in load(path)["arrays"]:
            assert ("order_key" in entry) is (entry["kind"] == "set")


# ================== a supplied manifest may not contradict the schema annotations (D2) ==


IMMUTABLE_VERSION = "urn:datacompany:immutable-version:1"
BITEMPORAL_ASSERTION = "urn:datacompany:bitemporal-assertion:1"


def tamper(schema_ref: str, **changes: Any) -> dict[str, Any]:
    return {**derive_hash_profile(schema_ref), **changes}


@pytest.mark.parametrize(
    ("label", "changes"),
    [
        ("exclusions deleted", {"excluded_pointers": []}),
        (
            "exclusion reason rewritten",
            {"excluded_pointers": [{"pointer": "/content_hash", "reason": "projection_or_cache"}]},
        ),
        ("undeclared normalization", {"unicode_normalization": "nfc"}),
        ("absent and null conflated", {"absent_vs_null": "equivalent"}),
        ("opaque subtree invented", {"opaque_pointers": ["/profile_ref"]}),
    ],
)
def test_a_manifest_contradicting_its_schema_annotations_cannot_hash(
    label: str, changes: dict[str, Any]
) -> None:
    """DM-AT-28: the schema's annotations are the authority, not the caller's manifest.

    ``validate_hash_profile`` only proves the manifest is well formed. A well-formed manifest
    that deletes the released exclusions turns ``resolved_at`` -- a consumer's own resolution
    observation -- into hashed content, so two services would compute different "canonical"
    hashes for the same object and both would be "valid".
    """
    del label
    fixture = vector("immutable-version-nested-pins")
    forged = tamper(IMMUTABLE_VERSION, **changes)
    with pytest.raises(HashProfileError, match="contradicts the released annotations"):
        compute_content_hash(fixture["instance"], IMMUTABLE_VERSION, profile=forged)


def test_the_exact_reported_bypass_no_longer_reproduces() -> None:
    """The verifier's repro, verbatim: strip exclusions, re-include the excluded paths."""
    fixture = vector("immutable-version-nested-pins")
    forged = derive_hash_profile(IMMUTABLE_VERSION)
    forged["excluded_pointers"] = []
    forged["included_pointers"] = [
        *forged["included_pointers"],
        "/content_hash",
        "/profile_ref/resolved_at",
    ]
    validate_hash_profile(forged)  # still a well-formed manifest: that was never the guard
    with pytest.raises(HashProfileError):
        compute_content_hash(fixture["instance"], IMMUTABLE_VERSION, profile=forged)


def test_a_manifest_that_drops_a_released_included_pointer_is_rejected() -> None:
    fixture = vector("immutable-version-nested-pins")
    forged = derive_hash_profile(IMMUTABLE_VERSION)
    forged["included_pointers"] = [p for p in forged["included_pointers"] if p != "/created_by"]
    with pytest.raises(HashProfileError, match="drops released included pointers"):
        compute_content_hash(fixture["instance"], IMMUTABLE_VERSION, profile=forged)


def test_a_manifest_that_redeclares_a_released_array_is_rejected() -> None:
    """Re-declaring a released set-like array as ordered would make member order matter."""
    fixture = vector("immutable-version-nested-pins")
    forged = derive_hash_profile(IMMUTABLE_VERSION)
    forged["arrays"] = [
        {"pointer": "/pack_refs", "kind": "ordered"} if a["pointer"] == "/pack_refs" else a
        for a in forged["arrays"]
    ]
    with pytest.raises(HashProfileError, match="re-declares or drops the released array"):
        compute_content_hash(fixture["instance"], IMMUTABLE_VERSION, profile=forged)


def test_a_merged_domain_extension_is_still_accepted() -> None:
    """The check must reject contradictions without breaking the sanctioned extension path."""
    fixture = vector("ordered-array-preserves-order")
    profile = profile_for(fixture)
    validate_profile_against_schema(profile, fixture["schema_ref"])
    assert (
        compute_content_hash(fixture["instance"], fixture["schema_ref"], profile=profile)
        == fixture["expected_content_hash"]
    )


# ============================ one declaration per pointer, and no pointer on both sides ==


def test_two_array_declarations_for_one_pointer_are_rejected() -> None:
    """``uniqueItems`` cannot see this: the two entries differ in ``kind``, so they are
    distinct objects. The hash view keys arrays by pointer, so the last one silently won."""
    forged = derive_hash_profile(IMMUTABLE_VERSION)
    assert {"pointer": "/pack_refs", "kind": "ordered"} not in forged["arrays"]
    forged["arrays"] = [*forged["arrays"], {"pointer": "/pack_refs", "kind": "ordered"}]
    assert len(forged["arrays"]) == len({json.dumps(a, sort_keys=True) for a in forged["arrays"]})
    with pytest.raises(HashProfileError, match="one_array_declaration_per_pointer"):
        validate_hash_profile(forged)


def test_a_redeclared_array_can_no_longer_change_the_hash_by_reordering() -> None:
    fixture = vector("immutable-version-nested-pins")
    forged = derive_hash_profile(IMMUTABLE_VERSION)
    forged["arrays"] = [*forged["arrays"], {"pointer": "/pack_refs", "kind": "ordered"}]
    with pytest.raises(HashProfileError):
        compute_content_hash(fixture["instance"], IMMUTABLE_VERSION, profile=forged)


def test_a_pointer_may_not_be_both_included_and_excluded() -> None:
    forged = derive_hash_profile(IMMUTABLE_VERSION)
    excluded = forged["excluded_pointers"][0]["pointer"]
    forged["included_pointers"] = sorted({*forged["included_pointers"], excluded})
    with pytest.raises(HashProfileError, match="a_pointer_is_either_included_or_excluded"):
        validate_hash_profile(forged)


def test_two_exclusions_for_one_pointer_are_rejected() -> None:
    forged = derive_hash_profile(IMMUTABLE_VERSION)
    first = forged["excluded_pointers"][0]
    forged["excluded_pointers"] = [*forged["excluded_pointers"], {**first, "reason": "signature"}]
    with pytest.raises(HashProfileError, match="one_exclusion_per_pointer"):
        validate_hash_profile(forged)


@pytest.mark.parametrize("path", files(MANIFEST_DIR), ids=lambda p: p.stem)
def test_a_released_manifest_declares_each_pointer_once_and_on_one_side(path: Path) -> None:
    manifest = load(path)
    pointers = [entry["pointer"] for entry in manifest["arrays"]]
    assert len(pointers) == len(set(pointers))
    excluded = {entry["pointer"] for entry in manifest["excluded_pointers"]}
    assert len(excluded) == len(manifest["excluded_pointers"])
    assert excluded.isdisjoint(manifest["included_pointers"])
    assert excluded.isdisjoint(manifest["opaque_pointers"])


# ============================= an absent set order key is its own error, not a duplicate ==


def set_like_profile(order_key: list[str]) -> dict[str, Any]:
    """A minimal released-shaped manifest for a set-like array of objects."""
    return {
        **derive_hash_profile("urn:datacompany:stable-identity:1"),
        "included_pointers": ["/members", "/members/-", "/members/-/id", "/members/-/label"],
        "excluded_pointers": [],
        "opaque_pointers": [],
        "arrays": [{"pointer": "/members", "kind": "set", "order_key": order_key}],
    }


def test_an_absent_order_key_is_not_a_duplicate() -> None:
    """Two members that simply lack the order key are distinct valid data, not one member.

    Reachable for any domain extension whose order key is optional; the released pin order
    key happens to be four schema-required fields, which is why it never surfaced.
    """
    profile = set_like_profile(["/id"])
    members = {"members": [{"label": "one"}, {"label": "two"}]}
    with pytest.raises(MissingOrderKeyError, match="does not carry the released order-key"):
        build_hash_view(members, profile)


def test_a_partially_absent_composite_order_key_names_the_missing_path() -> None:
    profile = set_like_profile(["/id", "/label"])
    with pytest.raises(MissingOrderKeyError, match=r"\['/label'\]"):
        build_hash_view({"members": [{"id": "a"}]}, profile)


def test_explicit_null_order_keys_are_still_genuine_duplicates() -> None:
    """An explicit null is a real shared value, so this must stay a duplicate."""
    profile = set_like_profile(["/id"])
    members = {"members": [{"id": None, "label": "one"}, {"id": None, "label": "two"}]}
    with pytest.raises(DuplicateSetMemberError, match="share the canonical order key"):
        build_hash_view(members, profile)


def test_distinct_order_keys_sort_and_are_accepted() -> None:
    profile = set_like_profile(["/id"])
    view = build_hash_view({"members": [{"id": "b"}, {"id": "a"}]}, profile)
    assert [member["id"] for member in view["members"]] == ["a", "b"]


# ================ the schema boundary and the hash engine agree on what an integer is ===


def test_an_integral_double_hashes_as_the_integer_it_is() -> None:
    """JSON has one number type: ``2.0`` and ``2`` are the same value and the same bytes.

    Only Python's parser distinguishes them, so a schema-valid ``{"type": "integer"}`` member
    used to be accepted by the boundary and then rejected by the engine -- and a
    JSON-parsing peer language would have hashed it happily, breaking cross-language parity.
    """
    fixture = vector("immutable-version-nested-pins")
    as_float = json.loads(json.dumps(fixture["instance"]))
    as_float["version_number"] = float(as_float["version_number"])
    assert isinstance(as_float["version_number"], float)
    assert validate_instance(as_float, fixture["schema_ref"]) == []
    assert hash_of({**fixture, "instance": as_float}) == fixture["expected_content_hash"]
    assert canonical_json_bytes({"n": 2.0}) == canonical_json_bytes({"n": 2}) == b'{"n":2}'


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2.0, 2), (-0.0, 0), (float(2**53), 2**53), (0.1, None), (float(2**53) * 4, None)],
)
def test_stable_integer_admits_only_exactly_representable_integers(
    value: float, expected: int | None
) -> None:
    assert stable_integer(value) == expected


def test_a_non_integral_double_is_still_rejected_everywhere() -> None:
    fixture = vector("decimal-carried-as-string")
    instance = json.loads(json.dumps(fixture["instance"]))
    instance["value"]["measurement"] = 0.30000000000000004
    with pytest.raises(UnstableFloatError):
        compute_content_hash(instance, fixture["schema_ref"], profile=profile_for(fixture))
    with pytest.raises(UnstableFloatError):
        canonical_sha256({"measurement": 0.1})


def test_build_hash_view_guards_floats_itself_not_only_through_jcs() -> None:
    """Pins the hash-view float guard directly, so removing it is not an equivalent mutant.

    ``build_hash_view`` normalizes an integral double to a Python ``int`` and rejects an
    unstable one, both observable before any serialization happens.
    """
    profile = set_like_profile(["/id"])
    view = build_hash_view({"members": [{"id": "a", "label": 2.0}]}, profile)
    assert view["members"][0]["label"] == 2
    assert isinstance(view["members"][0]["label"], int)
    with pytest.raises(UnstableFloatError, match="binary_float_policy=reject"):
        build_hash_view({"members": [{"id": "a", "label": 0.1}]}, profile)


# ==================================== U+2028 / U+2029 are ordinary code points (M8) =====


def test_line_and_paragraph_separators_are_emitted_literally() -> None:
    """RFC 8785 escapes the seven short escapes plus ``\\u00xx`` for the remaining C0
    controls, and nothing else. Escaping U+2028/U+2029 -- which several JavaScript
    serializers do, because they are not valid inside an ES5 string literal -- produces
    different bytes and a different, wrong hash."""
    canonical = canonical_json_bytes({"a\u2028b": "x\u2029y"})
    assert canonical == '{"a\u2028b":"x\u2029y"}'.encode()
    assert b"\xe2\x80\xa8" in canonical
    assert b"\xe2\x80\xa9" in canonical
    assert b"\\u2028" not in canonical
    assert b"\\u2029" not in canonical


def test_the_separator_golden_vector_carries_them_in_a_key_and_in_a_value() -> None:
    fixture = vector("unicode-line-and-paragraph-separator")
    payload = fixture["instance"]["value"]
    assert any("\u2028" in name or "\u2029" in name for name in payload)
    assert any("\u2028" in value or "\u2029" in value for value in payload.values())
    canonical = fixture["expected_hash_view_canonical_json"]
    assert "\u2028" in canonical
    assert "\u2029" in canonical
    assert "\\u2028" not in canonical
    assert "\\u2029" not in canonical
    assert hash_of(fixture) == fixture["expected_content_hash"]


def test_escaping_the_separators_would_produce_a_different_hash() -> None:
    """States the failure explicitly, so a serializer that escapes them cannot pass."""
    literal = canonical_sha256({"k": "a\u2028b"})
    escaped = canonical_sha256({"k": "a\\u2028b"})
    assert literal != escaped


# =========================== a payload subtree is declared, or explicitly opaque, never ==
# =========================== hashed by default ==========================================


def test_an_explicitly_opaque_subtree_is_hashed_whole() -> None:
    fixture = vector("decimal-carried-as-string")
    profile = derive_hash_profile(fixture["schema_ref"])
    assert profile["opaque_pointers"] == ["/value"]
    assert hash_of(fixture) == fixture["expected_content_hash"]


def test_an_object_that_is_neither_declared_nor_opaque_is_not_hashed_by_default() -> None:
    """Silence used to mean "hash the whole subtree undeclared", which failed open for
    every domain that shipped no profile extensions at all."""
    fixture = vector("decimal-carried-as-string")
    undeclared = {**derive_hash_profile(fixture["schema_ref"]), "opaque_pointers": []}
    with pytest.raises(UndeclaredPathError, match="neither this object's members nor"):
        build_hash_view(fixture["instance"], undeclared)


def test_declaring_one_payload_member_still_forces_every_sibling_to_be_declared() -> None:
    """Declare none or declare all: a partial declaration is the loud half of the rule."""
    fixture = vector("decimal-carried-as-string")
    partial = merge_profile_extensions(
        derive_hash_profile(fixture["schema_ref"]), {"included_pointers": ["/value/note"]}
    )
    with pytest.raises(UndeclaredPathError, match="/value/measurement"):
        build_hash_view(fixture["instance"], partial)


def test_an_array_inside_an_opaque_subtree_still_needs_its_collection_kind() -> None:
    """Opacity is about member declaration, never about RFC 8785 array-order ambiguity."""
    fixture = vector("decimal-carried-as-string")
    instance = json.loads(json.dumps(fixture["instance"]))
    instance["value"] = {"steps": ["a", "b"]}
    profile = derive_hash_profile(fixture["schema_ref"])
    assert profile["opaque_pointers"] == ["/value"]
    with pytest.raises(UndeclaredArrayError):
        build_hash_view(instance, profile)


def test_an_arrays_only_extension_declares_a_collection_inside_an_opaque_subtree() -> None:
    """The green half of the rule above, and the one nobody had written down.

    Neither prefix set is built from ``arrays``: ``_declared_prefixes`` is built from
    ``included_pointers | excluded_pointers`` and ``_included_prefixes`` -- the one the
    OPACITY decision consults -- from ``included_pointers`` alone. An ``arrays``-only
    extension therefore declares the collection kind *without* adding a declared child, so
    the subtree stays opaque and its undeclared members still pass. (The falsification
    recipe recorded for D4 named ``_declared_prefixes``; since the opaque/exclusion defect
    was closed it is ``_included_prefixes`` that has to be patched to turn this red. See the
    precision note on D4 in ``config/foundation-decisions.json``.) The
    two rules the envelope's own ``$comment`` states -- "declare one member, declare them
    all" and "arrays inside it still require their own declaration" -- are independent, and
    satisfying the second does not trigger the first.

    Without this test, three red-half assertions across two languages said an array under
    an opaque subtree needs a declaration and none said one could be supplied. That gap is
    what got recorded in the wave-2 register as D4, "an opaque subtree containing an array
    is unhashable" -- a capability gap that does not exist.
    """
    fixture = vector("decimal-carried-as-string")
    instance = json.loads(json.dumps(fixture["instance"]))
    instance["value"] = {"steps": ["b", "a"], "note": "undeclared, and still opaque"}
    profile = merge_profile_extensions(
        derive_hash_profile(fixture["schema_ref"]),
        {"arrays": [{"pointer": "/value/steps", "kind": "ordered"}]},
    )
    assert profile["opaque_pointers"] == ["/value"]
    assert "/value/steps" not in profile["included_pointers"]
    assert build_hash_view(instance, profile)["value"] == instance["value"]


def test_an_opaque_payload_that_is_itself_an_array_is_declarable() -> None:
    """``bitemporal-assertion`` types ``/value`` as ``object|array|...``, so the opaque
    payload may *be* the array rather than contain one. Same arrays-only extension, same
    outcome: the pointer of the declaration is the payload root."""
    fixture = vector("decimal-carried-as-string")
    instance = json.loads(json.dumps(fixture["instance"]))
    instance["value"] = ["b", "a"]
    profile = merge_profile_extensions(
        derive_hash_profile(fixture["schema_ref"]),
        {"arrays": [{"pointer": "/value", "kind": "ordered"}]},
    )
    assert build_hash_view(instance, profile)["value"] == ["b", "a"]


def test_a_domain_extension_may_not_invent_an_opaque_subtree() -> None:
    """Opacity is a property of the released envelope, exactly like an exclusion."""
    base = derive_hash_profile(BITEMPORAL_ASSERTION)
    with pytest.raises(HashProfileError, match="may only add included_pointers and arrays"):
        merge_profile_extensions(base, {"opaque_pointers": ["/subject_ref"]})


def test_derived_profile_declares_the_released_serialization_rules() -> None:
    profile = derive_hash_profile("urn:datacompany:immutable-version:1")
    assert profile["serialization"] == "rfc8785"
    assert profile["encoding"] == "utf-8"
    assert profile["byte_order_mark"] is False
    assert profile["digest_algorithm"] == "sha256"
    assert profile["absent_vs_null"] == "distinct"
    assert profile["unicode_normalization"] == "none"
    assert profile["timestamp_representation"] == "rfc3339_utc_z"
    assert profile["decimal_representation"] == "decimal_string"
    assert profile["binary_float_policy"] == "reject"


# ===================================== two guards that could not fire (D4, D7) ==
#
# Both were stated correctly in prose and enforced nowhere.
#
#  * `validate_profile_against_schema` built the expected manifest with
#    `derive_hash_profile(schema_ref, profile_version=profile["profile_version"])` -- the
#    expected value was constructed FROM the value under test, so the agreement loop over
#    `profile_version` was unfalsifiable. `EXTENSIONS.md` §5.2 prescribes "change both
#    together with a `profile_version` bump" as the remedy for the inconsistent exclusion
#    cascade, and that bump was enforced in neither direction.
#  * `validate_hash_profile` ended with a bare `schema_registry()` under a comment claiming
#    it made "a manifest referencing an unreleased schema fail here". It takes no argument,
#    never reads `profile["schema_ref"]`, and discards what it builds.


PINNED_VERSION_REF = "urn:datacompany:pinned-version-ref:1"
UNRELEASED_SCHEMA_REF = "urn:datacompany:definitely-not-released:1"


def test_a_manifest_that_bumps_its_profile_version_unilaterally_is_rejected() -> None:
    """The reproduction: a released derivation with `profile_version` overwritten.

    This was ACCEPTED. The expected manifest was derived using the supplied number, so the
    two always agreed however absurd the number was.
    """
    forged = derive_hash_profile(PINNED_VERSION_REF)
    forged["profile_version"] = 99999
    with pytest.raises(HashProfileError, match="declares profile_version 99999"):
        validate_profile_against_schema(forged, PINNED_VERSION_REF)


@pytest.mark.parametrize("version", [1, 3, 7, 99999])
def test_no_profile_version_other_than_the_implemented_one_is_verifiable(version: int) -> None:
    """`profile_version` names the rule set that produced the manifest.

    Parametrised across plausible bumps as well as an absurd one, because a check that only
    rejects 99999 would still let a quiet neighbour through.

    **`1` is the important one and is why this list moved.** It read `[2, 7, 99999]` while
    the engine implemented version 1, on the reasoning that "`2` is the value a real
    unilateral change to the exclusion cascade would write". That change then happened --
    `DERIVATION_PROFILE_VERSION` moved 1 -> 2 on 2026-08-04 when §5.2's cascade was fixed --
    and the old list's most load-bearing case became the IMPLEMENTED version, i.e. a case
    that could no longer fail. The value a stale manifest now carries is `1`: every committed
    manifest declared it until that commit, so a consumer replaying an old one must be
    refused, not silently verified against rules that no longer produced it. The list is
    therefore the implemented version's two neighbours plus the absurd cases, and it has to
    be re-centred on every bump for exactly the reason this note exists.
    """
    forged = derive_hash_profile(PINNED_VERSION_REF)
    forged["profile_version"] = version
    with pytest.raises(HashProfileError, match="this engine implements derivation profile"):
        validate_profile_against_schema(forged, PINNED_VERSION_REF)


def test_the_derived_profile_version_is_the_pinned_constant() -> None:
    """The deriver may not stamp a version whose rules it does not implement.

    `derive_hash_profile` used to take `profile_version=`, so it could mint a manifest that
    `validate_profile_against_schema` was then obliged to reject. The knob is gone.
    """
    import inspect

    from research_contracts.canonical.hash_profile import DERIVATION_PROFILE_VERSION

    assert "profile_version" not in inspect.signature(derive_hash_profile).parameters
    for schema_ref in (PINNED_VERSION_REF, IMMUTABLE_VERSION, BITEMPORAL_ASSERTION):
        assert derive_hash_profile(schema_ref)["profile_version"] == DERIVATION_PROFILE_VERSION


def test_every_released_manifest_declares_the_implemented_profile_version() -> None:
    """The other half of the pin, and what makes a bump a reviewable two-sided edit.

    Bumping `DERIVATION_PROFILE_VERSION` without moving the committed manifests is red here,
    which is the enforcement `EXTENSIONS.md` §5.2 asks for and prose could not provide.
    """
    from research_contracts.canonical.hash_profile import DERIVATION_PROFILE_VERSION

    paths = files(MANIFEST_DIR)
    assert paths, "no released manifests found; an empty enumeration is not a clean one"
    for path in paths:
        assert load(path)["profile_version"] == DERIVATION_PROFILE_VERSION, path


def test_a_manifest_naming_an_unreleased_schema_is_rejected() -> None:
    """The reproduction for D7, through the public API `canonical/__init__` exports."""
    forged = derive_hash_profile(PINNED_VERSION_REF)
    forged["schema_ref"] = UNRELEASED_SCHEMA_REF
    with pytest.raises(HashProfileError, match="which is not a released schema"):
        validate_hash_profile(forged)


def test_an_unreleased_schema_ref_fails_in_the_manifest_not_in_the_hash_view() -> None:
    """The guard's stated purpose: fail HERE, not later and unrecognisably.

    The message has to name the manifest and the ref, because the fault a caller actually
    has is "this manifest is for a schema nobody released", not "cannot resolve pointer".
    """
    forged = derive_hash_profile(PINNED_VERSION_REF)
    forged["schema_ref"] = UNRELEASED_SCHEMA_REF
    with pytest.raises(HashProfileError) as raised:
        validate_hash_profile(forged)
    assert UNRELEASED_SCHEMA_REF in str(raised.value)
    assert "hash-view manifest" in str(raised.value)


def test_a_merged_extension_of_an_unreleased_schema_is_also_rejected() -> None:
    """`merge_profile_extensions` revalidates, so the second entry point is closed too."""
    forged = derive_hash_profile(PINNED_VERSION_REF)
    forged["schema_ref"] = UNRELEASED_SCHEMA_REF
    with pytest.raises(HashProfileError, match="which is not a released schema"):
        merge_profile_extensions(forged, {"included_pointers": ["/whatever"]})


@pytest.mark.parametrize("path", files(MANIFEST_DIR), ids=lambda p: p.stem)
def test_a_released_manifest_still_passes_both_new_guards(path: Path) -> None:
    """The false-positive control for the six probes above.

    Every committed manifest must survive the version pin and the registry check unchanged;
    a "fix" that rejected everything would satisfy every probe and ship a dead engine.
    """
    manifest = load(path)
    validate_hash_profile(manifest)
    validate_profile_against_schema(manifest, manifest["schema_ref"])


# ========== the §5.2 exclusion cascade, and the §6.4 composition point (2026-08-04) ==
#
# Two decisions taken together, and the reason they land in one place is `profile_version`.
# §5.2 recorded the `arrays` exact-match cascade as "STILL OPEN ... reproduce the quirk, or
# change both together with a `profile_version` bump"; the bump is what makes the second
# option a single reviewable change, and `DERIVATION_PROFILE_VERSION` is pinned in code so it
# cannot be a quiet one. §6.4 recorded `x-datacompany-composition-point` as "read by no code" and
# asked for a decision; it was implemented.
#
# Both are exercised against SYNTHETIC probes, never against the corpus. Neither change moves
# a single committed byte -- measured, with a positive control -- so a corpus assertion would
# be green before and after and could falsify nothing.

CASCADE_PROBE = "urn:datacompany:exclusion-cascade-probe:1"
COMPOSITION_PROBE = "urn:datacompany:composition-point-probe:1"


@pytest.fixture
def register_probe(monkeypatch: pytest.MonkeyPatch):
    """Register a synthetic schema in the real registry -- the established probe pattern.

    ``registry.canonical_schemas`` is patched as an ATTRIBUTE rather than as an imported
    binding, because ``hash_profile`` resolves through ``resolve_pointer`` at call time and a
    module-level import would keep answering from the unpatched object.
    """
    from research_contracts.canonical import registry as registry_module

    def _register(*schemas: dict[str, Any]) -> None:
        merged = {
            **registry_module.canonical_schemas(),
            **{schema["$id"]: schema for schema in schemas},
        }
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: merged)

    return _register


def _cascade_probe(**extra: Any) -> dict[str, Any]:
    """An excluded subtree containing an array, plus a survivor that proves non-vacuity."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CASCADE_PROBE,
        "type": "object",
        "properties": {
            "kept": {"type": "string"},
            # The array OUTSIDE the exclusion. Without it a filter that dropped every array
            # would pass the assertions below, which is the shape of a guard that cannot be
            # falsified from the green side.
            "survivor": {
                "type": "array",
                "items": {"type": "string"},
                "x-datacompany-array": {"kind": "ordered"},
            },
            "sig": {
                "type": "object",
                "x-datacompany-hash-excluded": True,
                "x-datacompany-hash-exclusion-reason": "signature",
                "properties": {
                    # STRICTLY under the exclusion, never AT it: an exact-match filter cannot
                    # see this one, which is the whole quirk.
                    "parts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "x-datacompany-array": {"kind": "ordered"},
                    },
                    "blob": {"type": "object", "x-datacompany-hash-opaque": True},
                },
            },
            **extra,
        },
    }


def test_an_array_nested_under_an_exclusion_is_dropped_from_the_manifest(register_probe) -> None:
    """§5.2, closed 2026-08-04: `arrays` cascades by PREFIX like the other two members.

    This is the section's own worked example, made executable. `arrays` was filtered by EXACT
    match while `included_pointers` and `opaque_pointers` were filtered by prefix, so
    excluding `/sig` dropped `/sig/parts` from `included_pointers` and `/sig/blob` from
    `opaque_pointers` and LEFT `{"pointer": "/sig/parts", "kind": "ordered"}` in `arrays`. The
    entry was inert -- the excluded subtree is never visited -- but
    `validate_profile_against_schema` compares `arrays` exactly, so a port that filtered all
    three consistently rejected every manifest this engine produced, and §9 item 6 had to
    order every port to reproduce the quirk.

    Synthetic, deliberately. No committed schema declares an array at or under an exclusion,
    so the fix moves zero committed bytes and a corpus assertion could not tell the two rules
    apart. `/survivor` is the non-vacuity half: a filter that dropped every array would
    satisfy the `/sig/parts` assertion alone.
    """
    register_probe(_cascade_probe())
    profile = derive_hash_profile(CASCADE_PROBE)

    assert [entry["pointer"] for entry in profile["arrays"]] == ["/survivor"]
    # ...and the two members that ALREADY cascaded by prefix still do, so this test measures
    # the change rather than a rewrite of the whole cascade.
    assert profile["included_pointers"] == ["/kept", "/survivor"]
    assert profile["opaque_pointers"] == []
    assert [entry["pointer"] for entry in profile["excluded_pointers"]] == ["/sig"]


def test_an_array_exactly_at_an_exclusion_is_still_dropped(register_probe) -> None:
    """The half that always worked, kept so a regression cannot hide behind the new half.

    An exact-match filter and a prefix filter agree here. Asserting only the nested case
    would leave the engine free to lose the exact case entirely.
    """
    register_probe(
        _cascade_probe(
            at={
                "type": "array",
                "items": {"type": "string"},
                "x-datacompany-hash-excluded": True,
                "x-datacompany-hash-exclusion-reason": "signature",
                "x-datacompany-array": {"kind": "ordered"},
            }
        )
    )
    profile = derive_hash_profile(CASCADE_PROBE)
    assert [entry["pointer"] for entry in profile["arrays"]] == ["/survivor"]
    assert [entry["pointer"] for entry in profile["excluded_pointers"]] == ["/at", "/sig"]


def _composition_probe(point: Any = ..., **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": COMPOSITION_PROBE,
        "type": "object",
        "$defs": {"domain_extension": {"type": "object"}},
        "properties": {"payload": {"type": "object", "x-datacompany-hash-opaque": True}},
        **extra,
    }
    if point is not ...:
        body["x-datacompany-composition-point"] = point
    return body


def test_an_envelope_declaring_no_composition_point_is_not_extensible(register_probe) -> None:
    """§6.4, implemented 2026-08-04: `merge_profile_extensions` is bound to the annotation.

    It implemented the composition-point CONCEPT -- a domain may add `included_pointers` and
    `arrays` and nothing else -- while being driven entirely by its `extensions` argument and
    never consulting this member, so every released schema was extensible in practice whether
    or not it said so. Twelve of the eighteen released schemas declare no composition point;
    they are non-extensible now, and this is that rule.
    """
    register_probe(_composition_probe(point=...))
    base = derive_hash_profile(COMPOSITION_PROBE)
    with pytest.raises(HashProfileError, match="declares no x-datacompany-composition-point"):
        merge_profile_extensions(base, {"arrays": [{"pointer": "/payload", "kind": "ordered"}]})


def test_an_envelope_declaring_a_composition_point_is_still_extensible(register_probe) -> None:
    """The GREEN half, and the control without which the refusal above proves nothing.

    A gate that refused every extension would satisfy the previous test and would break the
    §9 item 11 arrays-only route that refuted D4. The two probes differ by exactly the
    annotation.
    """
    register_probe(_composition_probe(point="#/$defs/domain_extension"))
    base = derive_hash_profile(COMPOSITION_PROBE)
    merged = merge_profile_extensions(
        base, {"arrays": [{"pointer": "/payload", "kind": "ordered"}]}
    )
    assert [entry["pointer"] for entry in merged["arrays"]] == ["/payload"]
    # The extension really was the only difference: nothing else about the manifest moved.
    assert merged["included_pointers"] == base["included_pointers"]
    assert merged["opaque_pointers"] == base["opaque_pointers"]


def test_a_composition_point_that_resolves_to_nothing_is_refused_at_merge(
    register_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The merge route re-checks resolvability rather than trusting derivation, and can fire.

    `merge_profile_extensions` is public API over ANY well-formed `canonical-hash-profile.v1`
    manifest -- nothing obliges the caller to have produced it with `derive_hash_profile`. So
    a schema whose composition point names a `$defs` entry that does not exist would be
    extensible through this route while being underivable through the other, which is exactly
    the two-entry-point asymmetry D7 was about. One helper, one message, both routes.

    Reaching it needs a manifest for a schema that derives cleanly and a schema that does
    not, which is what the two `register_probe` calls construct: the manifest is derived
    against the sound schema, then the registry answer for the same `$id` is swapped for the
    broken one. That is not a contrived shape -- it is a committed manifest replayed after
    its schema was edited, which is the ordinary way the two drift apart.
    """
    from research_contracts.canonical import registry as registry_module

    register_probe(_composition_probe(point="#/$defs/domain_extension"))
    base = derive_hash_profile(COMPOSITION_PROBE)

    broken = _composition_probe(point="#/$defs/domian_extension")
    merged = {**registry_module.canonical_schemas(), COMPOSITION_PROBE: broken}
    monkeypatch.setattr(registry_module, "canonical_schemas", lambda: merged)

    with pytest.raises(HashProfileError, match="resolves to no \\$defs entry"):
        merge_profile_extensions(base, {"arrays": [{"pointer": "/payload", "kind": "ordered"}]})
    # ...and the same schema is underivable, which is what makes the two routes agree.
    with pytest.raises(HashProfileError, match="resolves to no \\$defs entry"):
        derive_hash_profile(COMPOSITION_PROBE)


def test_a_composition_point_is_resolved_against_its_own_document(register_probe) -> None:
    """`base_id`, not the entry schema, and the distinction is load-bearing.

    The derivation walk crosses documents through `$ref`, and `#/$defs/...` is relative to
    the document the NODE belongs to. Resolving against the entry schema instead would
    diagnose the wrong document: here the referenced envelope's `domain_extension` exists in
    the referenced document and NOT in the entry one, so an entry-relative resolution reports
    a sound schema as broken.
    """
    referenced = _composition_probe(point="#/$defs/domain_extension")
    entry = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:datacompany:composition-point-entry-probe:1",
        "type": "object",
        # Deliberately NO `$defs/domain_extension` here.
        "properties": {"wrapped": {"$ref": f"{COMPOSITION_PROBE}#"}},
    }
    register_probe(referenced, entry)
    profile = derive_hash_profile("urn:datacompany:composition-point-entry-probe:1")
    assert "/wrapped" in profile["included_pointers"]


def test_an_explicit_null_composition_point_is_malformed_not_absent(register_probe) -> None:
    """PRESENCE, not a null-valued read -- and the distinction is a two-route property.

    Both engines test `"x-datacompany-composition-point" not in schema` rather than
    `.get(...) is None`. Nothing asserted that until now: an independent refuter mutated
    Python to `.get(...) is None` and TypeScript to `=== undefined` and BOTH suites stayed
    fully green, the only survivor of 23 mutations. The behaviour was already correct; it
    was simply unmeasured, which is the same thing as unowned.

    What the mutation reintroduces is the asymmetry D7 is about. A schema whose point is an
    explicit `null` is DECLARED and BROKEN, and derivation says exactly that. Under the
    mutation the merge route instead reports it as no declaration at all, so the two entry
    points describe one schema in two contradictory ways -- and the one that says "declare a
    composition point" is advising an author to add something already there.
    """
    register_probe(_composition_probe(point=None))

    with pytest.raises(HashProfileError) as derived:
        derive_hash_profile(COMPOSITION_PROBE)
    assert "declares x-datacompany-composition-point as null" in str(derived.value)

    # The manifest cannot be derived from the broken schema, so it is derived from the sound
    # one and replayed against the broken registry -- a committed manifest whose schema was
    # edited afterwards, which is the ordinary way the two drift apart.
    register_probe(_composition_probe(point="#/$defs/domain_extension"))
    base = derive_hash_profile(COMPOSITION_PROBE)
    register_probe(_composition_probe(point=None))

    with pytest.raises(HashProfileError) as merged:
        merge_profile_extensions(base, {"arrays": [{"pointer": "/payload", "kind": "ordered"}]})
    # THE SAME diagnosis as derivation, not "declares none": one schema, one story.
    assert "declares x-datacompany-composition-point as null" in str(merged.value)
    assert "declares no x-datacompany-composition-point" not in str(merged.value)


def test_a_composition_point_declared_at_depth_is_refused_with_a_message_that_is_true(
    register_probe,
) -> None:
    """The refusal names the ROOT, because the annotation is legal at any depth.

    `_require_released_annotations` shape-checks and RESOLVES a composition point wherever
    the walk reaches it, so a schema declaring a valid one on a nested node derives cleanly
    -- and was then told it "declares no x-datacompany-composition-point", which is false about
    that schema. Root-only is still the rule; the message now says so and names where the
    declaration actually is.
    """
    nested = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": COMPOSITION_PROBE,
        "type": "object",
        "$defs": {"domain_extension": {"type": "object"}},
        "properties": {
            "payload": {
                "type": "object",
                "x-datacompany-hash-opaque": True,
                "x-datacompany-composition-point": "#/$defs/domain_extension",
            }
        },
    }
    register_probe(nested)
    # Non-vacuity: the nested declaration really is validated rather than ignored.
    derive_hash_profile(COMPOSITION_PROBE)

    with pytest.raises(HashProfileError) as raised:
        merge_profile_extensions(
            derive_hash_profile(COMPOSITION_PROBE),
            {"arrays": [{"pointer": "/payload", "kind": "ordered"}]},
        )
    message = str(raised.value)
    assert "at its document ROOT" in message
    assert '"/payload"' in message, message


def test_composing_an_extensible_envelope_does_not_make_the_composer_extensible(
    register_probe,
) -> None:
    """F4: the blast radius reaches CONSUMER schemas, not only the twelve released ones.

    A domain schema written as `allOf: [{"$ref": <envelope>}]` reaches the envelope's
    composition point at pointer `""`, because `allOf`/`$ref` do not advance the pointer --
    but the point is not a member of the composing document, so the composer is
    non-extensible until it declares its own. That is a new authoring requirement for every
    consumer using the §9 item 11 / D9 arrays-only runtime route, and this pins both the
    requirement and the diagnostic that states it.

    Root-only rather than "anywhere at pointer ``''``" is a decision, and this shape is why
    the alternative was rejected: `run-manifest:1` composes `stable-identity:1`, so TWO
    points arrive at `""` there and which one governs is undecided.
    """
    composer = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:datacompany:composition-point-composer-probe:1",
        "type": "object",
        "allOf": [{"$ref": COMPOSITION_PROBE}],
    }
    register_probe(_composition_probe(point="#/$defs/domain_extension"), composer)
    base = derive_hash_profile("urn:datacompany:composition-point-composer-probe:1")

    with pytest.raises(HashProfileError) as raised:
        merge_profile_extensions(base, {"arrays": [{"pointer": "/payload", "kind": "ordered"}]})
    message = str(raised.value)
    assert "at its document ROOT" in message
    # ...and the clause that makes it actionable rather than merely true: the walk DID reach
    # one, at the root pointer, through composition.
    assert '""' in message, message
    assert "must declare its OWN" in message

    # The GREEN half: declaring its own point makes the composer extensible.
    composer_with_point = {
        **composer,
        "$defs": {"domain_extension": {"type": "object"}},
        "x-datacompany-composition-point": "#/$defs/domain_extension",
    }
    register_probe(_composition_probe(point="#/$defs/domain_extension"), composer_with_point)
    merged = merge_profile_extensions(
        derive_hash_profile("urn:datacompany:composition-point-composer-probe:1"),
        {"arrays": [{"pointer": "/payload", "kind": "ordered"}]},
    )
    assert [entry["pointer"] for entry in merged["arrays"]] == ["/payload"]

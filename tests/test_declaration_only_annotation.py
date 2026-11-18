"""D9 CLOSED: an array inside an opaque subtree is declarable from a committed schema.

``x-datacompany-hash-declaration-only`` (vocabulary 1.2) says: *this schema node is reached only
to carry annotations; it does not declare a hashed path.* The node is still walked and its
``x-datacompany-array`` still reaches the manifest; what the flag removes is the node's own
pointer, and every pointer beneath it, from ``included_pointers``.

That closes a defect two RELEASED statements made unavoidable:

* ``schemas/canonical/bitemporal-assertion.v1.schema.json`` `/value` ``$comment`` --
  "Arrays inside it still require their own ordered/set-like declaration."
* ``schemas/canonical/canonical-hash-profile.v1.schema.json`` ``arrays`` ``$comment`` --
  "An array that is not declared here has undeclared collection semantics and is rejected,
  **including inside an opaque subtree**."

Both were unsatisfiable from any committed schema. Reaching ``/value/tags`` needed a
``properties`` chain, ``_Walker`` put every ``properties`` name into ``included_pointers``, a
declared child revoked the subtree's opacity, and hashing the payload then raised
``UndeclaredPathError`` on the first undeclared sibling. The only route that worked was a
runtime ``merge_profile_extensions`` call -- which ``research_contracts#16`` used to refute
D4, making the escape hatch load-bearing evidence for a closed defect.

**The closure is the equality**, not the capability: the schema route must derive a manifest
byte-identical to the runtime route's merged one. Without that, the two routes still
disagree and D9 is only relocated.

Every test here was mutation-proven: the guard it names was broken, the test was confirmed
RED, and the break reverted. The mutations are listed in the commit body.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import (
    build_hash_view,
    canonical_json_bytes,
    canonical_sha256,
    derive_hash_profile,
    merge_profile_extensions,
)
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical.errors import HashProfileError
from research_contracts.canonical.hash_profile import DERIVATION_PROFILE_VERSION
from research_contracts.canonical.hash_view import UndeclaredPathError
from research_contracts.canonical.registry import canonical_schemas

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "canonical-hash" / "v1" / "declaration-only"
TS_HASH_PROFILE = ROOT / "packages" / "typescript" / "src" / "hashProfile.ts"

ANNOTATION = "x-datacompany-hash-declaration-only"

#: Equality pin over the committed fixture suite. A floor lets a fixture vanish unnoticed;
#: this suite is small enough that an equality costs nothing and is the only shape that
#: makes a deletion loud. Mirrored in
#: ``packages/typescript/test/declarationOnly.test.ts``.
EXPECTED_FIXTURES = 9

PROBE_ID = "urn:datacompany:declaration-only-unit-probe:1"

#: The RFC 8785 bytes both engines must produce for a merged `arrays` list holding one
#: fullwidth (U+FF21, one UTF-16 unit) and one astral (U+1F600, a surrogate pair) pointer.
#: Code-point order puts U+FF21 first; UTF-16 order would put U+1F600 first. Asserted as a
#: LITERAL in both suites so neither engine can agree with its own recomputation.
ASTRAL_ARRAYS_CANONICAL = (
    '[{"kind":"ordered","pointer":"/\uff21"},{"kind":"ordered","pointer":"/\U0001f600"}]'
)


def fixture_files() -> list[Path]:
    """Every committed declaration-only fixture, refusing to return an empty list.

    ``Path.glob`` over a missing or emptied directory returns ``[]`` in silence, and a suite
    parametrised over ``[]`` reports zero failures as health. That is defect B1's shape and
    it is refused here rather than left to the equality pin alone, because the pin lives in
    a test that a collection error would prevent from ever running.
    """
    found = sorted(FIXTURE_DIR.glob("*.json"))
    if not found:  # pragma: no cover - the guard exists so this branch never runs
        raise AssertionError(f"{FIXTURE_DIR}: no declaration-only fixtures found")
    return found


FIXTURES = fixture_files()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def register(monkeypatch: pytest.MonkeyPatch):
    """Register synthetic schemas in the real registry, the established probe pattern.

    ``hash_profile._require_released_schema_ref`` resolves through ``resolve_pointer``, the
    same call the deriver uses, precisely so a probe registered this way is visible to both.
    Patching ``registry_module.canonical_schemas`` -- the attribute, not an imported binding
    -- is what makes that work.
    """

    def _register(*schemas: dict[str, Any]) -> None:
        merged = {**canonical_schemas(), **{schema["$id"]: schema for schema in schemas}}
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: merged)

    return _register


#: What makes a probe schema an EXTENSIBLE envelope, spread into every probe whose test
#: drives the RUNTIME route (``merge_profile_extensions`` with an arrays-only extension).
#:
#: Since 2026-08-04 that route is gated on ``x-datacompany-composition-point``
#: (``EXTENSIONS.md`` §6.4): an envelope that declares none is non-extensible, so a probe
#: standing in for an extensible envelope has to say so. Defined once rather than per probe
#: because the D9 closure is a BYTE EQUALITY between the schema route and the runtime route,
#: and two probes that differ in anything but the flag under test make that equality
#: measure something else.
EXTENSIBLE_ENVELOPE: dict[str, Any] = {
    "x-datacompany-composition-point": "#/$defs/domain_extension",
    "$defs": {
        "domain_extension": {
            "$comment": "Declared composition point for the probe's runtime route.",
            "type": "object",
        }
    },
}


def opaque_probe(value_properties: dict[str, Any] | None = None, **root: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"type": "object", "x-datacompany-hash-opaque": True}
    if value_properties is not None:
        value["properties"] = value_properties
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROBE_ID,
        "type": "object",
        **EXTENSIBLE_ENVELOPE,
        "properties": {"id": {"type": "string"}, "value": value, **root},
    }


ORDERED_TAGS: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string"},
    ANNOTATION: True,
    "x-datacompany-array": {"kind": "ordered"},
}


# ============================================================ 1. the committed fixtures ===


def test_the_fixture_suite_is_pinned_as_an_equality() -> None:
    """A deleted fixture must be as loud as a wrong one."""
    assert len(FIXTURES) == EXPECTED_FIXTURES, [path.name for path in FIXTURES]


def test_the_evidence_the_register_cites_is_actually_in_the_fixtures() -> None:
    """B3, found by an independent refuter. The replay was guarded, so the evidence was not.

    ``test_every_fixture_replays_against_the_engine`` reads
    ``fixture.get("equivalent_runtime_route")`` and ``fixture.get("also_derived_from", [])``.
    Both are OPTIONAL, so deleting the runtime route from every ``derives`` fixture -- the
    thing the register calls "the closure, committed as data" -- left the suite at the same
    passing count in BOTH engines. The same shape held for ``also_derived_from``.

    A conditional assertion is not a pin; what makes it one is a floor on how many fixtures
    must carry the member at all. Mirrored in the TypeScript suite.
    """
    fixtures = [load(path) for path in FIXTURES]
    derives = [f for f in fixtures if f["expect"] == "derives"]
    assert len(derives) == 4, [f["fixture_id"] for f in derives]

    with_runtime = [f for f in derives if f.get("equivalent_runtime_route")]
    assert len(with_runtime) == len(derives), (
        "every `derives` fixture must carry the runtime route it is byte-identical to; "
        f"missing on {[f['fixture_id'] for f in derives if not f.get('equivalent_runtime_route')]}"
    )
    for fixture in with_runtime:
        route = fixture["equivalent_runtime_route"]
        assert route["schema"]["$id"] == fixture["probe_schema"]["$id"], fixture["fixture_id"]
        assert route["extensions"].get("arrays"), fixture["fixture_id"]

    alternatives = sum(len(f.get("also_derived_from", [])) for f in derives)
    assert alternatives >= 3, alternatives

    rejects = [f for f in fixtures if f["expect"] == "rejects"]
    assert len(rejects) == 5, [f["fixture_id"] for f in rejects]
    for fixture in rejects:
        assert fixture.get("expected_error"), fixture["fixture_id"]
        assert fixture.get("expected_message_contains"), fixture["fixture_id"]

    # B2: at least one rejection message must be NON-ASCII, or the cross-language rendering
    # parity both engines assert in prose is untested in the only dimension it can break.
    non_ascii = [f for f in rejects if not f["expected_message_contains"].isascii()]
    assert non_ascii, "no fixture exercises non-ASCII message rendering"


def test_both_fixture_kinds_are_present() -> None:
    """Non-vacuity in the dimension that actually rots.

    A suite of five ``rejects`` fixtures would prove the guard fires and say nothing about
    the capability; five ``derives`` fixtures would prove the capability and leave the guard
    unfalsified. Both halves are required to exist.
    """
    kinds = [load(path)["expect"] for path in FIXTURES]
    assert kinds.count("derives") >= 4, kinds
    assert kinds.count("rejects") >= 5, kinds


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_every_fixture_replays_against_the_engine(path: Path, register) -> None:
    """The committed corpus IS the oracle a port replays.

    Each ``derives`` fixture pins four independent things, because each fails differently:
    the derived manifest, the hash view's canonical bytes, its digest, and -- the D9 closure
    -- that the runtime route produces the byte-identical manifest.
    """
    fixture = load(path)
    schema = fixture["probe_schema"]
    register(schema)

    if fixture["expect"] == "rejects":
        with pytest.raises(HashProfileError) as raised:
            derive_hash_profile(schema["$id"])
        assert type(raised.value).__name__ == fixture["expected_error"]
        assert fixture["expected_message_contains"] in str(raised.value), str(raised.value)
        return

    manifest = derive_hash_profile(schema["$id"])
    # Byte-exact, not structural: the fixture commits the manifest's RFC 8785 bytes so a
    # port compares the one representation both languages must agree on. (It also keeps a
    # probe URN out of the `schema_ref` sweep in `tests/test_schema_ref_resolution.py`,
    # which would otherwise demand a deferred OWNER for a document nobody owes.)
    expected_manifest = json.loads(fixture["expected_manifest_canonical_json"])
    assert (
        canonical_json_bytes(manifest).decode("utf-8")
        == (fixture["expected_manifest_canonical_json"])
    )

    view = build_hash_view(fixture["instance"], manifest)
    assert (
        canonical_json_bytes(view).decode("utf-8") == (fixture["expected_hash_view_canonical_json"])
    )
    assert canonical_sha256(view) == fixture["expected_content_hash"]

    for alternative in fixture.get("also_derived_from", []):
        register(alternative)
        assert derive_hash_profile(alternative["$id"]) == expected_manifest, (
            "the same declaration reached through a different composition derived a "
            "different manifest"
        )
        register(schema)

    runtime = fixture.get("equivalent_runtime_route")
    if runtime is not None:
        register(runtime["schema"])
        merged = merge_profile_extensions(
            derive_hash_profile(runtime["schema"]["$id"]), runtime["extensions"]
        )
        assert canonical_json_bytes(merged) == canonical_json_bytes(expected_manifest), (
            "D9 is NOT closed: the schema route and the runtime route derive different "
            "manifests for the same declaration"
        )


# ================================================ 2. the closure, against a RELEASED schema ==


def test_the_two_routes_agree_byte_for_byte_on_the_released_opaque_subtree(register) -> None:
    """**This equality IS the closure of D9.**

    ``bitemporal-assertion:1`` `/value` is the only released opaque subtree and the exact
    shape the defect was written about. The runtime route is the one ``rc#16`` refuted D4
    through; the schema route is the one D9 recorded as unreachable. They must now produce
    the same manifest, byte for byte under RFC 8785 -- not merely "both work", which two
    disagreeing manifests would also satisfy.

    The comparison is on canonical BYTES rather than ``==`` so that a member-order
    difference introduced by any JSON round trip cannot pass as agreement, and cannot fail
    as disagreement either.
    """
    reference = "urn:datacompany:bitemporal-assertion:1"
    released = canonical_schemas()[reference]
    runtime_route = merge_profile_extensions(
        derive_hash_profile(reference),
        {"arrays": [{"pointer": "/value/tags", "kind": "ordered"}]},
    )

    mirror = json.loads(json.dumps(released))
    value = mirror["$defs"]["assertion_fields"]["properties"]["value"]
    # Non-vacuity: if the released subtree ever stops being opaque, this test proves nothing.
    assert value["x-datacompany-hash-opaque"] is True, value
    value["properties"] = {"tags": ORDERED_TAGS}
    register(mirror)
    schema_route = derive_hash_profile(reference)

    assert canonical_json_bytes(schema_route) == canonical_json_bytes(runtime_route)
    # ...and it is not vacuously equal because both are the unextended released manifest.
    assert any(entry["pointer"] == "/value/tags" for entry in schema_route["arrays"])
    assert "/value/tags" not in schema_route["included_pointers"]


def test_the_released_comments_that_make_this_capability_normative_are_still_there() -> None:
    """The two released statements this annotation exists to satisfy, read from the schemas.

    Quoted rather than paraphrased. If either ``$comment`` is reworded away, the capability
    stops being normative and this test says so instead of the annotation quietly becoming a
    local invention.
    """
    assertion = canonical_schemas()["urn:datacompany:bitemporal-assertion:1"]
    value_comment = assertion["$defs"]["assertion_fields"]["properties"]["value"]["$comment"]
    assert (
        "Arrays inside it still require their own ordered/set-like declaration" in value_comment
    ), value_comment

    profile = canonical_schemas()["urn:datacompany:canonical-hash-profile:1"]
    arrays_comment = profile["properties"]["arrays"]["$comment"]
    assert "including inside an opaque subtree" in arrays_comment, arrays_comment


def test_the_run_manifest_comment_no_longer_claims_the_route_is_impossible() -> None:
    """``run-manifest.v1`` `parameters` refused opacity BECAUSE of D9. That reason is spent.

    The ``$comment`` said in so many words that "no schema annotation can supply that
    declaration inside an opaque subtree". Leaving that sentence in place after the fix
    would be released prose asserting an impossibility that no longer holds -- and the next
    author to read it would re-derive the wrong conclusion from a released artefact. The
    schema's SHAPE is deliberately unchanged: converting `parameters` to an opaque bag is a
    separate, canonical-hash-affecting decision.
    """
    parameters = canonical_schemas()["urn:datacompany:run-manifest:1"]["$defs"]["inputs"][
        "properties"
    ]["parameters"]
    comment = parameters["$comment"]
    assert "No schema annotation can supply that declaration" not in comment, comment
    assert ANNOTATION in comment, comment
    # The shape is untouched: still a declared set-like array of named parameters.
    assert parameters["x-datacompany-array"] == {"kind": "set", "order_key": ["/name"]}
    assert "x-datacompany-hash-opaque" not in parameters


# ================================================== 3. the design constraints, one by one ==


def test_the_suppression_cascades_by_prefix_and_not_by_exact_match(register) -> None:
    """An array OF OBJECTS would otherwise leak its members and revoke the opacity anyway.

    Exact-match suppression drops ``/value/tags`` and leaves ``/value/tags/-/id`` and
    ``/value/tags/-/label`` behind, which puts ``/value`` back in the included-prefix set.
    The instance carries an undeclared sibling, so a leak is a raise rather than a
    quieter wrong answer.
    """
    register(
        opaque_probe(
            {
                "tags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
                    },
                    ANNOTATION: True,
                    "x-datacompany-array": {"kind": "set", "order_key": ["/id"]},
                }
            }
        )
    )
    manifest = derive_hash_profile(PROBE_ID)
    leaked = [p for p in manifest["included_pointers"] if p.startswith("/value/")]
    assert leaked == [], leaked
    assert manifest["included_pointers"] == ["/id", "/value"]

    view = build_hash_view(
        {"id": "x", "value": {"tags": [{"id": "b"}, {"id": "a"}], "other": 1}}, manifest
    )
    assert view["value"]["other"] == 1
    assert [member["id"] for member in view["value"]["tags"]] == ["a", "b"]


def test_the_array_declaration_survives_the_suppression(register) -> None:
    """``arrays`` is NOT filtered by declaration-only -- that is the whole point.

    Deliberately its own test rather than an aside in the case above: an implementation that
    filtered ``arrays`` too would still produce an opaque subtree and correct
    ``included_pointers``, so every opacity assertion would stay green while the collection
    declaration silently vanished and the instance became unhashable.

    §5.2's released inconsistency -- ``arrays`` is filtered by EXACT match for exclusions
    while everything else cascades -- is a bug-compatible quirk that must not be copied here.
    """
    register(opaque_probe({"tags": ORDERED_TAGS}))
    manifest = derive_hash_profile(PROBE_ID)
    assert manifest["arrays"] == [{"pointer": "/value/tags", "kind": "ordered"}]
    # The behavioural half: without the entry, the same instance is unhashable.
    assert build_hash_view({"id": "x", "value": {"tags": ["b", "a"]}}, manifest)["value"][
        "tags"
    ] == ["b", "a"]


def test_the_opacity_of_the_enclosing_subtree_survives(register) -> None:
    """The symptom D9 was written about: the undeclared sibling must hash, not raise."""
    register(opaque_probe({"tags": ORDERED_TAGS}))
    manifest = derive_hash_profile(PROBE_ID)
    assert manifest["opaque_pointers"] == ["/value"]
    view = build_hash_view({"id": "x", "value": {"tags": ["a"], "other": 1}}, manifest)
    assert view["value"] == {"tags": ["a"], "other": 1}

    # The discriminating control: WITHOUT the flag, the identical schema raises. Otherwise
    # this test would pass against an engine in which opacity was never at risk.
    unflagged = {key: value for key, value in ORDERED_TAGS.items() if key != ANNOTATION}
    register(opaque_probe({"tags": unflagged}))
    unflagged_manifest = derive_hash_profile(PROBE_ID)
    assert "/value/tags" in unflagged_manifest["included_pointers"]
    with pytest.raises(UndeclaredPathError, match="/value/other"):
        build_hash_view({"id": "x", "value": {"tags": ["a"], "other": 1}}, unflagged_manifest)


@pytest.mark.parametrize(
    ("route", "tags_node"),
    [
        ("inline", ORDERED_TAGS),
        ("allOf", {"allOf": [ORDERED_TAGS]}),
        ("anyOf", {"anyOf": [ORDERED_TAGS]}),
        ("oneOf", {"oneOf": [ORDERED_TAGS]}),
        ("then", {"if": {"type": "array"}, "then": ORDERED_TAGS}),
    ],
)
def test_the_same_declaration_derives_the_same_manifest_through_every_composition(
    register, route: str, tags_node: dict[str, Any]
) -> None:
    """**The test that catches an inline suppression.**

    Suppressing the pointer where ``properties`` adds it -- the obvious one-line
    implementation -- cannot see a flag that arrives afterwards through a ``$ref`` or an
    ``allOf``/``anyOf``/``oneOf``/``then``/``else`` branch, because the walk visits those
    AFTER the ``properties`` loop has already added the child pointer. Such an engine
    derives a manifest that depends on how the schema was WRITTEN rather than on what it
    means, and a second implementation composing in another order diverges from it silently.

    ``$ref`` is covered separately below because it resolves through a different code path.
    """
    register(opaque_probe({"tags": tags_node}))
    through_composition = derive_hash_profile(PROBE_ID)

    register(opaque_probe({"tags": ORDERED_TAGS}))
    inline = derive_hash_profile(PROBE_ID)

    assert through_composition == inline, (
        f"the {route} route derived a different manifest from the inline one; the "
        "suppression is composition-order dependent"
    )
    # Non-vacuity: both must actually carry the declaration, or two empty manifests match.
    assert inline["arrays"] == [{"pointer": "/value/tags", "kind": "ordered"}]


def test_a_declaration_reached_through_a_ref_derives_the_same_manifest(register) -> None:
    """The ``$ref`` half of the case above, which resolves through ``resolve_ref``.

    Kept separate because the two failure modes are different: an inline check misses the
    applicator branches because of ORDER, and misses a ``$ref`` because the flag is in
    another document entirely.
    """
    through_ref = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROBE_ID,
        "type": "object",
        "$defs": {"tags": ORDERED_TAGS},
        "properties": {
            "id": {"type": "string"},
            "value": {
                "type": "object",
                "x-datacompany-hash-opaque": True,
                "properties": {"tags": {"$ref": "#/$defs/tags"}},
            },
        },
    }
    register(through_ref)
    referenced = derive_hash_profile(PROBE_ID)
    register(opaque_probe({"tags": ORDERED_TAGS}))
    assert referenced == derive_hash_profile(PROBE_ID)
    assert referenced["included_pointers"] == ["/id", "/value"]


def test_only_the_literal_true_has_an_effect(register) -> None:
    """``is True``, exactly like the two boolean annotations released before it.

    REWRITTEN 2026-08-04, not deleted. This test used to assert that ``False``, ``1``,
    ``"true"``, ``None`` and ``{}`` were **silent no-ops** -- that ``/value/tags`` stayed in
    ``included_pointers``. That was a true statement about the READ and a false one about the
    contract: ``EXTENSIONS.md`` §9 item 8 already said "``is True`` semantics ... **or,
    better, reject everything but ``true`` at load time, as the meta-schema does**", and the
    meta-schema has always said ``const: true``. A silent no-op on a suppression flag is the
    same fail-open as §7.2 reached by writing the flag wrongly instead of by deleting it, so
    the engines now refuse it (§8, correction C2).

    Both halves that mattered are kept, and the second is why this is a rewrite rather than a
    replacement:

    1. no value but the literal ``true`` may have the flag's EFFECT -- now guaranteed a
       fortiori, because such a schema does not derive at all; and
    2. the read itself is still an IDENTITY comparison. That is the property the original
       docstring was really protecting -- a truthiness "fix" would make ``1`` and ``"true"``
       suppress a pointer the other engine still declares -- and it is no longer observable
       through the manifest, because the refusal fires first. It is pinned on the source
       instead, in both languages, so removing the refusal cannot silently restore the
       divergence underneath it.
    """
    for value in (False, 1, "true", None, {}):
        flagged = {**ORDERED_TAGS, ANNOTATION: value}
        register(opaque_probe({"tags": flagged}))
        with pytest.raises(HashProfileError, match="identity comparison"):
            derive_hash_profile(PROBE_ID)

    # The control: the literal true still suppresses. Without it, an engine that refused
    # every flagged schema would satisfy the loop above.
    register(opaque_probe({"tags": ORDERED_TAGS}))
    assert "/value/tags" not in derive_hash_profile(PROBE_ID)["included_pointers"]

    # (2) -- the read underneath the refusal is still `is True`, in both engines.
    python_source = (
        Path(__file__).resolve().parents[1] / "src/research_contracts/canonical/hash_profile.py"
    ).read_text(encoding="utf-8")
    port_source = (
        Path(__file__).resolve().parents[1] / "packages/typescript/src/hashProfile.ts"
    ).read_text(encoding="utf-8")
    assert f'schema.get("{ANNOTATION}") is True' in python_source
    assert f"schema['{ANNOTATION}'] === true" in port_source


def test_manifest_pointer_order_is_by_code_point_in_both_engines(register) -> None:
    """C3's other half: the two engines must SORT identically, not merely both sort.

    ``merge_profile_extensions`` was changed to sort ``arrays`` so the schema and runtime
    routes agree byte for byte. Nothing asserted WHICH order. Python's ``sorted`` compares
    code POINTS; JavaScript's ``<`` and a bare ``.sort()`` compare UTF-16 code UNITS, and the
    two disagree for astral characters -- the G1 divergence class this repository already
    carries an order-key fixture for, and the same shape as the ``ensure_ascii`` defect fixed
    one commit earlier. Both engines happened to be right; neither was pinned, so rewriting
    the comparator with ``split('')`` left all 701 TypeScript tests green.

    U+FF21 (FULLWIDTH LATIN CAPITAL LETTER A) is ONE UTF-16 unit, 65313. U+1F600 is a
    surrogate pair whose first unit is 0xD83D, 55357. Code-point order puts U+FF21 first;
    UTF-16 order puts U+1F600 first, so this pair separates the two sorts. A merged manifest
    reaches both: ``included_pointers`` through the shared string sort, ``arrays`` through
    the comparator added for C3.

    The canonical bytes are pinned as a literal that the TypeScript mirror asserts too, so
    neither engine can agree merely with its own recomputation.
    """
    fullwidth, emoji = "\uff21", "\U0001f600"
    register(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": PROBE_ID,
            "type": "object",
            **EXTENSIBLE_ENVELOPE,
            "properties": {
                fullwidth: {
                    "type": "array",
                    "items": {"type": "string"},
                    "x-datacompany-array": {"kind": "ordered"},
                }
            },
        }
    )
    merged = merge_profile_extensions(
        derive_hash_profile(PROBE_ID),
        {
            "included_pointers": [f"/{emoji}"],
            "arrays": [{"pointer": f"/{emoji}", "kind": "ordered"}],
        },
    )

    assert merged["included_pointers"] == [f"/{fullwidth}", f"/{emoji}"]
    assert [entry["pointer"] for entry in merged["arrays"]] == [f"/{fullwidth}", f"/{emoji}"]
    assert canonical_json_bytes(merged["arrays"]).decode("utf-8") == ASTRAL_ARRAYS_CANONICAL


# ======================================================= 4. the guard, proven able to fire ==


def test_the_flag_outside_an_opaque_subtree_is_refused(register) -> None:
    """A gate that can fire. Outside an opaque subtree the flag is a reasonless exclusion.

    The message must name the difference, because "rejected" alone sends the author looking
    for a typo rather than for ``x-datacompany-hash-excluded``.
    """
    register(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": PROBE_ID,
            "type": "object",
            # The sibling is load-bearing, not scenery. With ``tags`` alone, removing the
            # guard leaves ``included_pointers`` EMPTY and the manifest is rejected anyway by
            # the released ``minItems`` -- so the mutation would go red for the wrong reason
            # and the guard would be a nicer message rather than a rule. With a sibling the
            # manifest is WELL FORMED and silently claims ``/tags`` is not part of the
            # contract, with no ``excluded_pointers`` entry saying why. That is the fail-open
            # this guard exists for.
            "properties": {"id": {"type": "string"}, "tags": ORDERED_TAGS},
        }
    )
    with pytest.raises(HashProfileError) as raised:
        derive_hash_profile(PROBE_ID)
    message = str(raised.value)
    assert '["/tags"]' in message, message
    assert "x-datacompany-hash-excluded" in message, message


def test_the_flag_on_the_opaque_node_itself_is_refused(register) -> None:
    """STRICTLY under, never AT -- otherwise the guard is a formality.

    "At or under" would be satisfied by any node carrying both annotations, so an author
    could suppress any pointer anywhere by adding ``x-datacompany-hash-opaque`` beside the flag.
    This is the control that makes the guard's *strictness* load-bearing rather than
    incidental.
    """
    register(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": PROBE_ID,
            "type": "object",
            # Same reason as above: the sibling keeps the manifest well formed without the
            # guard, so relaxing "strictly under" to "at or under" fails HERE rather than
            # incidentally on an empty ``included_pointers``.
            "properties": {
                "id": {"type": "string"},
                "value": {
                    "type": "array",
                    "items": {"type": "string"},
                    "x-datacompany-hash-opaque": True,
                    ANNOTATION: True,
                    "x-datacompany-array": {"kind": "ordered"},
                },
            },
        }
    )
    with pytest.raises(HashProfileError, match="on one node"):
        derive_hash_profile(PROBE_ID)


def test_the_pair_is_refused_one_level_deeper_too(register) -> None:
    """C1, found by an independent refuter. "Strictly under" alone was walk-past-able.

    The ancestor test is satisfied by ANY opaque ancestor, so a node carrying both
    annotations slipped through whenever it happened to sit inside another opaque subtree --
    which is precisely the bypass the ancestor test exists to prevent, relocated one level
    down. ``/value`` opaque with ``/value/inner`` opaque-and-flagged derived cleanly and gave
    ``opaque_pointers: ["/value", "/value/inner"]``.

    The pair is now refused unconditionally, which also makes the engine and the
    meta-schema's per-node ``declaration_only_pairing`` agree instead of only appearing to.
    """
    register(
        opaque_probe(
            {
                "inner": {
                    "type": "object",
                    "x-datacompany-hash-opaque": True,
                    ANNOTATION: True,
                    "properties": {
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "x-datacompany-array": {"kind": "ordered"},
                        }
                    },
                }
            }
        )
    )
    with pytest.raises(HashProfileError) as raised:
        derive_hash_profile(PROBE_ID)
    message = str(raised.value)
    assert '["/value/inner"]' in message, message
    assert "on one node" in message, message


def test_an_excluded_member_does_not_count_as_a_declared_one(register) -> None:
    """B1, found by an independent refuter. **The motivating shape did not work.**

    ``x-datacompany-hash-opaque`` and ``x-datacompany-hash-excluded`` exist for this combination --
    hash an open payload as it arrives while keeping a signature out of the digest -- and D9
    is about the one array such a payload routinely contains. The declare-none-or-declare-all
    guard read the RAW walk, where an excluded member is still a ``properties`` name, so it
    counted ``/value/sig`` as a declaration that revokes opacity and refused the whole shape.

    ``hash_view`` states the opposite rule in as many words, and
    ``tests/test_hash_view_opaque_exclusion.py`` is built on it: "Opacity is revoked by a
    DECLARED MEMBER and by nothing else. An EXCLUSION is the opposite act."

    Until this derived, the runtime escape hatch was STILL the only route for the motivating
    case, which is to say D9 was not closed for it. Asserted four ways, because each fails
    differently: it derives at all; the exclusion survived; the opacity survived; and the
    manifest is byte-identical to the runtime route's.
    """
    register(
        opaque_probe(
            {
                "sig": {
                    "type": "string",
                    "x-datacompany-hash-excluded": True,
                    "x-datacompany-hash-exclusion-reason": "signature",
                },
                "tags": ORDERED_TAGS,
            }
        )
    )
    manifest = derive_hash_profile(PROBE_ID)
    assert manifest["included_pointers"] == ["/id", "/value"]
    assert [e["pointer"] for e in manifest["excluded_pointers"]] == ["/value/sig"]
    assert manifest["opaque_pointers"] == ["/value"]
    assert manifest["arrays"] == [{"pointer": "/value/tags", "kind": "ordered"}]

    view = build_hash_view(
        {"id": "x", "value": {"sig": "s", "tags": ["b", "a"], "other": 1}}, manifest
    )
    assert view == {"id": "x", "value": {"tags": ["b", "a"], "other": 1}}

    # The equality that makes it a CLOSURE rather than a capability.
    register(
        opaque_probe(
            {
                "sig": {
                    "type": "string",
                    "x-datacompany-hash-excluded": True,
                    "x-datacompany-hash-exclusion-reason": "signature",
                }
            }
        )
    )
    runtime = merge_profile_extensions(
        derive_hash_profile(PROBE_ID), {"arrays": [{"pointer": "/value/tags", "kind": "ordered"}]}
    )
    assert canonical_json_bytes(manifest) == canonical_json_bytes(runtime)


def test_an_opaque_pointer_under_a_declaration_only_pointer_is_not_listed(register) -> None:
    """C2. The comment claiming this filter "could only ever be a no-op" was false.

    The argument was about ANCESTORS -- every flag sits strictly under an opaque pointer --
    and said nothing about DESCENDANTS. ``/value`` opaque, ``/value/inner`` flagged and
    ``/value/inner/deeper`` opaque puts an opaque pointer squarely under a declaration-only
    one, and the manifest listed it: a path asserted inside a subtree the same manifest says
    contributes no paths.

    Dropping it changes no behaviour, because opacity matches by prefix and ``/value``
    already covers everything beneath the flag. That is exactly why it has to be a rule with
    a test rather than a comment with an argument -- a behaviourally inert mistake is the
    kind that survives every suite.
    """
    register(
        opaque_probe(
            {
                "inner": {
                    "type": "object",
                    ANNOTATION: True,
                    "properties": {
                        "deeper": {
                            "type": "object",
                            "x-datacompany-hash-opaque": True,
                            "properties": {"t": {"type": "string"}},
                        }
                    },
                }
            }
        )
    )
    manifest = derive_hash_profile(PROBE_ID)
    assert manifest["opaque_pointers"] == ["/value"], manifest["opaque_pointers"]
    assert manifest["included_pointers"] == ["/id", "/value"]
    # ...and the subtree still hashes as opaque, so nothing was lost by dropping it.
    assert build_hash_view({"id": "x", "value": {"inner": {"deeper": {"t": "v"}}}}, manifest)[
        "value"
    ] == {"inner": {"deeper": {"t": "v"}}}


def test_the_two_routes_agree_when_the_flagged_array_sorts_first(register) -> None:
    """C3. The byte equality was an ACCIDENT of sort order until ``merge`` started sorting.

    ``derive_hash_profile`` sorts ``arrays``; ``merge_profile_extensions`` appended. They
    agreed on ``bitemporal-assertion:1`` only because ``/value/tags`` happens to sort after
    ``/basis_refs``. Put the flagged array FIRST and the same manifest came out in two
    different byte sequences -- while D9's closure is stated as a BYTE equality.

    ``validate_profile_against_schema`` compares ``arrays`` per pointer, so nothing noticed.
    """
    probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROBE_ID,
        "type": "object",
        **EXTENSIBLE_ENVELOPE,
        "properties": {
            "aaa": {
                "type": "object",
                "x-datacompany-hash-opaque": True,
                "properties": {"tags": ORDERED_TAGS},
            },
            "zzz": {
                "type": "array",
                "items": {"type": "string"},
                "x-datacompany-array": {"kind": "ordered"},
            },
        },
    }
    register(probe)
    schema_route = derive_hash_profile(PROBE_ID)
    assert [e["pointer"] for e in schema_route["arrays"]] == ["/aaa/tags", "/zzz"]

    unflagged = json.loads(json.dumps(probe))
    del unflagged["properties"]["aaa"]["properties"]
    register(unflagged)
    runtime_route = merge_profile_extensions(
        derive_hash_profile(PROBE_ID), {"arrays": [{"pointer": "/aaa/tags", "kind": "ordered"}]}
    )
    assert [e["pointer"] for e in runtime_route["arrays"]] == ["/aaa/tags", "/zzz"]
    assert canonical_json_bytes(schema_route) == canonical_json_bytes(runtime_route)


def test_a_non_ascii_pointer_renders_identically_in_both_engines(register) -> None:
    """B2. ``json.dumps`` escapes non-ASCII; ``JSON.stringify`` does not.

    Both engines' guards render pointer lists through the same JSON spelling and both assert
    in prose that the texts are byte-identical. That was true only for ASCII: a member named
    ``café😀`` rendered ``["/caf\\u00e9\\ud83d\\ude00"]`` in Python against ``["/café😀"]``
    in TypeScript, and every fixture that could have caught it was ASCII -- so the parity
    claim was vacuous in the one dimension where it could fail.

    The committed non-ASCII rejection fixture is what actually pins the two engines together;
    this asserts the Python half produces the literal characters.
    """
    register(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": PROBE_ID,
            "type": "object",
            "properties": {"id": {"type": "string"}, "caf\u00e9\U0001f600": ORDERED_TAGS},
        }
    )
    with pytest.raises(HashProfileError) as raised:
        derive_hash_profile(PROBE_ID)
    message = str(raised.value)
    assert '["/caf\u00e9\U0001f600"]' in message, message
    assert "\\u00e9" not in message, "the pointer was escaped; JSON.stringify would not escape it"


def test_declaring_some_members_of_an_opaque_subtree_beside_the_flag_is_refused(
    register,
) -> None:
    """ "Declare none or declare all" -- diagnosed at derivation, not at hash time.

    A declared sibling revokes the opacity, and the declaration-only pointer is then the one
    member that cannot be declared. Left ungated this raises ``UndeclaredPathError`` on some
    instance later, naming the instance path and not the two annotations that disagree.
    """
    register(opaque_probe({"note": {"type": "string"}, "tags": ORDERED_TAGS}))
    with pytest.raises(HashProfileError) as raised:
        derive_hash_profile(PROBE_ID)
    message = str(raised.value)
    assert '["/value/note"]' in message, message
    assert '["/value/tags"]' in message, message


def test_a_nested_opaque_sibling_still_revokes_the_outer_subtrees_opacity(register) -> None:
    """The discriminating half of the nested-subtree case. FOUND BY MUTATION.

    Nesting is legal when the flag sits inside the INNER subtree, and broken when it sits
    beside it: ``/value/nested`` is a declared member of ``/value``, so ``/value``'s opacity
    is revoked and ``/value/tags`` -- which is deliberately not a declared member -- becomes
    the one member that cannot be declared.

    Without this test, the guard passed while carrying a clause that skipped any declared
    pointer lying inside another opaque subtree. That clause made the legal case pass for the
    wrong reason (so the "group by the outermost ancestor instead of the nearest" mutation
    stayed green) *and* silently permitted this broken one.
    """
    register(
        opaque_probe(
            {
                "tags": ORDERED_TAGS,
                "nested": {
                    "type": "object",
                    "x-datacompany-hash-opaque": True,
                    "properties": {"note": {"type": "string"}},
                },
            }
        )
    )
    with pytest.raises(HashProfileError) as raised:
        derive_hash_profile(PROBE_ID)
    message = str(raised.value)
    # The declared member is reported by name, and so is the flag it collides with. Every
    # declared descendant is listed rather than only the shallowest: which member revoked the
    # opacity is the question the author is trying to answer, and a truncated list makes that
    # a guess.
    assert '"/value/nested"' in message, message
    assert '"/value/tags"' in message, message


def test_the_guard_does_not_fire_on_the_shapes_it_must_allow(register) -> None:
    """The false-positive control for all three refusals above.

    A guard that raised on everything would satisfy every rejection test in this file. Three
    legal shapes, each of which a naive guard gets wrong: a plain opaque subtree with no flag
    anywhere, a flag two levels deep, and a flag inside an opaque subtree that is itself
    excluded (legal and inert, exactly like the array declaration beside it).
    """
    register(opaque_probe())
    assert derive_hash_profile(PROBE_ID)["opaque_pointers"] == ["/value"]

    # A properties CHAIN, with the flag on its outermost node only: the prefix cascade
    # carries the suppression down, so the array node itself needs no flag. This is the
    # intended shape for a deep declaration and the reason the meta-schema does NOT require
    # an annotation beside the flag -- see its `declaration_only_pairing` $comment.
    array_only = {key: value for key, value in ORDERED_TAGS.items() if key != ANNOTATION}
    register(
        opaque_probe(
            {
                "nested": {
                    "type": "object",
                    ANNOTATION: True,
                    "properties": {"tags": array_only},
                }
            }
        )
    )
    deep = derive_hash_profile(PROBE_ID)
    assert deep["arrays"] == [{"pointer": "/value/nested/tags", "kind": "ordered"}]
    assert deep["included_pointers"] == ["/id", "/value"]
    assert build_hash_view(
        {"id": "x", "value": {"nested": {"tags": ["b", "a"]}, "other": 1}}, deep
    )["value"] == {"nested": {"tags": ["b", "a"]}, "other": 1}

    # Nested opaque subtrees: the inner root IS a declared member of the outer one, and that
    # is sound rather than the mixed-declaration error. A guard grouping by EVERY opaque
    # ancestor instead of the nearest one refuses this.
    register(
        opaque_probe(
            {
                "nested": {
                    "type": "object",
                    "x-datacompany-hash-opaque": True,
                    "properties": {"tags": ORDERED_TAGS},
                }
            }
        )
    )
    nested = derive_hash_profile(PROBE_ID)
    assert nested["opaque_pointers"] == ["/value", "/value/nested"]
    assert nested["included_pointers"] == ["/id", "/value", "/value/nested"]
    assert nested["arrays"] == [{"pointer": "/value/nested/tags", "kind": "ordered"}]

    excluded_probe = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROBE_ID,
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "value": {
                "type": "object",
                "x-datacompany-hash-opaque": True,
                "x-datacompany-hash-excluded": True,
                "x-datacompany-hash-exclusion-reason": "signature",
                "properties": {"tags": ORDERED_TAGS},
            },
        },
    }
    register(excluded_probe)
    inert = derive_hash_profile(PROBE_ID)
    assert inert["opaque_pointers"] == []
    assert [entry["pointer"] for entry in inert["excluded_pointers"]] == ["/value"]


def test_no_released_schema_uses_the_annotation_so_no_committed_manifest_moved() -> None:
    """The measurement behind leaving ``DERIVATION_PROFILE_VERSION`` at 1.

    ``EXTENSIONS.md`` §1.3 makes adding a NAME a minor change and reserves a
    ``profile_version`` bump for changing what an EXISTING annotation means. This is the
    executable half of that argument: no released schema carries the new name, so every
    committed manifest derives byte-identically. It is re-measured from the corpus rather
    than asserted, because the claim stops being true the moment a released schema adopts
    the annotation -- at which point this goes red and the version question is reopened
    deliberately instead of by omission.
    """

    def carries(node: Any) -> bool:
        if isinstance(node, dict):
            return ANNOTATION in node or any(carries(child) for child in node.values())
        if isinstance(node, list):
            return any(carries(child) for child in node)
        return False

    users = sorted(
        schema_id for schema_id, schema in canonical_schemas().items() if carries(schema)
    )
    assert users == [], users
    # The positive control this census needs. `ANNOTATION in json.dumps(schema)` was the
    # first spelling and it reported `run-manifest:1` as a user: that schema NAMES the
    # annotation in a `$comment` and carries it nowhere. A text census over a corpus whose
    # prose discusses the thing being counted is a false-positive machine, so the walk looks
    # for the KEY -- and this proves the walk can still find one when it is there.
    assert carries({"properties": {"a": {ANNOTATION: True}}})
    assert not carries({"$comment": f"mentions {ANNOTATION} in prose"})
    for path in sorted((ROOT / "fixtures" / "canonical-hash" / "v1" / "manifests").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest == derive_hash_profile(manifest["schema_ref"]), path.name
        # The IMPLEMENTED constant, not the literal 1 this line used to carry. That literal
        # said "the declaration-only change did not bump the version", which was true and is
        # no longer the whole story: `DERIVATION_PROFILE_VERSION` moved 1 -> 2 on 2026-08-04
        # for a DIFFERENT rule change (§5.2's exclusion cascade). What this test is about
        # survives unchanged -- no released schema carries the annotation, so no committed
        # manifest moved because of IT -- and pinning the literal here would have made this
        # test red for a reason it does not measure.
        assert manifest["profile_version"] == DERIVATION_PROFILE_VERSION, path.name


# ============================================================== 5. two-language parity ====


def test_the_typescript_port_implements_the_same_annotation() -> None:
    """Parsed from the port, so a Python-only vocabulary addition is red rather than silent.

    ``EXTENSIONS.md`` §9 item 12 states the rule this enforces: a port that invents a local
    annotation for this derives a manifest the other engine cannot derive, which is a
    cross-language split. The same applies in reverse -- adding it to Python alone is the
    same split, pointing the other way.
    """
    source = TS_HASH_PROFILE.read_text(encoding="utf-8")
    # Non-vacuity first: a renamed or unreadable file makes every check below trivially true.
    assert "class Walker" in source, TS_HASH_PROFILE
    assert f"schema['{ANNOTATION}'] === true" in source, "the port does not collect the flag"
    assert "declarationOnly" in source
    # Post-filter, not inline: the pointer is filtered where `included` is built.
    assert "!isUnderExclusion(pointer) && !isDeclarationOnly(pointer)" in source
    # ...by PREFIX, mirroring Python.
    assert "pointer === suppressed || pointer.startsWith(`${suppressed}/`)" in source
    # ...and BOTH guards exist and are CALLED, not merely defined. Two, not one: they run at
    # different points on purpose -- placement against the raw walk, the
    # declare-none-or-declare-all rule against the DERIVED included list -- and collapsing
    # them back into one call site is what made the port refuse the signed opaque payload.
    assert "requireDeclarationOnlyIsLegallyPlaced(walker, schemaRef);" in source
    assert (
        "requireDeclarationOnlyDoesNotCollideWithADeclaredMember(walker, included, schemaRef);"
        in source
    )
    # The pair refusal is unconditional (C1), not "unless it has an opaque ancestor".
    assert "walker.opaque.has(p)" in source
    # `opaque_pointers` is filtered by declaration-only too (C2)...
    assert "!isUnderExclusion(p) && !isDeclarationOnly(p)" in source
    # ...and the merge sorts `arrays` by CODE POINT, so the two routes agree structurally (C3).
    assert "compareCodePoints(a.pointer, b.pointer)" in source

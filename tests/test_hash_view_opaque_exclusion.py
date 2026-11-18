"""An exclusion inside an opaque subtree must not revoke the subtree's opacity.

``x-datacompany-hash-opaque`` and ``x-datacompany-hash-excluded`` exist so that a domain can hash an
open payload as it arrives while keeping a signature, a resolution observation or another
non-hashable member out of the digest. That combination -- "exclude the signature from an
opaque payload" -- did not work: ``_ViewBuilder._declared_prefixes`` was built from
``included | excluded``, so an excluded ``/payload/signature`` injected ``/payload`` into the
prefix set, ``opaque = not declared_children and ...`` discarded the manifest's own
``opaque_pointers: ["/payload"]``, and every undeclared SIBLING of the signature raised
``UndeclaredPathError``. Removing only the nested exclusion hashed the identical instance.

The rule the engine now implements, and which the released ``$comment`` on
``bitemporal-assertion:1`` ``/value`` already states, is that opacity is revoked by a
DECLARED MEMBER -- an included pointer -- and by nothing else. An exclusion is the opposite
act. So an opaque subtree is hashed as an opaque unit MINUS its explicitly excluded
descendants, and its undeclared descendants stay legal.

Every case carries its false-positive control: the "declare one member, declare them all"
rule must still fire, an object that is neither declared nor opaque must still raise, and the
exclusion must still remove exactly the member it names.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import UndeclaredPathError, build_hash_view
from research_contracts.canonical import registry as registry_module
from research_contracts.canonical.hash_profile import derive_hash_profile, merge_profile_extensions
from research_contracts.canonical.registry import canonical_schemas

ROOT = Path(__file__).resolve().parents[1]
TS_HASH_VIEW = ROOT / "packages" / "typescript" / "src" / "hashView.ts"

PROBE_ID = "urn:datacompany:opaque-exclusion-probe:1"

#: A signed, open payload: the motivating shape for the two annotations existing at all.
SIGNED_OPAQUE_PAYLOAD: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": PROBE_ID,
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "payload": {
            "type": "object",
            "x-datacompany-hash-opaque": True,
            "properties": {
                "signature": {
                    "type": "string",
                    "x-datacompany-hash-excluded": True,
                    "x-datacompany-hash-exclusion-reason": "signature",
                }
            },
        },
    },
}

INSTANCE: dict[str, Any] = {
    "id": "x",
    "payload": {"signature": "sig", "body": {"k": 1}, "undeclared_sibling": True},
}


@pytest.fixture
def register(monkeypatch: pytest.MonkeyPatch):
    """Register a synthetic schema in the real registry and return its derived manifest."""

    def _register(schema: dict[str, Any]) -> dict[str, Any]:
        schemas = {**canonical_schemas(), PROBE_ID: schema}
        monkeypatch.setattr(registry_module, "canonical_schemas", lambda: schemas)
        return derive_hash_profile(PROBE_ID)

    return _register


def test_the_probe_manifest_really_declares_both_annotations(register) -> None:
    """Non-vacuity. Every case below would be satisfied by a manifest that declared
    neither annotation, because then there would be no opacity to revoke and no exclusion
    to revoke it."""
    profile = register(SIGNED_OPAQUE_PAYLOAD)
    assert profile["opaque_pointers"] == ["/payload"]
    assert [entry["pointer"] for entry in profile["excluded_pointers"]] == ["/payload/signature"]
    assert profile["included_pointers"] == ["/id", "/payload"]


def test_an_exclusion_inside_an_opaque_subtree_leaves_the_subtree_opaque(register) -> None:
    """The defect, as a behaviour: the undeclared siblings of the excluded member hash."""
    profile = register(SIGNED_OPAQUE_PAYLOAD)
    view = build_hash_view(INSTANCE, profile)
    assert view == {"id": "x", "payload": {"body": {"k": 1}, "undeclared_sibling": True}}


def test_the_exclusion_still_removes_exactly_the_member_it_names(register) -> None:
    """The control for the case above. An engine that "fixed" opacity by ignoring the
    exclusion entirely would also stop raising, and would hash the signature into the
    digest -- the opposite defect, wearing the same green."""
    profile = register(SIGNED_OPAQUE_PAYLOAD)
    payload = build_hash_view(INSTANCE, profile)["payload"]
    assert "signature" not in payload
    assert set(payload) == {"body", "undeclared_sibling"}


def test_removing_the_nested_exclusion_does_not_change_the_undeclared_siblings(register) -> None:
    """The discriminating comparison the reproduction rested on.

    Before the fix these two manifests disagreed about the SAME instance: without the
    exclusion the payload hashed, with it the identical undeclared members raised. They may
    now differ only in the excluded member itself.
    """
    with_exclusion = register(SIGNED_OPAQUE_PAYLOAD)
    without = {
        **SIGNED_OPAQUE_PAYLOAD,
        "properties": {
            **SIGNED_OPAQUE_PAYLOAD["properties"],
            "payload": {"type": "object", "x-datacompany-hash-opaque": True},
        },
    }
    unsigned = register(without)
    signed_view = build_hash_view(INSTANCE, with_exclusion)
    unsigned_view = build_hash_view(INSTANCE, unsigned)
    assert unsigned_view["payload"] == {**signed_view["payload"], "signature": "sig"}


def test_a_declared_member_of_an_opaque_subtree_still_revokes_opacity() -> None:
    """The released rule that was NOT changed, and the false-positive control for the fix.

    ``bitemporal-assertion:1`` ``/value`` says it in the schema itself: "the moment a domain
    declares any member of value, it must declare all of them". A fix that made opacity
    unconditional would pass every case above and silently delete this rule.
    """
    fixture_ref = "urn:datacompany:bitemporal-assertion:1"
    partial = merge_profile_extensions(
        derive_hash_profile(fixture_ref), {"included_pointers": ["/value/note"]}
    )
    assert partial["opaque_pointers"] == ["/value"]
    instance = {"value": {"note": "declared", "measurement": "undeclared"}}
    with pytest.raises(UndeclaredPathError, match="/value/measurement"):
        build_hash_view(instance, partial)


def test_without_the_opaque_declaration_the_same_manifest_still_rejects(register) -> None:
    """The other false-positive control: the fix widened OPACITY, not the whole gate.

    Two halves, because they raise at different places. With the exclusion present
    ``/payload`` is still a declared prefix, so its undeclared members are rejected one by
    one; with neither annotation the object itself is rejected as undeclared.
    """
    profile = register(SIGNED_OPAQUE_PAYLOAD)
    stripped = {**profile, "opaque_pointers": []}
    with pytest.raises(UndeclaredPathError, match="/payload/body: not declared"):
        build_hash_view(INSTANCE, stripped)

    bare = {**stripped, "excluded_pointers": []}
    with pytest.raises(UndeclaredPathError, match="neither this object's members nor"):
        build_hash_view(INSTANCE, bare)


def test_an_exclusion_outside_an_opaque_subtree_still_declares_its_parent(register) -> None:
    """``_declared_prefixes`` keeps its meaning: an exclusion is still enough to make its
    parent object a declared one, so an object whose every member is excluded is still
    hashable as the empty view. Only the OPACITY decision stopped consulting exclusions."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PROBE_ID,
        "type": "object",
        "properties": {
            "envelope": {
                "type": "object",
                "properties": {
                    "signature": {
                        "type": "string",
                        "x-datacompany-hash-excluded": True,
                        "x-datacompany-hash-exclusion-reason": "signature",
                    }
                },
            }
        },
    }
    profile = register(schema)
    assert profile["opaque_pointers"] == []
    assert build_hash_view({"envelope": {"signature": "sig"}}, profile) == {"envelope": {}}
    # ...and an undeclared sibling is still rejected there, because nothing is opaque.
    with pytest.raises(UndeclaredPathError, match="/envelope/body"):
        build_hash_view({"envelope": {"signature": "sig", "body": 1}}, profile)


# ================================================================= two-language parity ===
#
# Parsed from BOTH sides: `packages/typescript/test/hashView.test.ts` reads this module's
# Python counterpart, and this reads the port. Deleting either mirror is a red test rather
# than a silently one-directional pin.


def test_the_typescript_port_decides_opacity_from_the_included_prefixes_too() -> None:
    source = TS_HASH_VIEW.read_text(encoding="utf-8")
    # Non-vacuity first: an unreadable or renamed file would make every check below
    # trivially absent.
    assert "class ViewBuilder" in source, TS_HASH_VIEW
    assert "hasIncludedChildren" in source
    assert re.search(r"const opaque =\s*!this\.hasIncludedChildren\(pointer\)", source), (
        "the port still decides opacity from hasDeclaredChildren, which is true of the "
        "parent of every EXCLUDED pointer"
    )

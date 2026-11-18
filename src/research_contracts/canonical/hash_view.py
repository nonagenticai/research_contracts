"""Steps 2-5 of the section 4.3 canonical hash algorithm: the semantic hash view."""

from __future__ import annotations

import unicodedata
from typing import Any

from .errors import (
    CanonicalError,
    DuplicateSetMemberError,
    MissingOrderKeyError,
    UndeclaredArrayError,
    UnstableFloatError,
)
from .jcs import canonicalize, stable_integer

__all__ = ["build_hash_view"]

# The RFC 6901 "append/any-index" array token used in hash-view path declarations.
# Not a credential — S105 matches the *name*, not the value.
_ARRAY_TOKEN = "-"  # noqa: S105

#: Returned by ``_pointer_at`` when the pointer does not resolve at all. Distinct from an
#: explicit ``null``, which is a real value that two members can genuinely share.
_ABSENT = object()


class UndeclaredPathError(CanonicalError):
    """A member that the released hash-view manifest does not declare."""


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _pointer_at(value: Any, pointer: str) -> Any:
    """Resolve ``pointer`` inside ``value``, returning ``_ABSENT`` when it does not resolve.

    An absent member, an untraversable node and an explicit ``null`` are three different
    facts. Collapsing the first two onto ``None`` would make every member that simply lacks
    the order key look like the same member.
    """
    if pointer == "":
        # D8: RFC 6901's whole-document pointer, which for a member-relative order key
        # addresses the MEMBER ITSELF. This is what makes a set of scalars declarable; the
        # empty pointer is only reachable here, because only order_key_pointer admits it.
        return value
    if not pointer.startswith("/"):
        # RFC 6901 section 3: a non-empty JSON Pointer BEGINS with '/'. Nothing that
        # reaches here can be relative -- ``order_key_pointer`` is
        # ``hash_view_pointer`` plus ``""``, and ``hash_view_pointer`` pins
        # ``^(/([^/~]|~[01])*)+$`` -- so a pointer without one is malformed, and an
        # order key that cannot be read is an ABSENT order key, which raises
        # ``MissingOrderKeyError`` rather than silently keying on something else.
        return _ABSENT
    node = value
    # ``pointer.split("/")[1:]``, NOT ``pointer.lstrip("/").split("/")``.
    #
    # ⚠️ ``lstrip`` strips EVERY leading slash, and RFC 6901's reference tokens may be
    # EMPTY: ``"//a"`` is the two tokens ``["", "a"]`` -- the member named ``""`` and
    # then its member ``"a"`` -- and the released ``hash_view_pointer`` pattern
    # ``^(/([^/~]|~[01])*)+$`` accepts it, because ``([^/~]|~[01])*`` matches zero
    # characters. Under ``lstrip`` it collapsed to the single token ``["a"]``, so an
    # ``order_key: ["//a"]`` resolved against ``{"a": 1}`` -- a member that does NOT
    # carry the declared key -- and was accepted, while the member that does carry it,
    # ``{"": {"a": 1}}``, was reported absent. Both directions wrong, and the accepting
    # one fails open: two set members distinguished by a key neither of them has.
    #
    # `hashView.ts` carries the identical fix. These two implementations are verified
    # byte-equivalent by the differential fuzzer, and a fix to one is a defect in the
    # other until it lands in both.
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            return _ABSENT
        node = node[token]
    return node


class _ViewBuilder:
    def __init__(self, profile: dict[str, Any]) -> None:
        self.included: set[str] = set(profile["included_pointers"])
        self.excluded: set[str] = {entry["pointer"] for entry in profile["excluded_pointers"]}
        self.arrays: dict[str, dict[str, Any]] = {
            entry["pointer"]: entry for entry in profile["arrays"]
        }
        self.opaque: tuple[str, ...] = tuple(profile["opaque_pointers"])
        self.keep_nulls = profile["absent_vs_null"] == "distinct"
        normalization = profile["unicode_normalization"]
        self.normalization = None if normalization == "none" else normalization.upper()
        self._declared_prefixes = self._parents(self.included | self.excluded)
        # The narrower half: the parents of the INCLUDED pointers alone. An exclusion is not
        # a declaration -- it removes a descendant from the hash view, it does not name one
        # that must be hashed -- so it is deliberately absent here. See
        # ``_build_object`` for why the two sets cannot be one.
        self._included_prefixes = self._parents(self.included)

    @staticmethod
    def _parents(pointers: set[str]) -> set[str]:
        """The parent pointer of every pointer that has one, plus the document root.

        The membership test is ``"/" in pointer[1:]``, not ``"/" in pointer.lstrip("/")``,
        for the reason spelled out in ``_pointer_at``: a reference token may be EMPTY, so
        ``"//a"`` is two tokens and its parent is ``"/"``. ``lstrip`` read it as one token
        and gave it no parent at all, which revoked the declaration of an object whose
        members the manifest does declare -- failing toward ``UndeclaredPathError`` rather
        than open, but wrong, and wrong in a way the TypeScript port shares.
        """
        parents = {""}
        parents.update(
            pointer.rsplit("/", 1)[0]
            for pointer in pointers
            if pointer.startswith("/") and "/" in pointer[1:]
        )
        return parents

    def _has_declared_children(self, pointer: str) -> bool:
        return pointer in self._declared_prefixes

    def _has_included_children(self, pointer: str) -> bool:
        """True when the manifest names a member of ``pointer`` as a hashed path."""
        return pointer in self._included_prefixes

    def _is_declared_opaque(self, pointer: str) -> bool:
        """True when ``pointer`` is, or sits under, an explicitly opaque released subtree."""
        return any(
            pointer == declared or pointer.startswith(f"{declared}/") for declared in self.opaque
        )

    def _text(self, value: str) -> str:
        if self.normalization is None:
            return value
        return unicodedata.normalize(self.normalization, value)

    def build(self, value: Any, pointer: str) -> Any:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, float):
            integral = stable_integer(value)
            if integral is None:
                raise UnstableFloatError(
                    f"{pointer or '/'}: binary float {value!r} may not enter a hashed input; the "
                    "released profile declares binary_float_policy=reject"
                )
            # JSON has one number type: a schema-valid integer that Python's parser handed
            # back as 2.0 is the integer 2, and RFC 8785 renders both identically. Normalize
            # so this implementation cannot disagree with a JSON-parsing peer language.
            return integral
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return self._text(value)
        if isinstance(value, list):
            return self._build_array(value, pointer)
        if isinstance(value, dict):
            return self._build_object(value, pointer)
        raise CanonicalError(f"{pointer or '/'}: {type(value).__name__} is not JSON data")

    def _build_object(self, value: dict[str, Any], pointer: str) -> dict[str, Any]:
        # Declare none or declare all, and say which: an object either has its members
        # declared one by one, or sits in a subtree the released schema explicitly marks
        # x-datacompany-hash-opaque. Silence is not a third option -- it used to mean "hash the
        # whole subtree undeclared", which failed open for every domain that shipped no
        # profile extensions at all.
        #
        # Opacity is revoked by a DECLARED MEMBER and by nothing else. The released
        # ``$comment`` on ``bitemporal-assertion:1`` ``/value`` states the rule as "the
        # moment a domain declares any member of value, it must declare all of them", and a
        # declared member is an INCLUDED pointer. An EXCLUSION is the opposite act: it takes
        # a descendant out of the hash view. Testing opacity against
        # ``_has_declared_children`` -- which is also true of the parent of every excluded
        # pointer -- made "exclude the signature from an opaque payload" impossible: the
        # exclusion injected the payload into the prefix set, opacity was revoked, and every
        # undeclared SIBLING of the signature then raised ``UndeclaredPathError``. That is
        # the motivating case for the two annotations existing at all, so an opaque subtree
        # is hashed as an opaque unit MINUS its explicitly excluded descendants, and its
        # undeclared descendants stay legal -- which is what opacity means.
        declared_children = self._has_declared_children(pointer)
        opaque = not self._has_included_children(pointer) and self._is_declared_opaque(pointer)
        if not declared_children and not opaque:
            raise UndeclaredPathError(
                f"{pointer or '/'}: the released hash-view manifest declares neither this "
                "object's members nor this subtree as opaque; declare every member, or mark "
                "the subtree x-datacompany-hash-opaque in the schema"
            )
        view: dict[str, Any] = {}
        for name, child in value.items():
            child_pointer = f"{pointer}/{_escape(name)}"
            if child_pointer in self.excluded:
                continue
            if child_pointer not in self.included and not opaque:
                raise UndeclaredPathError(
                    f"{child_pointer}: not declared by the released hash-view manifest"
                )
            if child is None and not self.keep_nulls:
                continue
            view[name] = self.build(child, child_pointer)
        return view

    def _build_array(self, value: list[Any], pointer: str) -> list[Any]:
        declaration = self.arrays.get(pointer)
        if declaration is None:
            raise UndeclaredArrayError(
                f"{pointer or '/'}: array has no released ordered/set-like declaration"
            )
        element_pointer = f"{pointer}/{_ARRAY_TOKEN}"
        members = [self.build(item, element_pointer) for item in value]
        if declaration["kind"] == "ordered":
            return members

        order_key: list[str] = declaration["order_key"]
        keyed: list[tuple[bytes, Any]] = []
        seen: dict[bytes, int] = {}
        for index, member in enumerate(members):
            key_values = [_pointer_at(member, key_pointer) for key_pointer in order_key]
            absent = [
                key_pointer
                for key_pointer, key_value in zip(order_key, key_values, strict=True)
                if key_value is _ABSENT
            ]
            if absent:
                raise MissingOrderKeyError(
                    f"{pointer}/{index}: set-like member does not carry the released order-key "
                    f"path(s) {absent}; every member of a set-like array must carry its whole "
                    "released order key, and an absent key is not the same fact as a shared one"
                )
            key_bytes = canonicalize(key_values)
            if key_bytes in seen:
                raise DuplicateSetMemberError(
                    f"{pointer}: set-like array members {seen[key_bytes]} and {index} share the "
                    f"canonical order key {key_bytes.decode('utf-8')}"
                )
            seen[key_bytes] = index
            keyed.append((key_bytes, member))
        keyed.sort(key=lambda entry: entry[0])
        return [member for _, member in keyed]


def build_hash_view(instance: Any, profile: dict[str, Any]) -> Any:
    """Return the semantic hash view of ``instance`` under a released manifest.

    Implements section 4.3 steps 2 through 5: keep the schema-declared semantic paths,
    remove exactly the schema-marked non-hashable paths (nested target ``content_hash``
    values are ordinary declared members and stay in), enforce every array's released
    collection kind, reject duplicate set members, and apply the released absent-versus-null
    and Unicode rules without ever normalizing undeclared.
    """
    return _ViewBuilder(profile).build(instance, "")

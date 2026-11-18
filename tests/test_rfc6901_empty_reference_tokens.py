"""An RFC 6901 reference token may be EMPTY, and both hash-view implementations ate it.

``hash_view._pointer_at`` tokenised a pointer as ``pointer.lstrip("/").split("/")``, and
``hashView.ts`` did the same thing with ``pointer.replace(/^\\/+/, '').split('/')``. Stripping
EVERY leading slash is not the RFC 6901 tokenisation. RFC 6901 section 3 says a pointer is a
sequence of ``'/'`` followed by a reference token, and section 4 says a reference token may be
the EMPTY string -- it addresses a member literally named ``""``, which JSON permits and
``JSON.parse`` produces as an ordinary member.

So ``"//a"`` is the two tokens ``["", "a"]``: the member named ``""``, then its member ``"a"``.
Stripped, it became the single token ``["a"]``.

**THE PROFILE'S OWN GRAMMAR ACCEPTS IT.** ``canonical-hash-profile.v1``'s
``hash_view_pointer`` pins ``^(/([^/~]|~[01])*)+$`` with ``minLength: 2``, and
``([^/~]|~[01])*`` matches zero characters -- so ``"//a"`` is a legal declared pointer, and
``order_key_pointer`` is that grammar plus ``""``. A released manifest may therefore declare
an order key the resolver cannot read, and nothing anywhere refuses it.

WHICH WAY IT FAILED. Both ways at once, and one of them fails OPEN:

* ``_pointer_at({"a": 1}, "//a")`` returned ``1``. A set-like member that does NOT carry the
  declared key was accepted, keyed on a member it happened to have under a different path.
  Two members can then be "distinguished" by a key neither of them has.
* ``_pointer_at({"": {"a": 1}}, "//a")`` returned the absent marker. The member that DOES
  carry the declared key was rejected with ``MissingOrderKeyError``.

WHY THIS FILE ASSERTS THE TYPESCRIPT SOURCE TOO. The canonical hash is a CROSS-LANGUAGE
contract: the two implementations are verified byte-equivalent by the differential fuzzer, so
fixing one and not the other converts a shared defect into a divergence, which is worse. The
real TypeScript regression test is ``packages/typescript/test/rfc6901EmptyTokens.test.ts`` and
runs under jest. It cannot run from here -- ``test_differential_fuzz.py`` records why the
``gates`` job has no Node toolchain, and a test that skipped when Node was absent would
reproduce the defect this repository exists to prevent -- so what runs here is a source
tripwire on the idiom itself. It is a weaker instrument than the jest test and is not a
substitute for it; it exists so that a future edit that reintroduces the strip in EITHER
language goes red in the suite that always runs.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path
from typing import Any

import pytest

from research_contracts.canonical import derive_hash_profile
from research_contracts.canonical.errors import MissingOrderKeyError
from research_contracts.canonical.hash_view import _ABSENT, _pointer_at, build_hash_view

ROOT = Path(__file__).resolve().parents[1]
PROFILE_SCHEMA = ROOT / "schemas" / "canonical" / "canonical-hash-profile.v1.schema.json"
PYTHON_SOURCE = ROOT / "src" / "research_contracts" / "canonical" / "hash_view.py"
TYPESCRIPT_SOURCE = ROOT / "packages" / "typescript" / "src" / "hashView.ts"

#: The member name that an empty reference token addresses. Spelled out because ``""`` inside
#: a pointer literal is invisible, and every assertion below turns on it.
EMPTY_NAME = ""


def _pointer_grammar() -> tuple[re.Pattern[str], int]:
    """The released ``hash_view_pointer`` pattern and minimum length, read from the schema.

    Read, not restated. A test that hard-codes the regex would keep passing if the released
    grammar were narrowed to exclude empty tokens, which is the one edit that would make this
    whole file moot.
    """
    document = json.loads(PROFILE_SCHEMA.read_text(encoding="utf-8"))
    declaration = document["$defs"]["hash_view_pointer"]
    return re.compile(declaration["pattern"]), int(declaration["minLength"])


def _set_like_profile(order_key: list[str], included: list[str]) -> dict[str, Any]:
    """A released-shaped manifest for a set-like array whose order key has an empty token."""
    return {
        **derive_hash_profile("urn:datacompany:stable-identity:1"),
        "included_pointers": included,
        "excluded_pointers": [],
        "opaque_pointers": [],
        "arrays": [{"pointer": "/members", "kind": "set", "order_key": order_key}],
    }


# ------------------------------------------- the premise: the grammar really accepts it ---


@pytest.mark.parametrize("pointer", ["//a", "/a//b", "//", "/a/", "///"])
def test_the_released_pointer_grammar_accepts_an_empty_reference_token(pointer: str) -> None:
    """If the profile schema refused these, the resolver would never see one and the defect
    would be unreachable. It does not refuse them: ``([^/~]|~[01])*`` matches zero characters,
    so every pointer here is a legal declared ``hash_view_pointer``."""
    pattern, min_length = _pointer_grammar()
    assert pattern.match(pointer), f"{pointer!r} rejected by the released grammar"
    assert len(pointer) >= min_length


# ------------------------------------------------------- the resolver, in both directions ---


def test_an_empty_token_addresses_the_member_named_empty_string() -> None:
    """``"//a"`` is ``["", "a"]``. The member that CARRIES the declared key must resolve.

    Before the fix this returned the absent marker, so the correct member was the one
    rejected.
    """
    assert _pointer_at({EMPTY_NAME: {"a": 1}}, "//a") == 1
    assert _pointer_at({EMPTY_NAME: 5}, "/") == 5
    assert _pointer_at({EMPTY_NAME: {EMPTY_NAME: 7}}, "//") == 7


def test_an_empty_token_does_not_resolve_a_member_that_lacks_it() -> None:
    """The fail-OPEN half, and the reason this is not merely a pedantic pointer bug.

    ``lstrip`` collapsed ``"//a"`` to ``"a"``, so a member with no ``""`` member at all
    resolved against its top-level ``"a"`` and was accepted as carrying the declared order
    key. A set-like array could then be ordered -- and its members deduplicated -- by a key
    that the manifest does not actually declare for them.
    """
    assert _pointer_at({"a": 1}, "//a") is _ABSENT
    assert _pointer_at({"a": {"b": 1}}, "//a/b") is _ABSENT


@pytest.mark.parametrize("pointer", ["a", "a/b", "~0a"])
def test_a_pointer_without_a_leading_slash_does_not_resolve(pointer: str) -> None:
    """RFC 6901 section 3: a non-empty pointer BEGINS with ``/``. Nothing that reaches the
    resolver can be relative -- ``order_key_pointer`` is ``hash_view_pointer`` plus ``""`` --
    so a pointer without one is malformed, and an unreadable order key is an ABSENT order
    key, which raises rather than keying on whatever the string happens to match."""
    assert _pointer_at({"a": {"b": 1}, "~0a": 2}, pointer) is _ABSENT


def test_the_whole_document_pointer_still_addresses_the_member_itself() -> None:
    """The D8 control. ``""`` is the one pointer that is not a leading slash followed by
    anything, and it is the whole reason ``order_key_pointer`` exists as a fourth pointer
    language: it makes a set of SCALARS declarable. A fix that started rejecting pointers
    without a leading slash must not take this with it."""
    assert _pointer_at("a scalar member", "") == "a scalar member"
    assert _pointer_at({"a": 1}, "") == {"a": 1}


# ------------------------------------------------------ end to end, through the hash view ---


def test_a_member_lacking_the_declared_empty_token_key_is_rejected() -> None:
    """The whole point, at the level a released manifest operates on.

    ``order_key: ["//a"]`` declares "the member's ``""`` member's ``a`` member". A member
    carrying a top-level ``a`` and no ``""`` does not carry that key, and used to be accepted
    as though it did.
    """
    profile = _set_like_profile(["//a"], ["/members", "/members/-", "/members/-/a"])
    with pytest.raises(MissingOrderKeyError, match=r"does not carry the released order-key"):
        build_hash_view({"members": [{"a": "one"}, {"a": "two"}]}, profile)


def test_members_that_do_carry_the_empty_token_key_are_ordered_by_it() -> None:
    """The other direction, and the assertion that keeps the fix from being "reject
    everything". These members really do carry ``//a``, so they must sort by it."""
    profile = _set_like_profile(["//a"], ["/members", "/members/-", "/members/-/", "/members/-//a"])
    members = {"members": [{EMPTY_NAME: {"a": "b"}}, {EMPTY_NAME: {"a": "a"}}]}
    view = build_hash_view(members, profile)
    assert [member[EMPTY_NAME]["a"] for member in view["members"]] == ["a", "b"]


def test_an_ordinary_order_key_is_untouched_by_the_fix() -> None:
    """The control for every released manifest in the tree: no released order key contains an
    empty token, so the fix must be a no-op for all of them."""
    profile = _set_like_profile(["/id"], ["/members", "/members/-", "/members/-/id"])
    view = build_hash_view({"members": [{"id": "b"}, {"id": "a"}]}, profile)
    assert [member["id"] for member in view["members"]] == ["a", "b"]


# ------------------------------------------------------- the two languages must agree ---


def _python_code(source: str) -> str:
    """``source`` with comments and docstrings removed, so a MENTION is not a CALL.

    ⚠️ Docstrings and comments only. Dropping every STRING token would also delete the
    ``"/"`` argument out of ``lstrip("/")`` and out of ``split("/")``, and the search below
    would then match nothing no matter what the file said -- a control that cannot fail.
    """
    lines = source.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, column = token.start
            lines[row - 1] = lines[row - 1][:column]

    docstring_lines: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, holders) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstring_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    return "\n".join(
        "" if number in docstring_lines else line for number, line in enumerate(lines, start=1)
    )


def _typescript_code(source: str) -> str:
    """``source`` with ``/* */`` and ``//`` comments removed, for the same reason."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines() if not line.lstrip().startswith("//")
    )


def test_neither_implementation_strips_leading_slashes_when_tokenising() -> None:
    """A source tripwire, and it is deliberately narrow about what it can prove.

    It cannot prove the TypeScript port is correct -- ``packages/typescript/test/
    rfc6901EmptyTokens.test.ts`` does that, under jest, and this suite has no Node. What it
    CAN do is fail when either file reintroduces the idiom that caused the divergence, in the
    suite that always runs. The canonical hash is a cross-language contract; a fix landed in
    one language only is a worse state than the shared defect was.
    """
    python_source = PYTHON_SOURCE.read_text(encoding="utf-8")
    typescript_source = TYPESCRIPT_SOURCE.read_text(encoding="utf-8")

    # ⚠️ Match against CODE, not against the file. Both files now carry a long comment
    # naming the idiom they must not use, so a naive substring search over the raw text
    # fails on the explanation of the fix -- a control that cannot distinguish a call from
    # a mention. Python is tokenised (comments and string literals dropped); TypeScript has
    # its `//` and `/* */` comments removed.
    assert 'lstrip("/")' not in _python_code(python_source), (
        "hash_view.py tokenises a pointer with lstrip again"
    )
    assert not re.search(r"replace\(\s*/\^\\/\+?/", _typescript_code(typescript_source)), (
        "hashView.ts strips leading slashes again"
    )

    # And the positive half: an absence proves nothing on its own, so pin what each file
    # must ACTUALLY do. Both must tokenise the RFC 6901 way -- drop the first (empty) split
    # element, keep every other one, empty or not.
    assert 'pointer.split("/")[1:]' in python_source
    assert "pointer.split('/').slice(1)" in typescript_source

"""Language-neutral rendering of a JSON value into an engine's error message text.

``EXTENSIONS.md`` §9 item 12 states the rule these two functions exist to keep: *two engines
that refuse the same schema with different words are a divergence a consumer reading either
one cannot reconcile.* It names the concrete trap — ``repr`` writes ``['/a']`` where
``JSON.stringify`` writes ``["/a"]`` — and the same trap has two more spellings that a port
reproduces only by accident:

* a quoted scalar. ``repr("nope")`` is ``'nope'`` and ``JSON.stringify("nope")`` is
  ``"nope"``. Decision F's own refusals were measured emitting both, one per language, for
  the same malformed rule.
* a type NAME. ``type(value).__name__`` is Python's type system (``str``, ``dict``,
  ``NoneType``, ``list``) and ``typeof`` is JavaScript's (``string``, ``object``,
  ``object``, ``object``). Neither is the type system the value actually has: these values
  are parsed JSON, so the honest vocabulary is JSON's own — the six names the ``type``
  keyword uses — and it is the only one both languages can spell identically.
* a NON-ASCII character. ``json.dumps`` defaults to ``ensure_ascii=True`` and escapes every
  code point above U+007F into ``\\uXXXX``; ``JSON.stringify`` escapes nothing above the
  control range. A member named ``café`` therefore renders as ``["/caf\\u00e9"]`` in Python
  and ``["/café"]`` in the port, for the same refusal of the same schema. This is the
  third spelling of the same trap and it is the one no ASCII test can see, which is why
  :func:`json_text` passes ``ensure_ascii=False`` and a non-ASCII case is committed to
  ``fixtures/canonical-annotations/v1/refusals.json`` rather than left to review.
* an UNPAIRED SURROGATE, which is the fourth spelling and was **introduced by the fix for
  the third**. With ``ensure_ascii=True`` Python escaped a lone surrogate to ``\\ud800`` and
  happened to agree with ES2019's well-formed ``JSON.stringify``; turning it off made Python
  emit the raw code point, which diverges *and* cannot be encoded to UTF-8 at all -- so
  printing or logging a legitimate refusal raised ``UnicodeEncodeError`` and a diagnostic
  became an unhandled crash. Reverting ``ensure_ascii`` would reopen the third; escaping only
  the unpaired surrogates closes both, which is what :func:`json_text` does. A committed case
  sits beside the two ``café😀`` ones.

Mirrored by ``packages/typescript/src/rendering.ts``, function for function.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["json_text", "json_type"]


def json_text(value: Any) -> str:
    """Render ``value`` as compact JSON, byte for byte as ``JSON.stringify`` would.

    BOTH keyword arguments are load-bearing and neither is a default:

    * ``separators`` — ``json.dumps`` defaults to ``", "`` and ``": "``, which no
      ``JSON.stringify`` output ever contains.
    * ``ensure_ascii=False`` — ``json.dumps`` defaults to ``True`` and escapes every code
      point above U+007F, which ``JSON.stringify`` does not. Dropping this argument is
      invisible to every ASCII test and makes the two engines' refusals of a schema with a
      non-ASCII member name differ; the committed refusal record carries a case that fails
      the moment it is dropped.

    …and the surrogate pass afterwards is the correction that argument needed. ES2019 made
    ``JSON.stringify`` **well formed**, and "well formed" is two rules, not one: an UNPAIRED
    surrogate is emitted as ``\\ud800``, and an adjacent high+low PAIR is the astral
    character it encodes and is emitted as that character. ``ensure_ascii=False`` gets both
    wrong. It emits a lone surrogate raw, which diverges from the port and, worse, produces a
    ``str`` that ``.encode("utf-8")`` REFUSES -- so a legitimate refusal could not be printed
    or logged without raising ``UnicodeEncodeError``, turning a diagnostic into a second
    failure. :func:`_well_formed` implements both rules, so this function agrees with
    ``JSON.stringify`` on **every** UTF-16 sequence rather than only on the reachable ones.

    That distinction was earned. This docstring used to argue that a pair "cannot happen"
    because "a Python ``str`` holds code points, so an astral character is one code point and
    never a pair". The conclusion does not follow from the premise: a ``str`` can perfectly
    well hold two ADJACENT surrogate code points --
    ``b"\\xed\\xa0\\xbd\\xed\\xb8\\x80".decode("utf-8", "surrogatepass")`` is exactly that -- and on
    that input the old pass escaped both while the port emitted ``😀``. The true reason such a
    value never arrives is different and stronger: ``json``'s DECODER combines an adjacent
    ``\\uD83D\\uDE00`` escape pair into one code point at parse time, everything reaching here
    came through ``json.load``, and the only ``surrogatepass`` in this package is an *encode*
    in :mod:`~research_contracts.canonical.jcs`. The code no longer relies on that argument
    either way, which is the point: a correctness property should not rest on an input being
    unreachable.

    The result is not the RFC 8785 canonicalization — ``jcs.canonicalize`` is that, and it
    is a HASHED input where this is a human-readable diagnostic. They are deliberately
    separate: this one is allowed to render a value RFC 8785 would refuse.
    """
    rendered = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if not any("\ud800" <= character <= "\udfff" for character in rendered):
        return rendered
    return _well_formed(rendered)


def _high(character: str) -> bool:
    return "\ud800" <= character <= "\udbff"


def _low(character: str) -> bool:
    return "\udc00" <= character <= "\udfff"


def _well_formed(rendered: str) -> str:
    """Apply ES2019's two well-formedness rules to ``rendered``'s surrogate code points.

    A high immediately followed by a low is a UTF-16 pair: JavaScript sees ONE astral
    character there, so this emits that character. Anything else in ``D800``-``DFFF`` is
    unpaired and is escaped, in the lower-case hex V8 emits.
    """
    out: list[str] = []
    index = 0
    while index < len(rendered):
        character = rendered[index]
        following = rendered[index + 1] if index + 1 < len(rendered) else ""
        if _high(character) and _low(following):
            code = 0x10000 + (ord(character) - 0xD800) * 0x400 + (ord(following) - 0xDC00)
            out.append(chr(code))
            index += 2
            continue
        out.append(f"\\u{ord(character):04x}" if _high(character) or _low(character) else character)
        index += 1
    return "".join(out)


def json_type(value: Any) -> str:
    """Name ``value``'s JSON type, using the six names JSON Schema's ``type`` keyword uses.

    ``bool`` is tested before ``int`` deliberately: in Python ``True`` IS an ``int``, so the
    obvious ordering renders ``true`` as a number and diverges from every other language.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    # Not reachable from a parsed JSON document, which is the only source these engines
    # read. Named rather than silently mapped onto one of the six above, because a value
    # that is not JSON at all is a different fault from a value of the wrong JSON type.
    return f"non-JSON {type(value).__name__}"

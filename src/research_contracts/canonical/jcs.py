"""RFC 8785 JSON Canonicalization Scheme.

This is a first-party implementation. It is deliberately not ``json.dumps(sort_keys=True)``:

* RFC 8785 sorts object member names by **UTF-16 code unit**, not by Unicode code point.
  The two orders differ whenever an astral-plane character (encoded as a surrogate pair
  starting at U+D800) is compared with a BMP character at or above U+E000.
* RFC 8785 serializes numbers with the ECMAScript ``Number::toString`` algorithm
  (ECMA-262 6.1.6.1.20), which Python's ``repr``/``json`` do not reproduce for exponent
  forms or for large integral magnitudes.
* RFC 8785 escapes only the seven short escapes plus ``\\u00xx`` for the remaining C0
  control characters, and emits every other code point literally as UTF-8.

The output is always UTF-8 without a byte-order mark.
"""

from __future__ import annotations

import math
import re
from typing import Any, Final

from .errors import UnstableFloatError, UnsupportedTypeError

__all__ = [
    "canonicalize",
    "es_number_to_string",
    "stable_integer",
    "utf16_sort_key",
]

# Largest magnitude an IEEE-754 double represents exactly as an integer.
MAX_EXACT_INTEGER: Final = 2**53

_SHORT_ESCAPES: Final = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}

_REPR_PATTERN: Final = re.compile(r"(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?\Z")


def utf16_sort_key(name: str) -> bytes:
    """Return the RFC 8785 sort key for an object member name.

    Lexicographic comparison of UTF-16 big-endian bytes is identical to numeric
    comparison of the UTF-16 code-unit sequences, which is what RFC 8785 section 3.2.3
    requires. Lone surrogates cannot be encoded and are rejected by the caller.
    """
    return name.encode("utf-16-be", errors="surrogatepass")


def stable_integer(value: float) -> int | None:
    """Return the exact integer of an integral double in range, or ``None`` if unstable.

    JSON has one number type, so ``2.0`` and ``2`` are the same JSON value and RFC 8785
    renders both as ``2``. Only Python's parser distinguishes them, which is why a
    schema-valid ``{"type": "integer"}`` member can arrive as a ``float``. Such a value is
    exactly representable and is not an unstable binary float, so it is normalized to the
    integer it is. Anything with a fractional part, ``NaN``/infinity, or a magnitude beyond
    the exact IEEE-754 double range is genuinely unstable and returns ``None``.
    """
    if math.isnan(value) or math.isinf(value) or not float(value).is_integer():
        return None
    as_integer = int(value)
    if abs(as_integer) > MAX_EXACT_INTEGER:
        return None
    return as_integer


def _shortest_decimal(value: float) -> tuple[str, int]:
    """Return ``(digits, n)`` with ``value == 0.digits * 10**n`` and ``digits`` shortest.

    ``digits`` has no leading or trailing zero. ``n`` is the ECMAScript ``n`` of
    ECMA-262 6.1.6.1.20, so ``k = len(digits)`` and ``digits * 10**(n - k) == value``.
    """
    match = _REPR_PATTERN.fullmatch(repr(value))
    if match is None:  # pragma: no cover - repr of a finite positive float always matches
        raise UnsupportedTypeError(f"cannot decompose float repr {value!r}")
    integer_part, fraction_part, exponent_part = (
        match.group(1),
        match.group(2) or "",
        match.group(3),
    )
    exponent = int(exponent_part) if exponent_part else 0

    digits = integer_part + fraction_part
    point = len(integer_part) + exponent
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")
    return digits, point


def es_number_to_string(value: float) -> str:
    """Serialize a number exactly as ECMAScript ``Number::toString`` does.

    RFC 8785 section 3.2.2.3 defers to that algorithm. ``NaN`` and the infinities are not
    representable in JSON and are rejected.
    """
    if isinstance(value, bool):  # pragma: no cover - guarded by the caller
        raise UnsupportedTypeError("bool is not a JSON number")
    if isinstance(value, int):
        if abs(value) > MAX_EXACT_INTEGER:
            raise UnstableFloatError(
                f"integer {value} exceeds the exact IEEE-754 double range "
                f"(+/-{MAX_EXACT_INTEGER}); carry it as a released decimal string instead"
            )
        value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise UnsupportedTypeError(f"{value!r} has no RFC 8785 representation")
    if value == 0.0:
        # ECMAScript renders both +0 and -0 as "0".
        return "0"
    if value < 0:
        return "-" + es_number_to_string(-value)

    digits, n = _shortest_decimal(value)
    k = len(digits)

    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * -n + digits
    exponent = n - 1
    sign = "+" if exponent >= 0 else "-"
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{mantissa}e{sign}{abs(exponent)}"


def _serialize_string(value: str) -> str:
    out = ['"']
    for character in value:
        code_point = ord(character)
        short = _SHORT_ESCAPES.get(code_point)
        if short is not None:
            out.append(short)
        elif code_point < 0x20:
            out.append(f"\\u{code_point:04x}")
        elif 0xD800 <= code_point <= 0xDFFF:
            raise UnsupportedTypeError(
                f"lone surrogate U+{code_point:04X} is not valid Unicode and cannot be "
                "canonicalized"
            )
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


def _serialize(value: Any, *, allow_binary_float: bool, path: str) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _serialize_string(value)
    if isinstance(value, int):
        return es_number_to_string(value)
    if isinstance(value, float):
        if not allow_binary_float:
            integral = stable_integer(value)
            if integral is None:
                raise UnstableFloatError(
                    f"{path or '/'}: binary float {value!r} may not enter a hashed input; use "
                    "the released decimal-string rule"
                )
            # An integral double in range IS the integer, in JSON and in RFC 8785 alike.
            return es_number_to_string(integral)
        return es_number_to_string(value)
    if isinstance(value, (list, tuple)):
        members = [
            _serialize(item, allow_binary_float=allow_binary_float, path=f"{path}/{index}")
            for index, item in enumerate(value)
        ]
        return "[" + ",".join(members) + "]"
    if isinstance(value, dict):
        names: list[str] = []
        for key in value:
            if not isinstance(key, str):
                raise UnsupportedTypeError(
                    f"{path or '/'}: object member name {key!r} is not a string"
                )
            names.append(key)
        members = []
        for key in sorted(names, key=utf16_sort_key):
            rendered_key = _serialize_string(key)
            rendered_value = _serialize(
                value[key], allow_binary_float=allow_binary_float, path=f"{path}/{key}"
            )
            members.append(f"{rendered_key}:{rendered_value}")
        return "{" + ",".join(members) + "}"
    raise UnsupportedTypeError(
        f"{path or '/'}: {type(value).__name__} has no RFC 8785 representation"
    )


def canonicalize(value: Any, *, allow_binary_float: bool = False) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes of ``value``, with no byte-order mark.

    ``allow_binary_float`` exists only to run the RFC 8785 conformance vectors, which
    contain binary floats by construction. Every released hash path leaves it ``False``.
    """
    return _serialize(value, allow_binary_float=allow_binary_float, path="").encode("utf-8")

/**
 * RFC 8785 JSON Canonicalization Scheme -- TypeScript port of
 * `src/research_contracts/canonical/jcs.py`.
 *
 * This is a first-party implementation. It is deliberately not `JSON.stringify`:
 *
 * * `JSON.stringify` renders `NaN`/`Infinity` as `null`, a silent value substitution.
 * * `JSON.stringify` emits a lone surrogate as `"\ud800"` (well-formed stringify, ES2019+)
 *   instead of refusing it.
 * * `JSON.stringify` honours `toJSON`, so a `Decimal`-like object silently becomes some
 *   other value.
 * * `JSON.stringify` does not sort object members at all.
 *
 * Two DIFFERENT orders are in play and conflating them is the highest-value bug in this
 * port:
 *
 * * object member NAMES sort by UTF-16 code unit (RFC 8785 section 3.2.3). Native JS
 *   string `<` and the default `Array.prototype.sort()` comparison are exactly that order,
 *   including for astral characters and lone surrogates. `compareUtf16CodeUnits` states it
 *   explicitly so it is inspectable and perturbable, and a test pins it against the native
 *   comparison.
 * * set-like ARRAY members sort by the raw UTF-8 bytes of their canonical order key
 *   (`hashView.ts`). UTF-8 byte order is Unicode CODE POINT order, which is NOT UTF-16
 *   code-unit order: U+E000 precedes U+10000 by code point but follows it by code unit.
 *   `hashView.ts` therefore sorts `Uint8Array`s with an unsigned byte comparator and never
 *   decodes to a string first.
 *
 * The output is always UTF-8 without a byte-order mark.
 */

import { UnstableFloatError, UnsupportedTypeError } from './errors';

/**
 * A value this engine can canonicalize.
 *
 * `bigint` carries a JSON integer literal that a `number` cannot hold exactly. Python's
 * `json.loads` yields an exact `int` for such a literal and rejects it at serialization
 * time; `JSON.parse` silently rounds it, so `parseCanonicalJson` re-materializes it as a
 * `bigint` to preserve the same fact. See `json.ts`.
 */
export type CanonicalValue =
  | null
  | boolean
  | string
  | number
  | bigint
  | CanonicalValue[]
  | { [key: string]: CanonicalValue };

/** Largest magnitude an IEEE-754 double represents exactly as an integer. */
export const MAX_EXACT_INTEGER = 2 ** 53;

/** The same bound as a `bigint`, for exact comparison of oversized integer literals. */
export const MAX_EXACT_INTEGER_BIGINT = 9007199254740992n;

const SHORT_ESCAPES: ReadonlyMap<number, string> = new Map([
  [0x08, '\\b'],
  [0x09, '\\t'],
  [0x0a, '\\n'],
  [0x0c, '\\f'],
  [0x0d, '\\r'],
  [0x22, '\\"'],
  [0x5c, '\\\\'],
]);

const UTF8 = new TextEncoder();

/**
 * Compare two object member names by UTF-16 code unit, as RFC 8785 section 3.2.3 requires.
 *
 * Python reaches this order by comparing `name.encode("utf-16-be", surrogatepass)` bytes.
 * In JavaScript a string IS a UTF-16 code-unit sequence, so `charCodeAt` comparison is the
 * same order -- and so is native `<`. Never use `localeCompare` or `Intl.Collator` (locale
 * dependent) and never spread or `Array.from` inside a comparator (that iterates CODE
 * POINTS, which is the other order).
 */
export function compareUtf16CodeUnits(left: string, right: string): number {
  const shared = Math.min(left.length, right.length);
  for (let index = 0; index < shared; index += 1) {
    const a = left.charCodeAt(index);
    const b = right.charCodeAt(index);
    if (a !== b) {
      return a < b ? -1 : 1;
    }
  }
  return left.length - right.length;
}

/**
 * The RFC 8785 sort key of a member name, as UTF-16 big-endian bytes.
 *
 * Mirrors Python's `utf16_sort_key`. Sorting by these bytes and sorting with
 * `compareUtf16CodeUnits` are the same order; this exists so a caller can reproduce the
 * Python key material verbatim.
 */
export function utf16SortKey(name: string): Uint8Array {
  const bytes = new Uint8Array(name.length * 2);
  for (let index = 0; index < name.length; index += 1) {
    const unit = name.charCodeAt(index);
    bytes[index * 2] = (unit >> 8) & 0xff;
    bytes[index * 2 + 1] = unit & 0xff;
  }
  return bytes;
}

/** Unsigned byte-wise comparison, the order Python's `bytes` comparison uses. */
export function compareBytes(left: Uint8Array, right: Uint8Array): number {
  const shared = Math.min(left.length, right.length);
  for (let index = 0; index < shared; index += 1) {
    if (left[index] !== right[index]) {
      return left[index] - right[index];
    }
  }
  return left.length - right.length;
}

/**
 * Return the exact integer of an integral double in range, or `null` if unstable.
 *
 * JSON has one number type, so `2.0` and `2` are the same JSON value and RFC 8785 renders
 * both as `2`. Anything with a fractional part, `NaN`/infinity, or a magnitude beyond the
 * exact IEEE-754 double range is genuinely unstable and returns `null`.
 *
 * `-0` normalizes to `0`, matching Python's `int(-0.0)`.
 */
export function stableInteger(value: number): number | null {
  if (!Number.isFinite(value) || !Number.isInteger(value)) {
    return null;
  }
  if (Math.abs(value) > MAX_EXACT_INTEGER) {
    return null;
  }
  return value === 0 ? 0 : value;
}

/**
 * Serialize a number exactly as ECMAScript `Number::toString` does.
 *
 * RFC 8785 section 3.2.2.3 defers to that algorithm, which is what `String(n)` IS by
 * definition -- Python has to emulate it, this port gets it natively. `NaN` and the
 * infinities are not representable in JSON and are rejected rather than silently becoming
 * `null` the way `JSON.stringify` would.
 *
 * A `bigint` takes the Python `int` branch: beyond +/-2^53 it is rejected outright, never
 * rounded. That branch is independent of `allowBinaryFloat`, exactly as in Python.
 */
export function esNumberToString(value: number | bigint): string {
  if (typeof value === 'bigint') {
    if (value > MAX_EXACT_INTEGER_BIGINT || value < -MAX_EXACT_INTEGER_BIGINT) {
      throw new UnstableFloatError(
        `integer ${value.toString()} exceeds the exact IEEE-754 double range ` +
          `(+/-${MAX_EXACT_INTEGER}); carry it as a released decimal string instead`,
      );
    }
    return esNumberToString(Number(value));
  }
  if (!Number.isFinite(value)) {
    throw new UnsupportedTypeError(`${String(value)} has no RFC 8785 representation`);
  }
  if (value === 0) {
    // ECMAScript renders both +0 and -0 as "0"; the explicit branch mirrors Python.
    return '0';
  }
  return String(value);
}

/**
 * Emit an RFC 8785 string literal.
 *
 * Seven short escapes, `\u00xx` LOWERCASE for the remaining C0 controls, and every other
 * code point literally as UTF-8. In particular U+2028 and U+2029 are ORDINARY code points
 * here: several JavaScript serializers escape them because they are not legal inside an
 * ES5 string literal, and doing so produces different bytes and a different, wrong hash.
 *
 * An unpaired surrogate is not valid Unicode and is refused -- a lone high, a lone low, and
 * a reversed pair alike.
 */
export function serializeString(value: string): string {
  let out = '"';
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    const short = SHORT_ESCAPES.get(unit);
    if (short !== undefined) {
      out += short;
      continue;
    }
    if (unit < 0x20) {
      out += `\\u${unit.toString(16).padStart(4, '0')}`;
      continue;
    }
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = index + 1 < value.length ? value.charCodeAt(index + 1) : -1;
      if (next >= 0xdc00 && next <= 0xdfff) {
        out += value[index] + value[index + 1];
        index += 1;
        continue;
      }
      throw new UnsupportedTypeError(
        `lone surrogate U+${unit.toString(16).toUpperCase().padStart(4, '0')} is not valid ` +
          'Unicode and cannot be canonicalized',
      );
    }
    if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new UnsupportedTypeError(
        `lone surrogate U+${unit.toString(16).toUpperCase().padStart(4, '0')} is not valid ` +
          'Unicode and cannot be canonicalized',
      );
    }
    out += value[index];
  }
  return `${out}"`;
}

/**
 * A plain JSON object: `{}`-shaped or null-prototype, and carrying no `toJSON`.
 *
 * Acceptance is a WHITELIST. `Date`, `Map`, `Set`, typed arrays, class instances and
 * anything with a `toJSON` method are refused rather than silently coerced, because a
 * `Decimal`-like wrapper that stringifies to something else is precisely the failure this
 * engine exists to prevent.
 */
function isPlainJsonObject(value: object): boolean {
  const prototype = Object.getPrototypeOf(value) as object | null;
  if (prototype !== Object.prototype && prototype !== null) {
    return false;
  }
  return typeof (value as { toJSON?: unknown }).toJSON !== 'function';
}

function describe(value: unknown): string {
  if (value === undefined) {
    return 'undefined';
  }
  if (value === null) {
    return 'null';
  }
  if (typeof value !== 'object') {
    return typeof value;
  }
  const prototype = Object.getPrototypeOf(value) as { constructor?: { name?: string } } | null;
  return prototype?.constructor?.name ?? 'object';
}

function serialize(value: unknown, allowBinaryFloat: boolean, path: string): string {
  if (value === null) {
    return 'null';
  }
  if (value === true) {
    return 'true';
  }
  if (value === false) {
    return 'false';
  }
  if (typeof value === 'string') {
    return serializeString(value);
  }
  if (typeof value === 'bigint') {
    return esNumberToString(value);
  }
  if (typeof value === 'number') {
    if (!allowBinaryFloat) {
      const integral = stableInteger(value);
      if (integral === null) {
        throw new UnstableFloatError(
          `${path || '/'}: binary float ${String(value)} may not enter a hashed input; use ` +
            'the released decimal-string rule',
        );
      }
      // An integral double in range IS the integer, in JSON and in RFC 8785 alike.
      return esNumberToString(integral);
    }
    return esNumberToString(value);
  }
  if (Array.isArray(value)) {
    const members = value.map((item, index) =>
      serialize(item, allowBinaryFloat, `${path}/${index}`),
    );
    return `[${members.join(',')}]`;
  }
  if (typeof value === 'object' && isPlainJsonObject(value)) {
    const record = value as Record<string, unknown>;
    // Every own enumerable string key. JavaScript object keys are always strings, so
    // Python's "object member name is not a string" branch is unreachable here; symbol
    // keys are not own enumerable STRING keys and are therefore never members.
    const names = Object.keys(record).sort(compareUtf16CodeUnits);
    const members = names.map(
      (name) =>
        `${serializeString(name)}:${serialize(
          record[name],
          allowBinaryFloat,
          `${path}/${name}`,
        )}`,
    );
    return `{${members.join(',')}}`;
  }
  throw new UnsupportedTypeError(
    `${path || '/'}: ${describe(value)} has no RFC 8785 representation`,
  );
}

export interface CanonicalizeOptions {
  /**
   * Permit a genuine binary float in the output.
   *
   * Exists ONLY to run the RFC 8785 conformance vectors, which contain binary floats by
   * construction. Every released hash path leaves it `false`.
   */
  allowBinaryFloat?: boolean;
}

/** Return the RFC 8785 canonical UTF-8 bytes of `value`, with no byte-order mark. */
export function canonicalize(value: unknown, options: CanonicalizeOptions = {}): Uint8Array {
  return UTF8.encode(serialize(value, options.allowBinaryFloat === true, ''));
}

/** Return the RFC 8785 canonical text of `value`. `canonicalize` is the byte-level truth. */
export function canonicalizeToString(value: unknown, options: CanonicalizeOptions = {}): string {
  return serialize(value, options.allowBinaryFloat === true, '');
}

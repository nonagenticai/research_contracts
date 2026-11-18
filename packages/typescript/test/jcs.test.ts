/**
 * RFC 8785 serializer edge cases where JavaScript's own primitives disagree with the rule.
 *
 * Each case here is a place `JSON.stringify` would have produced a plausible-looking but
 * WRONG answer: a silent `null` for a non-finite number, a `"\ud800"` for a lone surrogate,
 * a `toJSON` substitution, or no member ordering at all.
 */

import {
  canonicalize,
  canonicalizeToString,
  compareBytes,
  compareUtf16CodeUnits,
  esNumberToString,
  MAX_EXACT_INTEGER,
  stableInteger,
} from '../src/jcs';
import { canonicalJsonBytes, canonicalSha256 } from '../src/engine';
import { UnstableFloatError, UnsupportedTypeError } from '../src/errors';
import { decodeUtf8 } from './fixtures';

describe('ECMAScript Number::toString boundaries', () => {
  it.each([
    [1e21, '1e+21'],
    [1e20, '100000000000000000000'],
    [1e-6, '0.000001'],
    [1e-7, '1e-7'],
    [5e-324, '5e-324'],
    [-0, '0'],
    [0, '0'],
    [1, '1'],
    [-2, '-2'],
    [2 ** 53, '9007199254740992'],
    [333333333.33333329, '333333333.3333333'],
    [1e30, '1e+30'],
    [4.5, '4.5'],
    [2e-3, '0.002'],
    [1e-27, '1e-27'],
  ])('String(%p) is %p', (value, expected) => {
    expect(esNumberToString(value)).toBe(expected);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    'refuses %p instead of silently emitting null the way JSON.stringify does',
    (value) => {
      expect(JSON.stringify(value)).toBe('null');
      expect(() => canonicalize(value, { allowBinaryFloat: true })).toThrow(
        UnsupportedTypeError,
      );
    },
  );

  it('parses 1e999 to Infinity, exactly as Python does, and then refuses it', () => {
    expect(JSON.parse('1e999')).toBe(Number.POSITIVE_INFINITY);
    expect(() => canonicalize(JSON.parse('1e999'), { allowBinaryFloat: true })).toThrow(
      UnsupportedTypeError,
    );
  });
});

describe('the exact-integer boundary', () => {
  it.each([
    [2.0, 2],
    [-0, 0],
    [MAX_EXACT_INTEGER, MAX_EXACT_INTEGER],
    [0.1, null],
    [MAX_EXACT_INTEGER * 4, null],
    [Number.NaN, null],
    [Number.POSITIVE_INFINITY, null],
  ])('stableInteger(%p) is %p', (value, expected) => {
    expect(stableInteger(value)).toBe(expected);
  });

  it('accepts 2^53 and refuses 2^53 + 1', () => {
    expect(esNumberToString(9007199254740992n)).toBe('9007199254740992');
    expect(() => canonicalJsonBytes(9007199254740993n)).toThrow(UnstableFloatError);
    expect(() => canonicalJsonBytes(-9007199254740993n)).toThrow(UnstableFloatError);
  });

  it('refuses an oversized integer even with allowBinaryFloat, as Python does', () => {
    // Python's `int` branch is independent of the flag; only the `float` branch honours it.
    expect(() => canonicalJsonBytes(9007199254740993n, { allowBinaryFloat: true })).toThrow(
      UnstableFloatError,
    );
  });

  it('renders 2.0 and 2 identically', () => {
    expect(decodeUtf8(canonicalJsonBytes({ n: 2.0 }))).toBe('{"n":2}');
    expect(decodeUtf8(canonicalJsonBytes({ n: 2 }))).toBe('{"n":2}');
  });

  it('rejects an unstable binary float on the released path', () => {
    expect(() => canonicalSha256({ measurement: 0.1 })).toThrow(UnstableFloatError);
  });
});

describe('string serialization', () => {
  it('uses the seven short escapes and lowercase \\u00xx for the other C0 controls', () => {
    expect(canonicalizeToString('\b\t\n\f\r"\\')).toBe('"\\b\\t\\n\\f\\r\\"\\\\"');
    expect(canonicalizeToString('\u0000\u0001\u000b\u000e\u001f')).toBe(
      '"\\u0000\\u0001\\u000b\\u000e\\u001f"',
    );
    // Lowercase, explicitly: an uppercase \u000B is different bytes and a different hash.
    expect(canonicalizeToString('\u000b')).not.toContain('\\u000B');
  });

  it('does NOT escape U+007F or U+0080', () => {
    expect(canonicalizeToString('\u007f\u0080')).toBe('"\u007f\u0080"');
  });

  it('emits U+2028 and U+2029 literally', () => {
    const canonical = canonicalize({ 'a\u2028b': 'x\u2029y' });
    expect(decodeUtf8(canonical)).toBe('{"a\u2028b":"x\u2029y"}');
    expect(Array.from(canonical)).toEqual(
      Array.from(new TextEncoder().encode('{"a\u2028b":"x\u2029y"}')),
    );
    expect(decodeUtf8(canonical)).not.toContain('\\u2028');
    expect(decodeUtf8(canonical)).not.toContain('\\u2029');
    // Escaping them -- which several JavaScript serializers do -- is a different hash.
    expect(canonicalSha256({ k: 'a\u2028b' })).not.toBe(canonicalSha256({ k: 'a\\u2028b' }));
  });

  it.each([
    ['a lone high surrogate', '\ud800'],
    ['a lone low surrogate', '\udc00'],
    ['a lone high surrogate at the end', 'ok\udbff'],
    ['a REVERSED surrogate pair', '\udc00\ud800'],
    ['a high surrogate followed by a BMP character', '\ud800a'],
  ])('throws on %s where JSON.stringify would emit an escape', (_label, value) => {
    expect(JSON.stringify(value)).toMatch(/\\ud[0-9a-f]{3}/i);
    expect(() => canonicalize(value)).toThrow(UnsupportedTypeError);
    expect(() => canonicalize({ [value]: 1 })).toThrow(UnsupportedTypeError);
  });

  it('accepts a well-formed surrogate pair as one astral code point', () => {
    expect(canonicalizeToString('😂')).toBe('"\u{1F602}"');
  });
});

describe('type whitelist', () => {
  it.each([
    ['a Date', new Date(0)],
    ['a Map', new Map()],
    ['a Set', new Set()],
    ['a typed array', new Uint8Array([1])],
    ['undefined', undefined],
    ['a function', (): void => undefined],
    ['a class instance', new (class Money {})()],
    ['an object with toJSON', { toJSON: (): string => 'surprise' }],
  ])('refuses %s', (_label, value) => {
    expect(() => canonicalize(value)).toThrow(UnsupportedTypeError);
  });

  it('refuses undefined inside an object rather than dropping it', () => {
    expect(JSON.stringify({ a: undefined })).toBe('{}');
    expect(() => canonicalize({ a: undefined })).toThrow(UnsupportedTypeError);
  });

  it('accepts a null-prototype object', () => {
    const bare = Object.create(null) as Record<string, unknown>;
    bare['b'] = 1;
    bare['a'] = 2;
    expect(canonicalizeToString(bare)).toBe('{"a":2,"b":1}');
  });
});

describe('the two orders, kept apart', () => {
  it('orders object member NAMES by UTF-16 code unit', () => {
    // U+1F602 has surrogate lead D83D, which precedes U+FB33 as a code UNIT but follows it
    // as a code POINT.
    expect(canonicalizeToString({ '\ufb33': 1, '\u{1F602}': 2 })).toBe('{"\u{1F602}":2,"\ufb33":1}');
    expect(compareUtf16CodeUnits('\u{1F602}', '\ufb33')).toBeLessThan(0);
    // U+FB33 is a single PRECOMPOSED code point. The visually identical decomposed
    // sequence U+05D3 U+05BC starts at 0x05D3 and sorts the OTHER way, which is a real
    // trap when copying a character out of rendered text.
    expect(compareUtf16CodeUnits('\u{1F602}', '\u05d3\u05bc')).toBeGreaterThan(0);
  });

  it('compares raw bytes unsigned, which is Unicode code-point order', () => {
    const encode = (text: string): Uint8Array => new TextEncoder().encode(text);
    // U+E000 encodes as EE 80 80; U+10000 as F0 90 80 80. EE < F0, so PUA comes first.
    expect(compareBytes(encode('\ue000'), encode('\u{10000}'))).toBeLessThan(0);
    // The opposite of the code-unit answer for the very same pair.
    expect(compareUtf16CodeUnits('\ue000', '\u{10000}')).toBeGreaterThan(0);
    // Unsigned, not signed: a 0xEE byte must read as 238, not -18.
    expect(compareBytes(new Uint8Array([0xee]), new Uint8Array([0x41]))).toBeGreaterThan(0);
  });

  it('breaks ties on length', () => {
    expect(compareUtf16CodeUnits('ab', 'abc')).toBeLessThan(0);
    expect(compareBytes(new Uint8Array([1]), new Uint8Array([1, 0]))).toBeLessThan(0);
  });
});

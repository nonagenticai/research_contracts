/**
 * The first-party JSON parser: the integer guard, and the purity `JSON.parse` does not have.
 *
 * Two obligations:
 *
 * 1. an integer literal past 2^53 survives the parse, because `JSON.parse` rounds it away
 *    BEFORE any of our code runs and a port built on it accepts inputs Python refuses;
 * 2. `parseCanonicalJson` is a PURE FUNCTION OF ITS TEXT. On Node >= 24 `JSON.parse` is
 *    not: a document parsed earlier can rename a member of a document parsed later. That
 *    reddened the P8 differential fuzz on 5 of 200 measured seeds, and it silently
 *    corrupts `registry.ts`'s schema loading. See `src/json.ts` for the measurement.
 */

import { buildHashView, type HashProfile } from '../src/hashView';
import { canonicalJsonBytes } from '../src/engine';
import { deriveHashProfile } from '../src/hashProfile';
import { UnstableFloatError } from '../src/errors';
import { parseCanonicalJson } from '../src/json';
import { decodeUtf8 } from './fixtures';

const OVER = '9007199254740993'; // 2^53 + 1
const AT = '9007199254740992'; // 2^53, the largest exactly representable integer

function profileWith(included: string[], excluded: string[] = []): HashProfile {
  return {
    ...deriveHashProfile('urn:datacompany:stable-identity:1'),
    included_pointers: included,
    excluded_pointers: excluded.map((pointer) => ({
      pointer,
      reason: 'projection_or_cache',
    })),
    opaque_pointers: [],
    arrays: [],
  };
}

describe('the loss JSON.parse causes', () => {
  it('is real: bare JSON.parse silently rounds 2^53 + 1', () => {
    expect(JSON.parse(`{"n":${OVER}}`).n).toBe(9007199254740992);
    expect(String(JSON.parse(`{"n":${OVER}}`).n)).toBe(AT);
  });

  it('is prevented: parseCanonicalJson preserves the literal as a bigint', () => {
    const parsed = parseCanonicalJson(`{"n":${OVER}}`) as Record<string, unknown>;
    expect(typeof parsed['n']).toBe('bigint');
    expect(parsed['n']).toBe(9007199254740993n);
  });

  it('leaves an in-range integer a plain number', () => {
    const parsed = parseCanonicalJson(`{"a":${AT},"b":-42,"c":0}`) as Record<string, unknown>;
    expect(typeof parsed['a']).toBe('number');
    expect(typeof parsed['b']).toBe('number');
    expect(typeof parsed['c']).toBe('number');
  });

  it('leaves float literals alone: they are binary floats in Python too', () => {
    const parsed = parseCanonicalJson('{"a":1.5,"b":1e3,"c":9007199254740993.0}') as Record<
      string,
      unknown
    >;
    expect(typeof parsed['a']).toBe('number');
    expect(typeof parsed['b']).toBe('number');
    expect(typeof parsed['c']).toBe('number');
  });
});

describe('what the engine then does with it', () => {
  it('refuses the oversized integer at serialization time, as Python does', () => {
    const parsed = parseCanonicalJson(`{"n":${OVER}}`);
    expect(() => canonicalJsonBytes(parsed)).toThrow(UnstableFloatError);
    expect(() => canonicalJsonBytes(parsed)).toThrow(/exceeds the exact IEEE-754 double range/);
  });

  it('accepts exactly 2^53, the boundary Python accepts', () => {
    expect(decodeUtf8(canonicalJsonBytes(parseCanonicalJson(`{"n":${AT}}`)))).toBe(`{"n":${AT}}`);
  });

  /**
   * The reason the guard re-materializes a `bigint` rather than throwing at parse time.
   *
   * Python only raises where the value REACHES the serializer. An oversized integer at an
   * excluded pointer is dropped from the hash view first, and Python hashes the object
   * happily. Failing at parse would be a divergence in the other direction.
   */
  it('does not refuse an oversized integer that never reaches the hash view', () => {
    const instance = parseCanonicalJson(`{"kept":1,"dropped":${OVER}}`);
    const profile = profileWith(['/kept'], ['/dropped']);
    const view = buildHashView(instance, profile);
    expect(decodeUtf8(canonicalJsonBytes(view))).toBe('{"kept":1}');
  });

  it('refuses the same value once it is INCLUDED', () => {
    const instance = parseCanonicalJson(`{"kept":1,"dropped":${OVER}}`);
    const profile = profileWith(['/kept', '/dropped']);
    expect(() => canonicalJsonBytes(buildHashView(instance, profile))).toThrow(UnstableFloatError);
  });
});

// --------------------------------------------------------------------------------------
// Purity
// --------------------------------------------------------------------------------------

/**
 * The exact shape that poisons V8's member-name reuse, reduced from a real fuzz failure.
 *
 * `POISONER`'s second member name is the source text `\\`, which decodes to one backslash.
 * `VICTIM`'s second member name is an escape decoding to one character too. On Node >= 24
 * `JSON.parse(VICTIM)` returns the backslash for it once `POISONER` has been parsed.
 */
const POISONER = '{"a":1,"\\\\":2}';
const VICTIM = '{"a":1,"\\ufb00":2}';

describe('parseCanonicalJson is a pure function of its text', () => {
  const keysOf = (text: string): string[] =>
    Object.keys(parseCanonicalJson(text) as Record<string, unknown>);

  it('the two documents really are different, so the check is not vacuous', () => {
    // Control. Were these two texts to name the same members, every assertion below would
    // hold no matter how badly the parser leaked state between calls.
    expect(POISONER).not.toBe(VICTIM);
    expect(keysOf(POISONER)).toEqual(['a', '\\']);
    expect(keysOf(VICTIM)).toEqual(['a', 'ﬀ']);
  });

  it('does not let one document rename a member of the next', () => {
    const before = keysOf(VICTIM);
    parseCanonicalJson(POISONER);
    expect(keysOf(VICTIM)).toEqual(before);
    expect(keysOf(VICTIM)).toEqual(['a', 'ﬀ']);
  });

  it('does not depend on the order documents are parsed in', () => {
    const documents = [
      POISONER,
      VICTIM,
      '{"a":1,"\\n":2}',
      '{"a":1,"\\"":2}',
      '{"a":1,"\\u0041":2}',
      '{"a":1,"\\ud83d\\ude00":2}',
    ];
    const forward = documents.map(keysOf);
    const backward = [...documents].reverse().map(keysOf).reverse();
    expect(backward).toEqual(forward);
    // And each is genuinely its own name, not a neighbour's.
    expect(forward).toEqual([
      ['a', '\\'],
      ['a', 'ﬀ'],
      ['a', '\n'],
      ['a', '"'],
      ['a', 'A'],
      ['a', '\u{1F600}'],
    ]);
  });

  it('canonicalizes the victim to the same bytes whatever ran before it', () => {
    const alone = decodeUtf8(canonicalJsonBytes(parseCanonicalJson(VICTIM)));
    parseCanonicalJson(POISONER);
    expect(decodeUtf8(canonicalJsonBytes(parseCanonicalJson(VICTIM)))).toBe(alone);
    expect(alone).toBe('{"a":1,"ﬀ":2}');
  });
});

// --------------------------------------------------------------------------------------
// Parity with JSON.parse on everything the engine relies on
// --------------------------------------------------------------------------------------

describe('the parser reproduces the facts the engine judges', () => {
  it('keeps an unpaired surrogate escape unpaired, as json.loads does', () => {
    const parsed = parseCanonicalJson('{"s":"\\ud800"}') as Record<string, string>;
    expect(parsed['s']).toHaveLength(1);
    expect(parsed['s']?.charCodeAt(0)).toBe(0xd800);
  });

  it('pairs a surrogate pair escape into one astral code point', () => {
    const parsed = parseCanonicalJson('{"s":"\\ud83d\\ude00"}') as Record<string, string>;
    expect(parsed['s']).toBe('\u{1F600}');
  });

  it('stores __proto__ as data rather than reassigning the prototype', () => {
    const parsed = parseCanonicalJson('{"__proto__":{"polluted":true}}') as Record<
      string,
      unknown
    >;
    expect(Object.keys(parsed)).toEqual(['__proto__']);
    expect(Object.getPrototypeOf(parsed)).toBe(Object.prototype);
    expect((({}) as Record<string, unknown>)['polluted']).toBeUndefined();
  });

  it('gives a repeated member name its first position and its last value', () => {
    const parsed = parseCanonicalJson('{"a":1,"b":2,"a":3}') as Record<string, unknown>;
    expect(Object.keys(parsed)).toEqual(['a', 'b']);
    expect(parsed['a']).toBe(3);
  });

  it('reads the short escapes and every whitespace form', () => {
    expect(parseCanonicalJson('{"s":"\\"\\\\\\/\\b\\f\\n\\r\\t"}')).toEqual({
      s: '"\\/\b\f\n\r\t',
    });
    expect(parseCanonicalJson(' \t\r\n{ "a" : [ 1 , 2 ] } \t\r\n')).toEqual({ a: [1, 2] });
  });

  it('reads the empty containers and nesting', () => {
    expect(parseCanonicalJson('{}')).toEqual({});
    expect(parseCanonicalJson('[]')).toEqual([]);
    expect(parseCanonicalJson('[{},[[]],null,true,false]')).toEqual([{}, [[]], null, true, false]);
  });

  it('reads the number forms, signed zero included', () => {
    expect(parseCanonicalJson('[0,-0,1e3,1E+3,1e-3,-1.5,0.5]')).toEqual([
      0, -0, 1000, 1000, 0.001, -1.5, 0.5,
    ]);
    expect(Object.is(parseCanonicalJson('-0'), -0)).toBe(true);
  });

  it.each([
    ['{"a":1,}', 'a trailing comma in an object'],
    ['[1,]', 'a trailing comma in an array'],
    ['{"a":01}', 'a leading zero'],
    ['{"a":+1}', 'a leading plus'],
    ['{"a":.5}', 'a bare fraction'],
    ['{"a":1.}', 'a trailing decimal point'],
    ['{"a":1e}', 'an empty exponent'],
    ['{"a":NaN}', 'NaN'],
    ['{"a":Infinity}', 'Infinity'],
    ["{'a':1}", 'single quotes'],
    ['{a:1}', 'an unquoted member name'],
    ['{"a":1}{"b":2}', 'a second document'],
    ['{"a":"\\x41"}', 'an unknown escape'],
    ['{"a":"\\u00zz"}', 'a malformed \\u escape'],
    ['{"a":"unterminated}', 'an unterminated string'],
    ['', 'the empty document'],
    ['   ', 'whitespace only'],
  ])('refuses %p — %s', (text) => {
    expect(() => parseCanonicalJson(text)).toThrow(SyntaxError);
  });

  /**
   * The escape whitelist, stated as a whitelist.
   *
   * `\x41` alone left this open: it proves ONE unknown escape is refused, not that the set
   * is closed. A parser that also accepted `\v` -- which JavaScript string literals do and
   * JSON does not -- passed the whole suite. JSON defines exactly nine escape openers.
   */
  it.each([
    ['"', '"'],
    ['\\\\', '\\'],
    ['\\/', '/'],
    ['\\b', '\b'],
    ['\\f', '\f'],
    ['\\n', '\n'],
    ['\\r', '\r'],
    ['\\t', '\t'],
  ] as [string, string][])('accepts the escape \\%s', (source, decoded) => {
    const literal = source === '"' ? '\\"' : source;
    expect(parseCanonicalJson(`{"a":"${literal}"}`)).toEqual({ a: decoded });
  });

  it.each(['v', '0', 'a', 'e', "'", 'U', 'x', '\n'])(
    'refuses the escape \\%s, which JSON does not define',
    (opener) => {
      expect(() => parseCanonicalJson(`{"a":"\\${opener}"}`)).toThrow(SyntaxError);
    },
  );

  /**
   * The whitespace set, stated as a whitelist too.
   *
   * Asserting that space/tab/CR/LF are ACCEPTED does not pin that anything else is
   * REJECTED: a parser treating U+00A0 as whitespace passed the whole suite. Every
   * character below is DATA in JSON, and a document padded with one is malformed.
   */
  it.each([
    ['U+00A0 no-break space', '\u00a0'],
    ['U+FEFF byte-order mark', '\ufeff'],
    ['U+000B vertical tab', '\u000b'],
    ['U+000C form feed', '\u000c'],
    ['U+2028 line separator', '\u2028'],
    ['U+3000 ideographic space', '\u3000'],
  ])('refuses %s as a token separator', (_name, character) => {
    expect(() => parseCanonicalJson(`${character}{"a":1}`)).toThrow(SyntaxError);
    expect(() => parseCanonicalJson(`{"a":1}${character}`)).toThrow(SyntaxError);
    expect(() => parseCanonicalJson(`{"a":${character}1}`)).toThrow(SyntaxError);
  });

  /**
   * Nesting depth: a DEPARTURE from `JSON.parse`, pinned so it cannot drift silently.
   *
   * Recursive descent exhausts the JavaScript stack where V8's iterative parser does not,
   * and it does so with a `RangeError` rather than the `SyntaxError` every other refusal
   * raises. The exact limit moves with the ambient stack, so this pins the CLASS, not a
   * number: shallow nesting parses, and absurd nesting fails loudly rather than returning
   * a truncated value.
   */
  it('parses nesting deeper than anything this repository commits', () => {
    const depth = 500; // the deepest committed schema nests 14
    expect(parseCanonicalJson('['.repeat(depth) + ']'.repeat(depth))).toBeInstanceOf(Array);
  });

  it('fails loudly rather than silently truncating absurd nesting', () => {
    const depth = 200_000;
    let thrown: unknown;
    try {
      parseCanonicalJson('['.repeat(depth) + ']'.repeat(depth));
    } catch (error) {
      thrown = error;
    }
    expect(thrown).toBeInstanceOf(RangeError);
  });

  it('refuses a raw control character inside a string', () => {
    // Built from a code unit rather than written literally: a raw U+0001 in this source
    // file would be stripped by the repository's whitespace hygiene gate, and the test
    // would then assert nothing.
    const text = `{"a":"${String.fromCharCode(0x01)}"}`;
    expect(() => parseCanonicalJson(text)).toThrow(SyntaxError);
    expect(() => parseCanonicalJson(text)).toThrow(/U\+0001/);
  });
});

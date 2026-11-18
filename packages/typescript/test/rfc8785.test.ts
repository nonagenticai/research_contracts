/**
 * RFC 8785 conformance, against committed vectors whose expected values come from a native
 * ECMAScript oracle rather than from either implementation.
 *
 * 34 checks: 32 IEEE-754 number vectors + 2 structural samples.
 */

import { createHash } from 'node:crypto';

import { canonicalJsonBytes } from '../src/engine';
import { compareUtf16CodeUnits, esNumberToString, utf16SortKey } from '../src/jcs';
import { parseCanonicalJson } from '../src/json';
import { RFC_DIR, decodeUtf8, load } from './fixtures';
import { join } from 'node:path';

interface NumberVectors {
  vectors: { ieee754_hex: string; expected: string }[];
}

interface StructuralFixture {
  source: string;
  expected_canonical_json: string;
  expected_sha256: string;
  expected_key_order?: string[];
  contains_binary_floats: boolean;
}

const NUMBER_FLOOR = 32;
const STRUCTURAL_FILES = ['structural-sample.json', 'property-name-ordering.json'] as const;
const RFC_CHECK_FLOOR = NUMBER_FLOOR + STRUCTURAL_FILES.length; // 34

/** Decode an exact IEEE-754 double from its 16-hex-digit big-endian representation. */
function doubleFromHex(hex: string): number {
  const view = new DataView(new ArrayBuffer(8));
  for (let index = 0; index < 8; index += 1) {
    view.setUint8(index, Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16));
  }
  return view.getFloat64(0, false);
}

function sha256Prefixed(bytes: Uint8Array): string {
  return `sha256:${createHash('sha256').update(bytes).digest('hex')}`;
}

const numbers = load<NumberVectors>(join(RFC_DIR, 'number-serialization.json'));

describe('RFC 8785 conformance', () => {
  it(`replays ${RFC_CHECK_FLOOR} checks`, () => {
    expect(numbers.vectors.length).toBe(NUMBER_FLOOR);
    expect(numbers.vectors.length + STRUCTURAL_FILES.length).toBe(RFC_CHECK_FLOOR);
  });

  it('serializes every IEEE-754 vector exactly as the ECMAScript oracle does', () => {
    const mismatches: [string, string, string][] = [];
    for (const entry of numbers.vectors) {
      const rendered = esNumberToString(doubleFromHex(entry.ieee754_hex));
      if (rendered !== entry.expected) {
        mismatches.push([entry.ieee754_hex, entry.expected, rendered]);
      }
    }
    expect(mismatches).toEqual([]);
  });

  it.each(STRUCTURAL_FILES)('%s is reproduced byte-for-byte', (name) => {
    const fixture = load<StructuralFixture>(join(RFC_DIR, name));
    const document = parseCanonicalJson(fixture.source);
    const canonical = canonicalJsonBytes(document, {
      allowBinaryFloat: fixture.contains_binary_floats,
    });
    expect(decodeUtf8(canonical)).toBe(fixture.expected_canonical_json);
    expect(sha256Prefixed(canonical)).toBe(fixture.expected_sha256);
  });

  it('orders property names by UTF-16 code unit, which is not code-point order', () => {
    const fixture = load<StructuralFixture>(join(RFC_DIR, 'property-name-ordering.json'));
    const document = parseCanonicalJson(fixture.source) as Record<string, unknown>;
    const names = Object.keys(document);

    expect([...names].sort(compareUtf16CodeUnits)).toEqual(fixture.expected_key_order);

    // Native `.sort()` IS UTF-16 code-unit order. The explicit comparator exists to be
    // inspectable and perturbable, not because the native one is wrong.
    expect([...names].sort()).toEqual(fixture.expected_key_order);

    // The discriminating pair, stated explicitly: U+1F602 (surrogate lead D83D) against
    // U+FB33. Code-unit order puts the astral character FIRST; code-point order does not.
    const astral = '\u{1F602}';
    const bmp = 'דּ';
    expect(compareUtf16CodeUnits(astral, bmp)).toBeLessThan(0);
    expect(astral.codePointAt(0)).toBeGreaterThan(bmp.codePointAt(0) as number);

    const codePointOrder = [...names].sort((left, right) => {
      const a = Array.from(left).map((c) => c.codePointAt(0) ?? 0);
      const b = Array.from(right).map((c) => c.codePointAt(0) ?? 0);
      for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
        if (a[index] !== b[index]) {
          return a[index] - b[index];
        }
      }
      return a.length - b.length;
    });
    expect(codePointOrder).not.toEqual(fixture.expected_key_order);
  });

  it('agrees with the Python UTF-16BE byte key on every fixture name', () => {
    const fixture = load<StructuralFixture>(join(RFC_DIR, 'property-name-ordering.json'));
    const names = Object.keys(parseCanonicalJson(fixture.source) as Record<string, unknown>);
    const byBytes = [...names].sort((left, right) => {
      const a = utf16SortKey(left);
      const b = utf16SortKey(right);
      for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
        if (a[index] !== b[index]) {
          return a[index] - b[index];
        }
      }
      return a.length - b.length;
    });
    expect(byBytes).toEqual(fixture.expected_key_order);
  });

  it('emits UTF-8 without a byte-order mark', () => {
    const canonical = canonicalJsonBytes({ '€': '\u{1F602}' });
    expect(Array.from(canonical.slice(0, 3))).not.toEqual([0xef, 0xbb, 0xbf]);
    expect(decodeUtf8(canonical)).toBe('{"€":"\u{1F602}"}');
  });
});

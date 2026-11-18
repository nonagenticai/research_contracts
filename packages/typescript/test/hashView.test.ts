/**
 * Hash-view construction rules that no golden vector on its own pins.
 *
 * The headline case is the SET-MEMBER ORDER. Object member names sort by UTF-16 code unit
 * and set-like array members sort by the raw UTF-8 bytes of their canonical order key.
 * Those are different orders, and a port that reuses the member-name comparison for set
 * members produces a different array order, different canonical bytes and a different
 * digest -- silently, on data no existing committed vector contained.
 */

import { buildHashView, escapeToken, pointerAt, ABSENT, type HashProfile } from '../src/hashView';
import { canonicalizeToString } from '../src/jcs';
import { canonicalSha256 } from '../src/engine';
import { deriveHashProfile } from '../src/hashProfile';
import { UndeclaredArrayError, UndeclaredPathError } from '../src/errors';
import { mergeProfileExtensions } from '../src/hashProfile';
import { VECTOR_DIR, load, profileFor, vector, type VectorFixture } from './fixtures';
import { join } from 'node:path';

const PUA = '\ue000'; // U+E000, private use, three UTF-8 bytes EE 80 80
const ASTRAL = '\u{10000}'; // U+10000, four UTF-8 bytes F0 90 80 80, UTF-16 D800 DC00

function memberProfile(orderKey: string[]): HashProfile {
  return {
    ...deriveHashProfile('urn:datacompany:stable-identity:1'),
    included_pointers: ['/members', '/members/-', '/members/-/k'],
    excluded_pointers: [],
    opaque_pointers: [],
    arrays: [{ pointer: '/members', kind: 'set', order_key: orderKey }],
  };
}

describe('set-like members sort by UTF-8 bytes, not by UTF-16 code units', () => {
  const profile = memberProfile(['/k']);
  const members = [{ k: PUA }, { k: ASTRAL }, { k: 'a' }];

  it('orders by code point, which is what the Python reference produces', () => {
    const view = buildHashView({ members }, profile) as Record<string, { k: string }[]>;
    expect(view['members'].map((member) => member.k)).toEqual(['a', PUA, ASTRAL]);
  });

  it('is NOT the order a native JavaScript string sort would give', () => {
    // The bug this test exists to catch: decoding the canonical key bytes to a string and
    // calling `.sort()` puts the astral member SECOND, because its surrogate lead D800
    // precedes U+E000 as a code unit.
    const wrong = [PUA, ASTRAL, 'a'].sort();
    expect(wrong).toEqual(['a', ASTRAL, PUA]);
    expect(wrong).not.toEqual(['a', PUA, ASTRAL]);
  });

  it('produces different canonical bytes under the two orders', () => {
    const right = canonicalizeToString([{ k: 'a' }, { k: PUA }, { k: ASTRAL }]);
    const wrong = canonicalizeToString([{ k: 'a' }, { k: ASTRAL }, { k: PUA }]);
    expect(right).not.toBe(wrong);
    expect(canonicalSha256([{ k: 'a' }, { k: PUA }, { k: ASTRAL }])).not.toBe(
      canonicalSha256([{ k: 'a' }, { k: ASTRAL }, { k: PUA }]),
    );
  });

  it('is pinned by a committed golden vector generated from the Python reference', () => {
    const fixture = load<VectorFixture & { expected_set_member_order: string[] }>(
      join(VECTOR_DIR, 'set-like-array-astral-vs-private-use-order-key.json'),
    );
    expect(fixture.expected_set_member_order).toEqual(['a', PUA, ASTRAL]);
    const view = buildHashView(fixture.instance, profileFor(fixture)) as Record<string, unknown>;
    const tags = (view['value'] as Record<string, { id: string }[]>)['tags'];
    expect(tags.map((tag) => tag.id)).toEqual(fixture.expected_set_member_order);
  });

  it('keeps the duplicate check and the ordering on separate representations', () => {
    // The duplicate map is keyed by decoded TEXT; ordering uses raw BYTES. Two members
    // whose keys differ only in astral-ness must still be two members.
    const view = buildHashView({ members: [{ k: ASTRAL }, { k: PUA }] }, profile) as Record<
      string,
      { k: string }[]
    >;
    expect(view['members']).toHaveLength(2);
  });
});

describe('pointerAt is dict-only, deliberately', () => {
  it('cannot descend into an array', () => {
    expect(pointerAt({ a: [1, 2] }, '/a/0')).toBe(ABSENT);
    expect(pointerAt({ a: { '0': 'x' } }, '/a/0')).toBe('x');
  });

  it('distinguishes absent from an explicit null', () => {
    expect(pointerAt({ a: null }, '/a')).toBeNull();
    expect(pointerAt({}, '/a')).toBe(ABSENT);
  });

  it('does not walk the prototype chain', () => {
    expect(pointerAt({}, '/toString')).toBe(ABSENT);
    expect(pointerAt({}, '/constructor')).toBe(ABSENT);
  });

  it('unescapes ~1 and ~0 in that order', () => {
    expect(pointerAt({ 'a/b': 1 }, '/a~1b')).toBe(1);
    expect(pointerAt({ 'a~b': 1 }, '/a~0b')).toBe(1);
    expect(pointerAt({ 'a~1b': 1 }, '/a~01b')).toBe(1);
  });
});

describe('escapeToken escapes ~ before /', () => {
  it.each([
    ['a/b', 'a~1b'],
    ['a~b', 'a~0b'],
    ['a~1b', 'a~01b'],
    ['plain', 'plain'],
  ])('escapes %p to %p', (token, expected) => {
    expect(escapeToken(token)).toBe(expected);
  });
});

describe('declare none or declare all', () => {
  it('hashes an explicitly opaque subtree whole', () => {
    const fixture = vector('decimal-carried-as-string');
    const profile = deriveHashProfile(fixture.schema_ref);
    expect(profile.opaque_pointers).toEqual(['/value']);
  });

  it('refuses an object that is neither declared nor opaque', () => {
    const fixture = vector('decimal-carried-as-string');
    const undeclared: HashProfile = {
      ...deriveHashProfile(fixture.schema_ref),
      opaque_pointers: [],
    };
    expect(() => buildHashView(fixture.instance, undeclared)).toThrow(UndeclaredPathError);
    expect(() => buildHashView(fixture.instance, undeclared)).toThrow(
      /neither this object's members nor/,
    );
  });

  it('forces every sibling to be declared once one payload member is', () => {
    const fixture = vector('decimal-carried-as-string');
    const partial = mergeProfileExtensions(deriveHashProfile(fixture.schema_ref), {
      included_pointers: ['/value/note'],
    });
    expect(() => buildHashView(fixture.instance, partial)).toThrow(/\/value\/measurement/);
  });

  it('still demands a collection kind for an array inside an opaque subtree', () => {
    const fixture = vector('decimal-carried-as-string');
    const instance = { ...fixture.instance, value: { steps: ['a', 'b'] } };
    const profile = deriveHashProfile(fixture.schema_ref);
    expect(profile.opaque_pointers).toEqual(['/value']);
    expect(() => buildHashView(instance, profile)).toThrow(UndeclaredArrayError);
  });

  it('declares a collection inside an opaque subtree via an arrays-only extension', () => {
    // The green half of the rule above, mirroring the Python test of the same name.
    // Neither prefix set is built from `arrays`: `declaredPrefixes` is built from
    // included|excluded pointers and `includedPrefixes` -- the one the OPACITY decision
    // consults -- from included pointers alone. So an `arrays`-only extension supplies the
    // collection kind without adding a declared child: the subtree stays opaque and its
    // undeclared members still pass. The gap between these two halves is what the wave-2
    // register recorded as D4. (D4's recorded falsification recipe named `declaredPrefixes`;
    // since the opaque/exclusion defect was closed it is `includedPrefixes` that has to be
    // patched to turn this red -- see the precision note on D4 in
    // `config/foundation-decisions.json`.)
    const fixture = vector('decimal-carried-as-string');
    const instance = {
      ...fixture.instance,
      value: { steps: ['b', 'a'], note: 'undeclared, and still opaque' },
    };
    const profile = mergeProfileExtensions(deriveHashProfile(fixture.schema_ref), {
      arrays: [{ pointer: '/value/steps', kind: 'ordered' }],
    });
    expect(profile.opaque_pointers).toEqual(['/value']);
    expect(profile.included_pointers).not.toContain('/value/steps');
    const view = buildHashView(instance, profile) as Record<string, unknown>;
    expect(view.value).toEqual(instance.value);
  });

  it('declares an opaque payload that is itself an array', () => {
    // `/value` is typed object|array|..., so the opaque payload may BE the array.
    const fixture = vector('decimal-carried-as-string');
    const instance = { ...fixture.instance, value: ['b', 'a'] };
    const profile = mergeProfileExtensions(deriveHashProfile(fixture.schema_ref), {
      arrays: [{ pointer: '/value', kind: 'ordered' }],
    });
    const view = buildHashView(instance, profile) as Record<string, unknown>;
    expect(view.value).toEqual(['b', 'a']);
  });

  it('lets declared children WIN over an opaque declaration for the same subtree', () => {
    // `opaque = !declaredChildren && isDeclaredOpaque(pointer)`: declaring any child of an
    // opaque subtree turns the whole subtree back into declare-all.
    const fixture = vector('decimal-carried-as-string');
    const both = mergeProfileExtensions(deriveHashProfile(fixture.schema_ref), {
      included_pointers: ['/value/note'],
    });
    expect(both.opaque_pointers).toEqual(['/value']);
    expect(() => buildHashView(fixture.instance, both)).toThrow(UndeclaredPathError);
  });

  it('does not treat /ab as sitting under an opaque /a', () => {
    const profile: HashProfile = {
      ...deriveHashProfile('urn:datacompany:stable-identity:1'),
      included_pointers: ['/a', '/ab'],
      excluded_pointers: [],
      opaque_pointers: ['/a'],
      arrays: [],
    };
    // `/a` is opaque, so an undeclared member of it passes.
    expect(() => buildHashView({ a: { anything: 1 } }, profile)).not.toThrow();
    // `/ab` is a SIBLING, not a subtree of `/a`. A `startsWith('/a')` test without the
    // trailing slash would wrongly make it opaque and let its members through.
    expect(() => buildHashView({ a: { anything: 1 }, ab: { nope: 1 } }, profile)).toThrow(
      /^\/ab: the released hash-view manifest declares neither/,
    );
  });
});

describe('JavaScript-specific hazards', () => {
  it('stores a member literally named __proto__ as data', () => {
    const profile: HashProfile = {
      ...deriveHashProfile('urn:datacompany:stable-identity:1'),
      included_pointers: ['/__proto__', '/ok'],
      excluded_pointers: [],
      opaque_pointers: [],
      arrays: [],
    };
    const instance = JSON.parse('{"__proto__": "polluted", "ok": 1}') as Record<string, unknown>;
    expect(Object.hasOwn(instance, '__proto__')).toBe(true);
    const view = buildHashView(instance, profile);
    expect(canonicalizeToString(view)).toBe('{"__proto__":"polluted","ok":1}');
    // ...and nothing was assigned to any prototype on the way through.
    expect(Object.getPrototypeOf({})).toBe(Object.prototype);
  });

  it('normalizes -0 to 0 in the view', () => {
    const profile: HashProfile = {
      ...deriveHashProfile('urn:datacompany:stable-identity:1'),
      included_pointers: ['/n'],
      excluded_pointers: [],
      opaque_pointers: [],
      arrays: [],
    };
    const view = buildHashView({ n: -0 }, profile) as Record<string, number>;
    expect(Object.is(view['n'], 0)).toBe(true);
    expect(canonicalizeToString(view)).toBe('{"n":0}');
  });

  /**
   * DOCUMENTED DIVERGENCE, not a defect in the hash.
   *
   * `Object.keys` lists integer-like keys first, numerically, before insertion-ordered
   * string keys; a Python dict is pure insertion order. The canonical BYTES are unaffected
   * because member names are sorted anyway, but `buildObject` throws on the FIRST
   * undeclared member, so the two languages can name a different member in the error.
   */
  it('may report a different first undeclared member than Python does', () => {
    const instance = JSON.parse('{"b": 1, "2": 1}') as Record<string, unknown>;
    expect(Object.keys(instance)).toEqual(['2', 'b']);
    const profile: HashProfile = {
      ...deriveHashProfile('urn:datacompany:stable-identity:1'),
      included_pointers: ['/placeholder'],
      excluded_pointers: [],
      opaque_pointers: [],
      arrays: [],
    };
    expect(() => buildHashView(instance, profile)).toThrow(/^\/2: not declared/);
  });
});

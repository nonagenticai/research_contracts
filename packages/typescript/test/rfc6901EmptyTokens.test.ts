/**
 * An RFC 6901 reference token may be EMPTY, and `pointerAt` used to eat it.
 *
 * `pointerAt` tokenised with `pointer.replace(/^\/+/, '').split('/')`, the exact idiom
 * `hash_view.py` used with `pointer.lstrip("/")`. Stripping EVERY leading slash is not the
 * RFC 6901 tokenisation: section 4 says a reference token may be the empty string, which
 * addresses a member literally named `''` -- and `JSON.parse` produces such a member as an
 * ordinary own property. So `'//a'` is the two tokens `['', 'a']`, and stripped it became
 * the single token `['a']`.
 *
 * The released `hash_view_pointer` grammar ACCEPTS it: `^(/([^/~]|~[01])*)+$` with
 * `minLength: 2`, and `([^/~]|~[01])*` matches zero characters. A released manifest may
 * therefore declare an order key that the resolver could not read.
 *
 * It failed both ways, and one of them failed OPEN:
 *
 * - `pointerAt({a: 1}, '//a')` returned `1`. A member that does NOT carry the declared key
 *   was accepted, keyed on a member it happened to have under a different path.
 * - `pointerAt({'': {a: 1}}, '//a')` returned ABSENT. The member that DOES carry it was
 *   rejected.
 *
 * This is the TypeScript half of a CROSS-LANGUAGE fix. The Python half is
 * `tests/test_rfc6901_empty_reference_tokens.py`, and the two files assert the same facts
 * deliberately: the canonical hash is verified byte-equivalent between the two engines, so a
 * fix landed in one language only turns a shared defect into a divergence, which is worse.
 */

import { buildHashView, pointerAt, ABSENT, type HashProfile } from '../src/hashView';
import { deriveHashProfile } from '../src/hashProfile';
import { MissingOrderKeyError } from '../src/errors';

/** The member name an empty reference token addresses. Named because `''` is invisible. */
const EMPTY_NAME = '';

function setLikeProfile(orderKey: string[], included: string[]): HashProfile {
  return {
    ...deriveHashProfile('urn:datacompany:stable-identity:1'),
    included_pointers: included,
    excluded_pointers: [],
    opaque_pointers: [],
    arrays: [{ pointer: '/members', kind: 'set', order_key: orderKey }],
  };
}

describe('an empty RFC 6901 reference token is a member, not padding', () => {
  it('addresses the member named the empty string', () => {
    expect(pointerAt({ [EMPTY_NAME]: { a: 1 } }, '//a')).toBe(1);
    expect(pointerAt({ [EMPTY_NAME]: 5 }, '/')).toBe(5);
    expect(pointerAt({ [EMPTY_NAME]: { [EMPTY_NAME]: 7 } }, '//')).toBe(7);
  });

  it('does NOT resolve a member that lacks it -- the fail-open half', () => {
    // Before the fix this returned 1, so a member with no `''` member at all was accepted
    // as carrying the declared order key.
    expect(pointerAt({ a: 1 }, '//a')).toBe(ABSENT);
    expect(pointerAt({ a: { b: 1 } }, '//a/b')).toBe(ABSENT);
  });

  it('rejects a pointer with no leading slash', () => {
    // RFC 6901 section 3. Nothing that reaches here can be relative: `order_key_pointer` is
    // `hash_view_pointer` plus `''`. An unreadable order key must be an ABSENT order key.
    for (const pointer of ['a', 'a/b', '~0a']) {
      expect(pointerAt({ a: { b: 1 }, '~0a': 2 }, pointer)).toBe(ABSENT);
    }
  });

  it('still lets the whole-document pointer address the member itself', () => {
    // The D8 control: `''` is what makes a set of SCALARS declarable, and a fix that started
    // rejecting pointers without a leading slash must not take it along.
    expect(pointerAt('a scalar member', '')).toBe('a scalar member');
    expect(pointerAt({ a: 1 }, '')).toEqual({ a: 1 });
  });
});

describe('a set-like order key with an empty token, end to end', () => {
  it('rejects members that do not carry the declared key', () => {
    const profile = setLikeProfile(['//a'], ['/members', '/members/-', '/members/-/a']);
    expect(() => buildHashView({ members: [{ a: 'one' }, { a: 'two' }] }, profile)).toThrow(
      MissingOrderKeyError,
    );
  });

  it('orders the members that do carry it', () => {
    const profile = setLikeProfile(
      ['//a'],
      ['/members', '/members/-', '/members/-/', '/members/-//a'],
    );
    const members = { members: [{ [EMPTY_NAME]: { a: 'b' } }, { [EMPTY_NAME]: { a: 'a' } }] };
    const view = buildHashView(members, profile) as Record<
      string,
      Record<string, Record<string, string>>[]
    >;
    const keys = view['members'].map((member) => member[EMPTY_NAME]);
    expect(keys.map((key) => key?.['a'])).toEqual(['a', 'b']);
  });

  it('leaves an ordinary order key untouched', () => {
    // The control for every released manifest in the tree: no released order key contains an
    // empty token, so the fix must be a no-op for all of them.
    const profile = setLikeProfile(['/id'], ['/members', '/members/-', '/members/-/id']);
    const view = buildHashView({ members: [{ id: 'b' }, { id: 'a' }] }, profile) as Record<
      string,
      { id: string }[]
    >;
    expect(view['members'].map((member) => member.id)).toEqual(['a', 'b']);
  });
});

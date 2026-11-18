/**
 * Rejected hash inputs.
 *
 * The `rejected/*` fixtures name the expected failure by ERROR CLASS NAME, so this suite
 * resolves the class by name from the same taxonomy Python declares. A rename on either
 * side has to show up here.
 */

import { computeContentHash, verifyContentHash } from '../src/engine';
import { buildHashView } from '../src/hashView';
import { canonicalSha256 } from '../src/engine';
import { deriveHashProfile } from '../src/hashProfile';
import {
  CanonicalError,
  ContentHashMismatchError,
  DuplicateSetMemberError,
  MissingOrderKeyError,
  UndeclaredArrayError,
  UndeclaredPathError,
  UnknownExclusionError,
  UnstableFloatError,
} from '../src/errors';
import { validateSchemaOnly } from '../src/registry';
import type { HashProfile } from '../src/hashView';
import {
  REJECTED_DIR,
  clone,
  fixtureFiles,
  fixtureId,
  load,
  profileFor,
  vector,
  type RejectedFixture,
} from './fixtures';

const REJECTED_FLOOR = 3;

const ERROR_TYPES: Record<string, new (message: string) => CanonicalError> = {
  DuplicateSetMemberError,
  UndeclaredArrayError,
  UnstableFloatError,
  UnknownExclusionError,
  MissingOrderKeyError,
  UndeclaredPathError,
  ContentHashMismatchError,
};

const paths = fixtureFiles(REJECTED_DIR);

/** A minimal released-shaped manifest for a set-like array of objects. */
function setLikeProfile(orderKey: string[]): HashProfile {
  return {
    ...deriveHashProfile('urn:datacompany:stable-identity:1'),
    included_pointers: ['/members', '/members/-', '/members/-/id', '/members/-/label'],
    excluded_pointers: [],
    opaque_pointers: [],
    arrays: [{ pointer: '/members', kind: 'set', order_key: orderKey }],
  };
}

describe('rejected fixtures', () => {
  it(`discovers at least ${REJECTED_FLOOR} fixtures`, () => {
    expect(paths.length).toBeGreaterThanOrEqual(REJECTED_FLOOR);
  });

  it.each(paths.map((path) => [fixtureId(path), path] as const))(
    '%s fails with its named error class',
    (_id, path) => {
      const fixture = load<RejectedFixture>(path);
      const expected = ERROR_TYPES[fixture.expected_error];
      expect(expected).toBeDefined();
      let raised: unknown;
      try {
        computeContentHash(fixture.instance, fixture.schema_ref, {
          profile: profileFor(fixture),
        });
      } catch (error) {
        raised = error;
      }
      expect(raised).toBeInstanceOf(expected);
      expect((raised as Error).name).toBe(fixture.expected_error);
      expect((raised as Error).message).toContain(fixture.expected_message_contains);
    },
  );
});

describe('rejections the engine must make on constructed inputs', () => {
  it('rejects duplicate set-like members', () => {
    const fixture = vector('set-like-array-sorted-by-released-key');
    const instance = clone(fixture.instance);
    (
      (instance['value'] as Record<string, Record<string, string>[]>)['tags']
    ).push({ id: 'alpha', label: 'Alpha again' });
    expect(() =>
      computeContentHash(instance, fixture.schema_ref, { profile: profileFor(fixture) }),
    ).toThrow(DuplicateSetMemberError);
  });

  it('rejects duplicate pins that differ only in an EXCLUDED observation field', () => {
    // The hazard `uniqueItems` misses: same identity, different `resolved_at`.
    const fixture = vector('immutable-version-nested-pins');
    const instance = clone(fixture.instance);
    const pins = instance['pack_refs'] as Record<string, unknown>[];
    const twin = clone(pins[0]);
    twin['resolved_at'] = '2026-07-30T23:59:59Z';
    pins.push(twin);
    expect(validateSchemaOnly(instance, fixture.schema_ref)).toEqual([]);
    expect(() =>
      computeContentHash(instance, fixture.schema_ref, { profile: profileFor(fixture) }),
    ).toThrow(DuplicateSetMemberError);
  });

  it('rejects an array with no declared collection kind', () => {
    const fixture = vector('ordered-array-preserves-order');
    const profile = profileFor(fixture);
    const stripped: HashProfile = {
      ...profile,
      arrays: profile.arrays.filter((entry) => entry.kind !== 'ordered'),
    };
    expect(() =>
      computeContentHash(fixture.instance, fixture.schema_ref, { profile: stripped }),
    ).toThrow(UndeclaredArrayError);
  });

  it('rejects an unstable binary float', () => {
    const fixture = vector('decimal-carried-as-string');
    const instance = clone(fixture.instance);
    (instance['value'] as Record<string, unknown>)['measurement'] = 0.1;
    expect(() =>
      computeContentHash(instance, fixture.schema_ref, { profile: profileFor(fixture) }),
    ).toThrow(UnstableFloatError);
    expect(() => canonicalSha256({ measurement: 0.1 })).toThrow(UnstableFloatError);
  });

  it('rejects a non-integral double everywhere, not only through JCS', () => {
    const profile = setLikeProfile(['/id']);
    const view = buildHashView({ members: [{ id: 'a', label: 2.0 }] }, profile) as Record<
      string,
      Record<string, unknown>[]
    >;
    expect(view['members'][0]['label']).toBe(2);
    expect(Number.isInteger(view['members'][0]['label'])).toBe(true);
    expect(() => buildHashView({ members: [{ id: 'a', label: 0.1 }] }, profile)).toThrow(
      /binary_float_policy=reject/,
    );
  });

  it('rejects a hash-view path the manifest does not declare', () => {
    const fixture = vector('immutable-version-nested-pins');
    const instance = clone(fixture.instance);
    instance['smuggled'] = 'value';
    expect(() => buildHashView(instance, profileFor(fixture))).toThrow(UndeclaredPathError);
  });

  it('rejects a supplied content hash that does not recompute (DM-AT-29)', () => {
    const fixture = vector('immutable-version-nested-pins');
    const instance = clone(fixture.instance);
    instance['content_hash'] = `sha256:${'b'.repeat(64)}`;
    expect(() =>
      verifyContentHash(instance, fixture.schema_ref, { profile: profileFor(fixture) }),
    ).toThrow(/does not recompute/);

    instance['content_hash'] = fixture.expected_content_hash;
    expect(
      verifyContentHash(instance, fixture.schema_ref, { profile: profileFor(fixture) }),
    ).toBe(fixture.expected_content_hash);
  });

  it('does not silently accept an absent content hash', () => {
    const fixture = vector('immutable-version-nested-pins');
    const instance = clone(fixture.instance);
    delete instance['content_hash'];
    expect(() =>
      verifyContentHash(instance, fixture.schema_ref, { profile: profileFor(fixture) }),
    ).toThrow(CanonicalError);
  });

  it('rejects rather than defaults a verifiable shape with no supplied hash', () => {
    const fixture = vector('stable-identity-excluded-aggregate-version');
    expect(() => verifyContentHash(fixture.instance, fixture.schema_ref)).toThrow(/is absent/);
  });
});

describe('set-like order keys', () => {
  it('treats an absent order key as its own error, not a duplicate', () => {
    const profile = setLikeProfile(['/id']);
    expect(() =>
      buildHashView({ members: [{ label: 'one' }, { label: 'two' }] }, profile),
    ).toThrow(MissingOrderKeyError);
    expect(() =>
      buildHashView({ members: [{ label: 'one' }, { label: 'two' }] }, profile),
    ).toThrow(/does not carry the released order-key/);
  });

  it('names the missing path of a partially absent composite key', () => {
    const profile = setLikeProfile(['/id', '/label']);
    expect(() => buildHashView({ members: [{ id: 'a' }] }, profile)).toThrow(/\['\/label'\]/);
  });

  it('keeps two explicit-null order keys genuine duplicates', () => {
    const profile = setLikeProfile(['/id']);
    expect(() =>
      buildHashView(
        { members: [{ id: null, label: 'one' }, { id: null, label: 'two' }] },
        profile,
      ),
    ).toThrow(DuplicateSetMemberError);
  });

  it('sorts distinct order keys and accepts them', () => {
    const profile = setLikeProfile(['/id']);
    const view = buildHashView({ members: [{ id: 'b' }, { id: 'a' }] }, profile) as Record<
      string,
      Record<string, string>[]
    >;
    expect(view['members'].map((member) => member['id'])).toEqual(['a', 'b']);
  });
});

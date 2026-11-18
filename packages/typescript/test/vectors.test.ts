/**
 * Golden content-hash vectors.
 *
 * Every vector is asserted TWICE over: the canonical JSON must match byte-for-byte AND the
 * digest must match. A matching digest over a different canonical form is luck, not parity
 * -- SHA-256 collisions are not the failure mode, a fixture regenerated from the wrong
 * implementation is.
 */

import { canonicalJsonBytes, canonicalSha256, computeContentHash } from '../src/engine';
import { buildHashView } from '../src/hashView';
import { validateSchemaOnly } from '../src/registry';
import { validateInstance } from '../src/validation';
import {
  VECTOR_DIR,
  clone,
  decodeUtf8,
  fixtureFiles,
  fixtureId,
  hashOf,
  load,
  profileFor,
  vector,
  type VectorFixture,
} from './fixtures';

/**
 * The floor the Python suite replays. Raising it is a deliberate act: a new fixture must
 * be a new proof, never a quiet renumbering.
 *
 * 15 committed vectors + `set-like-array-astral-vs-private-use-order-key`, added by this
 * workstream to pin the UTF-8-byte set-member order that no existing vector covered.
 */
const VECTOR_FLOOR = 16;

const paths = fixtureFiles(VECTOR_DIR);

describe('golden content-hash vectors', () => {
  it(`discovers at least ${VECTOR_FLOOR} fixtures`, () => {
    expect(paths.length).toBeGreaterThanOrEqual(VECTOR_FLOOR);
  });

  it.each(paths.map((path) => [fixtureId(path), path] as const))(
    '%s reproduces the canonical bytes and the digest',
    (_id, path) => {
      const fixture = load<VectorFixture>(path);
      // Both layers, since `structural.ts` landed: the schema layer AND the released
      // cross-field rules. Asserting only the first would let a golden vector that breaks
      // an interval or equality invariant still be hashed and still read green.
      expect(validateSchemaOnly(fixture.instance, fixture.schema_ref)).toEqual([]);
      expect(validateInstance(fixture.instance, fixture.schema_ref)).toEqual([]);

      const profile = profileFor(fixture);
      const view = buildHashView(fixture.instance, profile);
      const canonical = canonicalJsonBytes(view);

      expect(decodeUtf8(canonical)).toBe(fixture.expected_hash_view_canonical_json);
      expect(canonicalSha256(view)).toBe(fixture.expected_content_hash);
      expect(
        computeContentHash(fixture.instance, fixture.schema_ref, { profile }),
      ).toBe(fixture.expected_content_hash);
    },
  );

  it('covers every required hash axis', () => {
    const covered = new Set<string>();
    for (const path of paths) {
      for (const axis of load<VectorFixture>(path).axis ?? []) {
        covered.add(axis);
      }
    }
    for (const required of [
      'unicode',
      'key-ordering',
      'decimals',
      'timestamps',
      'absent-vs-null',
      'ordered-arrays',
      'set-like-arrays',
      'nested-pinned-refs',
      'excluded-fields',
    ]) {
      expect(covered).toContain(required);
    }
  });
});

describe('the axes the vectors exist to pin', () => {
  it('drops every excluded field from the hash view', () => {
    const fixture = vector('immutable-version-nested-pins');
    const view = buildHashView(fixture.instance, profileFor(fixture)) as Record<string, unknown>;
    expect(Object.hasOwn(view, 'content_hash')).toBe(false);
    expect(Object.hasOwn(view, 'content_hash_signatures')).toBe(false);
    expect(Object.hasOwn(view['profile_ref'] as object, 'resolved_at')).toBe(false);
    for (const pin of view['pack_refs'] as Record<string, unknown>[]) {
      expect(Object.hasOwn(pin, 'resolved_at')).toBe(false);
    }
  });

  it('keeps NESTED target content hashes: only the subject’s own one is removed', () => {
    const fixture = vector('immutable-version-nested-pins');
    const view = buildHashView(fixture.instance, profileFor(fixture)) as Record<
      string,
      Record<string, string>
    >;
    expect(view['profile_ref']['content_hash']).toMatch(/^sha256:/);
    expect(view['decision_ref']['content_hash']).toMatch(/^sha256:/);
    for (const pin of view['pack_refs'] as unknown as Record<string, string>[]) {
      expect(pin['content_hash']).toMatch(/^sha256:/);
    }
  });

  it('is unchanged by signatures over the content hash', () => {
    expect(hashOf(vector('immutable-version-excluded-signatures'))).toBe(
      hashOf(vector('immutable-version-nested-pins')),
    );
  });

  it('is unchanged by the input order of a set-like array', () => {
    expect(hashOf(vector('set-like-array-input-order-reversed'))).toBe(
      hashOf(vector('set-like-array-sorted-by-released-key')),
    );
  });

  it('sorts a set-like array by its released canonical key', () => {
    const fixture = vector('set-like-array-input-order-reversed');
    const view = buildHashView(fixture.instance, profileFor(fixture)) as Record<string, unknown>;
    const tags = (view['value'] as Record<string, Record<string, string>[]>)['tags'];
    expect(tags.map((tag) => tag['id'])).toEqual(['alpha', 'mu', 'zeta']);
  });

  it('keeps an ordered array in its exact order', () => {
    const fixture = vector('ordered-array-preserves-order');
    const view = buildHashView(fixture.instance, profileFor(fixture)) as Record<string, unknown>;
    expect((view['value'] as Record<string, unknown>)['steps']).toEqual([
      'screen',
      'confirm',
      'treat',
    ]);
  });

  it('treats an absent member and an explicit null as distinct', () => {
    expect(hashOf(vector('absent-vs-explicit-null-absent'))).not.toBe(
      hashOf(vector('absent-vs-explicit-null-explicit')),
    );
  });

  it('applies no undeclared Unicode normalization', () => {
    const precomposed = vector('unicode-no-undeclared-normalization-precomposed');
    const decomposed = vector('unicode-no-undeclared-normalization-decomposed');
    const left = (precomposed.instance['value'] as Record<string, string>)['text'];
    const right = (decomposed.instance['value'] as Record<string, string>)['text'];
    expect(left).not.toBe(right);
    expect(right.normalize('NFC')).toBe(left);
    expect(hashOf(precomposed)).not.toBe(hashOf(decomposed));
  });

  it('carries a decimal as a string in the hash view', () => {
    const fixture = vector('decimal-carried-as-string');
    const view = buildHashView(fixture.instance, profileFor(fixture)) as Record<string, unknown>;
    const measurement = (view['value'] as Record<string, unknown>)['measurement'];
    expect(measurement).toBe('0.30000000000000004');
    expect(typeof measurement).toBe('string');
  });

  it('emits U+2028 and U+2029 literally in the golden separator vector', () => {
    const fixture = vector('unicode-line-and-paragraph-separator');
    const canonical = fixture.expected_hash_view_canonical_json;
    expect(canonical).toContain('\u2028');
    expect(canonical).toContain('\u2029');
    expect(canonical).not.toContain('\\u2028');
    expect(canonical).not.toContain('\\u2029');
    expect(hashOf(fixture)).toBe(fixture.expected_content_hash);
  });

  it('hashes an integral double as the integer it is', () => {
    const fixture = vector('immutable-version-nested-pins');
    const asFloat = clone(fixture.instance);
    // JSON has one number type; a peer language that parses `3` as `3.0` must not diverge.
    asFloat['version_number'] = Number(asFloat['version_number']) + 0.0;
    expect(validateSchemaOnly(asFloat, fixture.schema_ref)).toEqual([]);
    expect(hashOf({ ...fixture, instance: asFloat })).toBe(fixture.expected_content_hash);
  });
});

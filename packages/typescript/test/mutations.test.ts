/**
 * DM-AT-28 negative mutation tests.
 *
 * Each case names a committed base vector, applies pointer mutations to its instance and
 * declares whether the canonical content hash must change or must not. "Must not change" is
 * the harder half: it proves the excluded paths really are excluded.
 */

import { computeContentHash } from '../src/engine';
import { validateSchemaOnly } from '../src/registry';
import {
  MUTATION_DIR,
  clone,
  fixtureFiles,
  fixtureId,
  hashOf,
  load,
  profileFor,
  setPointer,
  vector,
  type MutationFixture,
} from './fixtures';

const MUTATION_FLOOR = 8;

const paths = fixtureFiles(MUTATION_DIR);

describe('mutation cases', () => {
  it(`discovers at least ${MUTATION_FLOOR} fixtures`, () => {
    expect(paths.length).toBeGreaterThanOrEqual(MUTATION_FLOOR);
  });

  it.each(paths.map((path) => [fixtureId(path), path] as const))(
    '%s changes or preserves the hash as declared',
    (_id, path) => {
      const testCase = load<MutationFixture>(path);
      const base = vector(testCase.base_fixture);
      const original = hashOf(base);
      expect(original).toBe(base.expected_content_hash);

      const mutated = clone(base.instance);
      for (const mutation of testCase.mutations) {
        setPointer(mutated, mutation.pointer, mutation.value);
      }
      expect(validateSchemaOnly(mutated, base.schema_ref)).toEqual([]);

      const mutatedHash = computeContentHash(mutated, base.schema_ref, {
        profile: profileFor(base),
      });
      if (testCase.expect === 'unchanged') {
        expect(mutatedHash).toBe(original);
      } else {
        expect(mutatedHash).not.toBe(original);
      }
    },
  );

  it('has an unchanged case for every excluded field class', () => {
    const covered = new Set<string>();
    for (const path of paths) {
      const testCase = load<MutationFixture>(path);
      if (testCase.expect !== 'unchanged') {
        continue;
      }
      for (const mutation of testCase.mutations) {
        covered.add(mutation.pointer.split('/').pop() as string);
      }
    }
    for (const field of ['resolved_at', 'aggregate_version', 'recorded_until', 'content_hash']) {
      expect(covered).toContain(field);
    }
  });
});

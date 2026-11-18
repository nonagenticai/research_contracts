/**
 * The two operator divergences EXTENSIONS.md recorded, replayed in the second language.
 *
 * Both were DERIVED rather than decided, and neither needed new normative semantics.
 *
 * Section 4.2 -- what `equal` means across languages. The document already prescribed the
 * answer: "A second implementation MUST use RFC 8785 canonical-byte equality, which agrees
 * with Python on every value the released schemas permit and is the same comparator
 * `unique_by` and `disjoint` are being moved to (D1)." The PYTHON engine used `==`, where
 * `bool` is an `int`, so `{"left": true, "right": 1}` was reported as HOLDING there and
 * VIOLATED here -- this port had already moved to canonical bytes. That is the divergence
 * these vectors close, and it was live rather than hypothetical.
 *
 * Section 4.5 -- a member missing its key was reported by `unique_by` and skipped in silence
 * by `disjoint`, in BOTH engines, so "the two sets are disjoint" could be true by vacuity one
 * member at a time. `hashView` had already decided the identical question fail-closed in
 * released code (`MissingOrderKeyError`), so `disjoint` was aligned onto `unique_by`.
 *
 * Section 9 is why this is one committed record replayed twice rather than two suites: a
 * closure in one language derives a result the other cannot, which is a cross-language split.
 * Every expected string below comes out of
 * `fixtures/canonical-cross-field/v1/operator-vectors.json`, whose failure lists were read
 * out of the Python engine, and they are compared element by element and in order. Python's
 * mirror is `tests/test_cross_field_operator_vectors.py`, over the same bytes.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { REPOSITORY_ROOT, canonicalSchemas } from '../src/registry';
import {
  collectCrossFieldRules,
  evaluateCrossFieldRules,
  resetCrossFieldCache,
} from '../src/structural';

interface VectorCase {
  readonly name: string;
  readonly section: string;
  readonly divergence: string;
  readonly probe_schema: Record<string, unknown> & { $id: string };
  readonly instance: unknown;
  readonly expect: {
    readonly failures: readonly string[];
    /** Present only on a DECLARED per-engine divergence; see `expectedFor` below. */
    readonly failures_port?: readonly string[];
    readonly port_divergence?: string;
  };
}

/**
 * What THIS engine must produce for a case.
 *
 * Every vector but one is shared. The exception is not an engine defect and no engine change
 * removes it: `JSON.parse` collapses an integer literal outside the exact IEEE-754 double
 * range to the nearest double before this code runs, so `9007199254740993` arrives as
 * `9007199254740992` and canonicalizes cleanly, where Python's `json.loads` yields the exact
 * `int` and RFC 8785 refuses it. The two PARSERS disagree; the two engines do not.
 */
function expectedFor(testCase: VectorCase): readonly string[] {
  return testCase.expect.failures_port ?? testCase.expect.failures;
}

const RECORD = JSON.parse(
  readFileSync(
    join(REPOSITORY_ROOT, 'fixtures', 'canonical-cross-field', 'v1', 'operator-vectors.json'),
    'utf-8',
  ),
) as { readonly sections: readonly string[]; readonly cases: readonly VectorCase[] };

/**
 * An EQUALITY, mirroring Python's `EXPECTED_CASES`. A vector appearing is as much a change to
 * what is measured as one disappearing, and a floor cannot catch the first.
 */
const EXPECTED_CASES = 23;

/**
 * Per section: [vectors expecting a FAILURE, vectors expecting NONE] as the RECORD states
 * them, mirroring Python's `EXPECTED_PER_SECTION`. EXACT, for the same reason
 * `EXPECTED_CASES` is: these were floors, the floors were then quoted as a count, and the
 * count was wrong -- "six expect no failure" when the answer is five. A floor is not the
 * number, so nobody can read the number off it.
 */
const EXPECTED_PER_SECTION: Record<string, readonly [number, number]> = {
  '4.2': [7, 3],
  '4.5': [11, 2],
};

/**
 * How many vectors may declare a different expectation for this engine, as an EQUALITY.
 * Mirrors Python's `EXPECTED_PORT_DIVERGENCES`. Pinning the COUNT is what stops the mechanism
 * becoming a way to launder a real divergence into the record: adding `failures_port` to a
 * second case is red until someone moves this number on purpose.
 */
const EXPECTED_PORT_DIVERGENCES = 1;

function withProbe<T>(schema: Record<string, unknown> & { $id: string }, body: () => T): T {
  const schemas = canonicalSchemas() as Map<string, unknown>;
  schemas.set(schema.$id, schema);
  resetCrossFieldCache();
  try {
    return body();
  } finally {
    schemas.delete(schema.$id);
    resetCrossFieldCache();
  }
}

/**
 * The four ways a weakened replay assertion would still read green, as `(expected, actual)`
 * predicates. Each is a spelling the replay above could have been written in; each is applied
 * below to a real engine result that has been broken.
 */
const WEAKER_COMPARISONS: Record<
  string,
  (want: readonly string[], actual: readonly string[]) => boolean
> = {
  'set equality (blind to order)': (want, actual) =>
    new Set(want).size === new Set(actual).size && want.every((item) => actual.includes(item)),
  'containment (blind to an extra failure)': (want, actual) =>
    want.every((item) => actual.includes(item)),
  'count only (blind to every word)': (want, actual) => want.length === actual.length,
  'joined substring (blind to order and to extras)': (want, actual) =>
    want.every((item) => actual.join(' | ').includes(item)),
};

describe('the recorded cross-field operator vectors replay in this port, byte for byte', () => {
  it('the record measures something, and not only failures', () => {
    expect(RECORD.cases).toHaveLength(EXPECTED_CASES);
    expect(new Set(RECORD.cases.map((entry) => entry.section))).toEqual(new Set(RECORD.sections));
    expect(new Set(RECORD.sections)).toEqual(new Set(Object.keys(EXPECTED_PER_SECTION)));
    for (const [section, [wantFail, wantPass]] of Object.entries(EXPECTED_PER_SECTION)) {
      const inSection = RECORD.cases.filter((entry) => entry.section === section);
      const failing = inSection.filter((entry) => entry.expect.failures.length > 0);
      const passing = inSection.filter((entry) => entry.expect.failures.length === 0);
      expect(failing).toHaveLength(wantFail);
      expect(passing).toHaveLength(wantPass);
    }
    expect(new Set(RECORD.cases.map((entry) => entry.name)).size).toBe(RECORD.cases.length);
  });

  it('a per-engine expectation is declared, counted and justified', () => {
    // The escape hatch that would otherwise launder a real split into the record. A case may
    // answer differently in the two engines only by carrying `failures_port`, only together
    // with a `port_divergence` saying why, and only while the COUNT matches the pin.
    const declared = RECORD.cases.filter((entry) => entry.expect.failures_port !== undefined);
    expect(declared).toHaveLength(EXPECTED_PORT_DIVERGENCES);
    for (const entry of declared) {
      expect((entry.expect.port_divergence ?? '').length).toBeGreaterThanOrEqual(80);
      expect(entry.expect.failures_port).not.toEqual([...entry.expect.failures]);
    }
    const orphans = RECORD.cases.filter(
      (entry) =>
        entry.expect.port_divergence !== undefined && entry.expect.failures_port === undefined,
    );
    expect(orphans.map((entry) => entry.name)).toEqual([]);
  });

  it.each(RECORD.cases.map((entry) => [entry.name, entry] as const))(
    'reproduces %s',
    (_name, testCase) => {
      withProbe(testCase.probe_schema, () => {
        // The EXACT list, in order. `toEqual` on arrays is element-wise and ordered, so a
        // reordering, an extra failure and a reworded one are each red -- which a
        // `toContain`/length check would not be.
        expect(evaluateCrossFieldRules(testCase.instance, testCase.probe_schema.$id)).toEqual([
          ...expectedFor(testCase),
        ]);
      });
    },
  );

  it.each(Object.keys(WEAKER_COMPARISONS))(
    'a weaker comparison -- %s -- would accept a real engine defect',
    (weakening) => {
      // A clean record cannot falsify a weakened comparison, so the discriminating power is
      // measured against a BROKEN engine result rather than against two hand-written arrays.
      // The previous version of this test compared `recorded` with `[...recorded]`, which is
      // a statement about `toEqual` and measures nothing about this suite.
      const testCase = RECORD.cases.find(
        (entry) => entry.section === '4.5' && entry.expect.failures.length === 2,
      );
      expect(testCase).toBeDefined();
      const target = testCase as VectorCase;
      const want = expectedFor(target);
      const actual = withProbe(target.probe_schema, () =>
        evaluateCrossFieldRules(target.instance, target.probe_schema.$id),
      );
      expect(actual).toEqual([...want]);
      // The defect: the same two failures in the other order. Section 4.5 makes failure order
      // contract text, so this is a real divergence and `toEqual` rejects it.
      const broken = [...actual].reverse();
      expect(broken).not.toEqual([...want]);
      expect(WEAKER_COMPARISONS[weakening](want, broken)).toBe(true);
    },
  );

  it('an operand with no canonical bytes is a failure and never a throw', () => {
    // `allowBinaryFloat` is not a blanket permit. `NaN` and `Infinity` cannot appear in the
    // committed record -- JSON has no literal for either and the record must stay strict
    // JSON -- so they are built here in code. This is the shape whose Python half was a
    // measured regression: `validate_instance` returned 16 failures before and RAISED after.
    const probe = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: 'urn:datacompany:cross-field-vector-probe:1',
      type: 'object',
      'x-datacompany-cross-field': [
        { rule: 'equal', name: 'left_equals_right', left: '/left', right: '/right' },
      ],
    };
    withProbe(probe, () => {
      for (const value of [NaN, Infinity, -Infinity, JSON.parse('"\ud800"')]) {
        const failures = evaluateCrossFieldRules({ left: value, right: value }, probe.$id);
        expect(failures.filter((failure) => failure.includes('cannot be decided'))).toHaveLength(2);
      }
      // The control: a canonicalizable value still reaches the equality verdict, so the loop
      // above cannot have been satisfied by an engine that refuses everything.
      expect(evaluateCrossFieldRules({ left: 'x', right: 'x' }, probe.$id)).toEqual([]);
    });
  });

  it('every released equal rule is decided by the comparator these vectors pin', () => {
    // The vectors run against a probe schema. A closure that reached only the probe would be
    // a test-only fix, so the same divergent pair is driven through a RELEASED rule.
    const sites: { ref: string; rule: Record<string, unknown> }[] = [];
    for (const ref of [...canonicalSchemas().keys()].sort()) {
      for (const rule of collectCrossFieldRules(ref)) {
        if (rule['rule'] === 'equal' || rule['rule'] === 'equal_when_both_present') {
          sites.push({ ref, rule: rule as Record<string, unknown> });
        }
      }
    }
    expect(sites.length).toBeGreaterThanOrEqual(3);
    const chosen = sites.find((site) => site.rule['rule'] === 'equal');
    expect(chosen).toBeDefined();
    const { ref, rule } = chosen as { ref: string; rule: Record<string, unknown> };
    const name = String(rule['name']);
    const instance: Record<string, unknown> = {};
    for (const pointer of [String(rule['left']), String(rule['right'])]) {
      place(instance, pointer, { consumer: true });
    }
    expect(
      evaluateCrossFieldRules(instance, ref).filter((failure) => failure.includes(name)),
    ).toEqual([]);
    place(instance, String(rule['right']), { consumer: 1 });
    expect(
      evaluateCrossFieldRules(instance, ref).filter((failure) => failure.includes(name)),
    ).not.toEqual([]);
  });
});

/** Write `value` at an RFC 6901 pointer, creating the intermediate objects. */
function place(instance: Record<string, unknown>, pointer: string, value: unknown): void {
  const tokens = pointer.replace(/^\//u, '').split('/');
  let node = instance;
  for (const token of tokens.slice(0, -1)) {
    node[token] ??= {};
    node = node[token] as Record<string, unknown>;
  }
  node[tokens[tokens.length - 1]] = value;
}

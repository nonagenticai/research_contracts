/**
 * The authoring-path fail-opens of `EXTENSIONS.md` §7.1-§7.4 and §7.6, in the second language.
 *
 * Decision F closed §7.5 by making both engines CONSULT the meta-schema -- restating its
 * rules in code, under a drift test that derives them back out of the meta-schema and
 * compares in both directions -- rather than by either engine growing a JSON Schema
 * validator of its own. §7.1-§7.4 are the same class on the DERIVATION side and are closed
 * the same way, so nothing normative was invented here either.
 *
 * §9 item 12 is why this file compares MESSAGES and not merely error classes: "two engines
 * that refuse the same schema with different words are a divergence a consumer reading
 * either one cannot reconcile." Every expected string below is read out of
 * `fixtures/canonical-annotations/v1/refusals.json`, whose `message` fields were produced by
 * the PYTHON engine. A rewording on either side turns this red, and there is no second copy
 * of the text to keep in step.
 *
 * Python's mirror is `tests/test_extension_vocabulary.py`, over the same file.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { HashProfileError, CrossFieldError, CanonicalError } from '../src/errors';
import { deriveHashProfile } from '../src/hashProfile';
import { REPOSITORY_ROOT, canonicalSchemas } from '../src/registry';
import { jsonText } from '../src/rendering';
import { collectCrossFieldRules, resetCrossFieldCache } from '../src/structural';

interface RefusalCase {
  readonly name: string;
  readonly section: string;
  readonly symptom: string;
  readonly entry_point: 'derive_hash_profile' | 'collect_cross_field_rules';
  readonly probe_schema: Record<string, unknown> & { $id: string };
  readonly expect: {
    readonly error?: string;
    readonly message?: string;
    readonly accepted?: boolean;
    readonly collected_rules?: number;
  };
}

const REFUSALS = JSON.parse(
  readFileSync(
    join(REPOSITORY_ROOT, 'fixtures', 'canonical-annotations', 'v1', 'refusals.json'),
    'utf-8',
  ),
) as { readonly cases: readonly RefusalCase[] };

/**
 * A floor AND a partition, mirroring Python's `MINIMUM_REFUSAL_CASES` /
 * `MINIMUM_ACCEPTED_CONTROLS`. Without the accepted half, an engine that refused EVERY
 * annotated node would satisfy this whole file.
 */
// EQUALITIES, not floors, and read out of the Python suite so the two pins are one
// number. They were `>= 23` and `>= 4` until 2026-08-04, when the section 6.4 closure
// took the record to 28 and 5 -- at which point a floor accepted the deletion of all
// four new cases plus one control with both suites still green. This file is the record
// the two engines are compared against, so slack here is slack in the parity itself.
const EXPECTED_REFUSAL_CASES = 28;
const EXPECTED_ACCEPTED_CONTROLS = 5;

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

function run(testCase: RefusalCase): unknown {
  if (testCase.entry_point === 'derive_hash_profile') {
    return deriveHashProfile(testCase.probe_schema.$id);
  }
  return collectCrossFieldRules(testCase.probe_schema.$id);
}

describe('the recorded authoring refusals replay in this port, byte for byte', () => {
  it('the record measures something, and not only refusals', () => {
    const refused = REFUSALS.cases.filter((entry) => entry.expect.message !== undefined);
    const accepted = REFUSALS.cases.filter((entry) => entry.expect.accepted === true);
    expect(refused.length).toBe(EXPECTED_REFUSAL_CASES);
    expect(accepted.length).toBe(EXPECTED_ACCEPTED_CONTROLS);
    // ...and the same two numbers as the Python suite, restated nowhere: a record that
    // grew in one language and not the other is exactly the drift this file prevents.
    const pySuite = readFileSync(
      join(REPOSITORY_ROOT, 'tests', 'test_extension_vocabulary.py'),
      'utf-8',
    );
    expect(pySuite).toContain(`EXPECTED_REFUSAL_CASES = ${EXPECTED_REFUSAL_CASES}`);
    expect(pySuite).toContain(`EXPECTED_ACCEPTED_CONTROLS = ${EXPECTED_ACCEPTED_CONTROLS}`);
    expect(refused.length + accepted.length).toBe(REFUSALS.cases.length);
    expect(new Set(REFUSALS.cases.map((entry) => entry.section))).toEqual(
      new Set([
        '7.1',
        '7.2',
        '7.3',
        '7.4',
        '7.5',
        '7.6',
        '8.row2',
        // The composition-point row: the last place the meta-schema constrained something
        // the engine did not constrain at all, closed 2026-08-04 (EXTENSIONS.md 6.4).
        '8.row7',
        '8.row8',
        'D9',
        'control',
      ]),
    );
  });

  it.each(REFUSALS.cases.map((entry) => [entry.name, entry] as const))(
    'reproduces %s',
    (_name, testCase) => {
      withProbe(testCase.probe_schema, () => {
        if (testCase.expect.accepted === true) {
          const result = run(testCase);
          if (testCase.expect.collected_rules !== undefined) {
            expect(result).toHaveLength(testCase.expect.collected_rules);
          }
          return;
        }
        let thrown: unknown;
        try {
          run(testCase);
        } catch (error) {
          thrown = error;
        }
        expect(thrown).toBeInstanceOf(CanonicalError);
        // The class BY NAME, exactly as Python compares it: the fixture is the only place
        // the class is written down, so neither engine can quietly widen it.
        expect((thrown as Error).constructor.name).toBe(testCase.expect.error);
        expect((thrown as Error).message).toBe(testCase.expect.message);
      });
    },
  );

  it('the two error classes the record names are the ones this port exports', () => {
    // A guard on the assertion above: `constructor.name` compared against a string cannot
    // fail if the string names a class that does not exist here, so the two are pinned.
    const named = new Set(
      REFUSALS.cases.map((entry) => entry.expect.error).filter((name) => name !== undefined),
    );
    expect(named).toEqual(new Set(['HashProfileError', 'CrossFieldError']));
    expect(HashProfileError.name).toBe('HashProfileError');
    expect(CrossFieldError.name).toBe('CrossFieldError');
  });
});

/**
 * The four symptom reproductions, written as EXTENSIONS.md §7 records them rather than as
 * abstract shapes, so this port fails for the same reason Python does and not merely at the
 * same time. Python's equivalents are the `test_7_*` functions in
 * `tests/test_extension_vocabulary.py`.
 */
describe('§7.1-§7.4: the derivation refuses what the meta-schema always rejected', () => {
  const PROBE_ID = 'urn:datacompany:authoring-fail-open-probe-ts:1';

  const CLEAN = {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: PROBE_ID,
    type: 'object',
    properties: {
      signature: {
        type: 'string',
        'x-datacompany-hash-excluded': true,
        'x-datacompany-hash-exclusion-reason': 'signature',
      },
      tags: {
        type: 'array',
        items: { type: 'string' },
        'x-datacompany-array': { kind: 'ordered' },
      },
    },
  };

  function mutate(edit: (schema: Record<string, never>) => void): Record<string, unknown> & {
    $id: string;
  } {
    const copy = JSON.parse(JSON.stringify(CLEAN)) as Record<string, never>;
    edit(copy);
    return copy as unknown as Record<string, unknown> & { $id: string };
  }

  it('accepts the unmutated probe, and derives what it declares', () => {
    // The false-positive control. Without it, an engine that refused every annotated node
    // would satisfy all four reproductions below.
    const profile = withProbe(CLEAN, () => deriveHashProfile(PROBE_ID));
    expect(profile.excluded_pointers).toEqual([{ pointer: '/signature', reason: 'signature' }]);
    expect(profile.arrays).toEqual([{ pointer: '/tags', kind: 'ordered' }]);
  });

  it('§7.1 refuses x-datacompany-hash-exclude, one letter short and read by nothing', () => {
    const probe = mutate((schema) => {
      const node = schema['properties']['signature'] as Record<string, unknown>;
      delete node['x-datacompany-hash-excluded'];
      node['x-datacompany-hash-exclude'] = true;
    });
    expect(() => withProbe(probe, () => deriveHashProfile(PROBE_ID))).toThrow(HashProfileError);
    expect(() => withProbe(probe, () => deriveHashProfile(PROBE_ID))).toThrow(
      /carries \["x-datacompany-hash-exclude"\]/,
    );
  });

  it('§7.2 refuses a lone exclusion reason, which used to derive an EMPTY exclusion set', () => {
    const probe = mutate((schema) => {
      const node = schema['properties']['signature'] as Record<string, unknown>;
      delete node['x-datacompany-hash-excluded'];
    });
    expect(() => withProbe(probe, () => deriveHashProfile(PROBE_ID))).toThrow(
      /x-datacompany-hash-exclusion-reason with no x-datacompany-hash-excluded/,
    );
  });

  it.each([
    ['a string', 'set'],
    ['an array', ['set']],
    ['a boolean', true],
  ])('§7.3 refuses %s x-datacompany-array, which used to derive arrays: []', (_label, value) => {
    const probe = mutate((schema) => {
      (schema['properties']['tags'] as Record<string, unknown>)['x-datacompany-array'] = value;
    });
    expect(() => withProbe(probe, () => deriveHashProfile(PROBE_ID))).toThrow(
      /x-datacompany-array at "\/tags" is a JSON \w+, not an object/,
    );
  });

  it('§7.4 refuses an x-datacompany-array that re-targets itself', () => {
    const probe = mutate((schema) => {
      (schema['properties']['tags'] as Record<string, unknown>)['x-datacompany-array'] = {
        pointer: '/elsewhere',
        kind: 'ordered',
      };
    });
    expect(() => withProbe(probe, () => deriveHashProfile(PROBE_ID))).toThrow(
      /x-datacompany-array at "\/tags" carries \["pointer"\]/,
    );
  });
});

/**
 * The two section 8 rows this change closed, in this port too (2026-08-04).
 *
 * Neither is one of the numbered defects. Both are rows of the section 8 table that the
 * engine simply did not consult, and both are per-node facts the meta-schema already states,
 * so they close by the same route as §7.1-§7.4 and with no new normative semantics.
 */
describe('section 8: the literal-true rule and the declaration-only/excluded pair', () => {
  const PROBE_ID = 'urn:datacompany:section-eight-probe-ts:1';

  function probe(signature: Record<string, unknown>): Record<string, unknown> & { $id: string } {
    return {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      properties: { signature, payload: { type: 'string' } },
    };
  }

  it('accepts the well-formed exclusion these mutate, and derives it', () => {
    // The false-positive control for both cases below.
    const clean = probe({
      type: 'string',
      'x-datacompany-hash-excluded': true,
      'x-datacompany-hash-exclusion-reason': 'signature',
    });
    const profile = withProbe(clean, () => deriveHashProfile(PROBE_ID));
    expect(profile.excluded_pointers).toEqual([{ pointer: '/signature', reason: 'signature' }]);
  });

  it.each([
    ['false', false],
    ['the string "true"', 'true'],
    ['0', 0],
  ])('refuses x-datacompany-hash-excluded declared as %s beside a valid reason', (_label, value) => {
    // Each of these used to derive excluded_pointers: [] and leave /signature in the hash
    // view -- §7.2's outcome, reached by writing the flag wrongly instead of deleting it.
    const mutant = probe({
      type: 'string',
      'x-datacompany-hash-excluded': value,
      'x-datacompany-hash-exclusion-reason': 'signature',
    });
    expect(() => withProbe(mutant, () => deriveHashProfile(PROBE_ID))).toThrow(
      /is read with an identity comparison|are read with an identity comparison/,
    );
  });

  it('refuses hash-declaration-only beside hash-excluded on one node', () => {
    const mutant = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      properties: {
        payload: {
          type: 'object',
          'x-datacompany-hash-opaque': true,
          properties: {
            tags: {
              type: 'array',
              'x-datacompany-hash-declaration-only': true,
              'x-datacompany-hash-excluded': true,
              'x-datacompany-hash-exclusion-reason': 'signature',
              'x-datacompany-array': { kind: 'ordered' },
            },
          },
        },
      },
    };
    expect(() => withProbe(mutant, () => deriveHashProfile(PROBE_ID))).toThrow(
      /carries x-datacompany-hash-declaration-only AND x-datacompany-hash-excluded/,
    );
  });
});

/**
 * §7.6, decided and pinned in this port too.
 *
 * DECIDED: an unknown operator is an AUTHORING fault, not an instance fault, so it is
 * refused when the rules are COLLECTED -- before any instance is examined. There is
 * therefore no partial failure list to discard. The rejected alternative is the one §7.6
 * names: collecting the unknown operator into the failure list beside the instance failures,
 * which would make the reported result depend on whether the instance happened to violate a
 * rule declared before it.
 */
describe('§7.6: an unknown operator refuses before any failure can be collected', () => {
  const PROBE_ID = 'urn:datacompany:seven-six-probe-ts:1';

  function probeWith(rules: unknown[]): Record<string, unknown> & { $id: string } {
    return {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      properties: { a: { type: 'integer' }, b: { type: 'integer' } },
      'x-datacompany-cross-field': rules,
    };
  }

  it('refuses identically whether or not the instance violates the sibling rule', () => {
    const probe = probeWith([
      { rule: 'equal', name: 'owner', left: '/a', right: '/b' },
      { rule: 'nope' },
    ]);
    const messages = [
      { a: 1, b: 2 },
      { a: 1, b: 1 },
    ].map((instance) => {
      let message = '';
      withProbe(probe, () => {
        try {
          collectCrossFieldRules(PROBE_ID);
          // Reached only if the refusal stopped happening; the assertions below then fail
          // on an empty string rather than passing by accident.
          void instance;
        } catch (error) {
          message = (error as Error).message;
        }
      });
      return message;
    });
    expect(messages[0]).toContain('declares rule "nope"');
    expect(messages[0]).toBe(messages[1]);
    // The refusal names the UNENFORCEABLE rule, not a failure of the enforceable one.
    expect(messages[0]).not.toContain('owner');
  });

  it('the control: two well-formed rules are both collected', () => {
    const probe = probeWith([
      { rule: 'equal', name: 'owner', left: '/a', right: '/b' },
      { rule: 'equal', name: 'tenant', left: '/a', right: '/b' },
    ]);
    withProbe(probe, () => {
      expect(collectCrossFieldRules(PROBE_ID)).toHaveLength(2);
    });
  });
});

/**
 * The renderer both engines' message text goes through.
 *
 * The table below is the SAME table as `RENDERINGS` in `tests/test_extension_vocabulary.py`,
 * with the same literals, because the property is that the two produce identical bytes.
 * Four spellings of one trap have been found here, each invisible to the tests that existed
 * when it landed: `repr` versus `JSON.stringify`, Python type names versus `typeof`,
 * `ensure_ascii=True` escaping what `JSON.stringify` leaves alone -- and, introduced by the
 * fix for the third, a lone surrogate left RAW where ES2019's well-formed `JSON.stringify`
 * escapes it.
 */
describe('jsonText renders exactly what Python renders', () => {
  it.each([
    ['a plain pointer list', ['/a'], '["/a"]'],
    ['an empty pointer', [''], '[""]'],
    ['a quote and a backslash', ['/q"b\\s'], '["/q\\"b\\\\s"]'],
    ['a tab', ['/t\there'], '["/t\\there"]'],
    ['a DEL, which is not escaped by either engine', ['/d\x7f'], '["/d\x7f"]'],
    ['a NUL, which both escape', ['/n\0'], '["/n\\u0000"]'],
    ['an accented letter, left alone by both', ['/café'], '["/café"]'],
    ['an astral emoji, left alone by both', ['/e\u{1f600}'], '["/e\u{1f600}"]'],
    ['an unpaired HIGH surrogate', ['/caf\ud800'], '["/caf\\ud800"]'],
    ['an unpaired LOW surrogate', ['/a\udfff'], '["/a\\udfff"]'],
    ['two unpaired highs in a row', ['/\ud800\ud801'], '["/\\ud800\\ud801"]'],
    // The one input on which the two engines DID disagree. Written as the two code units
    // deliberately -- in a JS string they ARE the astral character, which is exactly the
    // rule Python had to be taught.
    ['an adjacent high+low PAIR, which is one astral character', ['/\ud83d\ude00'], '["/\u{1f600}"]'],
    ['a string, not a list', 'nope', '"nope"'],
    ['null', null, 'null'],
  ] as [string, unknown, string][])('renders %s', (_description, value, expected) => {
    expect(jsonText(value)).toBe(expected);
  });

  it('every rendering survives a UTF-8 round trip', () => {
    // The half that was not a divergence but a CRASH: Python's raw lone surrogate could not
    // be encoded at all. This side never had that fault; the assertion is here so the two
    // suites make the same claim.
    for (const value of [['/caf\ud800'], ['/a\udfff'], ['/café'], ['/e\u{1f600}']]) {
      const rendered = jsonText(value);
      expect(Buffer.from(rendered, 'utf-8').toString('utf-8')).toBe(rendered);
    }
  });
});

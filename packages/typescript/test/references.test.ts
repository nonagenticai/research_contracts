/**
 * P6, first half: the 11 valid and 22 invalid committed reference fixtures.
 *
 * The obligation is NOT "the invalid ones throw something". It is that each one is rejected
 * **for the reason it declares**, and the tests below are built so that a rejection for any
 * other reason goes red:
 *
 * * every string in `expected_error_contains` must appear in the rendered failures;
 * * the rendering never dumps the instance, so a member name can only appear because the
 *   diagnosis named it -- proved with a decoy that IS in the instance and must NOT appear;
 * * a deliberately wrong-reason rejection is shown not to satisfy the gate; and
 * * stubbing out the cross-field evaluator makes four of the twenty-two VALIDATE, which is
 *   what proves the evaluator is load-bearing rather than decorative.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { CrossFieldError } from '../src/errors';
import { canonicalizeToString } from '../src/jcs';
import { REPOSITORY_ROOT, canonicalSchemas, validateSchemaOnly } from '../src/registry';
import {
  collectCrossFieldRules,
  evaluateCrossFieldRules,
  resetCrossFieldCache,
} from '../src/structural';
import {
  crossFieldRulesAreEvaluated,
  registerCrossFieldEvaluator,
  resetCrossFieldEvaluator,
  validateInstance,
} from '../src/validation';
import {
  INVALID_REF_DIR,
  VALID_REF_DIR,
  clone,
  fixtureFiles,
  fixtureId,
  load,
  type InvalidReferenceFixture,
  type ValidReferenceFixture,
} from './fixtures';

const VALID_FILES = fixtureFiles(VALID_REF_DIR);
const INVALID_FILES = fixtureFiles(INVALID_REF_DIR);

const validCases = VALID_FILES.map((path) => [fixtureId(path), path] as const);
const invalidCases = INVALID_FILES.map((path) => [fixtureId(path), path] as const);

/**
 * The four invalid fixtures NO JSON Schema validator can reject on its own.
 *
 * Named explicitly rather than discovered, because "the set is empty" would otherwise be a
 * silently passing answer, and this set is the falsifier for the whole cross-field layer.
 */
const CROSS_FIELD_ONLY = [
  'invalid-empty-valid-interval',
  'invalid-nested-cross-tenant-receipt',
  'invalid-receipt-subject-not-owned-by-consumer',
  'invalid-undeclared-singleton',
] as const;

describe('P6: the released engine validates every valid reference fixture', () => {
  it('replays exactly the 11 committed valid fixtures', () => {
    expect(VALID_FILES.length).toBe(11);
  });

  it('runs the RELEASED cross-field evaluator, not a stub', () => {
    // Without this the eleven below would be a schema-layer-only result reported as parity.
    expect(crossFieldRulesAreEvaluated()).toBe(true);
  });

  it.each(validCases)('%s validates against its declared schema_ref', (_id, path) => {
    const fixture = load<ValidReferenceFixture>(path);
    expect(fixture.expect).toBe('valid');
    expect(validateInstance(fixture.instance, fixture.schema_ref)).toEqual([]);
  });

  it('the valid corpus genuinely exercises the cross-field layer', () => {
    // Non-vacuity: if no valid fixture reached a cross-field rule, "they all validate" would
    // say nothing about the rules at all.
    const withRules = VALID_FILES.map((path) => load<ValidReferenceFixture>(path)).filter(
      (fixture) => collectCrossFieldRules(fixture.schema_ref).length > 0,
    );
    expect(withRules.length).toBeGreaterThan(0);
  });
});

describe('P6: every invalid reference fixture is rejected FOR ITS DECLARED REASON', () => {
  it('replays exactly the 22 committed invalid fixtures', () => {
    expect(INVALID_FILES.length).toBe(22);
  });

  it.each(invalidCases)('%s fails, and the failure names its declared reason', (_id, path) => {
    const fixture = load<InvalidReferenceFixture>(path);
    expect(fixture.expect).toBe('invalid');
    // A fixture with no declared reason would make the loop below vacuous.
    expect(fixture.expected_error_contains.length).toBeGreaterThan(0);

    const errors = validateInstance(fixture.instance, fixture.schema_ref);
    expect(errors.length).toBeGreaterThan(0);
    const rendered = errors.join(' | ');
    for (const expected of fixture.expected_error_contains) {
      expect(rendered).toContain(expected);
    }
  });

  /**
   * FALSE-POSITIVE CONTROL.
   *
   * Python renders a `not` failure by dumping the whole instance, so an
   * `expected_error_contains` naming any member of that instance is satisfied by a rejection
   * for a completely unrelated reason -- the gate reads the payload, not the diagnosis. This
   * port renders only the location, the message and the negated subschema, and this is the
   * test that keeps it that way: each decoy IS present in the fixture's instance and must
   * NOT be present in the rendered failures.
   */
  it.each([
    ['invalid-command-carrying-system-time', 'assertion_type'],
    ['invalid-cross-scope-global-with-tenant-id', 'owner_context'],
    ['invalid-first-version-with-supersession', 'created_by'],
    ['invalid-verified-receipt-with-failure-code', 'verification_profile_ref'],
    ['invalid-nested-cross-scope-receipt', 'verified_content_hash'],
  ] as const)(
    '%s: the decoy %s is in the instance but NOT in the rendered failures',
    (id, decoy) => {
      const fixture = load<InvalidReferenceFixture>(join(INVALID_REF_DIR, `${id}.json`));
      // The control is only meaningful if the decoy really is in the payload.
      expect(canonicalizeToString(fixture.instance)).toContain(decoy);
      const rendered = validateInstance(fixture.instance, fixture.schema_ref).join(' | ');
      expect(rendered.length).toBeGreaterThan(0);
      expect(rendered).not.toContain(decoy);
      // ...and the real reason still is.
      for (const expected of fixture.expected_error_contains) {
        expect(rendered).toContain(expected);
      }
    },
  );

  /**
   * FALSE-POSITIVE CONTROL, second form: "it threw something" is not "it threw for this".
   *
   * A valid fixture broken in a way the fixture does NOT declare is still rejected -- and
   * the gate for the declared reason must not be satisfied by that rejection.
   */
  it('a rejection for a DIFFERENT reason does not satisfy the declared reason', () => {
    const fixture = load<InvalidReferenceFixture>(
      join(INVALID_REF_DIR, 'invalid-uppercase-uuid.json'),
    );
    expect(fixture.expected_error_contains).toEqual(['entity_id']);

    // Restore the declared cause, then break something else entirely.
    const elsewhere = clone(fixture.instance) as Record<string, unknown>;
    elsewhere['entity_id'] = String(elsewhere['entity_id']).toLowerCase();
    elsewhere['resolved_at'] = '2026-07-30T12:00:00+02:00';

    const errors = validateInstance(elsewhere, fixture.schema_ref);
    expect(errors.length).toBeGreaterThan(0); // it IS rejected...
    expect(errors.join(' | ')).not.toContain('entity_id'); // ...but not for this reason.
  });
});

describe('P9: the cross-field layer is load-bearing, proved by removing it', () => {
  it('four invalid fixtures pass the JSON Schema layer alone', () => {
    for (const id of CROSS_FIELD_ONLY) {
      const fixture = load<InvalidReferenceFixture>(join(INVALID_REF_DIR, `${id}.json`));
      expect(validateSchemaOnly(fixture.instance, fixture.schema_ref)).toEqual([]);
    }
    // And they are exactly the four: any other fixture rejected by the schema layer alone
    // would make the count below drift without anyone noticing.
    const schemaClean = INVALID_FILES.map((path) => load<InvalidReferenceFixture>(path)).filter(
      (fixture) => validateSchemaOnly(fixture.instance, fixture.schema_ref).length === 0,
    );
    expect(schemaClean.map((fixture) => fixture.fixture_id).sort()).toEqual([...CROSS_FIELD_ONLY]);
  });

  it('stubbing the evaluator makes those four VALIDATE, so the released one is what rejects them', () => {
    try {
      registerCrossFieldEvaluator(() => []);
      expect(crossFieldRulesAreEvaluated()).toBe(false);
      for (const id of CROSS_FIELD_ONLY) {
        const fixture = load<InvalidReferenceFixture>(join(INVALID_REF_DIR, `${id}.json`));
        // Green where the contract requires red: this is the exact shape of the defect the
        // whole falsification discipline exists to catch.
        expect(validateInstance(fixture.instance, fixture.schema_ref)).toEqual([]);
      }
    } finally {
      resetCrossFieldEvaluator();
    }
    expect(crossFieldRulesAreEvaluated()).toBe(true);
    for (const id of CROSS_FIELD_ONLY) {
      const fixture = load<InvalidReferenceFixture>(join(INVALID_REF_DIR, `${id}.json`));
      const rendered = validateInstance(fixture.instance, fixture.schema_ref).join(' | ');
      for (const expected of fixture.expected_error_contains) {
        expect(rendered).toContain(expected);
      }
    }
  });

  it('perturbing a VALID fixture makes it fail, so "it validated" is not automatic', () => {
    const fixture = load<ValidReferenceFixture>(
      join(VALID_REF_DIR, 'bitemporal-assertion-command-without-system-time.json'),
    );
    expect(validateInstance(fixture.instance, fixture.schema_ref)).toEqual([]);

    // An inverted interval: invisible to JSON Schema, caught only by the released rule.
    const inverted = clone(fixture.instance) as Record<string, unknown>;
    inverted['valid_to'] = '1999-01-01T00:00:00Z';
    expect(validateSchemaOnly(inverted, fixture.schema_ref)).toEqual([]);
    expect(validateInstance(inverted, fixture.schema_ref).join(' | ')).toContain(
      'empty or inverted',
    );
  });

  /**
   * D0, the fail-open that a naive port reproduces by accident.
   *
   * Comparing RFC 3339 bounds as raw strings rejects the VALID half-second interval and
   * ACCEPTS the inverted one, because `.` (0x2E) sorts before `Z` (0x5A). JavaScript's `>`
   * on strings does exactly that, so this is the one place where the obvious implementation
   * silently disagrees with the contract in both directions. Both directions are pinned.
   */
  it('fractional-second bounds are compared as instants, not as strings', () => {
    const fixture = load<ValidReferenceFixture>(
      join(VALID_REF_DIR, 'bitemporal-assertion-command-without-system-time.json'),
    );
    const base = clone(fixture.instance) as Record<string, unknown>;

    const fine = { ...base, valid_from: '2026-01-01T00:00:00Z', valid_to: '2026-01-01T00:00:00.5Z' };
    expect('2026-01-01T00:00:00.5Z' > '2026-01-01T00:00:00Z').toBe(false); // the naive answer
    expect(validateInstance(fine, fixture.schema_ref)).toEqual([]); // the released answer

    const inverted = {
      ...base,
      valid_from: '2026-01-01T00:00:00.5Z',
      valid_to: '2026-01-01T00:00:00Z',
    };
    expect(validateInstance(inverted, fixture.schema_ref).join(' | ')).toContain(
      'empty or inverted',
    );
  });
});

/**
 * D3, closed as option B, mirrored here rather than assumed to have ported.
 *
 * `pinned-version-ref#/$defs/singleton` declares `equal /entity_id /version_id`. Its operands
 * used to be instance-root-ABSOLUTE, so composing it as a PROPERTY of another schema was
 * unevaluable in both engines and both had to say so rather than drop the rule. The rule now
 * declares `"scope": "relative"`, so its operands resolve against the location it is reached
 * at, and the composed pin is checked as itself.
 *
 * Both halves are pinned here, because this port can diverge from Python in either direction:
 * a port that ignored `scope` would still throw, and a port that treated EVERY rule as
 * relative would evaluate the absolute one against the wrong object and report nothing.
 * Python's equivalents live in `tests/test_d3_relative_scope.py`.
 */
describe('D3: relative scope evaluates at the composed location, in this port too', () => {
  const COMPOSED_ID = 'urn:datacompany:test-composed-pin:1';
  const ABSOLUTE_ID = 'urn:datacompany:test-absolute-rule:1';

  function withComposed(nested: unknown, body: (schemas: Map<string, unknown>) => void): void {
    const schemas = canonicalSchemas() as Map<string, unknown>;
    schemas.set(COMPOSED_ID, {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: COMPOSED_ID,
      type: 'object',
      properties: { pin: nested },
    });
    resetCrossFieldCache();
    try {
      body(schemas);
    } finally {
      schemas.delete(COMPOSED_ID);
      schemas.delete(ABSOLUTE_ID);
      resetCrossFieldCache();
    }
  }

  function singletonDef(): unknown {
    const schemas = canonicalSchemas();
    const pinned = schemas.get('urn:datacompany:pinned-version-ref:1') as Record<string, unknown>;
    return (pinned['$defs'] as Record<string, unknown>)['singleton'];
  }

  it('collects a relative rule reached through `properties` and evaluates it there', () => {
    withComposed(singletonDef(), () => {
      expect(collectCrossFieldRules(COMPOSED_ID)).toHaveLength(1);
      expect(evaluateCrossFieldRules({ pin: {} }, COMPOSED_ID)).toEqual([
        'equal: /pin/entity_id and /pin/version_id must both be present and equal',
      ]);
    });
  });

  it('is silent when the composed pin actually holds', () => {
    withComposed(singletonDef(), () => {
      const same = '11111111-1111-4111-8111-111111111111';
      expect(
        evaluateCrossFieldRules({ pin: { entity_id: same, version_id: same } }, COMPOSED_ID),
      ).toEqual([]);
    });
  });

  it('does not fall back to the instance root when the composed member is absent', () => {
    withComposed(singletonDef(), () => {
      // The root carries members spelled exactly like the rule's operands, and violating.
      const decoy = {
        entity_id: '11111111-1111-4111-8111-111111111111',
        version_id: '22222222-2222-4222-8222-222222222222',
      };
      expect(evaluateCrossFieldRules(decoy, COMPOSED_ID)).toEqual([]);
    });
  });

  it('still fails closed for a rule that did NOT opt in to relative scope', () => {
    const schemas = canonicalSchemas() as Map<string, unknown>;
    schemas.set(ABSOLUTE_ID, {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: ABSOLUTE_ID,
      type: 'object',
      'x-datacompany-cross-field': [{ rule: 'equal', left: '/entity_id', right: '/version_id' }],
    });
    withComposed({ $ref: ABSOLUTE_ID }, () => {
      expect(() => collectCrossFieldRules(COMPOSED_ID)).toThrow(CrossFieldError);
      expect(() => collectCrossFieldRules(COMPOSED_ID)).toThrow(/instance-root-absolute/);
    });
  });
});

/**
 * Parity is by construction, not by coincidence: the failure-message templates the fixtures
 * assert against are read out of the Python source, so a reword on either side goes red.
 */
describe('parity: the cross-field failure templates are the ones merged Python emits', () => {
  const pythonSource = readFileSync(
    join(REPOSITORY_ROOT, 'src', 'research_contracts', 'canonical', 'structural.py'),
    'utf-8',
  );

  it.each([
    ['must both be present and equal'],
    ['must be equal when both present'],
    ['is empty or inverted; a half-open '],
    ['null is not a released encoding for an interval bound'],
    ['is required to bound the interval'],
  ])('Python still emits %j', (template) => {
    expect(pythonSource).toContain(template);
  });

  it('and this port emits the same text for the fixtures that exercise them', () => {
    const interval = load<InvalidReferenceFixture>(
      join(INVALID_REF_DIR, 'invalid-empty-valid-interval.json'),
    );
    expect(validateInstance(interval.instance, interval.schema_ref)).toEqual([
      'valid: interval [2027-01-01T00:00:00Z, 2026-01-01T00:00:00Z) is empty or inverted; ' +
        'a half-open interval must be non-empty',
    ]);

    const singleton = load<InvalidReferenceFixture>(
      join(INVALID_REF_DIR, 'invalid-undeclared-singleton.json'),
    );
    expect(validateInstance(singleton.instance, singleton.schema_ref)).toEqual([
      'equal: /entity_id and /version_id must both be present and equal',
    ]);

    const tenant = load<InvalidReferenceFixture>(
      join(INVALID_REF_DIR, 'invalid-nested-cross-tenant-receipt.json'),
    );
    expect(validateInstance(tenant.instance, tenant.schema_ref)).toEqual([
      'no_cross_tenant_receipt: /subject_local_ref/resource_tenant_id and ' +
        '/pinned_version_ref/resource_tenant_id must be equal when both present',
    ]);

    const owned = load<InvalidReferenceFixture>(
      join(INVALID_REF_DIR, 'invalid-receipt-subject-not-owned-by-consumer.json'),
    );
    expect(validateInstance(owned.instance, owned.schema_ref)).toEqual([
      'subject_local_ref_is_owned_by_consumer: /consumer_context and ' +
        '/subject_local_ref/owner_context must both be present and equal',
    ]);
  });
});

/**
 * Decision F: a malformed annotation fails CLOSED, in this port too.
 *
 * This port used to be the worse half of the divergence: `Array.isArray` returned false for
 * a bare string and the declaration was skipped in SILENCE -- no rules, no error. Python at
 * least crashed. Both now throw `CrossFieldError`, and the shapes below are exactly the ones
 * `schemas/meta/datacompany-extension-vocabulary.v1.schema.json` already rejected, so nothing
 * normative was invented to close this. Python's mirror lives in
 * `tests/test_extension_vocabulary.py`.
 */
describe('decision F: a malformed cross-field declaration throws rather than no-opping', () => {
  const PROBE_ID = 'urn:datacompany:decision-f-probe:1';

  function collectWith(declaration: unknown): () => void {
    const schemas = canonicalSchemas() as Map<string, unknown>;
    schemas.set(PROBE_ID, {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      'x-datacompany-cross-field': declaration,
    });
    resetCrossFieldCache();
    return () => {
      try {
        collectCrossFieldRules(PROBE_ID);
      } finally {
        schemas.delete(PROBE_ID);
        resetCrossFieldCache();
      }
    };
  }

  it.each([
    ['a bare string, which this port used to skip in silence', 'equal'],
    ['an object rather than an array', { rule: 'equal' }],
    ['an empty array, indistinguishable from a deleted rule', []],
    ['a null member', [null]],
    ['a nested array member', [['equal']]],
    ['an unregistered operator', [{ rule: 'equals', left: '/a', right: '/b' }]],
    ['a rule missing an operand the evaluator indexes', [{ rule: 'equal', left: '/a' }]],
    ['an operand belonging to a different operator', [{ rule: 'equal', left: '/a', right: '/b', at: '/c' }]],
    ['an operand that is not a pointer', [{ rule: 'equal', left: 'a', right: '/b' }]],
    ['an unreleased scope', [{ rule: 'equal', left: '/a', right: '/b', scope: 'sideways' }]],
  ] as const)('rejects %s', (_description, declaration) => {
    expect(collectWith(declaration)).toThrow(CrossFieldError);
  });

  it('accepts the well-formed control', () => {
    // Without this, an engine that threw on EVERY declaration would satisfy the sweep above.
    const schemas = canonicalSchemas() as Map<string, unknown>;
    schemas.set(PROBE_ID, {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      'x-datacompany-cross-field': [{ rule: 'equal', left: '/entity_id', right: '/version_id' }],
    });
    resetCrossFieldCache();
    try {
      expect(collectCrossFieldRules(PROBE_ID)).toHaveLength(1);
    } finally {
      schemas.delete(PROBE_ID);
      resetCrossFieldCache();
    }
  });
});

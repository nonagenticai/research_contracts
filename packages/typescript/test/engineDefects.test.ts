/**
 * Three engine defects, closed in both languages, with their parity pins.
 *
 * 1. An exclusion inside an OPAQUE subtree revoked the subtree's opacity, so "exclude the
 *    signature from an opaque payload" -- the motivating case for the two annotations
 *    existing at all -- threw `UndeclaredPathError` on every undeclared sibling.
 * 2. A cross-field rule under `if`, `not`, `dependentSchemas` or `unevaluatedProperties` was
 *    collected by nothing and reported nothing, while the same rule under `allOf` or `then`
 *    reported the violation. A silent drop is the vacuity class; all four now fail closed,
 *    matching the `contains`/`propertyNames` precedent.
 * 3. Two objects both MISSING a compared field compared equal, so
 *    `comparePinToOwnerResponse({}, {})` answered `null` -- "verified".
 *
 * ...plus the RFC 6901 index-token grammar, where the two engines genuinely disagreed:
 * `/a/+0` resolved to element 0 in Python and to nothing here.
 *
 * Python's mirrors are `tests/test_hash_view_opaque_exclusion.py`,
 * `tests/test_cross_field_uncollected_keywords.py`,
 * `tests/test_verification_missing_field_symmetry.py` and
 * `tests/test_rfc6901_index_tokens.py`. Each block below parses the Python source for the
 * table it mirrors, so neither engine can drift alone.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { CrossFieldError, UndeclaredPathError } from '../src/errors';
import { deriveHashProfile, mergeProfileExtensions } from '../src/hashProfile';
import { buildHashView } from '../src/hashView';
import { REPOSITORY_ROOT, canonicalSchemas } from '../src/registry';
import {
  collectCrossFieldRuleSites,
  collectCrossFieldRules,
  evaluateCrossFieldRules,
  pointerInto,
  resetCrossFieldCache,
  MISSING,
} from '../src/structural';
import {
  COMPARED_FIELDS,
  comparePinToOwnerResponse,
  conditionalPinFields,
  requiredPinFields,
} from '../src/verification';

const PY = (name: string): string =>
  readFileSync(join(REPOSITORY_ROOT, 'src', 'research_contracts', 'canonical', name), 'utf-8');

const PY_TEST = (name: string): string =>
  readFileSync(join(REPOSITORY_ROOT, 'tests', name), 'utf-8');

type JsonRecord = Record<string, unknown>;

/** Register synthetic schemas for the body of one test, then take them back out again. */
function withSchemas(extra: Record<string, JsonRecord>, body: () => void): void {
  const schemas = canonicalSchemas() as Map<string, unknown>;
  for (const [id, schema] of Object.entries(extra)) {
    schemas.set(id, schema);
  }
  resetCrossFieldCache();
  try {
    body();
  } finally {
    for (const id of Object.keys(extra)) {
      schemas.delete(id);
    }
    resetCrossFieldCache();
  }
}

// ============================ 1. an exclusion inside an opaque subtree keeps it opaque ===

describe('defect 1: an exclusion below an opaque pointer does not revoke opacity', () => {
  const PROBE_ID = 'urn:datacompany:opaque-exclusion-probe:1';

  const SIGNED_OPAQUE_PAYLOAD: JsonRecord = {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: PROBE_ID,
    type: 'object',
    properties: {
      id: { type: 'string' },
      payload: {
        type: 'object',
        'x-datacompany-hash-opaque': true,
        properties: {
          signature: {
            type: 'string',
            'x-datacompany-hash-excluded': true,
            'x-datacompany-hash-exclusion-reason': 'signature',
          },
        },
      },
    },
  };

  const INSTANCE = {
    id: 'x',
    payload: { signature: 'sig', body: { k: 1 }, undeclared_sibling: true },
  };

  it('derives a manifest that really declares both annotations', () => {
    // Non-vacuity: with no opacity to revoke and no exclusion to revoke it, every case
    // below would be trivially satisfied.
    withSchemas({ [PROBE_ID]: SIGNED_OPAQUE_PAYLOAD }, () => {
      const profile = deriveHashProfile(PROBE_ID);
      expect(profile.opaque_pointers).toEqual(['/payload']);
      expect(profile.excluded_pointers.map((entry) => entry.pointer)).toEqual([
        '/payload/signature',
      ]);
      expect(profile.included_pointers).toEqual(['/id', '/payload']);
    });
  });

  it('hashes the opaque subtree minus exactly the excluded member', () => {
    withSchemas({ [PROBE_ID]: SIGNED_OPAQUE_PAYLOAD }, () => {
      const view = buildHashView(INSTANCE, deriveHashProfile(PROBE_ID)) as JsonRecord;
      expect({ ...view }).toEqual({
        id: 'x',
        payload: { body: { k: 1 }, undeclared_sibling: true },
      });
      // The control for the control: an engine that "fixed" opacity by ignoring the
      // exclusion would also stop throwing, and would hash the signature into the digest.
      expect(Object.keys(view['payload'] as JsonRecord).sort()).toEqual([
        'body',
        'undeclared_sibling',
      ]);
    });
  });

  it('still lets a DECLARED member of an opaque subtree revoke opacity', () => {
    // The released rule that was not changed, and the false-positive control for the fix:
    // `bitemporal-assertion:1` `/value` says "the moment a domain declares any member of
    // value, it must declare all of them". A fix that made opacity unconditional would pass
    // every case above and silently delete this rule.
    const partial = mergeProfileExtensions(deriveHashProfile('urn:datacompany:bitemporal-assertion:1'), {
      included_pointers: ['/value/note'],
    });
    expect(partial.opaque_pointers).toEqual(['/value']);
    expect(() =>
      buildHashView({ value: { note: 'declared', measurement: 'undeclared' } }, partial),
    ).toThrow(UndeclaredPathError);
  });

  it('still refuses an object that is neither declared nor opaque', () => {
    withSchemas({ [PROBE_ID]: SIGNED_OPAQUE_PAYLOAD }, () => {
      const profile = deriveHashProfile(PROBE_ID);
      // With the exclusion present `/payload` is still a declared prefix, so its undeclared
      // members are rejected one by one...
      expect(() => buildHashView(INSTANCE, { ...profile, opaque_pointers: [] })).toThrow(
        /^\/payload\/body: not declared/,
      );
      // ...and with neither annotation, the object itself is rejected as undeclared.
      expect(() =>
        buildHashView(INSTANCE, { ...profile, opaque_pointers: [], excluded_pointers: [] }),
      ).toThrow(/neither this object's members nor/);
    });
  });

  it('parity: merged Python decides opacity from its included prefixes too', () => {
    const source = PY('hash_view.py');
    expect(source).toContain('class _ViewBuilder'); // non-vacuity
    expect(source).toContain('_has_included_children');
    expect(source).toContain(
      'opaque = not self._has_included_children(pointer) and self._is_declared_opaque(pointer)',
    );
  });
});

// ================================ 2. an uncollected applicator fails closed, loudly ===

describe('defect 2: a rule under an uncollected applicator throws instead of vanishing', () => {
  const PROBE_ID = 'urn:datacompany:uncollected-keyword-probe:1';
  const NESTED_ID = 'urn:datacompany:uncollected-keyword-nested:1';

  const RULE = { rule: 'equal', scope: 'relative', left: '/a', right: '/b' } as const;
  const VIOLATING = { a: 1, b: 2 };

  const NESTED: JsonRecord = {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: NESTED_ID,
    type: 'object',
    'x-datacompany-cross-field': [RULE],
  };

  const UNCOLLECTED: Record<string, JsonRecord> = {
    if: { if: { $ref: NESTED_ID } },
    not: { not: { $ref: NESTED_ID } },
    dependentSchemas: { dependentSchemas: { a: { $ref: NESTED_ID } } },
    unevaluatedProperties: { unevaluatedProperties: { $ref: NESTED_ID } },
    // Absent from this list, and from Python's, while its direct sibling in the same
    // `unevaluated` vocabulary was present: a rule under it collected nothing, reported
    // nothing and threw nothing, in the engine whose job is to make that impossible.
    unevaluatedItems: { unevaluatedItems: { $ref: NESTED_ID } },
  };

  const UNLOCATABLE: Record<string, JsonRecord> = {
    contains: { contains: { $ref: NESTED_ID } },
    propertyNames: { propertyNames: { $ref: NESTED_ID } },
    // Applies to the DECODED contents of a string -- not a location in this document at all.
    contentSchema: { contentSchema: { $ref: NESTED_ID } },
  };

  /** Shapes 2020-12 does not read, so the SPECIFICATION drops the rule before this engine. */
  const LEGACY: Record<string, JsonRecord> = {
    additionalItems: { additionalItems: { $ref: NESTED_ID } },
    items: { items: [{ $ref: NESTED_ID }] },
  };

  /** The deliberate NON-blocking case: a bag of subschemas at no instance location. */
  const DEFINITION_BAGS: Record<string, JsonRecord> = {
    $defs: { $defs: { d: { $ref: NESTED_ID } } },
    definitions: { definitions: { d: { $ref: NESTED_ID } } },
  };

  /**
   * Every crossing the collector can make while blocked, and the keyword that must survive
   * it. `{not: {if: ...}}` alone never leaves the blocked-keyword loop, so three of the four
   * `blocked` hand-offs were unpinned -- and dropping it through the collected applicator
   * branches re-opens `if.allOf[0].<rule>` being COLLECTED, which is this defect itself.
   */
  const BLOCKED_CROSSINGS: [string, JsonRecord, string][] = [
    ['if.allOf[0]', { if: { allOf: [{ $ref: NESTED_ID }] } }, 'if'],
    ['not.allOf[0]', { not: { allOf: [{ $ref: NESTED_ID }] } }, 'not'],
    ['if.anyOf[0]', { if: { anyOf: [{ $ref: NESTED_ID }] } }, 'if'],
    ['if.oneOf[0]', { if: { oneOf: [{ $ref: NESTED_ID }] } }, 'if'],
    ['if.then', { if: { then: { $ref: NESTED_ID } } }, 'if'],
    ['if.else', { if: { else: { $ref: NESTED_ID } } }, 'if'],
    ['if.properties.x', { if: { properties: { x: { $ref: NESTED_ID } } } }, 'if'],
    ['if.patternProperties', { if: { patternProperties: { '^x$': { $ref: NESTED_ID } } } }, 'if'],
    ['if.prefixItems[0]', { if: { prefixItems: [{ $ref: NESTED_ID }] } }, 'if'],
    ['if.items', { if: { items: { $ref: NESTED_ID } } }, 'if'],
    ['if.additionalProperties', { if: { additionalProperties: { $ref: NESTED_ID } } }, 'if'],
    ['if.contains', { if: { contains: { $ref: NESTED_ID } } }, 'if'],
    ['if.not', { if: { not: { $ref: NESTED_ID } } }, 'if'],
    ['not.if', { not: { if: { $ref: NESTED_ID } } }, 'not'],
    ['allOf[0].if', { allOf: [{ if: { $ref: NESTED_ID } }] }, 'if'],
    ['allOf[0].not', { allOf: [{ not: { $ref: NESTED_ID } }] }, 'not'],
    ['properties.x.if', { properties: { x: { if: { $ref: NESTED_ID } } } }, 'if'],
    ['patternProperties.if', { patternProperties: { '^x$': { if: { $ref: NESTED_ID } } } }, 'if'],
    ['contains.if', { contains: { if: { $ref: NESTED_ID } } }, 'contains'],
    [
      'if.$ref',
      { if: { $ref: `${PROBE_ID}#/$defs/d` }, $defs: { d: { $ref: NESTED_ID } } },
      'if',
    ],
  ];

  /** The same crossings with the blocking keyword removed: the false-positive control. */
  const UNBLOCKED_CROSSINGS: [string, JsonRecord][] = [
    ['allOf[0].allOf[0]', { allOf: [{ allOf: [{ $ref: NESTED_ID }] }] }],
    ['allOf[0].then', { allOf: [{ then: { $ref: NESTED_ID } }] }],
    ['then.allOf[0]', { then: { allOf: [{ $ref: NESTED_ID }] } }],
    [
      'allOf[0].$ref',
      { allOf: [{ $ref: `${PROBE_ID}#/$defs/d` }], $defs: { d: { $ref: NESTED_ID } } },
    ],
  ];

  const COLLECTED: Record<string, JsonRecord> = {
    allOf: { allOf: [{ $ref: NESTED_ID }] },
    anyOf: { anyOf: [{ $ref: NESTED_ID }] },
    oneOf: { oneOf: [{ $ref: NESTED_ID }] },
    then: { if: { type: 'object' }, then: { $ref: NESTED_ID } },
    else: { if: { type: 'string' }, else: { $ref: NESTED_ID } },
  };

  function place(body: JsonRecord, run: () => void): void {
    withSchemas(
      {
        [NESTED_ID]: NESTED,
        [PROBE_ID]: {
          $schema: 'https://json-schema.org/draft/2020-12/schema',
          $id: PROBE_ID,
          ...body,
        },
      },
      run,
    );
  }

  it.each(Object.keys(COLLECTED))('still reports the violation under %s', (keyword) => {
    // The control. Every case below is a `toThrow`; without this, an engine that threw on
    // every placement -- or collected nothing anywhere -- would be green.
    place(COLLECTED[keyword], () => {
      expect(collectCrossFieldRules(PROBE_ID)).toHaveLength(1);
      expect(evaluateCrossFieldRules(VIOLATING, PROBE_ID)).toEqual([
        'equal: /a and /b must both be present and equal',
      ]);
    });
  });

  it.each(Object.keys(COLLECTED))('is silent under %s when the rule holds', (keyword) => {
    // The false-positive control: the rule discriminates between instances rather than
    // firing unconditionally.
    place(COLLECTED[keyword], () => {
      expect(evaluateCrossFieldRules({ a: 1, b: 1 }, PROBE_ID)).toEqual([]);
    });
  });

  it.each(Object.keys(UNCOLLECTED))('throws and names %s', (keyword) => {
    place(UNCOLLECTED[keyword], () => {
      expect(() => collectCrossFieldRules(PROBE_ID)).toThrow(CrossFieldError);
      expect(() => collectCrossFieldRules(PROBE_ID)).toThrow(
        new RegExp(`declared under '${keyword}', an applicator this engine does not collect`),
      );
    });
  });

  it.each(Object.keys(UNLOCATABLE))('keeps the existing %s precedent and its reason', (keyword) => {
    // The two families must stay distinguishable: an author whose rule is under `contains`
    // cannot fix it by moving to `allOf`, and one whose rule is under `if` can.
    place(UNLOCATABLE[keyword], () => {
      expect(() => collectCrossFieldRules(PROBE_ID)).toThrow(
        new RegExp(`declared under '${keyword}', a keyword with no single instance location`),
      );
    });
  });

  it.each(Object.keys(LEGACY))('throws under the dead pre-2020 shape %s', (keyword) => {
    // A 2020-12 validator reads no subschema in either, so a rule there is dropped by the
    // specification before this engine gets a say -- and dropped invisibly, since an unknown
    // member is legal and produces no diagnostic anywhere.
    place(LEGACY[keyword], () => {
      expect(() => collectCrossFieldRules(PROBE_ID)).toThrow(
        new RegExp(`declared under '${keyword}'`),
      );
      expect(() => collectCrossFieldRules(PROBE_ID)).toThrow(/2020-12/);
    });
  });

  it.each(Object.keys(DEFINITION_BAGS))('collects nothing from an uncomposed %s', (keyword) => {
    // The one placement that neither collects nor throws, and not the vacuity class: JSON
    // Schema applies nothing in an uncomposed bag either. The next case is what makes it safe.
    place(DEFINITION_BAGS[keyword], () => {
      expect(collectCrossFieldRules(PROBE_ID)).toEqual([]);
      expect(evaluateCrossFieldRules(VIOLATING, PROBE_ID)).toEqual([]);
    });
  });

  it.each(Object.keys(DEFINITION_BAGS))('reaches a COMPOSED %s entry through $ref', (keyword) => {
    // Why the bag is an exclusion and not a hole. Blocking it would make this case throw,
    // because the walk reaches the same node by both routes.
    place({ ...DEFINITION_BAGS[keyword], allOf: [{ $ref: `${PROBE_ID}#/${keyword}/d` }] }, () => {
      expect(collectCrossFieldRules(PROBE_ID)).toHaveLength(1);
      expect(evaluateCrossFieldRules(VIOLATING, PROBE_ID)).toEqual([
        'equal: /a and /b must both be present and equal',
      ]);
    });
  });

  it('reports the OUTERMOST blocking keyword when they nest', () => {
    place({ not: { if: { $ref: NESTED_ID } } }, () => {
      expect(() => collectCrossFieldRules(PROBE_ID)).toThrow(/declared under 'not'/);
    });
  });

  it.each(BLOCKED_CROSSINGS)('keeps the blocked flag across %s', (_label, body, keyword) => {
    place(body, () => {
      expect(() => collectCrossFieldRules(PROBE_ID)).toThrow(
        new RegExp(`declared under '${keyword}'`),
      );
    });
  });

  it.each(UNBLOCKED_CROSSINGS)('still collects the same shape unblocked: %s', (_label, body) => {
    // The false-positive control for the sweep above: every case there is a `toThrow`, so an
    // engine that threw on ANY nesting would be green.
    place(body, () => {
      expect(collectCrossFieldRules(PROBE_ID)).toHaveLength(1);
      expect(evaluateCrossFieldRules(VIOLATING, PROBE_ID)).toEqual([
        'equal: /a and /b must both be present and equal',
      ]);
    });
  });

  it('collects exactly 16 rule sites from the released corpus', () => {
    // Failing closed only costs nothing if nothing released is under a blocked keyword.
    // Measured through the real collector, over every released `$id` and `$defs` entry.
    //
    // Pinned EXACTLY, not as a floor. The floor this replaced was `>= 9` against a real
    // value of 15, and a collector mutated to stop following `$ref` drops to 13 and passes
    // it: a floor cannot catch the drop it exists for.
    //
    // 15 -> 16 when the FND-002 task 4 evidence tier merged: `evidence-location-version:1`
    // declares one released `equal` rule binding `evidence_location_id` to `entity_id`
    // (IMP-DEC-FND002-034). The pin doing exactly what it was built for -- the merge of two
    // independently green branches is precisely the case a floor would have absorbed.
    const refs: string[] = [];
    for (const [schemaId, schema] of canonicalSchemas()) {
      refs.push(schemaId);
      const defs = schema['$defs'];
      if (typeof defs === 'object' && defs !== null) {
        refs.push(...Object.keys(defs).map((name) => `${schemaId}#/$defs/${name}`));
      }
    }
    expect(refs.length).toBeGreaterThan(50); // non-vacuity
    let sites = 0;
    for (const ref of refs.sort()) {
      sites += collectCrossFieldRuleSites(ref).length;
    }
    expect(sites).toBe(16);
  });

  it('parity: merged Python blocks exactly the same keywords', () => {
    const source = PY('structural.py');
    expect(source).toContain('def _collect('); // non-vacuity
    const tuple = (name: string): string[] => {
      const match = new RegExp(`${name} = \\(([^)]*)\\)`).exec(source);
      expect(match).not.toBeNull();
      return [...(match?.[1] ?? '').matchAll(/"([^"]+)"/g)].map((hit) => hit[1]).sort();
    };
    // Compared against the very tables that drive the behavioural sweeps above, so this
    // asserts "Python lists what THIS engine demonstrably blocks" rather than restating two
    // literals side by side and calling the agreement parity.
    expect([
      ...tuple('_UNCOLLECTED_SCHEMA_KEYWORDS'),
      ...tuple('_UNCOLLECTED_MAP_KEYWORDS'),
    ].sort()).toEqual(Object.keys(UNCOLLECTED).sort());
    expect(tuple('_UNLOCATABLE_KEYWORDS')).toEqual(Object.keys(UNLOCATABLE).sort());
    // `items` in LEGACY is the array-VALUED form, handled in the walk rather than listed.
    expect(tuple('_LEGACY_SCHEMA_KEYWORDS')).toEqual(
      Object.keys(LEGACY)
        .filter((keyword) => keyword !== 'items')
        .sort(),
    );
    expect(tuple('_APPLICATOR_BRANCHES')).toEqual(Object.keys(COLLECTED).sort());
  });
});

// =========================== 3. a missing compared field is a mismatch, not a match ===

describe('defect 3: a field absent on both sides does not verify', () => {
  const MATCHING_GLOBAL: JsonRecord = {
    owner_context: 'terminology-broker',
    entity_type: 'approved_mapping',
    entity_id: '004417a8-a2b9-7ca3-e5c9-9037ddf2f225',
    version_id: '30bb8090-40d7-6b65-eb0f-c3017a8a1dc9',
    version_number: 3,
    resource_scope: 'global',
    schema_ref: 'urn:datacompany:stable-identity:1',
    content_hash: `sha256:${'c'.repeat(64)}`,
  };

  const MATCHING_TENANT: JsonRecord = {
    ...MATCHING_GLOBAL,
    resource_scope: 'tenant',
    resource_tenant_id: '6f8f57715090da2632453988d9a1501b',
  };

  function without(source: JsonRecord, field: string): JsonRecord {
    const copy = { ...source };
    delete copy[field];
    return copy;
  }

  it('verifies a complete matching pair, global and tenant scoped', () => {
    // The false-positive control the whole change has to survive: a fix that made absence a
    // mismatch unconditionally would reject every legal comparison, starting with the
    // released `verification-verified` fixture, which is global-scope.
    expect(comparePinToOwnerResponse({ ...MATCHING_GLOBAL }, { ...MATCHING_GLOBAL })).toBeNull();
    expect(comparePinToOwnerResponse({ ...MATCHING_TENANT }, { ...MATCHING_TENANT })).toBeNull();
  });

  it('does not verify two empty objects', () => {
    expect(comparePinToOwnerResponse({}, {})).toBe('owner_context_mismatch');
  });

  it.each(COMPARED_FIELDS.map(([field, code]) => [field, code]))(
    'reports %s absent on BOTH sides',
    (field, code) => {
      // No exception, and the exception this used to carry WAS the defect: it asserted that
      // dropping `resource_tenant_id` from both sides returned null, justified by "that
      // leaves a global-scope pair". It does not -- `MATCHING_TENANT.resource_scope` is
      // 'tenant' and is not deleted. The legal case is a genuinely global pair, below.
      const pin = without(MATCHING_TENANT, field);
      const response = without(MATCHING_TENANT, field);
      expect(comparePinToOwnerResponse(pin, response)).toBe(code);
    },
  );

  it('does not verify a tenant-scoped pair with no tenant id on either side', () => {
    // `requiredPinFields` reads only the UNCONDITIONAL required and deliberately does not
    // follow if/then/else, so it never learned that `resource_tenant_id` is required when
    // `resource_scope` is 'tenant'. Both engines answered null -- VERIFIED -- for this pair.
    // `verifyReference` refuses the pin at schema validation, but this comparison is exported
    // from index.ts and a direct caller got the silent pass.
    const pin = without(MATCHING_TENANT, 'resource_tenant_id');
    expect(pin['resource_scope']).toBe('tenant');
    expect(comparePinToOwnerResponse(pin, { ...pin })).toBe('resource_tenant_mismatch');
  });

  it('still verifies the genuinely legal absence: a global-scope pair', () => {
    // The false-positive control for the case above, correctly constructed this time. The
    // released `verification-verified` fixture is exactly this shape.
    expect(MATCHING_GLOBAL['resource_scope']).toBe('global');
    expect(Object.hasOwn(MATCHING_GLOBAL, 'resource_tenant_id')).toBe(false);
    expect(comparePinToOwnerResponse({ ...MATCHING_GLOBAL }, { ...MATCHING_GLOBAL })).toBeNull();
  });

  it('reads the conditional requirement from the schema and applies it to the pair', () => {
    // Teaching `requiredPinFields` to follow `then` would close the hole and break every
    // legal global verification with it. What closes it is the condition itself, evaluated
    // against the pair, with the discriminator and the required member both read from the pin
    // schema.
    expect([...conditionalPinFields(MATCHING_TENANT, MATCHING_TENANT)]).toEqual([
      'resource_tenant_id',
    ]);
    expect([...conditionalPinFields(MATCHING_GLOBAL, MATCHING_GLOBAL)]).toEqual([]);
    // One side only is not agreement about the discriminator, and that mismatch is already
    // reported on `resource_scope`, which precedes the tenant id in COMPARED_FIELDS.
    expect([...conditionalPinFields(MATCHING_TENANT, MATCHING_GLOBAL)]).toEqual([]);
    expect([...conditionalPinFields(MATCHING_GLOBAL, MATCHING_TENANT)]).toEqual([]);
    expect([...conditionalPinFields(MATCHING_TENANT, null)]).toEqual([]);
    // ...and an absent discriminator does not make the condition vacuously true: `properties`
    // does not apply to an absent member, which is why the released `if` also requires it.
    const scopeless = without(MATCHING_TENANT, 'resource_scope');
    expect([...conditionalPinFields(scopeless, { ...scopeless })]).toEqual([]);
  });

  it.each(COMPARED_FIELDS.map(([field, code]) => [field, code]))(
    'reports %s absent on ONE side, in either direction',
    (field, code) => {
      expect(comparePinToOwnerResponse(without(MATCHING_TENANT, field), MATCHING_TENANT)).toBe(
        code,
      );
      expect(comparePinToOwnerResponse(MATCHING_TENANT, without(MATCHING_TENANT, field))).toBe(
        code,
      );
    },
  );

  it('reports a missing content_hash on either side', () => {
    // The `content_hash` branch carried its own copy of the defect: `expected` was
    // `response['content_hash']`, so two objects carrying neither the hash nor any canonical
    // content compared `undefined === undefined` and passed.
    const both = without(MATCHING_GLOBAL, 'content_hash');
    expect(comparePinToOwnerResponse(both, { ...both })).toBe('content_hash_mismatch');
    expect(comparePinToOwnerResponse(MATCHING_GLOBAL, both)).toBe('content_hash_mismatch');
    expect(comparePinToOwnerResponse(both, MATCHING_GLOBAL)).toBe('content_hash_mismatch');
  });

  it('does not let an explicit null impersonate an absent member', () => {
    const nulled = { ...MATCHING_GLOBAL, version_number: null };
    const absent = without(MATCHING_GLOBAL, 'version_number');
    expect(comparePinToOwnerResponse(nulled, absent)).toBe('version_number_mismatch');
    expect(comparePinToOwnerResponse(absent, nulled)).toBe('version_number_mismatch');
    expect(comparePinToOwnerResponse(nulled, { ...nulled })).toBeNull();
  });

  it('does not let an explicit undefined impersonate a present member', () => {
    // JSON.parse never produces `undefined`, but a caller can hand one in, and a plain
    // `pin[field] !== response[field]` would read it as "present and equal to absent".
    const undef = { ...MATCHING_GLOBAL, entity_id: undefined };
    expect(comparePinToOwnerResponse(undef, without(MATCHING_GLOBAL, 'entity_id'))).toBe(
      'entity_id_mismatch',
    );
    expect(comparePinToOwnerResponse(undef, MATCHING_GLOBAL)).toBe('entity_id_mismatch');
  });

  it.each(COMPARED_FIELDS.map(([field]) => field))(
    'answers the same about %s whether or not the pair went through JSON',
    (field) => {
      // `Object.hasOwn` alone read `undefined` as PRESENT, so `{ owner_context: undefined }`
      // on both sides compared equal and returned null -- verified -- while the JSON round
      // trip of the same two objects returned `owner_context_mismatch`. Unreachable from JSON
      // input, but this comparison is exported and a JS caller can build such an object from
      // a partial record. `JSON.stringify({ x: undefined })` is `{}`: an undefined member IS
      // an absent member, and two engines must not disagree about the same document.
      const roundTrip = (record: JsonRecord): JsonRecord =>
        JSON.parse(JSON.stringify(record)) as JsonRecord;
      for (const base of [MATCHING_GLOBAL, MATCHING_TENANT]) {
        const undef = { ...base, [field]: undefined };
        expect(comparePinToOwnerResponse(undef, { ...undef })).toBe(
          comparePinToOwnerResponse(roundTrip(undef), roundTrip(undef)),
        );
        expect(comparePinToOwnerResponse(undef, { ...base })).toBe(
          comparePinToOwnerResponse(roundTrip(undef), roundTrip(base)),
        );
      }
    },
  );

  it('derives the pin schema unconditional required set', () => {
    // A walker that also read the scope conditional's `then` would add `resource_tenant_id`
    // and break every global verification; one that read nothing would make the comparison
    // permissive again.
    expect([...requiredPinFields()].sort()).toEqual([
      'content_hash',
      'entity_id',
      'entity_type',
      'owner_context',
      'resolved_at',
      'resource_scope',
      'schema_ref',
      'version_id',
      'version_number',
    ]);
    const compared = COMPARED_FIELDS.map(([field]) => field);
    expect(compared.filter((field) => !requiredPinFields().has(field))).toEqual([
      'resource_tenant_id',
    ]);
  });

  it('parity: merged Python derives the same set from the same schema', () => {
    const source = PY('verification.py');
    expect(source).toContain('def compare_pin_to_owner_response'); // non-vacuity
    expect(source).toContain('def required_pin_fields');
    expect(source).toContain('def conditional_pin_fields');
    expect(source).toContain('resolve_pointer(PIN_SCHEMA_REF)');
    expect(source).toContain('_ABSENT = object()');
    // The "must not name" checks below read CODE, not prose: the docstrings quote the schema
    // on purpose, and a check that failed on its own explanation would not survive a week.
    // ...nor the COMPARED_FIELDS table, which names every field on purpose: its ORDER decides
    // which code a multi-field mismatch reports and is itself the contract.
    const code = source
      .replace(/"""[\s\S]*?"""/g, '')
      .replace(/^\s*#.*$/gm, '')
      .replace(/COMPARED_FIELDS[^=]*=\s*\([\s\S]*?\n\)/, '');
    expect(code).toContain('def conditional_pin_fields'); // non-vacuity for the stripped view
    expect(code).not.toContain('("owner_context"'); // the table really was removed
    for (const [field] of COMPARED_FIELDS) {
      expect(source).not.toContain(`required.add("${field}")`);
    }
    // Beyond that table, Python may not NAME the conditionally required member or the value
    // that triggers it. Both are derived here too, from the same schema Python reads: an
    // engine that shipped `field == "resource_tenant_id"` would pass every behavioural test
    // above and drift silently the moment the released conditional changed.
    const conditional = [...conditionalPinFields(MATCHING_TENANT, MATCHING_TENANT)];
    expect(conditional.length).toBeGreaterThan(0); // else this check verifies nothing
    for (const member of conditional) {
      expect(code).not.toContain(`"${member}"`);
    }
    expect(code).not.toContain(`"${String(MATCHING_TENANT['resource_scope'])}"`);
  });
});

// ================================== 19. the RFC 6901 array-index grammar, in both engines ===

describe('defect 19: only an RFC 6901 array index resolves an element', () => {
  const PROBE_ID = 'urn:datacompany:rfc6901-index-probe:1';

  /**
   * `token -> is it an RFC 6901 array-index?`. Mirrors `INDEX_TOKENS` in
   * `tests/test_rfc6901_index_tokens.py`, and the last case in this block parses that table
   * out of the Python test so the two cannot drift.
   */
  const INDEX_TOKENS: Record<string, boolean> = {
    '+0': false,
    ' 0': false,
    '0_0': false,
    '٠': false, // ARABIC-INDIC DIGIT ZERO
    '-0': false,
    '-1': false,
    '00': false,
    '01': false,
    '': false,
    '0.0': false,
    '1e0': false,
    '-': false,
    a: false,
    '0': true,
    '1': true,
    '10': true,
    '9007199254740993': true,
  };

  it('holds both answers', () => {
    // Non-vacuity: an all-false table would be a tautology over a resolver that resolves
    // nothing at all.
    const accepted = Object.values(INDEX_TOKENS).filter(Boolean).length;
    expect(accepted).toBeGreaterThanOrEqual(4);
    expect(Object.keys(INDEX_TOKENS).length - accepted).toBeGreaterThanOrEqual(10);
  });

  it.each(Object.keys(INDEX_TOKENS))('resolves %j only when it is an index', (token) => {
    const resolved = pointerInto({ a: [5, 6] }, `/a/${token}`);
    if (INDEX_TOKENS[token] && Number(token) < 2) {
      expect(resolved).toBe([5, 6][Number(token)]);
    } else {
      expect(resolved).toBe(MISSING);
    }
  });

  it.each(Object.keys(INDEX_TOKENS))('gives the same answer through a rule for %j', (token) => {
    withSchemas(
      {
        [PROBE_ID]: {
          $schema: 'https://json-schema.org/draft/2020-12/schema',
          $id: PROBE_ID,
          'x-datacompany-cross-field': [
            { rule: 'equal', scope: 'relative', left: `/a/${token}`, right: '/b' },
          ],
        },
      },
      () => {
        const failures = evaluateCrossFieldRules({ a: [5], b: 5 }, PROBE_ID);
        if (token === '0') {
          expect(failures).toEqual([]);
        } else {
          expect(failures).toEqual([`equal: /a/${token} and /b must both be present and equal`]);
        }
      },
    );
  });

  it('still resolves every element of a well-formed index', () => {
    // The false-positive control that matters most: `locations` builds its own pointers with
    // plain decimal indices, so a grammar that was too strict would silently stop evaluating
    // every relative rule under `items`.
    expect(pointerInto({ a: [7, 8] }, '/a/0')).toBe(7);
    expect(pointerInto({ a: [7, 8] }, '/a/1')).toBe(8);
    expect(pointerInto({ a: [7] }, '/a/1')).toBe(MISSING);
    expect(pointerInto({ a: [] }, '/a/0')).toBe(MISSING);
  });

  it('parity: the two engines carry the identical grammar and the identical table', () => {
    // Compared as TEXT, not as two hand-written descriptions of one idea -- which is exactly
    // how the previous divergence was documented and stayed wrong.
    const source = PY('structural.py');
    const match = /_ARRAY_INDEX = re\.compile\(r"([^"]+)"\)/.exec(source);
    expect(match).not.toBeNull();
    expect(match?.[1]).toBe('0|[1-9][0-9]*');

    const pythonTest = PY_TEST('test_rfc6901_index_tokens.py');
    const table = /INDEX_TOKENS: dict\[str, bool\] = \{([\s\S]*?)\n\}/.exec(pythonTest);
    expect(table).not.toBeNull();
    const pythonTokens = [...(table?.[1] ?? '').matchAll(/^\s*"((?:[^"\\]|\\.)*)": (True|False),/gmu)];
    expect(pythonTokens.length).toBe(Object.keys(INDEX_TOKENS).length);
    for (const [, token, verdict] of pythonTokens) {
      const decoded = token.replace(/\\u([0-9a-fA-F]{4})/gu, (_all, hex: string) =>
        String.fromCharCode(parseInt(hex, 16)),
      );
      expect(Object.hasOwn(INDEX_TOKENS, decoded)).toBe(true);
      expect(INDEX_TOKENS[decoded]).toBe(verdict === 'True');
    }
  });
});

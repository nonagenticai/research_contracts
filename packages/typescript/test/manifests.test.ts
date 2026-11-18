/**
 * Released hash-view manifests.
 *
 * A committed manifest is not read back and trusted: it is DERIVED from the schema
 * annotations and the derivation must equal the committed file exactly. Reading a manifest
 * and asserting it equals itself proves nothing.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { computeContentHash } from '../src/engine';
import {
  DERIVATION_PROFILE_VERSION,
  HASH_PROFILE_SCHEMA_REF,
  deepEqual,
  deriveHashProfile,
  mergeProfileExtensions,
  validateHashProfile,
  validateProfileAgainstSchema,
  type HashProfile,
} from '../src/hashProfile';
import { HashProfileError, UnknownExclusionError } from '../src/errors';
import { canonicalSchemas, validateSchemaOnly } from '../src/registry';
import {
  crossFieldRulesAreEvaluated,
  registerCrossFieldEvaluator,
  resetCrossFieldEvaluator,
} from '../src/validation';
import {
  MANIFEST_DIR,
  clone,
  fixtureFiles,
  fixtureId,
  load,
  profileFor,
  vector,
} from './fixtures';

const MANIFEST_FLOOR = 5;
const IMMUTABLE_VERSION = 'urn:datacompany:immutable-version:1';
const BITEMPORAL_ASSERTION = 'urn:datacompany:bitemporal-assertion:1';
const PINNED_VERSION_REF = 'urn:datacompany:pinned-version-ref:1';
const UNRELEASED_SCHEMA_REF = 'urn:datacompany:definitely-not-released:1';

const paths = fixtureFiles(MANIFEST_DIR);

describe('released manifests', () => {
  it(`discovers at least ${MANIFEST_FLOOR} fixtures`, () => {
    expect(paths.length).toBeGreaterThanOrEqual(MANIFEST_FLOOR);
  });

  it.each(paths.map((path) => [fixtureId(path), path] as const))(
    '%s matches its schema and the derivation from the annotations',
    (_id, path) => {
      const manifest = load<HashProfile>(path);
      expect(validateSchemaOnly(manifest, HASH_PROFILE_SCHEMA_REF)).toEqual([]);
      expect(() => {
        validateHashProfile(manifest);
      }).not.toThrow();
      const derived = deriveHashProfile(manifest.schema_ref);
      // Deep equality first, then the exact diff if it fails.
      if (!deepEqual(manifest, derived)) {
        expect(derived).toEqual(manifest);
      }
      expect(deepEqual(manifest, derived)).toBe(true);
    },
  );

  it('names a released reason on every excluded pointer', () => {
    const reasons = new Set<string>();
    for (const path of paths) {
      for (const entry of load<HashProfile>(path).excluded_pointers) {
        reasons.add(entry.reason);
      }
    }
    const released = new Set([
      'own_content_hash',
      'signature',
      'transport_envelope',
      'resolution_observation',
      'projection_or_cache',
      'aggregate_version',
      'recorded_until',
    ]);
    for (const reason of reasons) {
      expect(released).toContain(reason);
    }
    for (const required of [
      'own_content_hash',
      'signature',
      'resolution_observation',
      'aggregate_version',
      'recorded_until',
    ]) {
      expect(reasons).toContain(required);
    }
  });

  it('declares an order key on set-like arrays and none on ordered arrays', () => {
    for (const path of paths) {
      for (const entry of load<HashProfile>(path).arrays) {
        expect(Object.hasOwn(entry, 'order_key')).toBe(entry.kind === 'set');
      }
    }
  });

  it('declares each pointer once and on one side only', () => {
    for (const path of paths) {
      const manifest = load<HashProfile>(path);
      const arrayPointers = manifest.arrays.map((entry) => entry.pointer);
      expect(new Set(arrayPointers).size).toBe(arrayPointers.length);
      const excluded = new Set(manifest.excluded_pointers.map((entry) => entry.pointer));
      expect(excluded.size).toBe(manifest.excluded_pointers.length);
      for (const pointer of excluded) {
        expect(manifest.included_pointers).not.toContain(pointer);
        expect(manifest.opaque_pointers).not.toContain(pointer);
      }
    }
  });
});

describe('a manifest may not contradict the schema annotations', () => {
  const tamper = (schemaRef: string, changes: Partial<HashProfile>): HashProfile => ({
    ...deriveHashProfile(schemaRef),
    ...changes,
  });

  it.each([
    ['exclusions deleted', { excluded_pointers: [] }],
    [
      'exclusion reason rewritten',
      { excluded_pointers: [{ pointer: '/content_hash', reason: 'projection_or_cache' }] },
    ],
    ['undeclared normalization', { unicode_normalization: 'nfc' }],
    ['absent and null conflated', { absent_vs_null: 'equivalent' }],
    ['opaque subtree invented', { opaque_pointers: ['/profile_ref'] }],
  ] as [string, Partial<HashProfile>][])('%s cannot hash', (_label, changes) => {
    const fixture = vector('immutable-version-nested-pins');
    const forged = tamper(IMMUTABLE_VERSION, changes);
    expect(() =>
      computeContentHash(fixture.instance, IMMUTABLE_VERSION, { profile: forged }),
    ).toThrow(/contradicts the released annotations/);
  });

  it('no longer reproduces the reported bypass: strip exclusions, re-include the paths', () => {
    const fixture = vector('immutable-version-nested-pins');
    const forged = deriveHashProfile(IMMUTABLE_VERSION);
    forged.excluded_pointers = [];
    forged.included_pointers = [
      ...forged.included_pointers,
      '/content_hash',
      '/profile_ref/resolved_at',
    ];
    // Still a well-formed manifest: that was never the guard.
    expect(() => {
      validateHashProfile(forged);
    }).not.toThrow();
    expect(() =>
      computeContentHash(fixture.instance, IMMUTABLE_VERSION, { profile: forged }),
    ).toThrow(HashProfileError);
  });

  it('rejects a manifest that drops a released included pointer', () => {
    const fixture = vector('immutable-version-nested-pins');
    const forged = deriveHashProfile(IMMUTABLE_VERSION);
    forged.included_pointers = forged.included_pointers.filter((p) => p !== '/created_by');
    expect(() =>
      computeContentHash(fixture.instance, IMMUTABLE_VERSION, { profile: forged }),
    ).toThrow(/drops released included pointers/);
  });

  it('rejects a manifest that re-declares a released set-like array as ordered', () => {
    const fixture = vector('immutable-version-nested-pins');
    const forged = deriveHashProfile(IMMUTABLE_VERSION);
    forged.arrays = forged.arrays.map((entry) =>
      entry.pointer === '/pack_refs' ? { pointer: '/pack_refs', kind: 'ordered' } : entry,
    );
    expect(() =>
      computeContentHash(fixture.instance, IMMUTABLE_VERSION, { profile: forged }),
    ).toThrow(/re-declares or drops the released array/);
  });

  it('rejects a manifest declared for a different schema', () => {
    const fixture = vector('immutable-version-nested-pins');
    const other = deriveHashProfile(BITEMPORAL_ASSERTION);
    expect(() =>
      computeContentHash(fixture.instance, fixture.schema_ref, { profile: other }),
    ).toThrow(/which is not the hashed object/);
  });

  it('still accepts the sanctioned domain-extension path', () => {
    const fixture = vector('ordered-array-preserves-order');
    const profile = profileFor(fixture);
    expect(() => {
      validateProfileAgainstSchema(profile, fixture.schema_ref);
    }).not.toThrow();
    expect(computeContentHash(fixture.instance, fixture.schema_ref, { profile })).toBe(
      fixture.expected_content_hash,
    );
  });

  it('rejects a domain extension that removes or adds an exclusion', () => {
    const base = deriveHashProfile(BITEMPORAL_ASSERTION);
    expect(() => mergeProfileExtensions(base, { excluded_pointers: [] })).toThrow(
      /may only add included_pointers and arrays/,
    );
  });

  it('rejects a domain extension that invents an opaque subtree', () => {
    const base = deriveHashProfile(BITEMPORAL_ASSERTION);
    expect(() => mergeProfileExtensions(base, { opaque_pointers: ['/subject_ref'] })).toThrow(
      /may only add included_pointers and arrays/,
    );
  });

  it('rejects an unknown hash exclusion reason', () => {
    const manifest = clone(
      load<HashProfile>(`${MANIFEST_DIR}/immutable-version.v1.profile.json`),
    );
    manifest.excluded_pointers = [
      ...manifest.excluded_pointers,
      { pointer: '/created_by', reason: 'because_we_felt_like_it' },
    ];
    expect(() => {
      validateHashProfile(manifest);
    }).toThrow(HashProfileError);
  });

  /**
   * GAP CLOSED. This test used to assert the opposite, and said it would go red the moment
   * an evaluator was registered rather than silently becoming stale. It did, and here is
   * the closed form.
   *
   * Python's `validate_hash_profile` runs the released `x-datacompany-cross-field` rules
   * (`one_array_declaration_per_pointer`, `one_exclusion_per_pointer`,
   * `a_pointer_is_either_included_or_excluded`, `an_opaque_subtree_is_not_also_excluded`).
   * `structural.ts` now runs them too, so a manifest carrying two declarations for one
   * pointer is malformed to BOTH engines instead of only to Python.
   */
  it('cross-field manifest rules are evaluated: two declarations for one pointer are refused', () => {
    expect(crossFieldRulesAreEvaluated()).toBe(true);

    const forged = deriveHashProfile(IMMUTABLE_VERSION);
    forged.arrays = [...forged.arrays, { pointer: '/pack_refs', kind: 'ordered' }];
    // Python raises HashProfileError("one_array_declaration_per_pointer") here. So does this.
    expect(() => {
      validateHashProfile(forged);
    }).toThrow(/one_array_declaration_per_pointer/);

    // The derivation check remains the second line of defence on the hash path itself.
    const fixture = vector('immutable-version-nested-pins');
    expect(() =>
      computeContentHash(fixture.instance, IMMUTABLE_VERSION, { profile: forged }),
    ).toThrow(HashProfileError);

    // Falsifier: with the evaluator stubbed out, the very same manifest is accepted -- which
    // is what proves the rule, and not some other check, is what rejected it above.
    try {
      registerCrossFieldEvaluator(() => []);
      expect(() => {
        validateHashProfile(forged);
      }).not.toThrow();
    } finally {
      resetCrossFieldEvaluator();
    }
  });

  it('keeps the error taxonomy Python declares', () => {
    const error = new UnknownExclusionError('x');
    expect(error).toBeInstanceOf(UnknownExclusionError);
    expect(error).toBeInstanceOf(HashProfileError);
    expect(error.name).toBe('UnknownExclusionError');
  });

  // ------------------------------------------------------------------ D4 and D7 ----
  //
  // Both guards existed in this file's Python original and in this port, and neither could
  // fire. `validateProfileAgainstSchema` derived the expected manifest with
  // `{ profileVersion: manifest.profile_version }` -- the expected value was built FROM the
  // value under test -- and `validateHashProfile` ended with a bare `schemaRegistry()` call
  // that reads no argument and discards its result.

  it('rejects a manifest that bumps its profile_version unilaterally', () => {
    const forged = deriveHashProfile(PINNED_VERSION_REF);
    forged.profile_version = 99999;
    expect(() => {
      validateProfileAgainstSchema(forged, PINNED_VERSION_REF);
    }).toThrow(/declares profile_version 99999/);
  });

  // `1` is the important one and is why this list moved. It read `[2, 7, 99999]` while the
  // engine implemented version 1; `DERIVATION_PROFILE_VERSION` then moved 1 -> 2 for
  // EXTENSIONS.md 5.2's exclusion-cascade fix, which turned the list's most load-bearing
  // case into the IMPLEMENTED version -- a case that can no longer fail. `1` is what a
  // stale manifest now carries, and refusing it is the whole point of the pin. Mirrors
  // Python's `test_no_profile_version_other_than_the_implemented_one_is_verifiable`.
  it.each([1, 3, 7, 99999])('refuses to verify a manifest at profile_version %s', (version) => {
    const forged = deriveHashProfile(PINNED_VERSION_REF);
    forged.profile_version = version;
    expect(() => {
      validateProfileAgainstSchema(forged, PINNED_VERSION_REF);
    }).toThrow(HashProfileError);
  });

  it('derives the pinned profile_version and offers no override', () => {
    // The `DeriveOptions` parameter is gone: a deriver able to stamp a version whose rules
    // it does not implement produces a manifest its own validator must reject.
    expect(deriveHashProfile.length).toBe(1);
    for (const schemaRef of [PINNED_VERSION_REF, IMMUTABLE_VERSION, BITEMPORAL_ASSERTION]) {
      expect(deriveHashProfile(schemaRef).profile_version).toBe(DERIVATION_PROFILE_VERSION);
    }
  });

  it('agrees with Python on the implemented profile_version', () => {
    // The two engines verify each other's manifests, so the constants must move together.
    // Read from the Python source rather than retyped, so a one-sided bump is red HERE
    // rather than at some consumer.
    const source = readFileSync(
      resolve(__dirname, '../../../src/research_contracts/canonical/hash_profile.py'),
      'utf-8',
    );
    const matched = /^DERIVATION_PROFILE_VERSION: Final\[int\] = (\d+)$/m.exec(source);
    expect(matched).not.toBeNull();
    expect(Number((matched as RegExpExecArray)[1])).toBe(DERIVATION_PROFILE_VERSION);
  });

  it.each(paths.map((path) => [fixtureId(path), path] as const))(
    '%s declares the implemented profile_version',
    (_id, path) => {
      expect(load<HashProfile>(path).profile_version).toBe(DERIVATION_PROFILE_VERSION);
    },
  );

  it('rejects a manifest naming an unreleased schema', () => {
    const forged = deriveHashProfile(PINNED_VERSION_REF);
    forged.schema_ref = UNRELEASED_SCHEMA_REF;
    expect(() => {
      validateHashProfile(forged);
    }).toThrow(/which is not a released schema/);
  });

  it('rejects an unreleased schema_ref through mergeProfileExtensions too', () => {
    const forged = deriveHashProfile(PINNED_VERSION_REF);
    forged.schema_ref = UNRELEASED_SCHEMA_REF;
    expect(() => {
      mergeProfileExtensions(forged, { included_pointers: ['/whatever'] });
    }).toThrow(/which is not a released schema/);
  });

  it.each(paths.map((path) => [fixtureId(path), path] as const))(
    '%s still passes both new guards',
    (_id, path) => {
      // The false-positive control: a "fix" that rejected everything would satisfy every
      // probe above and ship a dead engine.
      const manifest = load<HashProfile>(path);
      expect(() => {
        validateHashProfile(manifest);
        validateProfileAgainstSchema(manifest, manifest.schema_ref);
      }).not.toThrow();
    },
  );

  it('derives the released serialization rules', () => {
    const profile = deriveHashProfile(IMMUTABLE_VERSION);
    expect(profile.serialization).toBe('rfc8785');
    expect(profile.encoding).toBe('utf-8');
    expect(profile.byte_order_mark).toBe(false);
    expect(profile.digest_algorithm).toBe('sha256');
    expect(profile.absent_vs_null).toBe('distinct');
    expect(profile.unicode_normalization).toBe('none');
    expect(profile.timestamp_representation).toBe('rfc3339_utc_z');
    expect(profile.decimal_representation).toBe('decimal_string');
    expect(profile.binary_float_policy).toBe('reject');
  });
});

// ======== the 5.2 exclusion cascade, and the 6.4 composition point (2026-08-04) ========
//
// Mirrors `tests/test_canonical_hash.py`'s block of the same name, assertion for assertion.
// Both are exercised against SYNTHETIC probes, never against the corpus: neither change
// moves a single committed byte -- measured, with a positive control -- so a corpus
// assertion would be green before and after and could falsify nothing.

const CASCADE_PROBE = 'urn:datacompany:exclusion-cascade-probe:1';
const COMPOSITION_PROBE = 'urn:datacompany:composition-point-probe:1';

type Probe = Record<string, unknown> & { $id: string };

/** Register probe schemas for the body's duration, then remove them. */
function withSchemas(extra: Probe[], body: () => void): void {
  const schemas = canonicalSchemas() as Map<string, unknown>;
  for (const schema of extra) {
    schemas.set(schema.$id, schema);
  }
  try {
    body();
  } finally {
    for (const schema of extra) {
      schemas.delete(schema.$id);
    }
  }
}

/** An excluded subtree containing an array, plus a survivor that proves non-vacuity. */
function cascadeProbe(extra: Record<string, unknown> = {}): Probe {
  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: CASCADE_PROBE,
    type: 'object',
    properties: {
      kept: { type: 'string' },
      // The array OUTSIDE the exclusion. Without it a filter that dropped every array would
      // pass the assertions below, which is the shape of a guard that cannot be falsified
      // from the green side.
      survivor: { type: 'array', items: { type: 'string' }, 'x-datacompany-array': { kind: 'ordered' } },
      sig: {
        type: 'object',
        'x-datacompany-hash-excluded': true,
        'x-datacompany-hash-exclusion-reason': 'signature',
        properties: {
          // STRICTLY under the exclusion, never AT it: an exact-match filter cannot see this
          // one, which is the whole quirk.
          parts: {
            type: 'array',
            items: { type: 'string' },
            'x-datacompany-array': { kind: 'ordered' },
          },
          blob: { type: 'object', 'x-datacompany-hash-opaque': true },
        },
      },
      ...extra,
    },
  };
}

const ABSENT = Symbol('no composition point declared');

function compositionProbe(point: unknown = ABSENT): Probe {
  const body: Probe = {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: COMPOSITION_PROBE,
    type: 'object',
    $defs: { domain_extension: { type: 'object' } },
    properties: { payload: { type: 'object', 'x-datacompany-hash-opaque': true } },
  };
  // A SENTINEL rather than `undefined`, because `compositionProbe(null)` must produce a
  // schema that DECLARES the annotation with a null value -- the whole subject of the
  // explicit-null test below. Keying "absent" off `undefined` would make that probe
  // indistinguishable from "declares none" and the test vacuous.
  if (point !== ABSENT) {
    body['x-datacompany-composition-point'] = point;
  }
  return body;
}

describe('the exclusion cascade filters arrays by prefix (5.2, profile_version 2)', () => {
  it('drops an array nested UNDER an exclusion', () => {
    // 5.2's own worked example, made executable. `arrays` was filtered by EXACT match while
    // `included_pointers` and `opaque_pointers` were filtered by prefix, so excluding `/sig`
    // dropped `/sig/parts` from `included_pointers` and `/sig/blob` from `opaque_pointers`
    // and LEFT `{"pointer": "/sig/parts", "kind": "ordered"}` in `arrays`. The entry was
    // inert, but `validateProfileAgainstSchema` compares `arrays` exactly, so a port that
    // filtered all three consistently rejected every manifest Python produced -- and 9 item
    // 6 had to order every port to reproduce the quirk. `/survivor` is the non-vacuity half.
    withSchemas([cascadeProbe()], () => {
      const profile = deriveHashProfile(CASCADE_PROBE);
      expect(profile.arrays.map((entry) => entry.pointer)).toEqual(['/survivor']);
      // ...and the two members that ALREADY cascaded by prefix still do.
      expect(profile.included_pointers).toEqual(['/kept', '/survivor']);
      expect(profile.opaque_pointers).toEqual([]);
      expect(profile.excluded_pointers.map((entry) => entry.pointer)).toEqual(['/sig']);
    });
  });

  it('still drops an array EXACTLY at an exclusion', () => {
    // The half that always worked, kept so a regression cannot hide behind the new half: an
    // exact filter and a prefix filter agree here, and asserting only the nested case would
    // leave the engine free to lose this one entirely.
    const probe = cascadeProbe({
      at: {
        type: 'array',
        items: { type: 'string' },
        'x-datacompany-hash-excluded': true,
        'x-datacompany-hash-exclusion-reason': 'signature',
        'x-datacompany-array': { kind: 'ordered' },
      },
    });
    withSchemas([probe], () => {
      const profile = deriveHashProfile(CASCADE_PROBE);
      expect(profile.arrays.map((entry) => entry.pointer)).toEqual(['/survivor']);
      expect(profile.excluded_pointers.map((entry) => entry.pointer)).toEqual(['/at', '/sig']);
    });
  });
});

describe('mergeProfileExtensions is bound to x-datacompany-composition-point (6.4)', () => {
  it('refuses an extension to an envelope that declares none', () => {
    // It implemented the composition-point CONCEPT while being driven entirely by its
    // `extensions` argument and never consulting this member, so every released schema was
    // extensible in practice whether or not it said so. Twelve of the eighteen released
    // schemas declare no composition point and are non-extensible now.
    withSchemas([compositionProbe()], () => {
      const base = deriveHashProfile(COMPOSITION_PROBE);
      expect(() => {
        mergeProfileExtensions(base, { arrays: [{ pointer: '/payload', kind: 'ordered' }] });
      }).toThrow(/declares no x-datacompany-composition-point/);
    });
  });

  it('still accepts an extension to an envelope that declares one', () => {
    // The GREEN half, and the control without which the refusal above proves nothing: a gate
    // that refused every extension would satisfy it and would break the 9 item 11 arrays-only
    // route that refuted D4. The two probes differ by exactly the annotation.
    withSchemas([compositionProbe('#/$defs/domain_extension')], () => {
      const base = deriveHashProfile(COMPOSITION_PROBE);
      const merged = mergeProfileExtensions(base, {
        arrays: [{ pointer: '/payload', kind: 'ordered' }],
      });
      expect(merged.arrays.map((entry) => entry.pointer)).toEqual(['/payload']);
      expect(merged.included_pointers).toEqual(base.included_pointers);
      expect(merged.opaque_pointers).toEqual(base.opaque_pointers);
    });
  });

  it('refuses a composition point that resolves to nothing, at merge as well as at derivation', () => {
    // `mergeProfileExtensions` is public API over ANY well-formed manifest -- nothing obliges
    // the caller to have produced it with `deriveHashProfile` -- so a schema whose
    // composition point names a `$defs` entry that does not exist would be extensible through
    // this route while underivable through the other. That is the two-entry-point asymmetry
    // D7 was about. One helper, one message, both routes.
    let base: HashProfile | null = null;
    withSchemas([compositionProbe('#/$defs/domain_extension')], () => {
      base = deriveHashProfile(COMPOSITION_PROBE);
    });
    withSchemas([compositionProbe('#/$defs/domian_extension')], () => {
      expect(() => {
        mergeProfileExtensions(base as unknown as HashProfile, {
          arrays: [{ pointer: '/payload', kind: 'ordered' }],
        });
      }).toThrow(/resolves to no \$defs entry/);
      expect(() => {
        deriveHashProfile(COMPOSITION_PROBE);
      }).toThrow(/resolves to no \$defs entry/);
    });
  });

  it('resolves a composition point against its OWN document, not the entry schema', () => {
    // `baseId`, not the entry schema, and the distinction is load-bearing: the walk crosses
    // documents through `$ref` and `#/$defs/...` is relative to the document the NODE belongs
    // to. Here the referenced envelope's `domain_extension` exists in the referenced document
    // and NOT in the entry one, so an entry-relative resolution reports a sound schema broken.
    const entry: Probe = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: 'urn:datacompany:composition-point-entry-probe:1',
      type: 'object',
      // Deliberately NO `$defs/domain_extension` here.
      properties: { wrapped: { $ref: `${COMPOSITION_PROBE}#` } },
    };
    withSchemas([compositionProbe('#/$defs/domain_extension'), entry], () => {
      const profile = deriveHashProfile('urn:datacompany:composition-point-entry-probe:1');
      expect(profile.included_pointers).toContain('/wrapped');
    });
  });
  it('treats an explicit null as malformed, not as absent', () => {
    // PRESENCE, and the distinction is a two-route property: derivation must not call the
    // point malformed while merge calls it absent. Nothing asserted it until an independent
    // refuter mutated Python to `.get(...) is None` and this engine to `=== undefined` and
    // both suites stayed green -- the only survivor of 23 mutations.
    //
    // MEASURED AFTERWARDS, and the two halves are NOT the same finding. In Python the
    // mutation is a real defect: `.get(...) is None` conflates an explicit null with an
    // absent member, so merge reports "declares no x-datacompany-composition-point" while
    // derivation reports "as null". In TypeScript it is an EQUIVALENT MUTANT and cannot be
    // killed by any test: a member present with the value `undefined` is unreachable from
    // `JSON.parse`, so `Object.hasOwn` and `=== undefined` decide identically. Verified
    // rather than argued -- both routes emit the identical "as null" message with the
    // mutation applied and without it. `Object.hasOwn` is kept because it states the intent
    // and mirrors Python, not because a test forces it.
    //
    // Mirrors Python's test_an_explicit_null_composition_point_is_malformed_not_absent,
    // which IS the falsifiable half.
    withSchemas([compositionProbe(null)], () => {
      expect(() => deriveHashProfile(COMPOSITION_PROBE)).toThrow(
        /declares x-datacompany-composition-point as null/,
      );
    });
    let base: HashProfile | null = null;
    withSchemas([compositionProbe('#/$defs/domain_extension')], () => {
      base = deriveHashProfile(COMPOSITION_PROBE);
    });
    withSchemas([compositionProbe(null)], () => {
      let thrown: unknown;
      try {
        mergeProfileExtensions(base as unknown as HashProfile, {
          arrays: [{ pointer: '/payload', kind: 'ordered' }],
        });
      } catch (error) {
        thrown = error;
      }
      // THE SAME diagnosis as derivation, not "declares none": one schema, one story.
      expect((thrown as Error).message).toMatch(/declares x-datacompany-composition-point as null/);
      expect((thrown as Error).message).not.toMatch(/declares no x-datacompany-composition-point/);
    });
  });

  it('refuses a point declared at DEPTH with a message that is true', () => {
    // `requireReleasedAnnotations` shape-checks and RESOLVES a composition point wherever
    // the walk reaches it, so a schema declaring a valid one on a nested node derives
    // cleanly -- and was then told it "declares no x-datacompany-composition-point", which is
    // false about that schema. Root-only is still the rule; the message now says so.
    const nested: Probe = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: COMPOSITION_PROBE,
      type: 'object',
      $defs: { domain_extension: { type: 'object' } },
      properties: {
        payload: {
          type: 'object',
          'x-datacompany-hash-opaque': true,
          'x-datacompany-composition-point': '#/$defs/domain_extension',
        },
      },
    };
    withSchemas([nested], () => {
      // Non-vacuity: the nested declaration really is validated rather than ignored.
      const base = deriveHashProfile(COMPOSITION_PROBE);
      let thrown: unknown;
      try {
        mergeProfileExtensions(base, { arrays: [{ pointer: '/payload', kind: 'ordered' }] });
      } catch (error) {
        thrown = error;
      }
      expect((thrown as Error).message).toContain('at its document ROOT');
      expect((thrown as Error).message).toContain('"/payload"');
    });
  });

  it('does not make a schema extensible merely by COMPOSING an extensible envelope', () => {
    // F4: the blast radius reaches CONSUMER schemas. `allOf: [{$ref: envelope}]` reaches the
    // envelope's point at pointer '' -- `allOf`/`$ref` do not advance the pointer -- but it
    // is not a member of the composing document, so the composer is non-extensible until it
    // declares its own. Root-only rather than "anywhere at pointer ''" is a decision, and
    // this shape is why: `run-manifest:1` composes `stable-identity:1`, so two points arrive
    // at '' there and which one governs is undecided.
    const COMPOSER = 'urn:datacompany:composition-point-composer-probe:1';
    const composer: Probe = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: COMPOSER,
      type: 'object',
      allOf: [{ $ref: COMPOSITION_PROBE }],
    };
    withSchemas([compositionProbe('#/$defs/domain_extension'), composer], () => {
      const base = deriveHashProfile(COMPOSER);
      let thrown: unknown;
      try {
        mergeProfileExtensions(base, { arrays: [{ pointer: '/payload', kind: 'ordered' }] });
      } catch (error) {
        thrown = error;
      }
      const message = (thrown as Error).message;
      expect(message).toContain('at its document ROOT');
      expect(message).toContain('""');
      expect(message).toContain('must declare its OWN');
    });
    // The GREEN half: declaring its own point makes the composer extensible.
    const withPoint: Probe = {
      ...composer,
      $defs: { domain_extension: { type: 'object' } },
      'x-datacompany-composition-point': '#/$defs/domain_extension',
    };
    withSchemas([compositionProbe('#/$defs/domain_extension'), withPoint], () => {
      const merged = mergeProfileExtensions(deriveHashProfile(COMPOSER), {
        arrays: [{ pointer: '/payload', kind: 'ordered' }],
      });
      expect(merged.arrays.map((entry) => entry.pointer)).toEqual(['/payload']);
    });
  });
});

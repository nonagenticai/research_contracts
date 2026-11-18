/**
 * D9 CLOSED, in the second language: `x-datacompany-hash-declaration-only` (vocabulary 1.2).
 *
 * The port of `tests/test_declaration_only_annotation.py`, replaying the SAME committed
 * fixtures. `EXTENSIONS.md` §9 item 12 is explicit that a port which invents a local
 * annotation for this "derives a manifest the Python engine cannot derive, which is a
 * cross-language split" — and adding it to Python alone is the identical split pointing the
 * other way. Both engines therefore land in one change, and both replay one corpus.
 *
 * The annotation says: this schema node is reached only to carry annotations; it declares no
 * hashed path. Its `x-datacompany-array` still reaches the manifest, while its pointer — and
 * every pointer beneath it — stays out of `included_pointers`, so the enclosing
 * `x-datacompany-hash-opaque` subtree keeps its opacity.
 */

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { canonicalJsonBytes, canonicalSha256 } from '../src/engine';
import { HashProfileError } from '../src/errors';
import { deriveHashProfile, mergeProfileExtensions } from '../src/hashProfile';
import { buildHashView, type HashProfile } from '../src/hashView';
import { canonicalSchemas, REPOSITORY_ROOT } from '../src/registry';

type JsonRecord = Record<string, unknown>;

const ANNOTATION = 'x-datacompany-hash-declaration-only';
const FIXTURE_DIR = join(REPOSITORY_ROOT, 'fixtures', 'canonical-hash', 'v1', 'declaration-only');
const PY_SUITE = join(REPOSITORY_ROOT, 'tests', 'test_declaration_only_annotation.py');
const PY_ENGINE = join(
  REPOSITORY_ROOT,
  'src',
  'research_contracts',
  'canonical',
  'hash_profile.py',
);
/**
 * The renderer MOVED out of `PY_ENGINE`. `_json` was folded into
 * `canonical/rendering.py::json_text`, the single JSON rendering both engines' message
 * text goes through, so `hash_profile.py` carries `ensure_ascii=False` zero times.
 */
const PY_RENDERING = join(
  REPOSITORY_ROOT,
  'src',
  'research_contracts',
  'canonical',
  'rendering.py',
);

/**
 * Equality pin, cross-checked against Python's `EXPECTED_FIXTURES` below so the two engines
 * cannot drift into replaying different corpora. `readdirSync` throws for a missing
 * directory rather than globbing to `[]`, which is the failure Python's own loader guards.
 */
const EXPECTED_FIXTURES = 9;

interface Fixture {
  fixture_id: string;
  expect: 'derives' | 'rejects';
  probe_schema: JsonRecord & { $id: string };
  expected_manifest_canonical_json?: string;
  instance?: unknown;
  expected_hash_view_canonical_json?: string;
  expected_content_hash?: string;
  also_derived_from?: (JsonRecord & { $id: string })[];
  equivalent_runtime_route?: { schema: JsonRecord & { $id: string }; extensions: JsonRecord };
  expected_error?: string;
  expected_message_contains?: string;
}

function fixtureFiles(): string[] {
  const found = readdirSync(FIXTURE_DIR)
    .filter((name) => name.endsWith('.json'))
    .sort();
  if (found.length === 0) {
    throw new Error(`${FIXTURE_DIR}: no declaration-only fixtures found`);
  }
  return found.map((name) => join(FIXTURE_DIR, name));
}

const FIXTURES: Fixture[] = fixtureFiles().map(
  (path) => JSON.parse(readFileSync(path, 'utf-8')) as Fixture,
);

/** Register probe schemas for the body's duration, then remove them. */
function withSchemas(extra: (JsonRecord & { $id: string })[], body: () => void): void {
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

const PROBE_ID = 'urn:datacompany:declaration-only-unit-probe:1';

const ORDERED_TAGS: JsonRecord = {
  type: 'array',
  items: { type: 'string' },
  [ANNOTATION]: true,
  'x-datacompany-array': { kind: 'ordered' },
};

/**
 * What makes a probe schema an EXTENSIBLE envelope, spread into every probe whose test
 * drives the RUNTIME route (`mergeProfileExtensions` with an arrays-only extension).
 *
 * Since 2026-08-04 that route is gated on `x-datacompany-composition-point` (`EXTENSIONS.md`
 * 6.4): an envelope that declares none is non-extensible, so a probe standing in for an
 * extensible envelope has to say so. Defined once rather than per probe because the D9
 * closure is a BYTE EQUALITY between the schema route and the runtime route, and two probes
 * that differ in anything but the flag under test make that equality measure something else.
 * Mirrors `EXTENSIBLE_ENVELOPE` in the Python suite.
 */
const EXTENSIBLE_ENVELOPE: JsonRecord = {
  'x-datacompany-composition-point': '#/$defs/domain_extension',
  $defs: {
    domain_extension: {
      $comment: "Declared composition point for the probe's runtime route.",
      type: 'object',
    },
  },
};

function opaqueProbe(valueProperties?: JsonRecord): JsonRecord & { $id: string } {
  const value: JsonRecord = { type: 'object', 'x-datacompany-hash-opaque': true };
  if (valueProperties !== undefined) {
    value['properties'] = valueProperties;
  }
  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: PROBE_ID,
    type: 'object',
    ...EXTENSIBLE_ENVELOPE,
    properties: { id: { type: 'string' }, value },
  };
}

function decode(bytes: Uint8Array): string {
  return new TextDecoder('utf-8').decode(bytes);
}

// ============================================================ 1. the committed fixtures ===

describe('the committed declaration-only corpus', () => {
  it('is pinned as an equality, and agrees with the number Python pins', () => {
    expect(FIXTURES.length).toBe(EXPECTED_FIXTURES);
    // Read out of the Python suite rather than restated, so the two pins are one number.
    const source = readFileSync(PY_SUITE, 'utf-8');
    const match = /EXPECTED_FIXTURES = (\d+)/.exec(source);
    expect(match).not.toBeNull();
    expect(Number((match as RegExpExecArray)[1])).toBe(EXPECTED_FIXTURES);
  });

  it('contains both fixture kinds, so neither half is unfalsified', () => {
    const kinds = FIXTURES.map((fixture) => fixture.expect);
    expect(kinds.filter((kind) => kind === 'derives').length).toBeGreaterThanOrEqual(4);
    expect(kinds.filter((kind) => kind === 'rejects').length).toBeGreaterThanOrEqual(5);
  });

  it('really carries the evidence the register cites', () => {
    // B3. The replay reads `equivalent_runtime_route` and `also_derived_from` through
    // optional access, so deleting them from every fixture left BOTH engines at the same
    // passing count -- the "closure, committed as data" was unpinned. A conditional
    // assertion is not a pin; a floor on how many fixtures carry the member is.
    const derives = FIXTURES.filter((f) => f.expect === 'derives');
    expect(derives.length).toBe(4);
    for (const fixture of derives) {
      expect(fixture.equivalent_runtime_route).toBeDefined();
      expect(fixture.equivalent_runtime_route?.schema.$id).toBe(fixture.probe_schema.$id);
      expect(fixture.equivalent_runtime_route?.extensions['arrays']).toBeTruthy();
    }
    const alternatives = derives.reduce((n, f) => n + (f.also_derived_from ?? []).length, 0);
    expect(alternatives).toBeGreaterThanOrEqual(3);

    const rejects = FIXTURES.filter((f) => f.expect === 'rejects');
    expect(rejects.length).toBe(5);
    // B2: at least one message must be NON-ASCII, or the cross-language rendering parity
    // both engines assert in prose is untested in the only dimension it can break.
    //
    // Code-point test rather than a regex. The first spelling was `/^[\x00-\x7F]*$/`, which
    // needed an `eslint-disable no-control-regex`; removing the disable by narrowing the
    // class to `[\x20-\x7E]` quietly made this DISAGREE with Python's `.isascii()` about
    // control characters -- a lint-driven weakening of an assertion. This matches
    // `.isascii()` exactly and needs no disable.
    const isAscii = (value: string): boolean =>
      [...value].every((character) => (character.codePointAt(0) ?? 0) < 0x80);
    expect(
      rejects.filter((f) => !isAscii(f.expected_message_contains as string)).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it.each(FIXTURES.map((fixture) => [fixture.fixture_id, fixture] as const))(
    '%s replays against this engine',
    (_id, fixture) => {
      if (fixture.expect === 'rejects') {
        withSchemas([fixture.probe_schema], () => {
          let thrown: unknown = null;
          try {
            deriveHashProfile(fixture.probe_schema.$id);
          } catch (error) {
            thrown = error;
          }
          expect(thrown).toBeInstanceOf(HashProfileError);
          expect((thrown as Error).constructor.name).toBe(fixture.expected_error);
          // The message text is pinned, not merely the error class: two engines that refuse
          // the same schema with different words are a divergence a consumer reading either
          // one cannot reconcile.
          expect((thrown as Error).message).toContain(
            fixture.expected_message_contains as string,
          );
        });
        return;
      }

      withSchemas([fixture.probe_schema], () => {
        const manifest = deriveHashProfile(fixture.probe_schema.$id);
        // Byte-exact, not structural: the fixture commits the manifest's RFC 8785 bytes, so
        // the two engines compare the one representation they must agree on.
        expect(decode(canonicalJsonBytes(manifest))).toBe(fixture.expected_manifest_canonical_json);

        const view = buildHashView(fixture.instance, manifest);
        expect(decode(canonicalJsonBytes(view))).toBe(fixture.expected_hash_view_canonical_json);
        expect(canonicalSha256(view)).toBe(fixture.expected_content_hash);

        for (const alternative of fixture.also_derived_from ?? []) {
          withSchemas([alternative], () => {
            expect(deriveHashProfile(alternative.$id)).toEqual(manifest);
          });
        }
      });

      // The D9 closure, committed: the runtime route must produce the byte-identical
      // manifest. Outside the block above, because the runtime probe shares the same `$id`.
      const runtime = fixture.equivalent_runtime_route;
      if (runtime !== undefined) {
        withSchemas([runtime.schema], () => {
          const merged = mergeProfileExtensions(
            deriveHashProfile(runtime.schema.$id),
            runtime.extensions,
          );
          expect(decode(canonicalJsonBytes(merged))).toBe(
            fixture.expected_manifest_canonical_json,
          );
        });
      }
    },
  );
});

// ============================================ 2. the closure against a RELEASED schema ====

describe('the two routes agree on the released opaque subtree', () => {
  it('derives byte-identical manifests from the schema route and the runtime route', () => {
    const reference = 'urn:datacompany:bitemporal-assertion:1';
    const runtimeRoute = mergeProfileExtensions(deriveHashProfile(reference), {
      arrays: [{ pointer: '/value/tags', kind: 'ordered' }],
    });

    const released = canonicalSchemas().get(reference) as JsonRecord;
    const mirror = JSON.parse(JSON.stringify(released)) as JsonRecord & { $id: string };
    const defs = mirror['$defs'] as JsonRecord;
    const assertionFields = defs['assertion_fields'] as JsonRecord;
    const value = (assertionFields['properties'] as JsonRecord)['value'] as JsonRecord;
    // Non-vacuity: if the released subtree stops being opaque this proves nothing.
    expect(value['x-datacompany-hash-opaque']).toBe(true);
    value['properties'] = { tags: ORDERED_TAGS };

    withSchemas([mirror], () => {
      const schemaRoute = deriveHashProfile(reference);
      expect(decode(canonicalJsonBytes(schemaRoute))).toBe(
        decode(canonicalJsonBytes(runtimeRoute)),
      );
      // ...and not vacuously equal because both are the unextended released manifest.
      expect(schemaRoute.arrays.some((entry) => entry.pointer === '/value/tags')).toBe(true);
      expect(schemaRoute.included_pointers).not.toContain('/value/tags');
    });
  });
});

// ================================================= 3. the design constraints, one by one ==

describe('the suppression rules', () => {
  it('cascades by PREFIX, so an array of objects does not leak its members', () => {
    const probe = opaqueProbe({
      tags: {
        type: 'array',
        items: {
          type: 'object',
          properties: { id: { type: 'string' }, label: { type: 'string' } },
        },
        [ANNOTATION]: true,
        'x-datacompany-array': { kind: 'set', order_key: ['/id'] },
      },
    });
    withSchemas([probe], () => {
      const manifest = deriveHashProfile(PROBE_ID);
      // Exact-match suppression would leave /value/tags/-/id and /value/tags/-/label here,
      // which makes /value a declared prefix again and revokes the opacity anyway.
      expect(manifest.included_pointers).toEqual(['/id', '/value']);
      const view = buildHashView(
        { id: 'x', value: { tags: [{ id: 'b' }, { id: 'a' }], other: 1 } },
        manifest,
      ) as JsonRecord;
      const payload = view['value'] as JsonRecord;
      expect(payload['other']).toBe(1);
      expect((payload['tags'] as JsonRecord[]).map((member) => member['id'])).toEqual([
        'a',
        'b',
      ]);
    });
  });

  it('does NOT filter `arrays`, which is the whole point', () => {
    withSchemas([opaqueProbe({ tags: ORDERED_TAGS })], () => {
      const manifest = deriveHashProfile(PROBE_ID);
      expect(manifest.arrays).toEqual([{ pointer: '/value/tags', kind: 'ordered' }]);
      // The behavioural half: an engine that filtered `arrays` too would keep every opacity
      // assertion green while making the instance unhashable.
      const view = buildHashView({ id: 'x', value: { tags: ['b', 'a'] } }, manifest) as JsonRecord;
      expect((view['value'] as JsonRecord)['tags']).toEqual(['b', 'a']);
    });
  });

  it('leaves the enclosing subtree opaque, and WITHOUT the flag the same schema throws', () => {
    withSchemas([opaqueProbe({ tags: ORDERED_TAGS })], () => {
      const manifest = deriveHashProfile(PROBE_ID);
      expect(manifest.opaque_pointers).toEqual(['/value']);
      const view = buildHashView(
        { id: 'x', value: { tags: ['a'], other: 1 } },
        manifest,
      ) as JsonRecord;
      expect(view['value']).toEqual({ tags: ['a'], other: 1 });
    });

    // The discriminating control. Without it this would pass against an engine in which
    // opacity was never at risk.
    const unflagged: JsonRecord = { ...ORDERED_TAGS };
    delete unflagged[ANNOTATION];
    withSchemas([opaqueProbe({ tags: unflagged })], () => {
      const manifest = deriveHashProfile(PROBE_ID);
      expect(manifest.included_pointers).toContain('/value/tags');
      expect(() => buildHashView({ id: 'x', value: { tags: ['a'], other: 1 } }, manifest)).toThrow(
        /\/value\/other/,
      );
    });
  });

  it.each([
    ['allOf', { allOf: [ORDERED_TAGS] }],
    ['anyOf', { anyOf: [ORDERED_TAGS] }],
    ['oneOf', { oneOf: [ORDERED_TAGS] }],
    ['then', { if: { type: 'array' }, then: ORDERED_TAGS }],
  ] as [string, JsonRecord][])(
    'derives the same manifest whether the flag is inline or behind %s',
    (_route, tags) => {
      let inline: HashProfile | null = null;
      withSchemas([opaqueProbe({ tags: ORDERED_TAGS })], () => {
        inline = deriveHashProfile(PROBE_ID);
      });
      withSchemas([opaqueProbe({ tags })], () => {
        // An INLINE suppression at the `properties` loop cannot see a flag that arrives
        // afterwards through an applicator branch, so it would derive a manifest that
        // depends on how the schema was written rather than on what it means.
        expect(deriveHashProfile(PROBE_ID)).toEqual(inline);
      });
      expect((inline as unknown as HashProfile).arrays).toEqual([
        { pointer: '/value/tags', kind: 'ordered' },
      ]);
    },
  );

  it('derives the same manifest when the flag arrives through a $ref', () => {
    const throughRef = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      $defs: { tags: ORDERED_TAGS },
      properties: {
        id: { type: 'string' },
        value: {
          type: 'object',
          'x-datacompany-hash-opaque': true,
          properties: { tags: { $ref: '#/$defs/tags' } },
        },
      },
    };
    let inline: HashProfile | null = null;
    withSchemas([opaqueProbe({ tags: ORDERED_TAGS })], () => {
      inline = deriveHashProfile(PROBE_ID);
    });
    withSchemas([throughRef], () => {
      expect(deriveHashProfile(PROBE_ID)).toEqual(inline);
    });
  });

  // REWRITTEN 2026-08-04, not deleted. These cases used to assert each value was a SILENT
  // NO-OP -- that `/value/tags` stayed in `included_pointers`. True of the read, false of the
  // contract: `EXTENSIONS.md` §9 item 8 already said "`is True` semantics ... or, better,
  // reject everything but `true` at load time, as the meta-schema does", and the meta-schema
  // has always said `const: true`. Both engines now refuse (§8, correction C2), which is
  // strictly stronger than not-suppressing. The property the old comment protected -- that a
  // truthiness "fix" must not make this engine suppress a pointer Python still declares -- is
  // no longer observable through the manifest, so it is pinned on the source below.
  it.each([[false], [1], ['true'], [null], [{}]] as [unknown][])(
    'refuses %p rather than treating it as the literal true',
    (value) => {
      withSchemas([opaqueProbe({ tags: { ...ORDERED_TAGS, [ANNOTATION]: value } })], () => {
        expect(() => deriveHashProfile(PROBE_ID)).toThrow(/identity comparison/);
      });
    },
  );

  it('the control: the literal true still suppresses, and the read is still identity', () => {
    // Without the control, an engine that refused every flagged schema would satisfy the
    // sweep above.
    withSchemas([opaqueProbe({ tags: ORDERED_TAGS })], () => {
      expect(deriveHashProfile(PROBE_ID).included_pointers).not.toContain('/value/tags');
    });
    const port = readFileSync(
      join(REPOSITORY_ROOT, 'packages', 'typescript', 'src', 'hashProfile.ts'),
      'utf-8',
    );
    const python = readFileSync(
      join(REPOSITORY_ROOT, 'src', 'research_contracts', 'canonical', 'hash_profile.py'),
      'utf-8',
    );
    expect(port).toContain(`schema['${ANNOTATION}'] === true`);
    expect(python).toContain(`schema.get("${ANNOTATION}") is True`);
  });
});

describe('manifest pointer ORDER', () => {
  // C3's other half. `mergeProfileExtensions` was changed to sort `arrays` so the two D9
  // routes agree byte for byte; nothing asserted WHICH order. Python's `sorted` compares code
  // POINTS, while JS `<` and a bare `.sort()` compare UTF-16 code UNITS, and the two disagree
  // for astral characters -- the G1 divergence class this repository already carries an
  // order-key fixture for. Both engines happened to be right; neither was pinned, so
  // rewriting `compareCodePoints` with `split('')`, or `sortedStrings` with a bare `.sort()`,
  // left all 701 tests green.
  //
  // U+FF21 is one UTF-16 unit (65313); U+1F600 is a surrogate pair starting 0xD83D (55357).
  // Code-point order puts U+FF21 first, UTF-16 order puts U+1F600 first.
  const FULLWIDTH = '\uFF21';
  const EMOJI = '\u{1F600}';
  // The same literal the Python suite pins, so neither engine agrees with its own
  // recomputation.
  const ASTRAL_ARRAYS_CANONICAL =
    `[{"kind":"ordered","pointer":"/${FULLWIDTH}"},{"kind":"ordered","pointer":"/${EMOJI}"}]`;

  it('sorts merged pointers by CODE POINT, not by UTF-16 code unit', () => {
    const probe = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      ...EXTENSIBLE_ENVELOPE,
      properties: {
        [FULLWIDTH]: {
          type: 'array',
          items: { type: 'string' },
          'x-datacompany-array': { kind: 'ordered' },
        },
      },
    };
    withSchemas([probe], () => {
      const merged = mergeProfileExtensions(deriveHashProfile(PROBE_ID), {
        included_pointers: [`/${EMOJI}`],
        arrays: [{ pointer: `/${EMOJI}`, kind: 'ordered' }],
      });
      // `included_pointers` goes through the shared string sort...
      expect(merged.included_pointers).toEqual([`/${FULLWIDTH}`, `/${EMOJI}`]);
      // ...and `arrays` through the comparator added for C3.
      expect(merged.arrays.map((entry) => entry.pointer)).toEqual([`/${FULLWIDTH}`, `/${EMOJI}`]);
      expect(decode(canonicalJsonBytes(merged.arrays))).toBe(ASTRAL_ARRAYS_CANONICAL);
    });
  });

  it('asserts the SAME literal bytes the Python suite pins, not merely its name', () => {
    // This grepped for the constant NAME and a substring, so flipping the Python literal to
    // UTF-16 order left TypeScript at 703/703 green while Python went red. Each side still
    // pinned its own literal, so behaviour was pinned -- but the claim that neither engine
    // can agree with its own recomputation was not true until the two literals are actually
    // compared. They are now: the Python constant is parsed out and matched byte for byte.
    const source = readFileSync(PY_SUITE, 'utf-8');
    const match = /^ASTRAL_ARRAYS_CANONICAL = \(\n\s*(['"])(.*?)\1\n\)/ms.exec(source);
    expect(match).not.toBeNull();
    // Python writes the two characters as \uXXXX / \UXXXXXXXX escapes in the source literal;
    // decode them so the comparison is on the CHARACTERS both engines emit, not on spelling.
    const pythonLiteral = (match as RegExpExecArray)[2]
      .replace(/\\U([0-9a-fA-F]{8})/g, (_m, h: string) => String.fromCodePoint(parseInt(h, 16)))
      .replace(/\\u([0-9a-fA-F]{4})/g, (_m, h: string) => String.fromCodePoint(parseInt(h, 16)));
    expect(pythonLiteral).toBe(ASTRAL_ARRAYS_CANONICAL);
    // ...and the comparison is not vacuous: the parsed literal must be the real thing, and
    // must NOT equal the UTF-16 ordering it is there to exclude. Without these, replacing the
    // line above with a tautology left both suites green.
    expect(pythonLiteral).toContain(FULLWIDTH);
    expect(pythonLiteral).toContain(EMOJI);
    expect(pythonLiteral.indexOf(FULLWIDTH)).toBeLessThan(pythonLiteral.indexOf(EMOJI));
    expect(pythonLiteral).not.toBe(
      `[{"kind":"ordered","pointer":"/${EMOJI}"},{"kind":"ordered","pointer":"/${FULLWIDTH}"}]`,
    );
  });
});

// ====================================================== 4. the guard, proven able to fire ==

describe('the placement guard', () => {
  it('refuses the flag outside an opaque subtree, and names the difference', () => {
    const probe = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      // The sibling is load-bearing: with `tags` alone, removing the guard leaves
      // `included_pointers` EMPTY and the released `minItems` rejects the manifest anyway,
      // so the guard would be a nicer message rather than a rule.
      properties: { id: { type: 'string' }, tags: ORDERED_TAGS },
    };
    withSchemas([probe], () => {
      expect(() => deriveHashProfile(PROBE_ID)).toThrow(/\["\/tags"\] is not strictly inside/);
      // "Rejected" alone sends the author looking for a typo rather than for the annotation
      // that actually does this job.
      expect(() => deriveHashProfile(PROBE_ID)).toThrow(/x-datacompany-hash-excluded/);
    });
  });

  it('refuses the flag ON the opaque node itself — strictly under, never at', () => {
    const probe = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      properties: {
        id: { type: 'string' },
        value: {
          type: 'array',
          items: { type: 'string' },
          'x-datacompany-hash-opaque': true,
          [ANNOTATION]: true,
          'x-datacompany-array': { kind: 'ordered' },
        },
      },
    };
    // "At or under" would be satisfied by the node itself, so any author could suppress any
    // pointer anywhere by adding x-datacompany-hash-opaque beside the flag.
    withSchemas([probe], () => {
      expect(() => deriveHashProfile(PROBE_ID)).toThrow(/on one node/);
    });
  });

  it('refuses the pair ONE LEVEL DEEPER too, inside another opaque subtree', () => {
    // C1, found by an independent refuter. The ancestor test is satisfied by ANY opaque
    // ancestor, so a node carrying both annotations slipped through whenever it happened to
    // sit inside another opaque subtree -- the very bypass the ancestor test exists to
    // prevent, relocated one level down.
    withSchemas(
      [
        opaqueProbe({
          inner: {
            type: 'object',
            'x-datacompany-hash-opaque': true,
            [ANNOTATION]: true,
            properties: {
              tags: { type: 'array', items: { type: 'string' }, 'x-datacompany-array': { kind: 'ordered' } },
            },
          },
        }),
      ],
      () => {
        expect(() => deriveHashProfile(PROBE_ID)).toThrow(/\["\/value\/inner"\]/);
        expect(() => deriveHashProfile(PROBE_ID)).toThrow(/on one node/);
      },
    );
  });

  it('does not count an EXCLUDED member as a declared one', () => {
    // B1, found by an independent refuter. THE MOTIVATING SHAPE DID NOT WORK. The guard read
    // the RAW walk, where an excluded member is still a `properties` name, so it counted
    // /value/sig as a declaration that revokes opacity and refused the signed opaque payload
    // the two annotations exist for -- while the runtime escape hatch hashed it correctly.
    const signed = opaqueProbe({
      sig: {
        type: 'string',
        'x-datacompany-hash-excluded': true,
        'x-datacompany-hash-exclusion-reason': 'signature',
      },
      tags: ORDERED_TAGS,
    });
    let derived: HashProfile | null = null;
    withSchemas([signed], () => {
      derived = deriveHashProfile(PROBE_ID);
      expect(derived.included_pointers).toEqual(['/id', '/value']);
      expect(derived.excluded_pointers.map((e) => e.pointer)).toEqual(['/value/sig']);
      expect(derived.opaque_pointers).toEqual(['/value']);
      expect(derived.arrays).toEqual([{ pointer: '/value/tags', kind: 'ordered' }]);
      expect(buildHashView({ id: 'x', value: { sig: 's', tags: ['b', 'a'], other: 1 } }, derived)).toEqual(
        { id: 'x', value: { tags: ['b', 'a'], other: 1 } },
      );
    });
    // The equality that makes it a CLOSURE rather than a capability.
    withSchemas(
      [
        opaqueProbe({
          sig: {
            type: 'string',
            'x-datacompany-hash-excluded': true,
            'x-datacompany-hash-exclusion-reason': 'signature',
          },
        }),
      ],
      () => {
        const runtime = mergeProfileExtensions(deriveHashProfile(PROBE_ID), {
          arrays: [{ pointer: '/value/tags', kind: 'ordered' }],
        });
        expect(decode(canonicalJsonBytes(runtime))).toBe(
          decode(canonicalJsonBytes(derived as unknown as HashProfile)),
        );
      },
    );
  });

  it('does not list an opaque pointer that sits UNDER a declaration-only one', () => {
    // C2. The comment claiming this filter could only be a no-op argued about ANCESTORS and
    // said nothing about DESCENDANTS. Dropping the pointer changes no behaviour, which is
    // exactly why it needs a test rather than a comment.
    withSchemas(
      [
        opaqueProbe({
          inner: {
            type: 'object',
            [ANNOTATION]: true,
            properties: {
              deeper: {
                type: 'object',
                'x-datacompany-hash-opaque': true,
                properties: { t: { type: 'string' } },
              },
            },
          },
        }),
      ],
      () => {
        const manifest = deriveHashProfile(PROBE_ID);
        expect(manifest.opaque_pointers).toEqual(['/value']);
        expect(manifest.included_pointers).toEqual(['/id', '/value']);
        const view = buildHashView(
          { id: 'x', value: { inner: { deeper: { t: 'v' } } } },
          manifest,
        ) as JsonRecord;
        expect(view['value']).toEqual({ inner: { deeper: { t: 'v' } } });
      },
    );
  });

  it('agrees with the runtime route when the flagged array sorts FIRST', () => {
    // C3. The byte equality was an accident of sort order until `mergeProfileExtensions`
    // started sorting: derive sorts, merge appended, and they agreed on
    // bitemporal-assertion:1 only because /value/tags sorts after /basis_refs.
    const probe = {
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE_ID,
      type: 'object',
      ...EXTENSIBLE_ENVELOPE,
      properties: {
        aaa: { type: 'object', 'x-datacompany-hash-opaque': true, properties: { tags: ORDERED_TAGS } },
        zzz: { type: 'array', items: { type: 'string' }, 'x-datacompany-array': { kind: 'ordered' } },
      },
    };
    let schemaRoute: HashProfile | null = null;
    withSchemas([probe], () => {
      schemaRoute = deriveHashProfile(PROBE_ID);
      expect(schemaRoute.arrays.map((e) => e.pointer)).toEqual(['/aaa/tags', '/zzz']);
    });
    const unflagged = JSON.parse(JSON.stringify(probe)) as typeof probe & { properties: JsonRecord };
    delete (unflagged.properties['aaa'] as JsonRecord)['properties'];
    withSchemas([unflagged], () => {
      const runtime = mergeProfileExtensions(deriveHashProfile(PROBE_ID), {
        arrays: [{ pointer: '/aaa/tags', kind: 'ordered' }],
      });
      expect(runtime.arrays.map((e) => e.pointer)).toEqual(['/aaa/tags', '/zzz']);
      expect(decode(canonicalJsonBytes(runtime))).toBe(
        decode(canonicalJsonBytes(schemaRoute as unknown as HashProfile)),
      );
    });
  });

  it('renders a NON-ASCII pointer without escaping it', () => {
    // B2. `JSON.stringify` never escapes non-ASCII; Python's `json.dumps` does by default,
    // so this side was always right and Python's was not. Asserted here anyway, because the
    // parity is a claim about BOTH engines and a later "escape it for safety" change on this
    // side would reopen the divergence from the other direction.
    withSchemas(
      [
        {
          $schema: 'https://json-schema.org/draft/2020-12/schema',
          $id: PROBE_ID,
          type: 'object',
          properties: { id: { type: 'string' }, 'caf\u00e9\u{1F600}': ORDERED_TAGS },
        },
      ],
      () => {
        let message = '';
        try {
          deriveHashProfile(PROBE_ID);
        } catch (error) {
          message = (error as Error).message;
        }
        expect(message).toContain('["/caf\u00e9\u{1F600}"]');
        expect(message).not.toContain('\\u00e9');
      },
    );
  });

  it('refuses a subtree that declares SOME members beside the flag', () => {
    withSchemas([opaqueProbe({ note: { type: 'string' }, tags: ORDERED_TAGS })], () => {
      expect(() => deriveHashProfile(PROBE_ID)).toThrow(/\["\/value\/note"\]/);
      expect(() => deriveHashProfile(PROBE_ID)).toThrow(/\["\/value\/tags"\]/);
    });
  });

  it('still refuses a nested opaque SIBLING, which revokes the outer opacity', () => {
    // The discriminating half of the nested case, FOUND BY MUTATION. Nesting is legal when
    // the flag sits INSIDE the inner subtree and broken when it sits beside it:
    // `/value/nested` is a declared member of `/value`, so `/value`'s opacity is revoked and
    // `/value/tags` becomes the one member that cannot be declared.
    withSchemas(
      [
        opaqueProbe({
          tags: ORDERED_TAGS,
          nested: {
            type: 'object',
            'x-datacompany-hash-opaque': true,
            properties: { note: { type: 'string' } },
          },
        }),
      ],
      () => {
        expect(() => deriveHashProfile(PROBE_ID)).toThrow(/"\/value\/nested"/);
        expect(() => deriveHashProfile(PROBE_ID)).toThrow(/\["\/value\/tags"\]/);
      },
    );
  });

  it('does NOT fire on the shapes it must allow', () => {
    // The false-positive control for all three refusals: a guard that raised on everything
    // would satisfy every one of them.
    withSchemas([opaqueProbe()], () => {
      expect(deriveHashProfile(PROBE_ID).opaque_pointers).toEqual(['/value']);
    });

    // One flag at the OUTERMOST node of a properties chain; the cascade carries it down, so
    // the array node needs no flag of its own.
    const arrayOnly: JsonRecord = { ...ORDERED_TAGS };
    delete arrayOnly[ANNOTATION];
    withSchemas(
      [opaqueProbe({ nested: { type: 'object', [ANNOTATION]: true, properties: { tags: arrayOnly } } })],
      () => {
        const deep = deriveHashProfile(PROBE_ID);
        expect(deep.arrays).toEqual([{ pointer: '/value/nested/tags', kind: 'ordered' }]);
        expect(deep.included_pointers).toEqual(['/id', '/value']);
      },
    );

    // Nested opaque subtrees: the inner root IS a declared member of the outer one, which is
    // sound. Grouping by every opaque ancestor instead of the NEAREST one refuses this.
    withSchemas(
      [
        opaqueProbe({
          nested: {
            type: 'object',
            'x-datacompany-hash-opaque': true,
            properties: { tags: ORDERED_TAGS },
          },
        }),
      ],
      () => {
        const nested = deriveHashProfile(PROBE_ID);
        expect(nested.opaque_pointers).toEqual(['/value', '/value/nested']);
        expect(nested.included_pointers).toEqual(['/id', '/value', '/value/nested']);
        expect(nested.arrays).toEqual([{ pointer: '/value/nested/tags', kind: 'ordered' }]);
      },
    );
  });
});

// ============================================================== 5. two-language parity ====

describe('parity with the Python engine', () => {
  it('reads the flag with the same identity check and the same post-filter', () => {
    const source = readFileSync(PY_ENGINE, 'utf-8');
    // Non-vacuity: an unreadable or renamed file makes every check below trivially true.
    expect(source).toContain('class _Walker');
    expect(source).toContain(`schema.get("${ANNOTATION}") is True`);
    expect(source).toContain('self.declaration_only');
    // Post-filter, not inline.
    expect(source).toContain('not _at_or_under(pointer, walker.declaration_only)');
    // ...and BOTH guards exist and are CALLED, not merely defined. Two, not one: they run at
    // different points on purpose -- placement against the raw walk, declare-none-or-all
    // against the DERIVED included list -- and collapsing them is what refused the signed
    // opaque payload.
    expect(source).toContain('_require_declaration_only_is_legally_placed(walker, schema_ref)');
    expect(source).toContain(
      '_require_declaration_only_does_not_collide_with_a_declared_member(walker, included, schema_ref)',
    );
    // The pair refusal is unconditional (C1), the opaque filter exists (C2), and the merge
    // sorts (C3) -- each mirrored on this side and asserted from that side.
    expect(source).toContain('walker.declaration_only & walker.opaque');
    expect(source).toContain('and not _at_or_under(pointer, walker.declaration_only)');
    // Read from PY_RENDERING, not `source`: the parity being pinned is unchanged, only the
    // file carrying it moved. It is pinned HARDER than before, because `json_text` also
    // escapes unpaired surrogates to match ES2019's well-formed `JSON.stringify` -- which
    // `ensure_ascii=False` on its own does not, and which it in fact REGRESSED.
    expect(readFileSync(PY_RENDERING, 'utf-8')).toContain('ensure_ascii=False');
    expect(source).toContain('key=lambda entry: entry["pointer"]');
  });

  it('registers the annotation in the closed meta-schema vocabulary', () => {
    const meta = JSON.parse(
      readFileSync(
        join(REPOSITORY_ROOT, 'schemas', 'meta', 'datacompany-extension-vocabulary.v1.schema.json'),
        'utf-8',
      ),
    ) as JsonRecord;
    const vocabulary = ((meta['$defs'] as JsonRecord)['vocabulary'] as JsonRecord)[
      'enum'
    ] as string[];
    expect(vocabulary).toContain(ANNOTATION);
  });
});

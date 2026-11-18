/**
 * The obligations no fixture can discharge: coverage equality (P7), falsifiability (P9) and
 * refusal-to-measure-nothing (P10).
 *
 * Wave 1's entire finding was that gates were never falsified. A suite that replays 66
 * fixtures and stays green when the engine is broken measures nothing; a suite that
 * discovers zero fixtures and reports "0 failed" measures nothing either. Both are proved
 * here rather than asserted in prose.
 */

import { mkdtempSync, readFileSync, existsSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { canonicalJsonBytes, canonicalSha256, computeContentHash } from '../src/engine';
import { deriveHashProfile, validateProfileAgainstSchema } from '../src/hashProfile';
import { buildHashView } from '../src/hashView';
import { HashProfileError, SchemaValidationError } from '../src/errors';
import { REPOSITORY_ROOT, canonicalSchemas, validateSchemaOnly } from '../src/registry';
import {
  checkCrossFieldRules,
  crossFieldRulesAreEvaluated,
  registerCrossFieldEvaluator,
  resetCrossFieldEvaluator,
} from '../src/validation';
import {
  HASH_ROOT,
  INVALID_REF_DIR,
  MANIFEST_DIR,
  MUTATION_DIR,
  REJECTED_DIR,
  RFC_DIR,
  VALID_REF_DIR,
  VECTOR_DIR,
  VERIFICATION_DIR,
  clone,
  decodeUtf8,
  fixtureFiles,
  load,
  profileFor,
  setPointer,
  vector,
  type VectorFixture,
} from './fixtures';

/**
 * P7 -- the coverage pin, as an EQUALITY, over the WHOLE committed corpus.
 *
 * The plan's "total = 111" is stale in two places, both of which are settled from the
 * fixtures on disk rather than from the prose: `hash/vectors` gained
 * `set-like-array-astral-vs-private-use-order-key` (15 -> 16) and
 * `references/verification` gained `verification-owner-content-does-not-validate`
 * (13 -> 14). The committed corpus is 113, and P6's "11 + 22 + 13" is likewise 11 + 22 + 14
 * = 47 reference checks -- which is why the plan's own summary line says 47 while its P6 row
 * says 13. A floor lets a fixture appear unnoticed; an equality does not.
 *
 * Every number here is cross-checked against Python's `SUITES` table below, so the two
 * engines cannot drift apart in silence.
 */
const RFC_NUMBER_VECTORS = 32;
const RFC_STRUCTURAL_FILES = 2;

const DIRECTORY_SUITES: readonly { name: string; directory: string; checks: number }[] = [
  { name: 'references/valid', directory: VALID_REF_DIR, checks: 11 },
  { name: 'references/invalid', directory: INVALID_REF_DIR, checks: 22 },
  { name: 'references/verification', directory: VERIFICATION_DIR, checks: 14 },
  { name: 'hash/vectors', directory: VECTOR_DIR, checks: 16 },
  { name: 'hash/mutations', directory: MUTATION_DIR, checks: 8 },
  { name: 'hash/rejected', directory: REJECTED_DIR, checks: 3 },
  { name: 'hash/manifests', directory: MANIFEST_DIR, checks: 5 },
];

const RFC_CHECKS = RFC_NUMBER_VECTORS + RFC_STRUCTURAL_FILES;
const EXPECTED_TOTAL_CHECKS =
  RFC_CHECKS + DIRECTORY_SUITES.reduce((total, suite) => total + suite.checks, 0);

const PY_HARNESS = join(
  REPOSITORY_ROOT,
  'src',
  'research_contracts',
  'tooling',
  'canonical_fixtures.py',
);

/** Read the Python harness's own pinned per-suite counts out of its source. */
function pythonSuiteCounts(): Map<string, number> {
  const source = readFileSync(PY_HARNESS, 'utf-8');
  const counts = new Map<string, number>();
  const pattern = /Suite\("([^"]+)",\s*[A-Z_]+\s*\/\s*"([^"]+)",\s*(\d+)\)/g;
  for (const match of source.matchAll(pattern)) {
    counts.set(match[1], Number(match[3]));
  }
  return counts;
}

describe('P7: the check count is pinned as an equality', () => {
  it.each(DIRECTORY_SUITES.map((suite) => [suite.name, suite] as const))(
    '%s contributes exactly its pinned number of checks',
    (_name, suite) => {
      expect(fixtureFiles(suite.directory).length).toBe(suite.checks);
    },
  );

  it('replays exactly 32 RFC 8785 number vectors and 2 structural samples', () => {
    const numbers = load<{ vectors: unknown[] }>(join(RFC_DIR, 'number-serialization.json'));
    expect(numbers.vectors.length).toBe(RFC_NUMBER_VECTORS);
    expect(fixtureFiles(RFC_DIR).length).toBe(RFC_STRUCTURAL_FILES + 1);
  });

  it(`totals exactly ${EXPECTED_TOTAL_CHECKS} checks, the whole committed corpus`, () => {
    const observed =
      RFC_CHECKS +
      DIRECTORY_SUITES.reduce((total, suite) => total + fixtureFiles(suite.directory).length, 0);
    expect(observed).toBe(EXPECTED_TOTAL_CHECKS);
    expect(EXPECTED_TOTAL_CHECKS).toBe(113);
  });

  it('the reference and verification scope is 47 checks, counted from disk', () => {
    // The plan states 47 in one place and 11 + 22 + 13 = 46 in another. The fixtures decide:
    // the verification suite has 14 members since the fix that turns an unhashable owner
    // response into a rejected receipt instead of an escaping error and no audit record.
    const reference = DIRECTORY_SUITES.filter((suite) => suite.name.startsWith('references/'));
    expect(reference.map((suite) => fixtureFiles(suite.directory).length)).toEqual([11, 22, 14]);
    expect(reference.reduce((total, suite) => total + fixtureFiles(suite.directory).length, 0)).toBe(
      47,
    );
  });

  it('agrees, suite by suite, with the number Python pins in EXPECTED_CHECKS', () => {
    const python = pythonSuiteCounts();
    // Non-vacuity first: an unparsed harness would silently make every lookup `undefined`.
    expect(python.size).toBe(8);
    for (const suite of DIRECTORY_SUITES) {
      expect(python.get(suite.name)).toBe(suite.checks);
    }
    expect(python.get('hash/rfc8785')).toBe(RFC_CHECKS);
    const pythonTotal = [...python.values()].reduce((total, value) => total + value, 0);
    // Not "the TS total is a subset of Python's" any more: the two engines replay the SAME
    // corpus, so the two pins are one number.
    expect(pythonTotal).toBe(EXPECTED_TOTAL_CHECKS);
  });
});

describe('P10: the suite refuses to measure nothing', () => {
  it('throws rather than returning [] for an EMPTY fixture directory', () => {
    const empty = mkdtempSync(join(tmpdir(), 'datacompany-empty-'));
    try {
      expect(() => fixtureFiles(empty)).toThrow(/no fixtures found/);
    } finally {
      rmSync(empty, { recursive: true, force: true });
    }
  });

  it('throws rather than returning [] for a MISSING fixture directory', () => {
    // Python's `Path.glob` on a missing directory returns [] silently -- the exact shape of
    // defect B1. `readdirSync` raises, and this pins that it is never caught and softened.
    expect(() => fixtureFiles(join(HASH_ROOT, 'no-such-suite'))).toThrow();
  });

  it('ignores non-JSON files rather than counting them as fixtures', () => {
    const directory = mkdtempSync(join(tmpdir(), 'datacompany-nonjson-'));
    try {
      writeFileSync(join(directory, 'README.md'), '# not a fixture\n');
      expect(() => fixtureFiles(directory)).toThrow(/no fixtures found/);
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  it('enumerates fixtures ONLY through fixtureFiles, so it cannot be relocated into vacuity', () => {
    const suiteFiles = [
      'vectors.test.ts',
      'mutations.test.ts',
      'rejected.test.ts',
      'manifests.test.ts',
      'references.test.ts',
      'verification.test.ts',
    ];
    for (const name of suiteFiles) {
      const source = readFileSync(join(__dirname, name), 'utf-8');
      // Each replaying suite discovers its corpus through the throwing loader...
      expect(source).toContain('fixtureFiles(');
      // ...and none of them reads a directory itself, where an empty result would be green.
      expect(source).not.toContain('readdirSync');
      expect(source).not.toContain('globSync');
    }
  });

  it('resolves a repository root that actually holds the fixture tree', () => {
    // Defect B1 in the Python register: a root computed by counting `..` levels points
    // outside the package once installed, every glob returns [], and the suite reads green
    // over zero schemas. An existence assertion is the cheapest guard against that class.
    expect(existsSync(join(REPOSITORY_ROOT, 'schemas', 'canonical'))).toBe(true);
    expect(existsSync(HASH_ROOT)).toBe(true);
    expect(existsSync(VECTOR_DIR)).toBe(true);
  });
});

/**
 * Places where Python is NORMATIVE and doing the obviously-right thing would be a silent
 * divergence. Each is pinned so a later "cleanup" goes red instead of shipping.
 *
 * The first two assertions of each case are a SOURCE tripwire and prove only that the shape
 * is still there; the behavioural assertion that follows is the real gate.
 */
describe('bug-compatible quirks: Python is normative, do not clean these up', () => {
  const pythonSource = readFileSync(
    join(REPOSITORY_ROOT, 'src', 'research_contracts', 'canonical', 'hash_profile.py'),
    'utf-8',
  );
  const tsSource = readFileSync(join(__dirname, '..', 'src', 'hashProfile.ts'), 'utf-8');

  it('the exclusion cascade filters ALL THREE members by prefix, and declaration-only is a separate rule', () => {
    // REWRITTEN 2026-08-04, not deleted. This case read "the exclusion cascade filters arrays
    // by EXACT match and everything else by PREFIX" and pinned that asymmetry as normative:
    // `arrays` dropped only an exact key while `included_pointers` and `opaque_pointers`
    // dropped anything at or under an exclusion, so an array nested under an excluded subtree
    // survived in the manifest. EXTENSIONS.md §5.2 offered two remedies -- reproduce it, or
    // change both engines together with a `profile_version` bump -- and the second was taken:
    // `DERIVATION_PROFILE_VERSION` is 2 and every committed manifest moved with it. The old
    // assertions are recorded here rather than silently replaced, because a bug-compatibility
    // pin that is deleted is indistinguishable from one that was quietly lost.
    //
    // All three exclusion filters now go through the SAME named predicate in each language.
    expect(pythonSource).toContain('pointer == prefix or pointer.startswith(f"{prefix}/")');
    // THREE times, not two: `included_pointers`, `opaque_pointers` AND `arrays` each apply
    // it. A copy-paste that dropped one call site would still satisfy `toContain`, and
    // dropping the `arrays` one is precisely the regression this case exists to catch.
    expect(pythonSource.split('not _at_or_under(pointer, excluded_pointers)').length - 1).toBe(3);
    expect(tsSource.split('!isUnderExclusion(').length - 1).toBe(3);
    // ...and the shapes that made the old quirk are GONE from both engines, so a revert
    // cannot hide behind the rewritten prose.
    expect(pythonSource).not.toContain('if pointer in excluded_pointers:');
    expect(pythonSource).not.toContain('entry["pointer"] != pointer');
    expect(tsSource).not.toContain('excludedPointers.has(pointer)');
    expect(tsSource).not.toContain('entry.pointer !== pointer');
    // D9's declaration-only cascade is a DIFFERENT rule that did not move: it is by prefix
    // for its own reason (an exact filter leaks an array-of-objects' member pointers and
    // revokes the opacity it exists to preserve) and must NEVER reach `arrays` at all --
    // carrying the declaration out of an undeclared subtree is the annotation's whole
    // purpose. "The filters are consistent now" is true of the exclusion cascade and says
    // nothing about this one.
    // TWICE, and exactly twice: `included_pointers` and `opaque_pointers`. A THIRD call site
    // would be `arrays` acquiring the filter it must never have, which is the one cleanup
    // that leaves every committed manifest byte-identical and still breaks D9.
    expect(
      pythonSource.split('not _at_or_under(pointer, walker.declaration_only)').length - 1,
    ).toBe(2);
    expect(tsSource.split('!isDeclarationOnly(').length - 1).toBe(2);
    expect(tsSource).toContain('pointer === suppressed || pointer.startsWith(`${suppressed}/`)');

    // The behavioural gate, unchanged in shape: both engines derive every committed manifest
    // byte for byte. It is what catches a cascade change in either direction.
    for (const path of fixtureFiles(MANIFEST_DIR)) {
      const manifest = load<ReturnType<typeof deriveHashProfile>>(path);
      expect(deriveHashProfile(manifest.schema_ref)).toEqual(manifest);
    }
  });

  it('an x-datacompany-array declaration may no longer carry its own pointer (§7.4)', () => {
    // REWRITTEN, not deleted. This test used to read "carries its own pointer OVERRIDES the
    // derived one", and it was written to record the fail-open rather than to catch it: its
    // own comment said "no committed schema triggers it, so there is nothing to assert
    // behaviourally here". It stayed GREEN through the closure, because both source strings
    // it pins are still there -- the merge order is unchanged on purpose. A test that
    // documents the opposite of the truth while passing is the shape this repository keeps
    // finding, so the claim is re-stated to what is now true and given the behavioural half
    // it never had.
    //
    // The merge order IS still `{"pointer": derived, **annotation}`, annotation last. That
    // is deliberate and mirrored: changing the precedence would be a divergence, and it is
    // no longer dangerous because the shape that exploited it is refused at the node.
    expect(pythonSource).toContain('{"pointer": pointer, **array_declaration}');
    expect(tsSource).toContain('{ pointer, ...(arrayDeclaration as object) }');
    // The behavioural half, in both directions: the re-targeting declaration is refused,
    // and the declaration WITHOUT a pointer still lands at the pointer the walk derived --
    // which is what distinguishes closing the defect from deleting the feature.
    const PROBE = 'urn:datacompany:array-pointer-precedence-probe:1';
    const schemas = canonicalSchemas() as Map<string, unknown>;
    const probe = (declaration: unknown) => ({
      $schema: 'https://json-schema.org/draft/2020-12/schema',
      $id: PROBE,
      type: 'object',
      properties: {
        tags: { type: 'array', items: { type: 'string' }, 'x-datacompany-array': declaration },
      },
    });
    try {
      schemas.set(PROBE, probe({ pointer: '/elsewhere', kind: 'ordered' }));
      expect(() => deriveHashProfile(PROBE)).toThrow(HashProfileError);
      schemas.set(PROBE, probe({ kind: 'ordered' }));
      expect(deriveHashProfile(PROBE).arrays).toEqual([{ pointer: '/tags', kind: 'ordered' }]);
    } finally {
      schemas.delete(PROBE);
    }
  });

  it('all three flags are read with an identity check, and non-true values are REFUSED', () => {
    // REWRITTEN, not deleted -- the third in this file, and the one that was missed when the
    // other two were done. The old title said `false/0/1/"true"` were "silent no-ops"; they
    // are refused at derivation since §8's correction C2, so the title asserted the opposite
    // of the behaviour while the body passed on source strings that are still there.
    //
    // The Python side pinned only the bare substring `is True`, which the module's own
    // DOCSTRINGS satisfy: changing BOTH `x-datacompany-hash-excluded` and `x-datacompany-hash-opaque`
    // from `is True` to `bool(...)` left this green. Each of the three reads is now pinned in
    // full, in both languages, because the refusal fires first and the reads are no longer
    // observable through a derived manifest.
    for (const flag of [
      'x-datacompany-hash-excluded',
      'x-datacompany-hash-opaque',
      'x-datacompany-hash-declaration-only',
    ]) {
      expect(pythonSource).toContain(`schema.get("${flag}") is True`);
      expect(tsSource).toContain(`schema['${flag}'] === true`);
    }
    // A `=== true` -> truthiness "fix" would make one engine suppress a pointer the other
    // still declares -- a divergence in the direction nobody notices.
    expect(tsSource).not.toContain("if (schema['x-datacompany-hash-opaque'])");
    // And the refusal that now stands in front of all three.
    expect(pythonSource).toContain('_IDENTITY_COMPARED_FLAGS');
    expect(tsSource).toContain('IDENTITY_COMPARED_FLAGS');
  });

  it('a non-object x-datacompany-array now RAISES rather than being dropped (§7.3)', () => {
    // REWRITTEN, not deleted. The old assertion pinned the two type tests -- Python's
    // `isinstance(array_declaration, dict)` and this port's `isRecord(arrayDeclaration)` --
    // as the shared behaviour, and those tests WERE the fail-open: a non-object declaration
    // failed them and was dropped in silence. Both are gone, because after the annotation
    // guard neither could evaluate false any more, and a condition that cannot fire reads as
    // defence in depth while being untestable.
    expect(pythonSource).not.toContain('isinstance(array_declaration, dict)');
    expect(tsSource).not.toContain('if (isRecord(arrayDeclaration))');
    const PROBE = 'urn:datacompany:non-object-array-probe:1';
    const schemas = canonicalSchemas() as Map<string, unknown>;
    try {
      for (const declaration of ['set', ['set'], true]) {
        schemas.set(PROBE, {
          $schema: 'https://json-schema.org/draft/2020-12/schema',
          $id: PROBE,
          type: 'object',
          properties: {
            tags: { type: 'array', items: { type: 'string' }, 'x-datacompany-array': declaration },
          },
        });
        expect(() => deriveHashProfile(PROBE)).toThrow(HashProfileError);
      }
    } finally {
      schemas.delete(PROBE);
    }
  });

  it('manifest entries are ordered by RFC 8785 canonical bytes, the key merged Python uses', () => {
    // WS1 replaced a `repr` sort here, under which two manifests that are the same JSON
    // with entries written in different member order compared unequal. Both sides now use
    // the same canonical-bytes key, so the parity is by construction.
    expect(pythonSource).toContain('key=_canonical_order');
    expect(tsSource).toContain('compareBytes(canonicalOrder(a), canonicalOrder(b))');

    const committed = load<ReturnType<typeof deriveHashProfile>>(
      join(MANIFEST_DIR, 'immutable-version.v1.profile.json'),
    );
    // The behavioural gate: a member-order round trip must NOT be rejected.
    const reordered = clone(committed);
    reordered.excluded_pointers = reordered.excluded_pointers.map((entry) => ({
      reason: entry.reason,
      pointer: entry.pointer,
    }));
    expect(() => {
      validateProfileAgainstSchema(reordered, committed.schema_ref);
    }).not.toThrow();
  });
});

/**
 * B7, verified rather than assumed after the WS1 rebase.
 *
 * Python's `$` used to match BEFORE a trailing newline, so every anchored released pattern
 * was fail-open and `"sha256:<64 hex>\n"` validated. JSON Schema mandates ECMA-262, so
 * Python was the non-conformant side and Ajv was already right. WS1 fixed Python with an
 * explicit ECMA-262 pattern translation, which REMOVES the divergence rather than creating
 * one to emulate. Re-derived live against merged main, not read off the old source.
 */
describe('B7: anchored patterns reject a trailing newline in both engines', () => {
  it('rejects a trailing newline in a released anchored pattern', () => {
    const fixture = vector('immutable-version-nested-pins');
    expect(validateSchemaOnly(fixture.instance, fixture.schema_ref)).toEqual([]);

    const trailing = clone(fixture.instance);
    trailing['content_hash'] = `${String(fixture.instance['content_hash'])}\n`;
    const errors = validateSchemaOnly(trailing, fixture.schema_ref);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.join(' ')).toMatch(/content_hash/);
  });

  /**
   * The `^sha256:[0-9a-f]{64}$` anchored pattern, where OLD Python failed open: `$` matched
   * before a trailing `\n`, so a digest with a stray newline passed a check that every
   * conforming engine rejects. These expectations were read off BOTH engines after the WS1
   * rebase — merged Python via `validate_schema_only`, this port via Ajv.
   */
  const DIGEST = 'sha256:' + 'a'.repeat(64);
  it.each([
    [DIGEST, false],
    [`${DIGEST}\n`, true],
    [`${DIGEST}\r`, true],
    [`sha256:${'A'.repeat(64)}`, true],
    [`sha256:${'g'.repeat(64)}`, true],
    ['', true],
  ] as [string, boolean][])(
    'the anchored digest pattern rejects %j: %s (same answer as merged Python)',
    (value, rejected) => {
      const ref = 'urn:datacompany:stable-identity:1#/$defs/content_hash';
      expect(validateSchemaOnly(value, ref).length > 0).toBe(rejected);
    },
  );
});

describe('P9: each gate is proven able to fail', () => {
  const GOLDEN = 'immutable-version-nested-pins';

  it('P1/P2 -- perturbing a golden instance breaks BOTH the canonical bytes and the digest', () => {
    const fixture = vector(GOLDEN);
    const profile = profileFor(fixture);
    const clean = buildHashView(fixture.instance, profile);
    expect(decodeUtf8(canonicalJsonBytes(clean))).toBe(fixture.expected_hash_view_canonical_json);
    expect(canonicalSha256(clean)).toBe(fixture.expected_content_hash);

    const perturbed = clone(fixture.instance);
    setPointer(perturbed, '/created_by', 'someone-else');
    const dirty = buildHashView(perturbed, profile);
    expect(decodeUtf8(canonicalJsonBytes(dirty))).not.toBe(
      fixture.expected_hash_view_canonical_json,
    );
    expect(canonicalSha256(dirty)).not.toBe(fixture.expected_content_hash);
  });

  it('P1 -- a matching digest is not accepted as proof of matching canonical bytes', () => {
    // The two assertions are independent: this pins that the byte comparison is the one
    // that would catch a fixture regenerated from a different implementation.
    const fixture = vector(GOLDEN);
    const forged = `${fixture.expected_hash_view_canonical_json} `;
    expect(forged).not.toBe(fixture.expected_hash_view_canonical_json);
    expect(canonicalSha256(buildHashView(fixture.instance, profileFor(fixture)))).toBe(
      fixture.expected_content_hash,
    );
  });

  it('P3 -- an "unchanged" mutation case goes red if an excluded pointer stops being excluded', () => {
    const fixture = vector(GOLDEN);
    const profile = deriveHashProfile(fixture.schema_ref);
    // `/profile_ref/resolved_at` is a released exclusion: mutating it must NOT move the hash.
    const mutated = clone(fixture.instance);
    setPointer(mutated, '/profile_ref/resolved_at', '2031-01-01T00:00:00Z');
    expect(computeContentHash(mutated, fixture.schema_ref, { profile })).toBe(
      fixture.expected_content_hash,
    );
    // Break the exclusion and the same case flips to "changed" -- so the gate has teeth.
    const leaky = deriveHashProfile(fixture.schema_ref);
    leaky.excluded_pointers = leaky.excluded_pointers.filter(
      (entry) => entry.pointer !== '/profile_ref/resolved_at',
    );
    leaky.included_pointers = [...leaky.included_pointers, '/profile_ref/resolved_at'];
    // It cannot even be used: the derivation check refuses it before a hash is produced.
    expect(() => computeContentHash(mutated, fixture.schema_ref, { profile: leaky })).toThrow(
      HashProfileError,
    );
  });

  it('P5 -- the manifest gate is a DERIVATION check, so a tampered manifest goes red', () => {
    const committed = load<ReturnType<typeof deriveHashProfile>>(
      join(MANIFEST_DIR, 'immutable-version.v1.profile.json'),
    );
    const derived = deriveHashProfile(committed.schema_ref);
    expect(derived).toEqual(committed);

    // Reading the committed file and comparing it to itself would survive this.
    const tampered = clone(committed);
    tampered.included_pointers = tampered.included_pointers.filter((p) => p !== '/created_by');
    expect(tampered).not.toEqual(deriveHashProfile(tampered.schema_ref));
  });

  it('P9 -- the cross-field seam is genuinely consulted, so planting a rule goes red', () => {
    // The released evaluator is installed by default now, so a green hash run is a result
    // about BOTH layers rather than the schema layer alone.
    expect(crossFieldRulesAreEvaluated()).toBe(true);
    const fixture = vector(GOLDEN);
    expect(computeContentHash(fixture.instance, fixture.schema_ref)).toBe(
      fixture.expected_content_hash,
    );

    try {
      registerCrossFieldEvaluator(() => ['planted: the evaluator was consulted']);
      // A stub is not the released evaluator, and says so: a suite that swapped one in and
      // forgot to restore it cannot report itself as parity.
      expect(crossFieldRulesAreEvaluated()).toBe(false);
      expect(checkCrossFieldRules({}, fixture.schema_ref)).toEqual([
        'planted: the evaluator was consulted',
      ]);
      // Every hash of every vector now fails -- proof the seam is on the hashing path and
      // not a decorative export. A no-op seam would leave this line green.
      expect(() => computeContentHash(fixture.instance, fixture.schema_ref)).toThrow(
        /planted: the evaluator was consulted/,
      );
    } finally {
      resetCrossFieldEvaluator();
    }
    expect(crossFieldRulesAreEvaluated()).toBe(true);
    expect(computeContentHash(fixture.instance, fixture.schema_ref)).toBe(
      fixture.expected_content_hash,
    );
  });

  /**
   * FOUND BY PROBE, then closed.
   *
   * Stubbing `validateSchemaOnly` to return `[]` unconditionally left the whole suite green:
   * every hash fixture is schema-VALID, so `expect(validateSchemaOnly(...)).toEqual([])` is
   * satisfied by a validator that never validates, and the three `rejected/*` fixtures fail
   * inside the hash engine rather than at the schema layer. Step 1 of the section 4.3
   * algorithm therefore had no falsifying case anywhere in this port. This is that case.
   */
  it('P9 -- the JSON Schema layer is falsifiable: a schema-invalid instance is reported AND refused', () => {
    const fixture = vector(GOLDEN);
    expect(validateSchemaOnly(fixture.instance, fixture.schema_ref)).toEqual([]);

    const broken = clone(fixture.instance);
    broken['entity_id'] = 'not-a-uuid';
    const errors = validateSchemaOnly(broken, fixture.schema_ref);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.join(' ')).toMatch(/entity_id/);

    // ...and step 1 is genuinely on the hashing path, not merely exported.
    expect(() => computeContentHash(broken, fixture.schema_ref)).toThrow(SchemaValidationError);

    // A second, independent falsifier so one lenient keyword cannot hide the whole layer:
    // a required member removed entirely.
    const truncated = clone(fixture.instance);
    delete truncated['version_number'];
    expect(validateSchemaOnly(truncated, fixture.schema_ref).length).toBeGreaterThan(0);
    expect(() => computeContentHash(truncated, fixture.schema_ref)).toThrow(SchemaValidationError);
  });

  it('P9 -- the hash VIEW step is load-bearing: hashing the raw instance is a different digest', () => {
    const fixture = vector(GOLDEN);
    // If `buildHashView` were neutered into an identity function, every vector would go red
    // rather than quietly agreeing -- this states the two digests are genuinely different.
    expect(canonicalSha256(fixture.instance)).not.toBe(fixture.expected_content_hash);
  });

  it('P9 -- the fixture corpus is the oracle: an edited expectation cannot be satisfied', () => {
    const fixture = load<VectorFixture>(join(VECTOR_DIR, `${GOLDEN}.json`));
    const forged: VectorFixture = {
      ...fixture,
      expected_content_hash: `sha256:${'0'.repeat(64)}`,
    };
    const recomputed = computeContentHash(forged.instance, forged.schema_ref, {
      profile: profileFor(forged),
    });
    expect(recomputed).not.toBe(forged.expected_content_hash);
    expect(recomputed).toBe(fixture.expected_content_hash);
  });
});

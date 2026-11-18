/**
 * FND-002 tasks 2/3/6 in the SECOND language.
 *
 * `FND-CANONICAL-CONTRACT` requires the valid/invalid fixtures to pass "in Python and
 * TypeScript". This suite replays the same committed `fixtures/foundation/v1` corpus the
 * Python harness replays, from the repository root, never a copy: a transformed fixture
 * proves only that the transformation is self-consistent.
 *
 * FULL parity, both layers. Five of the 57 invalid fixtures carry `cross_field_only: true`
 * because the JSON Schema layer ACCEPTS them and only a released `x-datacompany-cross-field`
 * rule rejects them. This suite asserts BOTH halves of that for each of them — schema-valid,
 * and refused by `evaluateCrossFieldRules` — so the split is a measured property of the
 * corpus rather than a category anyone has to maintain by hand.
 *
 * That is a change of footing worth naming: when this suite was first written the port had
 * no cross-field evaluator and the four could only be asserted as a documented gap. A
 * sibling PR landed `src/structural.ts` on main mid-flight, so the gap closed and the
 * weaker assertion would have gone on passing while claiming something untrue. It is
 * replaced rather than kept.
 */

import { existsSync, readFileSync } from 'node:fs';
import { basename, join } from 'node:path';

import { canonicalJsonBytes, canonicalSha256, computeContentHash } from '../src/engine';
import { deriveHashProfile } from '../src/hashProfile';
import { buildHashView } from '../src/hashView';
import { parseCanonicalJson } from '../src/json';
import {
  FOUNDATION_SCHEMA_DIRS,
  REPOSITORY_ROOT,
  canonicalSchemas,
  schemaFailureCodes,
  validateSchemaOnly,
} from '../src/registry';
import { evaluateCrossFieldRules } from '../src/structural';
import { clone, decodeUtf8, fixtureFiles, load, setPointer } from './fixtures';

const FOUNDATION_ROOT = join(REPOSITORY_ROOT, 'fixtures', 'foundation', 'v1');
const VALID_DIR = join(FOUNDATION_ROOT, 'valid');
const INVALID_DIR = join(FOUNDATION_ROOT, 'invalid');
const HASH_DIR = join(FOUNDATION_ROOT, 'hash');
const MUTATION_DIR = join(FOUNDATION_ROOT, 'mutations');
const MANIFEST_DIR = join(FOUNDATION_ROOT, 'manifests');

/**
 * Pinned as an EQUALITY, mirroring `EXPECTED_FOUNDATION_CHECKS` in Python's
 * `tooling/foundation_fixtures.py`, and cross-checked against that file's own `Suite(...)`
 * table below so the two languages cannot drift apart in silence.
 */
const EXPECTED_VALID = 30;
const EXPECTED_INVALID = 58;
const EXPECTED_HASH = 2;
const EXPECTED_MUTATIONS = 6;
const EXPECTED_MANIFESTS = 2;
const EXPECTED_CROSS_FIELD_ONLY = 5;
const EXPECTED_FOUNDATION_CHECKS =
  EXPECTED_VALID + EXPECTED_INVALID + EXPECTED_HASH + EXPECTED_MUTATIONS + EXPECTED_MANIFESTS;

const PY_HARNESS = join(
  REPOSITORY_ROOT,
  'src',
  'research_contracts',
  'tooling',
  'foundation_fixtures.py',
);
const PY_REGISTRY = join(
  REPOSITORY_ROOT,
  'src',
  'research_contracts',
  'canonical',
  'registry.py',
);

interface FoundationFixture {
  fixture_id: string;
  schema_ref: string;
  rationale: string;
  instance: unknown;
  expected_error_contains?: string[];
  expected_schema_failures: { pointer: string; keyword: string }[];
  cross_field_only?: boolean;
}

interface HashFixture extends FoundationFixture {
  instance: Record<string, unknown>;
  expected_hash_view_canonical_json: string;
  expected_content_hash: string;
}

function fixtures(directory: string): FoundationFixture[] {
  return fixtureFiles(directory).map((path) => load<FoundationFixture>(path));
}

describe('the foundation corpus is present and pinned as an equality', () => {
  it('discovers exactly the pinned number of fixtures in every suite', () => {
    expect(fixtureFiles(VALID_DIR).length).toBe(EXPECTED_VALID);
    expect(fixtureFiles(INVALID_DIR).length).toBe(EXPECTED_INVALID);
    expect(fixtureFiles(HASH_DIR).length).toBe(EXPECTED_HASH);
    expect(fixtureFiles(MUTATION_DIR).length).toBe(EXPECTED_MUTATIONS);
    expect(fixtureFiles(MANIFEST_DIR).length).toBe(EXPECTED_MANIFESTS);
    expect(EXPECTED_FOUNDATION_CHECKS).toBe(98);
  });

  it("agrees, suite by suite, with Python's own pinned foundation counts", () => {
    const source = readFileSync(PY_HARNESS, 'utf-8');
    const counts = new Map<string, number>();
    for (const match of source.matchAll(
      /Suite\("([^"]+)",\s*[A-Z_]+\s*\/\s*"([^"]+)",\s*(\d+)\)/g,
    )) {
      counts.set(match[1], Number(match[3]));
    }
    // Non-vacuity first: an unparsed harness makes every lookup `undefined`, and
    // `undefined === undefined` would let a broken regex report agreement.
    expect(counts.size).toBe(5);
    expect(counts.get('foundation/valid')).toBe(EXPECTED_VALID);
    expect(counts.get('foundation/invalid')).toBe(EXPECTED_INVALID);
    expect(counts.get('foundation/hash')).toBe(EXPECTED_HASH);
    expect(counts.get('foundation/mutations')).toBe(EXPECTED_MUTATIONS);
    expect(counts.get('foundation/manifests')).toBe(EXPECTED_MANIFESTS);
    const total = [...counts.values()].reduce((sum, value) => sum + value, 0);
    expect(total).toBe(EXPECTED_FOUNDATION_CHECKS);
  });

  it('registers the same foundation tiers Python registers, in the same order', () => {
    const source = readFileSync(PY_REGISTRY, 'utf-8');
    const match = /FOUNDATION_SCHEMA_DIRS = \(([^)]*)\)/.exec(source);
    expect(match).not.toBeNull();
    const python = [...(match as RegExpExecArray)[1].matchAll(/"([a-z]+)"/g)].map((m) => m[1]);
    expect(python.length).toBeGreaterThan(0);
    expect(python).toEqual([...FOUNDATION_SCHEMA_DIRS]);
  });

  it('really loaded the foundation schemas into the shared registry', () => {
    const schemas = canonicalSchemas();
    for (const id of [
      'urn:datacompany:capability-status:1',
      'urn:datacompany:page:1',
      'urn:datacompany:problem-details:1',
      'urn:datacompany:release-ref:1',
      'urn:datacompany:research-access-context:1',
      'urn:datacompany:run-manifest:1',
      // The evidence tier, registered by FND-002 task 4. `locator-selector:1` is a $defs-only
      // document with no root shape, so a registry that skipped it would fail the location
      // fixtures with "unknown schema_ref" rather than with anything about a selector.
      'urn:datacompany:locator-selector:1',
      'urn:datacompany:evidence-location-version:1',
      'urn:datacompany:evidence-location-candidate:1',
      // Canonical-tier by directory, but the corpus below instantiates its four $defs, so a
      // registry that failed to load it would fail those fixtures for an unrelated reason.
      'urn:datacompany:typed-refs:1',
    ]) {
      expect(schemas.has(id)).toBe(true);
    }
    // ...and the canonical tier is still there beside them, not replaced by them.
    expect(schemas.has('urn:datacompany:stable-identity:1')).toBe(true);
  });
});

describe('valid foundation fixtures validate against the schema layer', () => {
  it.each(fixtures(VALID_DIR).map((f) => [f.fixture_id, f] as const))(
    '%s validates against BOTH layers',
    (_id, fixture) => {
      expect(validateSchemaOnly(fixture.instance, fixture.schema_ref)).toEqual([]);
      // The cross-field layer too: a fixture that satisfies the schema while violating a
      // released interval or equality rule is not a valid instance of this contract.
      expect(evaluateCrossFieldRules(fixture.instance, fixture.schema_ref)).toEqual([]);
    },
  );
});

describe('invalid foundation fixtures are refused, each for its declared reason', () => {
  const all = fixtures(INVALID_DIR);
  const schemaRejectable = all.filter((f) => f.cross_field_only !== true);
  const crossFieldOnly = all.filter((f) => f.cross_field_only === true);

  it('splits the corpus exactly as pinned, so neither half can quietly absorb the other', () => {
    expect(crossFieldOnly.length).toBe(EXPECTED_CROSS_FIELD_ONLY);
    expect(schemaRejectable.length).toBe(EXPECTED_INVALID - EXPECTED_CROSS_FIELD_ONLY);
  });

  it.each(schemaRejectable.map((f) => [f.fixture_id, f] as const))(
    '%s is rejected for its declared (pointer, keyword), not merely rejected',
    (_id, fixture) => {
      expect(validateSchemaOnly(fixture.instance, fixture.schema_ref).length).toBeGreaterThan(0);

      // `expected_error_contains` pins jsonschema's ENGLISH PROSE and is deliberately NOT
      // asserted here: Ajv says `must match pattern "y"` where Python says
      // `'x' does not match 'y'`, and `must NOT have unevaluated properties` without naming
      // the member Python names. That is defect D2f, and asserting it would either fail
      // honestly or force the fixtures to encode one engine's wording as the contract.
      //
      // `expected_schema_failures` is the language-neutral half: the RFC 6901 pointer and
      // the JSON Schema 2020-12 keyword, both defined by the specification. It is the
      // INTERSECTION of what the two engines report, so containment is the assertion --
      // Ajv additionally surfaces the failed `if`, Python additionally cascades
      // `unevaluatedProperties`, and neither extra is anybody's contract.
      const declared = fixture.expected_schema_failures;
      // Non-vacuity: an empty declaration would satisfy every containment check below.
      expect(declared.length).toBeGreaterThan(0);
      const observed = schemaFailureCodes(fixture.instance, fixture.schema_ref);
      for (const entry of declared) {
        expect(observed).toContainEqual(entry);
      }
    },
  );

  it.each(crossFieldOnly.map((f) => [f.fixture_id, f] as const))(
    '%s is schema-VALID and refused by the cross-field layer, in this language too',
    (_id, fixture) => {
      // Both halves. The first alone would be satisfied by a broken schema; the second
      // alone would not establish that the rule is what does the work.
      expect(validateSchemaOnly(fixture.instance, fixture.schema_ref)).toEqual([]);
      expect(fixture.expected_schema_failures).toEqual([]);
      const failures = evaluateCrossFieldRules(fixture.instance, fixture.schema_ref);
      expect(failures.length).toBeGreaterThan(0);
      // ...and for the reason the fixture names. `expected_error_contains` for these four
      // is the cross-field rule NAME, which both engines emit verbatim from the schema --
      // unlike the JSON Schema prose, which is per-validator (defect D2f).
      const rendered = failures.join(' | ');
      for (const expected of fixture.expected_error_contains ?? []) {
        expect(rendered).toContain(expected);
      }
    },
  );
});

describe('the run manifest hashes identically in both languages', () => {
  it.each(fixtureFiles(HASH_DIR).map((p) => [basename(p, '.json'), p] as const))(
    '%s reproduces the golden canonical BYTES and the golden digest',
    (_id, path) => {
      const fixture = load<HashFixture>(path);
      const profile = deriveHashProfile(fixture.schema_ref);
      const view = buildHashView(fixture.instance, profile);
      // Bytes first. A matching digest over different canonical bytes is luck, not parity.
      expect(decodeUtf8(canonicalJsonBytes(view))).toBe(
        fixture.expected_hash_view_canonical_json,
      );
      expect(canonicalSha256(view)).toBe(fixture.expected_content_hash);
    },
  );

  it.each(fixtureFiles(MUTATION_DIR).map((p) => [basename(p, '.json'), p] as const))(
    '%s changes or preserves the digest exactly as declared',
    (_id, path) => {
      const mutationCase = load<{
        base_fixture: string;
        expect: 'changed' | 'unchanged';
        mutations: { pointer: string; value: unknown }[];
      }>(path);
      const basePath = join(HASH_DIR, `${mutationCase.base_fixture}.json`);
      expect(existsSync(basePath)).toBe(true);
      const base = load<HashFixture>(basePath);
      const mutated = clone(base.instance);
      for (const mutation of mutationCase.mutations) {
        setPointer(mutated, mutation.pointer, mutation.value);
      }
      const digest = computeContentHash(mutated, base.schema_ref);
      if (mutationCase.expect === 'unchanged') {
        expect(digest).toBe(base.expected_content_hash);
      } else {
        expect(digest).not.toBe(base.expected_content_hash);
      }
    },
  );

  it('DERIVES the committed run-manifest profile rather than reading it back', () => {
    for (const path of fixtureFiles(MANIFEST_DIR)) {
      const committed = load<ReturnType<typeof deriveHashProfile>>(path);
      expect(deriveHashProfile(committed.schema_ref)).toEqual(committed);
    }
  });
});

describe('falsifiability: each foundation gate is proven able to fail', () => {
  const GOLDEN = join(HASH_DIR, 'run-manifest-all-nine-groups.json');

  it('a perturbed golden instance breaks BOTH the canonical bytes and the digest', () => {
    const fixture = load<HashFixture>(GOLDEN);
    const profile = deriveHashProfile(fixture.schema_ref);
    const perturbed = clone(fixture.instance);
    setPointer(perturbed, '/method/engine_version', '9.9.9');
    const dirty = buildHashView(perturbed, profile);
    expect(decodeUtf8(canonicalJsonBytes(dirty))).not.toBe(
      fixture.expected_hash_view_canonical_json,
    );
    expect(canonicalSha256(dirty)).not.toBe(fixture.expected_content_hash);
  });

  it('the hash VIEW step is load-bearing: hashing the raw instance is a different digest', () => {
    const fixture = load<HashFixture>(GOLDEN);
    expect(canonicalSha256(fixture.instance)).not.toBe(fixture.expected_content_hash);
  });

  it('the schema layer is falsifiable over a FOUNDATION schema, not just a canonical one', () => {
    const fixture = load<FoundationFixture>(
      join(VALID_DIR, 'context-tenant-scoped-complete.json'),
    );
    expect(validateSchemaOnly(fixture.instance, fixture.schema_ref)).toEqual([]);
    const broken = clone(fixture.instance) as Record<string, unknown>;
    broken['purpose'] = 'not-a-released-purpose';
    const errors = validateSchemaOnly(broken, fixture.schema_ref);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.join(' ')).toMatch(/purpose/);
  });

  it('the released scope conditional is genuinely composed, not restated', () => {
    // A global-scoped context with a resource tenant must fail. This is the single rule the
    // whole reference contract rests on, and it must be the SAME rule at every depth.
    const fixture = load<FoundationFixture>(join(VALID_DIR, 'context-global-scoped-minimal.json'));
    expect(validateSchemaOnly(fixture.instance, fixture.schema_ref)).toEqual([]);
    const leaky = clone(fixture.instance) as Record<string, unknown>;
    leaky['resource_tenant_id'] = '11111111-1111-4111-8111-111111111111';
    expect(validateSchemaOnly(leaky, fixture.schema_ref).length).toBeGreaterThan(0);
  });

  it('refuses to measure nothing: an empty or missing foundation suite throws', () => {
    expect(() => fixtureFiles(join(FOUNDATION_ROOT, 'no-such-suite'))).toThrow();
  });

  it('enumerates ONLY through fixtureFiles, so it cannot be relocated into vacuity', () => {
    const source = readFileSync(__filename.replace(/\.js$/, '.ts'), 'utf-8');
    expect(source).toContain('fixtureFiles(');
    // Assembled from parts so this assertion is not itself the occurrence it searches for.
    const forbidden = ['readdir', 'Sync('].join('');
    expect(source.includes(forbidden)).toBe(false);
  });
});

describe('the generated TypeScript bindings are real and match the schemas', () => {
  const GENERATED = join(REPOSITORY_ROOT, 'generated', 'typescript', 'foundationTypes.ts');

  it('exists, is non-empty, and declares a type for every generated foundation schema', () => {
    expect(existsSync(GENERATED)).toBe(true);
    const source = readFileSync(GENERATED, 'utf-8');
    for (const name of [
      'ArtifactRef',
      'CapabilityStatus',
      'DocumentVersionRef',
      'EvidenceLocationCandidate',
      'EvidenceLocationRef',
      'EvidenceLocationVersion',
      'PageRequest',
      'PageResponse',
      'ProblemDetails',
      'ReleaseRef',
      'ResearchAccessContext',
      'RightsDecisionRef',
      'RunManifest',
    ]) {
      expect(source).toMatch(new RegExp(`export (interface|type) ${name}\\b`));
    }
  });

  it('keeps the schema_ref CONST on each typed ref instead of widening it to SchemaRef', () => {
    // Without this the four registered reference types generate as four byte-identical
    // copies of PinnedVersionRef: the composed `schema_ref: SchemaRef` from
    // pinned-version-ref:1 overwrites the local const, a consumer can pass a
    // DocumentVersionRef where an ArtifactRef is required, and both languages agree.
    const source = readFileSync(GENERATED, 'utf-8');
    for (const [name, urn] of [
      ['ArtifactRef', 'urn:datacompany:artifact-version:1'],
      ['DocumentVersionRef', 'urn:datacompany:document-version:1'],
      ['EvidenceLocationRef', 'urn:datacompany:evidence-location-version:1'],
      ['RightsDecisionRef', 'urn:datacompany:rights-decision-version:1'],
    ] as const) {
      const body = source.split(`export interface ${name} {`)[1].split('}')[0];
      expect(body).toContain(`schema_ref: "${urn}";`);
    }
  });

  it('brands scalar aliases instead of emitting a transparent `= string`', () => {
    // A transparent alias IS the weaker local alias the contract gate forbids: it would let
    // any string stand in for a sha256:<64 hex> content hash with the type checker's
    // blessing. The brand is what makes the generated binding load-bearing.
    const source = readFileSync(GENERATED, 'utf-8');
    expect(source).toContain('export type ContentHash = string & { readonly __brand: "ContentHash" };');
    expect(source).not.toMatch(/export type ContentHash = string;/);
    expect(source).not.toMatch(/export type Uuid = string;/);
  });
});

// The generated bindings must also COMPILE, not merely exist as text. `tsconfig.json`
// includes ../../generated/typescript, so `tsc --noEmit` in `ci:verify` type-checks them,
// and this import is what makes a compile failure land in this suite too rather than only
// in a separate step someone could reorder away.
import type {
  ArtifactRef,
  DocumentVersionRef,
  ProblemDetails,
  RunManifest,
} from '../../../generated/typescript/foundationTypes';

describe('the generated bindings type-check against a real fixture', () => {
  it('accepts a committed valid instance at the generated type', () => {
    const problem = load<FoundationFixture>(
      join(VALID_DIR, 'problem-capability-unavailable.json'),
    ).instance as unknown as ProblemDetails;
    expect(problem.code).toBe('capability_unavailable');
    expect(problem.retryable).toBe(false);

    const manifest = load<FoundationFixture>(
      join(VALID_DIR, 'run-manifest-all-nine-groups.json'),
    ).instance as unknown as RunManifest;
    expect(manifest.method.method_id).toBe('markov_cohort');
    expect(manifest.outputs.artifact_refs.length).toBe(1);
  });

  it('narrows each typed ref to its literal schema_ref at COMPILE time', () => {
    // The two annotations below are the gate, not the expectations. `schema_ref` is
    // declared as the literal URN, so assigning it to that literal type compiles; if the
    // generator ever widened it back to the branded `SchemaRef`, both lines would be
    // compile errors and `tsc --noEmit` in `ci:verify` would report them.
    const documentRef = load<FoundationFixture>(join(VALID_DIR, 'typed-ref-document-version.json'))
      .instance as unknown as DocumentVersionRef;
    const documentUrn: 'urn:datacompany:document-version:1' = documentRef.schema_ref;

    const artifact = load<FoundationFixture>(join(VALID_DIR, 'typed-ref-artifact.json'))
      .instance as unknown as ArtifactRef;
    const artifactUrn: 'urn:datacompany:artifact-version:1' = artifact.schema_ref;

    expect(documentUrn).not.toBe(artifactUrn);
  });
});

// Re-exported so the JSON parser is exercised on the foundation corpus too: `parseCanonicalJson`
// is what refuses an integer past 2^53, and a foundation fixture carrying one must not slip in.
describe('foundation fixtures survive the canonical JSON parse guard', () => {
  it('parses every committed foundation fixture without the 2^53 guard firing', () => {
    let parsed = 0;
    for (const directory of [VALID_DIR, INVALID_DIR, HASH_DIR, MUTATION_DIR, MANIFEST_DIR]) {
      for (const path of fixtureFiles(directory)) {
        parseCanonicalJson(readFileSync(path, 'utf-8'));
        parsed += 1;
      }
    }
    expect(parsed).toBe(EXPECTED_FOUNDATION_CHECKS);
  });
});

// FND-002 task 4. The evidence tier's whole point is a DISCRIMINATED union, and the property
// that makes it discriminated -- the six if/then guards cross-linking `selector_type` to the
// selector body -- is exactly the one a second engine could implement differently. Replaying
// the committed fixtures above already exercises it; these assert it directly, in this
// language, so a divergence is reported as a statement about the union rather than as one
// fixture among fifty-seven.
describe('the evidence selector union is discriminated in this language too', () => {
  const LOCATION = 'urn:datacompany:evidence-location-version:1';
  const CANDIDATE = 'urn:datacompany:evidence-location-candidate:1';
  const SELECTOR = 'urn:datacompany:locator-selector:1';

  function validInstance(name: string): Record<string, unknown> {
    return clone(
      load<FoundationFixture>(join(VALID_DIR, `${name}.json`)).instance,
    ) as Record<string, unknown>;
  }

  it('accepts the clean location, which is the control for every rejection below', () => {
    expect(validateSchemaOnly(validInstance('evidence-location-document-selector'), LOCATION)).toEqual(
      [],
    );
    expect(
      validateSchemaOnly(
        validInstance('evidence-location-candidate-transcript-selector'),
        CANDIDATE,
      ),
    ).toEqual([]);
  });

  it('refuses a selector body that does not match its declared selector_type', () => {
    // Both halves are well formed on their own: `tabular` is in the closed kind enum and the
    // body is a valid member of the union. Only the guard relates them, and without it Ajv
    // accepts this exactly as jsonschema does.
    const mismatched = validInstance('evidence-location-document-selector');
    mismatched['selector_type'] = 'tabular';
    expect(schemaFailureCodes(mismatched, LOCATION)).toContainEqual({
      pointer: '/selector',
      keyword: 'unevaluatedProperties',
    });
  });

  // The composition, not the declaration. The six guards are declared in `locator-selector:1`,
  // which is a $defs library and constrains nothing on its own: they bite only where a root
  // `allOf` composes them, and there are TWELVE such compositions across the two documents.
  // Measured before this was written -- deleting any one of the twelve `$ref`s left the whole
  // suite green for eleven of them, and with the media guard gone `selector_type: media`
  // carrying a full DOCUMENT body was ACCEPTED. The single case above covers one of the twelve.
  //
  // Behavioural rather than structural on purpose: asserting the twelve `$ref`s are present
  // would pass while a guard was composed and broken. This is also exactly the property a
  // second engine could implement differently -- Ajv's `if`/`then` short-circuiting is its own
  // code path -- so the cross-product is replayed here rather than trusted from Python.
  const SELECTOR_BODY_FIXTURES: Record<string, string> = {
    code: 'evidence-location-candidate-code-selector',
    document: 'evidence-location-document-selector',
    media: 'evidence-location-media-selector',
    notebook: 'evidence-location-notebook-selector',
    tabular: 'evidence-location-tabular-selector-by-row-index',
    transcript: 'evidence-location-candidate-transcript-selector',
  };

  const SELECTOR_CARRIERS: Record<string, string> = {
    [LOCATION]: 'evidence-location-document-selector',
    [CANDIDATE]: 'evidence-location-candidate-transcript-selector',
  };

  const KINDS = Object.keys(SELECTOR_BODY_FIXTURES).sort();

  /** The committed fixture for a name, or a thrown error -- never a silently absent one. */
  function fixtureNamed(table: Record<string, string>, key: string): string {
    const name = table[key];
    if (name === undefined) throw new Error(`no committed fixture for ${key}`);
    return name;
  }

  function selectorBody(kind: string): unknown {
    return validInstance(fixtureNamed(SELECTOR_BODY_FIXTURES, kind))['selector'];
  }

  const MISMATCH_PAIRS: Array<[string, string, string]> = [];
  for (const carrier of Object.keys(SELECTOR_CARRIERS).sort()) {
    for (const declared of KINDS) {
      for (const body of KINDS) {
        if (declared !== body) MISMATCH_PAIRS.push([carrier, declared, body]);
      }
    }
  }

  it('declares a body for every kind in the released enum, and 60 ordered pairs', () => {
    // Non-vacuity for the two cross-products below: a missing kind would silently shrink both.
    const released = canonicalSchemas().get(SELECTOR) as
      | { $defs: { selector_kind: { enum: string[] } } }
      | undefined;
    if (released === undefined) throw new Error(`${SELECTOR} is not registered`);
    expect(KINDS).toEqual([...released.$defs.selector_kind.enum].sort());
    expect(MISMATCH_PAIRS).toHaveLength(60);
  });

  it.each(
    Object.keys(SELECTOR_CARRIERS)
      .sort()
      .flatMap((carrier) => KINDS.map((kind) => [carrier, kind] as const)),
  )('accepts %s carrying its own %s selector', (carrier, kind) => {
    // THE FALSE-POSITIVE CONTROL for the 60 rejections below, all twelve of them. Without it,
    // a document that had lost `selector_fields` entirely would refuse every pairing and
    // satisfy all sixty mismatch assertions at once.
    const probe = validInstance(fixtureNamed(SELECTOR_CARRIERS, carrier));
    probe['selector_type'] = kind;
    probe['selector'] = selectorBody(kind);
    expect(validateSchemaOnly(probe, carrier)).toEqual([]);
  });

  it.each(MISMATCH_PAIRS)(
    'refuses %s declaring %s while carrying a %s body',
    (carrier, declared, body) => {
      // The failure must land under `/selector`: the declared kind is in the closed enum and
      // the body is a valid member of `any_selector`, so a rejection at `/` would mean the root
      // refused it for some other reason and the guard never ran.
      const probe = validInstance(fixtureNamed(SELECTOR_CARRIERS, carrier));
      probe['selector_type'] = declared;
      probe['selector'] = selectorBody(body);
      const codes = schemaFailureCodes(probe, carrier);
      expect(codes.filter((code) => code.pointer === '/selector')).not.toHaveLength(0);
    },
  );

  it.each([
    'current_right',
    'actor_or_service_ref',
    'requested_action',
    'requested_use_basis',
    'expiring_url',
    'rendered_bytes',
    'selection_digest',
    'storage_key',
    // The ninth: implementation-plans/05-guideline-registry-8814.md:1086-1087, "never hash the
    // expiring/current authorization receipt back into the location". Refused all along and
    // cited nowhere -- an evidence gap rather than a hole.
    'evidence_resolution_receipt_ref',
  ])('refuses the rights-bearing member %s on its own', (member) => {
    // One case per member, never one omnibus instance: an omnibus assertion stays green while
    // seven of the eight refusals silently stop working.
    const leaky = validInstance('evidence-location-document-selector');
    expect(leaky[member]).toBeUndefined();
    leaky[member] = 'anything at all';
    expect(schemaFailureCodes(leaky, LOCATION)).toContainEqual({
      pointer: '/',
      keyword: 'unevaluatedProperties',
    });
  });

  it('refuses both target refs and refuses neither, accepting exactly one', () => {
    const artifact = validInstance('evidence-location-tabular-selector-by-row-index')['artifact_ref'];

    const both = validInstance('evidence-location-document-selector');
    both['artifact_ref'] = artifact;
    expect(schemaFailureCodes(both, LOCATION)).toContainEqual({ pointer: '/', keyword: 'oneOf' });

    const neither = validInstance('evidence-location-document-selector');
    delete neither['document_version_ref'];
    expect(schemaFailureCodes(neither, LOCATION)).toContainEqual({ pointer: '/', keyword: 'oneOf' });
  });

  it('applies the released scope conditional AT DEPTH inside an active selector branch', () => {
    // The record is tabular-kinded, so a guard is narrowing `selector` while this is evaluated,
    // and the violation is three composed documents down rather than at the root. The pointer
    // is asserted: a failure at `/` would mean the outer boundary refused it and the nested
    // conditional never ran.
    const leaky = validInstance('evidence-location-tabular-selector-by-row-index');
    const pin = leaky['artifact_ref'] as Record<string, unknown>;
    expect(pin['resource_scope']).toBe('global');
    pin['resource_tenant_id'] = '11111111-1111-4111-8111-111111111111';
    expect(schemaFailureCodes(leaky, LOCATION)).toContainEqual({
      pointer: '/artifact_ref',
      keyword: 'not',
    });
  });

  it('refuses the registered identity on a candidate and requires it on a location', () => {
    const candidate = validInstance('evidence-location-candidate-transcript-selector');
    expect(candidate['evidence_location_id']).toBeUndefined();
    candidate['evidence_location_id'] = 'e71d1111-1111-4111-8111-111111111111';
    expect(schemaFailureCodes(candidate, CANDIDATE)).toContainEqual({
      pointer: '/',
      keyword: 'unevaluatedProperties',
    });

    const location = validInstance('evidence-location-document-selector');
    delete location['evidence_location_id'];
    expect(schemaFailureCodes(location, LOCATION)).toContainEqual({
      pointer: '/',
      keyword: 'required',
    });
  });
});

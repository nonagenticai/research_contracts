/**
 * Loading and resolution of the released canonical JSON Schema 2020-12 sources.
 *
 * TypeScript port of `src/research_contracts/canonical/registry.py`: load every
 * `schemas/canonical/*.schema.json`, key them by `$id`, resolve a `urn:...#/$defs/name`
 * reference, and expose a JSON Schema validator.
 *
 * SCOPE NOTE. This module is the JSON Schema layer ALONE, exactly like Python's
 * `validate_schema_only`, and on its own it accepts instances the released contract
 * rejects. The released `x-datacompany-cross-field` rules live in `structural.ts`, and
 * `validation.ts` pairs the two -- that pair is what a consumer validating a canonical
 * instance should reach for.
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

import Ajv2020, { type AnySchema, type ErrorObject, type ValidateFunction } from 'ajv/dist/2020';
import addFormats from 'ajv-formats';

import { SchemaValidationError } from './errors';
import { parseCanonicalJson } from './json';

type JsonRecord = Record<string, unknown>;

function findRepositoryRoot(): string {
  // Works from `src/` under ts-jest and from `dist/` after a build: both sit three levels
  // below the repository root. The upward search keeps it working if that ever changes.
  let candidate = __dirname;
  for (let depth = 0; depth < 8; depth += 1) {
    if (existsSync(join(candidate, 'schemas', 'canonical'))) {
      return candidate;
    }
    const parent = dirname(candidate);
    if (parent === candidate) {
      break;
    }
    candidate = parent;
  }
  return resolve(__dirname, '..', '..', '..');
}

export const REPOSITORY_ROOT = findRepositoryRoot();
export const CANONICAL_SCHEMA_DIR = join(REPOSITORY_ROOT, 'schemas', 'canonical');

/**
 * The FND-002 foundation tiers, resolved through the SAME registry as the canonical tier.
 *
 * Mirrors `FOUNDATION_SCHEMA_DIRS` in `src/research_contracts/canonical/registry.py`, and
 * `test/foundation.test.ts` asserts the two lists are byte-identical so they cannot drift.
 * They must share one registry rather than sit in two: a foundation schema `$ref`s the
 * canonical primitives, and a second registry would answer "unknown schema_ref" for exactly
 * the composed shapes FND-002 exists to release.
 *
 * `meta/` is deliberately absent -- it is the authoring-time gate over these documents, not
 * a released payload contract.
 *
 * `events/` joined on 2026-09-02 with `research-event-envelope.v1`. The directory had
 * existed, empty, since 2026-07-30; a closed list means a document in an unlisted directory
 * resolves to nothing on BOTH sides, and a TypeScript consumer that could not resolve the
 * envelope would read every outbox row as an unknown grammar.
 *
 * `jobs/` joined on 2026-09-04 with `durable-job.v1` and `job-attempt.v1`, for the same
 * reason: a subsystem already running in production against no released grammar.
 */
export const FOUNDATION_SCHEMA_DIRS = [
  'common',
  'context',
  'profiles',
  'capabilities',
  'manifests',
  'evidence',
  'events',
  'approvals',
  'jobs',
] as const;

let schemaCache: Map<string, JsonRecord> | null = null;
let ajvCache: Ajv2020 | null = null;
const validatorCache = new Map<string, ValidateFunction>();

/** Return every released canonical schema keyed by its `$id`. */
export function canonicalSchemas(): Map<string, JsonRecord> {
  if (schemaCache !== null) {
    return schemaCache;
  }
  const schemas = new Map<string, JsonRecord>();
  const directories = [
    CANONICAL_SCHEMA_DIR,
    ...FOUNDATION_SCHEMA_DIRS.map((name) => join(REPOSITORY_ROOT, 'schemas', name)),
  ];
  for (const directory of directories) {
    // A foundation tier that does not exist yet is not an error -- the directories are
    // created as the FND-002 tasks land. The canonical tier not existing IS one, and
    // `readdirSync` raises for it rather than globbing to [] the way Python's glob did.
    if (directory !== CANONICAL_SCHEMA_DIR && !existsSync(directory)) {
      continue;
    }
    const files = readdirSync(directory)
      .filter((name) => name.endsWith('.schema.json'))
      .sort();
    for (const name of files) {
      const path = join(directory, name);
      const schema = parseCanonicalJson(readFileSync(path, 'utf-8')) as JsonRecord;
      const schemaId = schema['$id'];
      if (typeof schemaId !== 'string' || schemaId === '') {
        throw new SchemaValidationError(`${path}: non-empty $id is required`);
      }
      if (schemas.has(schemaId)) {
        throw new SchemaValidationError(`${path}: duplicate $id ${schemaId}`);
      }
      schemas.set(schemaId, schema);
    }
  }
  if (schemas.size === 0) {
    throw new SchemaValidationError(
      `${CANONICAL_SCHEMA_DIR}: exists but holds no *.schema.json, so every reference would ` +
        'fail to resolve. An empty enumeration is not a clean one.',
    );
  }
  schemaCache = schemas;
  return schemas;
}

/**
 * An Ajv 2020-12 instance holding every released canonical schema.
 *
 * `strict: false` is required, not cosmetic: Ajv's strict mode rejects the released
 * `x-datacompany-*` annotation keywords outright, so the schemas would not load at all.
 */
export function schemaRegistry(): Ajv2020 {
  if (ajvCache !== null) {
    return ajvCache;
  }
  // `verbose` is load-bearing, not diagnostic noise: it is what puts the failing keyword's
  // own subschema on each error, which is the only place the CAUSE of a `not` failure is
  // named. See `describeCause`.
  const ajv = new Ajv2020({
    strict: false,
    allErrors: true,
    validateFormats: true,
    verbose: true,
  });
  addFormats(ajv);
  for (const [schemaId, schema] of canonicalSchemas()) {
    if (ajv.validateSchema(schema as AnySchema) !== true) {
      throw new SchemaValidationError(
        `${schemaId}: not a valid JSON Schema 2020-12: ${ajv.errorsText(ajv.errors)}`,
      );
    }
    ajv.addSchema(schema as AnySchema, schemaId);
  }
  ajvCache = ajv;
  return ajv;
}

function splitRef(schemaRef: string): [string, string] {
  const marker = schemaRef.indexOf('#');
  return marker === -1
    ? [schemaRef, '']
    : [schemaRef.slice(0, marker), schemaRef.slice(marker + 1)];
}

/** Resolve a `urn:...#/$defs/name` reference to its schema object. */
export function resolvePointer(schemaRef: string): unknown {
  const [base, fragment] = splitRef(schemaRef);
  const schemas = canonicalSchemas();
  const document = schemas.get(base);
  if (document === undefined) {
    throw new SchemaValidationError(`unknown schema_ref ${schemaRef}`);
  }
  if (fragment === '') {
    return document;
  }
  if (!fragment.startsWith('/')) {
    throw new SchemaValidationError(`unsupported non-pointer fragment in ${schemaRef}`);
  }
  let node: unknown = document;
  for (const raw of fragment.replace(/^\/+/, '').split('/')) {
    const token = raw.split('~1').join('/').split('~0').join('~');
    if (
      typeof node !== 'object' ||
      node === null ||
      Array.isArray(node) ||
      !Object.hasOwn(node, token)
    ) {
      throw new SchemaValidationError(`cannot resolve ${schemaRef} at ${token}`);
    }
    node = (node as JsonRecord)[token];
  }
  return node;
}

/**
 * Resolve an absolute or document-relative reference.
 *
 * Returns the schema object and the `$id` of the document it belongs to, so a walker can
 * keep resolving further `#/$defs/...` references in the right document.
 */
export function resolveRef(schemaRef: string, baseId?: string): [unknown, string] {
  const [base] = splitRef(schemaRef);
  const resolvedBase = base !== '' ? base : baseId;
  if (resolvedBase === undefined) {
    throw new SchemaValidationError(`relative reference ${schemaRef} has no base document`);
  }
  const absolute = base !== '' ? schemaRef : `${resolvedBase}${schemaRef}`;
  return [resolvePointer(absolute), resolvedBase];
}

/** Return a format-checking validator for a released schema or one of its `$defs`. */
export function validatorFor(schemaRef: string): ValidateFunction {
  const cached = validatorCache.get(schemaRef);
  if (cached !== undefined) {
    return cached;
  }
  const target = resolvePointer(schemaRef);
  if (typeof target !== 'object' || target === null || Array.isArray(target)) {
    throw new SchemaValidationError(`${schemaRef} does not resolve to a schema object`);
  }
  const validate = schemaRegistry().compile({ $ref: schemaRef });
  validatorCache.set(schemaRef, validate);
  return validate;
}

/**
 * Name the CAUSE of a failure whose Ajv message elides it, and nothing else.
 *
 * `must NOT be valid` and `must NOT have unevaluated properties` do not say WHICH condition
 * or WHICH member was at fault, and the committed `references/invalid/*` fixtures assert
 * exactly that: each one declares an `expected_error_contains` naming the field or rule it
 * is about, and a rejection for some other reason must not satisfy it.
 *
 * What is appended is deliberately narrow -- the offending member name, or the negated
 * SUBSCHEMA -- never the instance. Python's `jsonschema` renders a `not` failure by dumping
 * the whole instance, which makes any `expected_error_contains` naming any member of that
 * instance satisfiable by a rejection for a completely unrelated reason. This rendering is
 * strictly stronger, and `references.test.ts` proves it with a decoy: a member name that
 * appears in the fixture's instance but is not the cause must NOT appear here.
 */
function describeCause(error: ErrorObject): string {
  const params = error.params as Record<string, unknown>;
  switch (error.keyword) {
    case 'unevaluatedProperties':
      return ` (${JSON.stringify(params['unevaluatedProperty'])})`;
    case 'additionalProperties':
      return ` (${JSON.stringify(params['additionalProperty'])})`;
    case 'const':
      return ` (${JSON.stringify(params['allowedValue'])})`;
    case 'not':
      // `verbose: true` puts the negated subschema on the error. This is the only channel
      // that names, for example, `{"required":["resource_tenant_id"]}`.
      return ` under ${JSON.stringify(error.schema)}`;
    default:
      return '';
  }
}

/**
 * Return the JSON Schema errors of `instance` against `schemaRef`, and nothing else.
 *
 * This is the raw JSON Schema layer, the exact counterpart of Python's
 * `validate_schema_only`. It deliberately does NOT evaluate the released
 * `x-datacompany-cross-field` rules; `validateInstance` pairs the two and is what a consumer
 * validating a canonical instance wants.
 */
export function validateSchemaOnly(instance: unknown, schemaRef: string): string[] {
  const validate = validatorFor(schemaRef);
  if (validate(instance) === true) {
    return [];
  }
  const errors = validate.errors ?? [];
  return errors
    .map((error) => {
      const location = error.instancePath.replace(/^\//, '') || '<root>';
      return `${location}: ${error.message ?? 'is invalid'}${describeCause(error)}`;
    })
    .sort();
}

/**
 * Return each JSON Schema failure as a LANGUAGE-NEUTRAL `(pointer, keyword)` pair.
 *
 * The port of `registry.schema_failure_codes`. `validateSchemaOnly` renders Ajv's English
 * message text and Python's renders `jsonschema`'s, and the two never agree: Ajv says
 * `must match pattern "y"` where Python says `'x' does not match 'y'`, and
 * `must NOT have unevaluated properties` where Python names the offending member. A fixture
 * that pins prose can only be replayed by the engine whose prose it pinned -- defect D2f.
 *
 * Both halves of the pair come from the specification, not from an implementation: the
 * RFC 6901 instance location and the JSON Schema 2020-12 keyword that failed. Sorted and
 * de-duplicated, because subschema visit order is nobody's contract.
 */
export function schemaFailureCodes(
  instance: unknown,
  schemaRef: string,
): { pointer: string; keyword: string }[] {
  const validate = validatorFor(schemaRef);
  if (validate(instance) === true) {
    return [];
  }
  const seen = new Set<string>();
  for (const error of validate.errors ?? []) {
    // Ajv reports the root as '' where Python reports '/'; normalise to Python's spelling
    // so the two vocabularies are comparable rather than merely similar.
    const pointer = error.instancePath === '' ? '/' : error.instancePath;
    seen.add(`${pointer}\u0000${error.keyword}`);
  }
  return [...seen]
    .sort()
    .map((entry) => {
      const [pointer, keyword] = entry.split('\u0000');
      return { pointer, keyword };
    });
}

/** Reset the memoized schema/validator state. Test-only. */
export function resetRegistryCaches(): void {
  schemaCache = null;
  ajvCache = null;
  validatorCache.clear();
}

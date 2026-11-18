/**
 * Loading of the language-neutral canonical-hash fixtures.
 *
 * The fixtures under `fixtures/canonical-hash/v1/` are the ORACLE for both the Python
 * reference and this port. They are read from the repository root exactly as Python reads
 * them -- never copied into the package, never transformed on the way in. A transformed
 * fixture proves only that the transformation is self-consistent.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { basename, join } from 'node:path';

import {
  deriveHashProfile,
  mergeProfileExtensions,
  type HashProfile,
  type ProfileExtensions,
} from '../src/hashProfile';
import { computeContentHash } from '../src/engine';
import { parseCanonicalJson } from '../src/json';
import { REPOSITORY_ROOT } from '../src/registry';

export const HASH_ROOT = join(REPOSITORY_ROOT, 'fixtures', 'canonical-hash', 'v1');
export const RFC_DIR = join(HASH_ROOT, 'rfc8785');
export const VECTOR_DIR = join(HASH_ROOT, 'vectors');
export const MUTATION_DIR = join(HASH_ROOT, 'mutations');
export const REJECTED_DIR = join(HASH_ROOT, 'rejected');
export const MANIFEST_DIR = join(HASH_ROOT, 'manifests');

export const REFERENCE_ROOT = join(REPOSITORY_ROOT, 'fixtures', 'canonical-references', 'v1');
export const VALID_REF_DIR = join(REFERENCE_ROOT, 'valid');
export const INVALID_REF_DIR = join(REFERENCE_ROOT, 'invalid');
export const VERIFICATION_DIR = join(REFERENCE_ROOT, 'verification');

export const HASH_PROFILE_SCHEMA = 'urn:datacompany:canonical-hash-profile:1';

export interface ValidReferenceFixture {
  fixture_id: string;
  schema_ref: string;
  expect: 'valid';
  instance: unknown;
}

export interface InvalidReferenceFixture {
  fixture_id: string;
  schema_ref: string;
  expect: 'invalid';
  expected_error_contains: string[];
  instance: unknown;
}

export interface VerificationFixture {
  fixture_id: string;
  consumer_context: string;
  subject_local_ref: Record<string, unknown>;
  verification_profile_ref: string;
  pinned_version_ref: Record<string, unknown>;
  owner_response: Record<string, unknown> | null;
  expected_result: 'verified' | 'rejected';
  expected_failure_code: string | null;
}

export interface VectorFixture {
  fixture_id: string;
  axis?: string[];
  schema_ref: string;
  instance: Record<string, unknown>;
  expected_hash_view_canonical_json: string;
  expected_content_hash: string;
  profile_extensions?: ProfileExtensions | null;
}

export interface MutationFixture {
  fixture_id: string;
  base_fixture: string;
  expect: 'changed' | 'unchanged';
  mutations: { pointer: string; value: unknown }[];
  rationale: string;
}

export interface RejectedFixture {
  fixture_id: string;
  schema_ref: string;
  expected_error: string;
  expected_message_contains: string;
  instance: Record<string, unknown>;
  profile_extensions?: ProfileExtensions | null;
}

export function load<T = unknown>(path: string): T {
  return parseCanonicalJson(readFileSync(path, 'utf-8')) as T;
}

/**
 * Every `*.json` fixture in `directory`, sorted, and NEVER an empty list.
 *
 * An empty measurement is not a zero measurement: a suite that discovers no fixtures must
 * go red, not green.
 */
export function fixtureFiles(directory: string): string[] {
  const paths = readdirSync(directory)
    .filter((name) => name.endsWith('.json'))
    .sort()
    .map((name) => join(directory, name));
  if (paths.length === 0) {
    throw new Error(`no fixtures found under ${directory}`);
  }
  return paths;
}

export function fixtureId(path: string): string {
  return basename(path, '.json');
}

export function profileFor(fixture: {
  schema_ref: string;
  profile_extensions?: ProfileExtensions | null;
}): HashProfile {
  return mergeProfileExtensions(
    deriveHashProfile(fixture.schema_ref),
    fixture.profile_extensions ?? null,
  );
}

export function vector(id: string): VectorFixture {
  return load<VectorFixture>(join(VECTOR_DIR, `${id}.json`));
}

export function hashOf(fixture: VectorFixture): string {
  return computeContentHash(fixture.instance, fixture.schema_ref, {
    profile: profileFor(fixture),
  });
}

/** Deep structural clone through JSON, matching Python's `json.loads(json.dumps(x))`. */
export function clone<T>(value: T): T {
  return parseCanonicalJson(JSON.stringify(value)) as T;
}

/** Set a value at an RFC 6901 pointer, descending into arrays by index. */
export function setPointer(document: unknown, pointer: string, value: unknown): void {
  const tokens = pointer
    .replace(/^\/+/, '')
    .split('/')
    .map((token) => token.split('~1').join('/').split('~0').join('~'));
  let node: unknown = document;
  for (const token of tokens.slice(0, -1)) {
    node = Array.isArray(node)
      ? node[Number(token)]
      : (node as Record<string, unknown>)[token];
  }
  const last = tokens[tokens.length - 1];
  if (Array.isArray(node)) {
    node[Number(last)] = value;
  } else {
    (node as Record<string, unknown>)[last] = value;
  }
}

/** Decode canonical bytes back to text. Byte comparison stays the primary assertion. */
export function decodeUtf8(bytes: Uint8Array): string {
  return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
}

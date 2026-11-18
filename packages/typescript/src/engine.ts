/**
 * The released canonical hashing API (FND-005, shared foundation section 4.3).
 *
 * TypeScript port of `src/research_contracts/canonical/engine.py`.
 *
 * `canonicalJsonBytes` and `canonicalSha256` are the only sanctioned entry points. No
 * service invents a local JSON sorting recipe for an approval, idempotency or
 * input-snapshot hash.
 */

import { createHash } from 'node:crypto';

import { ContentHashMismatchError } from './errors';
import { deriveHashProfile, validateProfileAgainstSchema } from './hashProfile';
import { buildHashView, type HashProfile } from './hashView';
import { canonicalize, type CanonicalizeOptions } from './jcs';
import { assertValidInstance } from './validation';

export const DIGEST_PREFIX = 'sha256:';

/**
 * Return the RFC 8785 canonical UTF-8 bytes of `obj`, without a byte-order mark.
 *
 * `allowBinaryFloat` exists only for RFC 8785 conformance vectors. Every released hash path
 * leaves it `false`, so an unstable binary float raises instead of being silently hashed.
 */
export function canonicalJsonBytes(obj: unknown, options: CanonicalizeOptions = {}): Uint8Array {
  return canonicalize(obj, options);
}

/** Return `sha256:<64-lowercase-hex>` over the RFC 8785 canonical bytes of `obj`. */
export function canonicalSha256(obj: unknown, options: CanonicalizeOptions = {}): string {
  const digest = createHash('sha256').update(canonicalJsonBytes(obj, options)).digest('hex');
  return DIGEST_PREFIX + digest;
}

/** Validates a fully composed instance against its declared `schema_ref`, or throws. */
export type InstanceAssertion = (instance: unknown, schemaRef: string) => void;

export interface ComputeContentHashOptions {
  profile?: HashProfile;
  /**
   * Extension point. Defaults to `validation.assertValidInstance`, which is the JSON Schema
   * layer plus whatever cross-field evaluator has been registered. Pass your own to widen
   * or narrow step 1 without reaching into this module.
   */
  assertValid?: InstanceAssertion;
}

/**
 * Run the full ordered section 4.3 algorithm and return the canonical content hash.
 *
 * 1. validate the fully composed object against its declared `schema_ref`;
 * 2. build the schema-declared semantic hash view;
 * 3. remove only the schema-marked non-hashable paths (nested target `content_hash` values
 *    remain included);
 * 4. enforce each array's released ordered/set-like declaration and sort set members;
 * 5. apply the released absent-versus-null, timestamp, Unicode and decimal rules;
 * 6. serialize as RFC 8785 canonical JSON, UTF-8, no byte-order mark; and
 * 7. SHA-256 over those exact bytes rendered as `sha256:<64-lowercase-hex>`.
 */
export function computeContentHash(
  instance: unknown,
  schemaRef: string,
  options: ComputeContentHashOptions = {},
): string {
  const assertValid = options.assertValid ?? assertValidInstance;
  assertValid(instance, schemaRef);
  let profile = options.profile;
  if (profile === undefined) {
    profile = deriveHashProfile(schemaRef);
  } else {
    // A supplied manifest is checked against the schema's own annotations, not merely
    // against the manifest schema: a well-formed manifest that deletes an exclusion or
    // re-declares a released array would silently produce a second, contradictory
    // "canonical" hash for the same object.
    validateProfileAgainstSchema(profile, schemaRef);
  }
  return canonicalSha256(buildHashView(instance, profile));
}

export interface VerifyContentHashOptions extends ComputeContentHashOptions {
  field?: string;
}

/**
 * Recompute `instance[field]` and fail closed on a mismatch.
 *
 * A supplied hash is never trusted (document 16 acceptance test DM-AT-29).
 */
export function verifyContentHash(
  instance: unknown,
  schemaRef: string,
  options: VerifyContentHashOptions = {},
): string {
  const field = options.field ?? 'content_hash';
  const recomputed = computeContentHash(instance, schemaRef, options);
  const supplied =
    typeof instance === 'object' && instance !== null && !Array.isArray(instance)
      ? (instance as Record<string, unknown>)[field]
      : undefined;
  if (supplied === undefined || supplied === null) {
    throw new ContentHashMismatchError(
      `${field} is absent; a canonical hash must be supplied to be verified`,
    );
  }
  if (supplied !== recomputed) {
    throw new ContentHashMismatchError(
      `${field} does not recompute: supplied ${String(supplied)}, recomputed ${recomputed}`,
    );
  }
  return recomputed;
}

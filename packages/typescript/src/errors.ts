/**
 * Deterministic failure classes for the canonical hash engine (FND-005).
 *
 * The class NAMES are load-bearing: the language-neutral `rejected/*` fixtures name the
 * expected failure by class name, so a rename here silently decouples this port from the
 * Python reference. They mirror `src/research_contracts/canonical/errors.py` one for one,
 * plus `UndeclaredPathError`, which Python declares inside `hash_view.py` and which
 * `hashView.ts` re-exports from here for import-site parity.
 */

/** Base class for every canonical serialization or hash failure. */
export class CanonicalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CanonicalError';
  }
}

/** Step 1: the object does not validate against its declared `schema_ref`. */
export class SchemaValidationError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'SchemaValidationError';
  }
}

/** A released cross-field rule that JSON Schema cannot express failed. */
export class CrossFieldError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'CrossFieldError';
  }
}

/** The released hash-view manifest is missing, malformed, or does not match its schema. */
export class HashProfileError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'HashProfileError';
  }
}

/** A hash exclusion whose reason is not in the released closed set. */
export class UnknownExclusionError extends HashProfileError {
  constructor(message: string) {
    super(message);
    this.name = 'UnknownExclusionError';
  }
}

/** Step 4: an array with no released ordered/set-like declaration. */
export class UndeclaredArrayError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'UndeclaredArrayError';
  }
}

/** Step 4: a set-like array contains two members with the same canonical order key. */
export class DuplicateSetMemberError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'DuplicateSetMemberError';
  }
}

/**
 * Step 4: a set-like member does not carry a released order-key path at all.
 *
 * Distinct from `DuplicateSetMemberError`: an absent order key is a manifest or data
 * fault, not evidence that two members are the same member. Two members that both carry
 * an explicit `null` at the order key *are* duplicates and still fail as such.
 */
export class MissingOrderKeyError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'MissingOrderKeyError';
  }
}

/** Step 5: an unstable binary floating-point value may never enter a hashed input. */
export class UnstableFloatError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'UnstableFloatError';
  }
}

/** A value that RFC 8785 cannot canonicalize. */
export class UnsupportedTypeError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'UnsupportedTypeError';
  }
}

/** A supplied `content_hash` does not recompute. Supplied hashes are never trusted. */
export class ContentHashMismatchError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'ContentHashMismatchError';
  }
}

/** A member that the released hash-view manifest does not declare. */
export class UndeclaredPathError extends CanonicalError {
  constructor(message: string) {
    super(message);
    this.name = 'UndeclaredPathError';
  }
}

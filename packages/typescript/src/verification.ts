/**
 * Owner-resolver comparison and immutable ReferenceVerificationReceipt construction.
 *
 * TypeScript port of `src/research_contracts/canonical/verification.py`.
 *
 * Shared foundation section 4.2: before first use the consumer calls the registered owner
 * resolver by exact `entity_id`/`version_id`, validates the returned schema, recomputes
 * `content_hash` when canonical content is returned, and compares owner context, entity
 * type, identity, version identity/number, scope, tenant, schema and hash byte for byte.
 * Any missing field or mismatch fails closed. There is no fallback to latest.
 */

import { computeContentHash } from './engine';
import { CanonicalError, CrossFieldError, SchemaValidationError } from './errors';
import { resolvePointer, resolveRef } from './registry';
import { assertValidInstance, checkCrossFieldRules, validateInstance } from './validation';

export const RECEIPT_SCHEMA_REF = 'urn:datacompany:reference-verification-receipt:1';
export const PIN_SCHEMA_REF = 'urn:datacompany:pinned-version-ref:1';

/**
 * The receipt schema's own declaration of the permitted subject forms. Read from the schema
 * rather than restated here, so the two can never drift apart.
 */
export const SUBJECT_SCHEMA_REF = `${RECEIPT_SCHEMA_REF}#/$defs/receipt_fields/properties/subject_local_ref`;

/**
 * Every compared field in the released order, with its non-disclosing failure code.
 *
 * The ORDER is load-bearing and is itself a contract: it decides which `failure_code` a
 * multi-field mismatch reports. It mirrors Python's `COMPARED_FIELDS` exactly, and
 * `references.test.ts` pins the two lists against each other so neither can be reordered
 * alone.
 */
export const COMPARED_FIELDS: readonly (readonly [string, string])[] = [
  ['owner_context', 'owner_context_mismatch'],
  ['entity_type', 'entity_type_mismatch'],
  ['entity_id', 'entity_id_mismatch'],
  ['version_id', 'version_id_mismatch'],
  ['version_number', 'version_number_mismatch'],
  ['resource_scope', 'resource_scope_mismatch'],
  ['resource_tenant_id', 'resource_tenant_mismatch'],
  ['schema_ref', 'schema_ref_mismatch'],
  ['content_hash', 'content_hash_mismatch'],
];

export type JsonRecord = Record<string, unknown>;
export type OwnerResponse = JsonRecord | null;
export type Resolver = (entityId: string, versionId: string) => OwnerResponse;

/**
 * Distinguishes "the object does not carry this member" from "it carries `null`". Two objects
 * that both LACK a required field are not two objects that agree about it. A JavaScript
 * `undefined` cannot play this role here: `JSON.parse` never produces it, but a caller can
 * hand in `{ entity_id: undefined }`, and treating that as present would reopen the hole.
 */
const ABSENT = Symbol('absent');

/**
 * The member's value, or `ABSENT`.
 *
 * `undefined` counts as ABSENT, and that is the JSON reading rather than a convenience:
 * `JSON.stringify({ owner_context: undefined })` is `{}`, so a member carrying `undefined`
 * IS an absent member in every serialised form this contract compares. Reading it as present
 * made `{ owner_context: undefined }` on both sides compare equal and return `null` --
 * verified -- while the JSON round-trip of the same two objects returned
 * `owner_context_mismatch`. Unreachable from JSON input, but this comparison is exported from
 * `index.ts` and a JS caller can build such an object from a partial record without noticing;
 * two engines answering differently about the same document is the divergence class this
 * port exists to eliminate. Python has no `undefined`, so nothing there changes.
 *
 * `Object.hasOwn` is still the first half: an inherited member is not this record's member,
 * and `null` remains a value distinct from absence.
 */
function memberOf(record: JsonRecord, field: string): unknown {
  if (!Object.hasOwn(record, field) || record[field] === undefined) {
    return ABSENT;
  }
  return record[field];
}

let requiredPinFieldsCache: ReadonlySet<string> | null = null;

/**
 * The members the released pin schema requires UNCONDITIONALLY.
 *
 * Read out of `urn:datacompany:pinned-version-ref:1` rather than restated here, exactly like
 * `SUBJECT_SCHEMA_REF`, so the two cannot drift apart. It is what lets
 * `comparePinToOwnerResponse` treat a field absent on BOTH sides as a mismatch without also
 * rejecting the one released field whose absence is legal. Mirrors Python's
 * `verification.required_pin_fields`.
 *
 * Only `allOf` and `$ref` are followed. `if`/`then`/`else`, `anyOf` and `oneOf` are
 * deliberately NOT: the pin composes `stable-identity:1#/$defs/resource_scope_conditional`,
 * whose `then` requires `resource_tenant_id` only when `resource_scope` is `tenant` and whose
 * `else` FORBIDS it. Reading that `required` as unconditional would make every legal
 * global-scope verification report `resource_tenant_mismatch`.
 */
export function requiredPinFields(): ReadonlySet<string> {
  if (requiredPinFieldsCache !== null) {
    return requiredPinFieldsCache;
  }
  const required = new Set<string>();
  const walk = (node: unknown, baseId: string, seen: ReadonlySet<string>): void => {
    if (typeof node !== 'object' || node === null || Array.isArray(node)) {
      return;
    }
    const schema = node as JsonRecord;
    const id = schema['$id'];
    const currentBase = typeof id === 'string' ? id : baseId;
    const declared = schema['required'];
    if (Array.isArray(declared)) {
      for (const member of declared) {
        if (typeof member === 'string') {
          required.add(member);
        }
      }
    }
    const ref = schema['$ref'];
    if (typeof ref === 'string') {
      const [target, targetBase] = resolveRef(ref, currentBase);
      const absolute = ref.startsWith('#') ? `${targetBase}${ref}` : ref;
      if (!seen.has(absolute)) {
        walk(target, targetBase, new Set([...seen, absolute]));
      }
    }
    const branch = schema['allOf'];
    if (Array.isArray(branch)) {
      for (const subschema of branch) {
        walk(subschema, currentBase, seen);
      }
    }
  };
  const base = PIN_SCHEMA_REF.split('#')[0];
  walk(resolvePointer(PIN_SCHEMA_REF), base, new Set([PIN_SCHEMA_REF]));
  requiredPinFieldsCache = required;
  return required;
}

/** One released `if`/`then` requirement: the equalities tested, and the members required. */
interface ConditionalRequirement {
  readonly condition: readonly (readonly [string, unknown])[];
  readonly required: readonly string[];
}

/**
 * The `{member: value}` equalities a subschema tests, or `null` if it tests anything more.
 *
 * Only the exact shape the released scope conditional uses is read: an `if` that both
 * `require`s its discriminators and pins each with `const`. Anything richer is refused rather
 * than approximated -- a comparison that reports `resource_tenant_mismatch` for a pair that
 * legitimately agrees is exactly as broken as one that silently passes.
 *
 * The `required` half is not decoration. `properties` does not apply to an absent member, so
 * `if: { properties: { resource_scope: { const: 'tenant' } } }` alone is TRUE for an object
 * carrying no `resource_scope` at all. Mirrors Python's `verification._const_condition`.
 */
function constCondition(node: unknown): readonly (readonly [string, unknown])[] | null {
  if (typeof node !== 'object' || node === null || Array.isArray(node)) {
    return null;
  }
  const schema = node as JsonRecord;
  const allowed = new Set(['required', 'properties', '$comment']);
  if (Object.keys(schema).some((key) => !allowed.has(key))) {
    return null;
  }
  const properties = schema['properties'];
  if (typeof properties !== 'object' || properties === null || Array.isArray(properties)) {
    return null;
  }
  const entries = Object.entries(properties as JsonRecord);
  if (entries.length === 0) {
    return null;
  }
  const condition: (readonly [string, unknown])[] = [];
  for (const [member, declared] of entries) {
    if (typeof declared !== 'object' || declared === null || Array.isArray(declared)) {
      return null;
    }
    const sub = declared as JsonRecord;
    if (Object.keys(sub).some((key) => key !== 'const' && key !== '$comment')) {
      return null;
    }
    if (!Object.hasOwn(sub, 'const')) {
      return null;
    }
    condition.push([member, sub['const']] as const);
  }
  const declaredRequired = schema['required'];
  if (!Array.isArray(declaredRequired)) {
    return null;
  }
  const tested = new Set(condition.map(([member]) => member));
  const listed = new Set(declaredRequired.filter((member): member is string => typeof member === 'string'));
  if (listed.size !== tested.size || [...tested].some((member) => !listed.has(member))) {
    return null;
  }
  return condition.sort((left, right) => (left[0] < right[0] ? -1 : left[0] > right[0] ? 1 : 0));
}

let conditionalRequirementsCache: readonly ConditionalRequirement[] | null = null;

/**
 * Every `if`/`then` requirement the released pin schema declares.
 *
 * A SEPARATE walk from `requiredPinFields`, which must keep ignoring the conditional
 * branches: folding `then`'s `required` into the unconditional set would make every legal
 * global-scope verification report `resource_tenant_mismatch`. Mirrors Python's
 * `verification._conditional_pin_requirements`.
 */
function conditionalPinRequirements(): readonly ConditionalRequirement[] {
  if (conditionalRequirementsCache !== null) {
    return conditionalRequirementsCache;
  }
  const found: ConditionalRequirement[] = [];
  const walk = (node: unknown, baseId: string, seen: ReadonlySet<string>): void => {
    if (typeof node !== 'object' || node === null || Array.isArray(node)) {
      return;
    }
    const schema = node as JsonRecord;
    const id = schema['$id'];
    const currentBase = typeof id === 'string' ? id : baseId;
    const condition = constCondition(schema['if']);
    const consequent = schema['then'];
    if (
      condition !== null &&
      typeof consequent === 'object' &&
      consequent !== null &&
      !Array.isArray(consequent)
    ) {
      const declared = (consequent as JsonRecord)['required'];
      if (Array.isArray(declared)) {
        const members = declared.filter((member): member is string => typeof member === 'string');
        if (members.length > 0) {
          found.push({ condition, required: members });
        }
      }
    }
    const ref = schema['$ref'];
    if (typeof ref === 'string') {
      const [target, targetBase] = resolveRef(ref, currentBase);
      const absolute = ref.startsWith('#') ? `${targetBase}${ref}` : ref;
      if (!seen.has(absolute)) {
        walk(target, targetBase, new Set([...seen, absolute]));
      }
    }
    const branch = schema['allOf'];
    if (Array.isArray(branch)) {
      for (const subschema of branch) {
        walk(subschema, currentBase, seen);
      }
    }
  };
  const base = PIN_SCHEMA_REF.split('#')[0];
  walk(resolvePointer(PIN_SCHEMA_REF), base, new Set([PIN_SCHEMA_REF]));
  conditionalRequirementsCache = found;
  return found;
}

function conditionHolds(
  record: JsonRecord,
  condition: readonly (readonly [string, unknown])[],
): boolean {
  return condition.every(([member, value]) => Object.hasOwn(record, member) && record[member] === value);
}

/**
 * The members the released pin schema requires OF THIS PAIR, beyond the unconditional set.
 *
 * `requiredPinFields` reads only what the pin schema requires unconditionally, and that left
 * a real hole: the schema requires `resource_tenant_id` iff `resource_scope` is `tenant`, so
 * a pin declaring `"resource_scope": "tenant"` with NO tenant id, answered by a response with
 * no tenant id either, agreed about a member the contract says must be there --
 * `comparePinToOwnerResponse` returned `null`, VERIFIED. `verifyReference` blocks that pin at
 * schema validation, but this comparison is exported from `index.ts` and a direct caller got
 * the silent pass.
 *
 * The condition must hold on BOTH sides: a pin and a response that disagree about the
 * discriminator are already reported on the discriminator's own field, which precedes the
 * conditional one in `COMPARED_FIELDS`. Mirrors Python's `verification.conditional_pin_fields`.
 */
export function conditionalPinFields(pin: JsonRecord, response: OwnerResponse): ReadonlySet<string> {
  const members = new Set<string>();
  if (response === null) {
    return members;
  }
  for (const { condition, required } of conditionalPinRequirements()) {
    if (conditionHolds(pin, condition) && conditionHolds(response, condition)) {
      for (const member of required) {
        members.add(member);
      }
    }
  }
  return members;
}

/**
 * Return the non-disclosing failure code, or `null` when every field matches.
 *
 * A field the released pin schema REQUIRES must be present on both sides. Comparing with
 * `pin[field] !== response[field]` made two objects that both LACK the field compare equal,
 * so `comparePinToOwnerResponse({}, {})` answered `null` -- "every field matched, verified" --
 * which is the silent pass the whole comparison exists to prevent. Absence is now a mismatch
 * on the field's own code; the enum is closed, so no code is invented.
 *
 * `resource_tenant_id` is the one field absent on both sides legitimately, and only
 * CONDITIONALLY so: the released scope conditional REQUIRES it iff `resource_scope` is
 * `tenant` and FORBIDS it otherwise. Two GLOBAL-scope references therefore agree about it by
 * both omitting it, while two TENANT-scoped ones that both omit it agree about nothing -- and
 * that pair used to return `null`, VERIFIED. Both halves are read from the schema
 * (`requiredPinFields` and `conditionalPinFields`), never from a hardcoded field name, and
 * absent-on-one-side-only is still a mismatch -- a global pin answered with a tenant-scoped
 * target, or the reverse, does not silently pass.
 *
 * An owner that answers with content the released contract rejects -- content that does not
 * validate against the declared `schema_ref`, breaks a cross-field rule, carries an unstable
 * binary float or an undeclared array -- is a REJECTED verification, not an exception.
 * `computeContentHash` throws for all of those, and letting the throw escape means a
 * hostile or broken owner service suppresses the audit record entirely. The recorded code
 * is `content_hash_mismatch`, the closed enum's class for "the pinned hash could not be
 * reproduced from what the owner returned"; the enum is closed, so no code is invented.
 */
export function comparePinToOwnerResponse(pin: JsonRecord, response: OwnerResponse): string | null {
  if (response === null) {
    return 'target_not_found';
  }
  if (response['resolution_denied'] === true) {
    return 'resolution_denied';
  }
  const conditional = conditionalPinFields(pin, response);
  const required = new Set([...requiredPinFields(), ...conditional]);
  for (const [field, code] of COMPARED_FIELDS) {
    const pinned = memberOf(pin, field);
    let expected = memberOf(response, field);
    if (field === 'content_hash') {
      const canonicalContent = response['canonical_content'];
      if (canonicalContent !== undefined && canonicalContent !== null) {
        // Never trust a returned hash when the canonical content is available.
        const schemaRef = response['schema_ref'];
        if (typeof schemaRef !== 'string') {
          return code;
        }
        try {
          expected = computeContentHash(canonicalContent, schemaRef);
        } catch (error) {
          if (error instanceof CanonicalError) {
            return code;
          }
          throw error;
        }
      }
    }
    if (pinned === ABSENT || expected === ABSENT) {
      // Absent on BOTH sides is agreement only where the released pin schema permits the
      // field to be absent at all; absent on one side only never is.
      if (pinned === ABSENT && expected === ABSENT && !required.has(field)) {
        continue;
      }
      return code;
    }
    if (pinned !== expected) {
      return code;
    }
  }
  return null;
}

/**
 * Fail before the resolver when the local subject cannot carry a receipt at all.
 *
 * Section 4.2: `subject_local_ref` is a released `IdentityRef` or `PinnedVersionRef` whose
 * `owner_context` equals `consumer_context`. Both halves are read from the receipt schema --
 * the permitted forms from its declared subschema, the equality from its released
 * cross-field rules evaluated over the two arguments placed at their declared receipt
 * locations -- so no field name is restated here.
 */
function rejectUnusableSubject(consumerContext: string, subjectLocalRef: unknown): void {
  const errors = validateInstance(subjectLocalRef, SUBJECT_SCHEMA_REF);
  if (errors.length > 0) {
    throw new SchemaValidationError(
      `subject_local_ref is not a released reference form and produces no receipt: ${errors.join('; ')}`,
    );
  }
  const failures = checkCrossFieldRules(
    { consumer_context: consumerContext, subject_local_ref: subjectLocalRef },
    RECEIPT_SCHEMA_REF,
  );
  if (failures.length > 0) {
    throw new CrossFieldError(
      `subject_local_ref is not owned by the consumer and produces no receipt: ${failures.join('; ')}`,
    );
  }
}

export interface BuildReceiptArguments {
  receiptId: string;
  consumerContext: string;
  subjectLocalRef: JsonRecord;
  pinnedVersionRef: JsonRecord;
  verificationProfileRef: string;
  verifiedAt: string;
  failureCode: string | null;
  verifiedOwnerContext: string;
  verifiedSchemaRef: string;
  verifiedContentHash: string;
}

/**
 * Build and validate the immutable receipt for one verification attempt.
 *
 * Validation is the full released contract, schema AND cross-field rules. Checking only the
 * schema layer here would emit a `verified` receipt that the repository's own release gate
 * rejects.
 */
export function buildReceipt(args: BuildReceiptArguments): JsonRecord {
  const receipt: JsonRecord = {
    reference_verification_receipt_id: args.receiptId,
    consumer_context: args.consumerContext,
    subject_local_ref: args.subjectLocalRef,
    pinned_version_ref: args.pinnedVersionRef,
    verification_profile_ref: args.verificationProfileRef,
    verified_owner_context: args.verifiedOwnerContext,
    verified_schema_ref: args.verifiedSchemaRef,
    verified_content_hash: args.verifiedContentHash,
    verified_at: args.verifiedAt,
    result: args.failureCode ? 'rejected' : 'verified',
  };
  if (args.failureCode) {
    receipt['failure_code'] = args.failureCode;
  }
  assertValidInstance(receipt, RECEIPT_SCHEMA_REF);
  return receipt;
}

export interface VerifyReferenceArguments {
  resolver: Resolver;
  consumerContext: string;
  subjectLocalRef: JsonRecord;
  verificationProfileRef: string;
  verifiedAt: string;
  receiptId: string;
}

/**
 * Resolve, compare and return the immutable receipt.
 *
 * Malformed input never reaches the resolver: a bad pin, or a `subject_local_ref` that is
 * not a released reference owned by `consumerContext`, fails validation and produces no
 * receipt at all, which is what keeps a rejected receipt meaningful.
 */
export function verifyReference(
  pinnedVersionRef: JsonRecord,
  args: VerifyReferenceArguments,
): JsonRecord {
  const errors = validateInstance(pinnedVersionRef, PIN_SCHEMA_REF);
  if (errors.length > 0) {
    throw new SchemaValidationError(
      `a malformed pin is rejected by schema validation and produces no receipt: ${errors.join('; ')}`,
    );
  }
  rejectUnusableSubject(args.consumerContext, args.subjectLocalRef);
  const response = args.resolver(
    String(pinnedVersionRef['entity_id']),
    String(pinnedVersionRef['version_id']),
  );
  const failureCode = comparePinToOwnerResponse(pinnedVersionRef, response);
  return buildReceipt({
    receiptId: args.receiptId,
    consumerContext: args.consumerContext,
    subjectLocalRef: args.subjectLocalRef,
    pinnedVersionRef,
    verificationProfileRef: args.verificationProfileRef,
    verifiedAt: args.verifiedAt,
    failureCode,
    // A receipt records what the consumer compared against, never the target's data.
    verifiedOwnerContext: String(pinnedVersionRef['owner_context']),
    verifiedSchemaRef: String(pinnedVersionRef['schema_ref']),
    verifiedContentHash: String(pinnedVersionRef['content_hash']),
  });
}

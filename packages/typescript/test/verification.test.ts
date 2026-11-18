/**
 * P6, second half: the 14 committed verification fixtures.
 *
 * Each one must reproduce its EXACT `result` and `failure_code` -- not merely "a rejected
 * receipt". The failure codes are a closed, non-disclosing enum and the compared-field ORDER
 * decides which of several simultaneous mismatches is reported, so an engine that reports
 * the right verdict with the wrong code has not reproduced the fixture.
 *
 * Two gaps that a previous audit found in the Python harness are closed here rather than
 * inherited:
 *
 * * the resolver is called by EXACT `entity_id`/`version_id` IN THAT ORDER, and the test
 *   records the call rather than accepting `(...args) => response`, which answered any call
 *   whatsoever and stayed green when the two arguments were swapped; and
 * * the `COMPARED_FIELDS` precedence is pinned, and cross-checked against the Python source,
 *   so a reorder cannot silently change which code a multi-field mismatch reports.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { CanonicalError, SchemaValidationError } from '../src/errors';
import { REPOSITORY_ROOT } from '../src/registry';
import {
  COMPARED_FIELDS,
  comparePinToOwnerResponse,
  verifyReference,
  type JsonRecord,
  type OwnerResponse,
} from '../src/verification';
import {
  VERIFICATION_DIR,
  clone,
  fixtureFiles,
  fixtureId,
  load,
  type VerificationFixture,
} from './fixtures';

const VERIFICATION_FILES = fixtureFiles(VERIFICATION_DIR);
const cases = VERIFICATION_FILES.map((path) => [fixtureId(path), path] as const);

/** The same fixed inputs Python's harness uses, so the two produce the same receipt. */
const VERIFIED_AT = '2026-07-30T10:00:05Z';
const RECEIPT_ID = 'bbbbbbbb-0000-4000-8000-000000000001';

interface Call {
  entityId: string;
  versionId: string;
}

/**
 * A resolver that answers ONLY its fixture's exact pin, and records every call.
 *
 * `verification.py` states the rule the call has to obey: resolve by exact `entity_id` and
 * `version_id`, never fall back to latest. A resolver that ignores its arguments cannot
 * falsify that, so this one returns `null` -- which shows up as `target_not_found`, a
 * different failure code -- for anything else.
 */
function pinnedResolver(fixture: VerificationFixture, calls: Call[]) {
  const pin = fixture.pinned_version_ref;
  return (entityId: string, versionId: string): OwnerResponse => {
    calls.push({ entityId, versionId });
    if (entityId !== pin['entity_id'] || versionId !== pin['version_id']) {
      return null;
    }
    return fixture.owner_response;
  };
}

function runFixture(fixture: VerificationFixture, calls: Call[]): JsonRecord {
  return verifyReference(fixture.pinned_version_ref, {
    resolver: pinnedResolver(fixture, calls),
    consumerContext: fixture.consumer_context,
    subjectLocalRef: fixture.subject_local_ref,
    verificationProfileRef: fixture.verification_profile_ref,
    verifiedAt: VERIFIED_AT,
    receiptId: RECEIPT_ID,
  });
}

describe('P6: every verification fixture reproduces its exact result and failure_code', () => {
  it('replays exactly the 14 committed verification fixtures', () => {
    expect(VERIFICATION_FILES.length).toBe(14);
  });

  it.each(cases)('%s', (_id, path) => {
    const fixture = load<VerificationFixture>(path);
    const calls: Call[] = [];
    const receipt = runFixture(fixture, calls);

    expect(receipt['result']).toBe(fixture.expected_result);
    expect(receipt['failure_code'] ?? null).toBe(fixture.expected_failure_code);

    // The resolver is called exactly once, by exact identity, in the released order.
    expect(calls).toEqual([
      {
        entityId: fixture.pinned_version_ref['entity_id'],
        versionId: fixture.pinned_version_ref['version_id'],
      },
    ]);

    // A receipt records what the consumer compared against, never the target's data.
    expect(receipt['verified_owner_context']).toBe(fixture.pinned_version_ref['owner_context']);
    expect(receipt['verified_schema_ref']).toBe(fixture.pinned_version_ref['schema_ref']);
    expect(receipt['verified_content_hash']).toBe(fixture.pinned_version_ref['content_hash']);
  });

  it('the corpus covers both verdicts and more than one failure code', () => {
    // Non-vacuity: fourteen `rejected` receipts all reporting one code would satisfy a
    // per-fixture assertion while proving almost nothing about the comparison.
    const fixtures = VERIFICATION_FILES.map((path) => load<VerificationFixture>(path));
    expect(new Set(fixtures.map((fixture) => fixture.expected_result))).toEqual(
      new Set(['verified', 'rejected']),
    );
    // 11 distinct failure codes plus `null` for the one verified fixture.
    const codes = new Set(fixtures.map((fixture) => fixture.expected_failure_code));
    expect(codes.size).toBe(12);
    expect(codes.has(null)).toBe(true);
  });

  it('the resolver-order assertion is not vacuous: no pin has entity_id === version_id', () => {
    for (const path of VERIFICATION_FILES) {
      const pin = load<VerificationFixture>(path).pinned_version_ref;
      expect(pin['entity_id']).not.toBe(pin['version_id']);
    }
  });
});

describe('P9: the verification gate is proven able to fail', () => {
  const verified = () => load<VerificationFixture>(join(VERIFICATION_DIR, 'verification-verified.json'));

  it('a resolver that answers the wrong identity yields target_not_found, not verified', () => {
    // The falsifier for "resolve by exact entity_id/version_id, never fall back to latest":
    // swap the two arguments at the call site and the receipt changes.
    const fixture = verified();
    const calls: Call[] = [];
    const resolver = pinnedResolver(fixture, calls);
    const swapped = verifyReference(fixture.pinned_version_ref, {
      resolver: (entityId, versionId) => resolver(versionId, entityId),
      consumerContext: fixture.consumer_context,
      subjectLocalRef: fixture.subject_local_ref,
      verificationProfileRef: fixture.verification_profile_ref,
      verifiedAt: VERIFIED_AT,
      receiptId: RECEIPT_ID,
    });
    expect(swapped['result']).toBe('rejected');
    expect(swapped['failure_code']).toBe('target_not_found');
  });

  it('a supplied content_hash is never trusted over the returned canonical content', () => {
    // The owner returns the EXPECTED hash but content that does not recompute to it.
    const fixture = load<VerificationFixture>(
      join(VERIFICATION_DIR, 'verification-supplied-hash-not-trusted.json'),
    );
    expect(fixture.owner_response?.['content_hash']).toBe(
      fixture.pinned_version_ref['content_hash'],
    );
    expect(comparePinToOwnerResponse(fixture.pinned_version_ref, fixture.owner_response)).toBe(
      'content_hash_mismatch',
    );

    // Drop the canonical content and the very same response is accepted -- so the
    // recomputation, not the field comparison, is what rejects it.
    const trusting = clone(fixture.owner_response) as JsonRecord;
    delete trusting['canonical_content'];
    expect(comparePinToOwnerResponse(fixture.pinned_version_ref, trusting)).toBeNull();
  });

  it('an owner response that does not validate is a REJECTED receipt, not an escaping throw', () => {
    // A hostile or broken owner service must not be able to erase its own audit trail.
    const fixture = load<VerificationFixture>(
      join(VERIFICATION_DIR, 'verification-owner-content-does-not-validate.json'),
    );
    const content = fixture.owner_response?.['canonical_content'];
    const schemaRef = String(fixture.owner_response?.['schema_ref']);
    expect(() => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      (require('../src/engine') as typeof import('../src/engine')).computeContentHash(
        content,
        schemaRef,
      );
    }).toThrow(CanonicalError);

    const receipt = runFixture(fixture, []);
    expect(receipt['result']).toBe('rejected');
    expect(receipt['failure_code']).toBe('content_hash_mismatch');
  });

  it('a malformed pin produces NO receipt at all', () => {
    const fixture = verified();
    const broken = clone(fixture.pinned_version_ref);
    broken['entity_id'] = 'not-a-uuid';
    expect(() =>
      verifyReference(broken, {
        resolver: () => fixture.owner_response,
        consumerContext: fixture.consumer_context,
        subjectLocalRef: fixture.subject_local_ref,
        verificationProfileRef: fixture.verification_profile_ref,
        verifiedAt: VERIFIED_AT,
        receiptId: RECEIPT_ID,
      }),
    ).toThrow(SchemaValidationError);
  });

  it('a subject the consumer does not own produces NO receipt at all', () => {
    const fixture = verified();
    expect(() =>
      verifyReference(fixture.pinned_version_ref, {
        resolver: () => fixture.owner_response,
        consumerContext: 'some-other-context',
        subjectLocalRef: fixture.subject_local_ref,
        verificationProfileRef: fixture.verification_profile_ref,
        verifiedAt: VERIFIED_AT,
        receiptId: RECEIPT_ID,
      }),
    ).toThrow(/not owned by the consumer/);
  });

  /**
   * FALSE-POSITIVE CONTROL: the right verdict with the wrong code must fail the gate.
   *
   * Every rejected fixture reports `result: "rejected"`, so asserting the verdict alone is
   * satisfied by ANY rejection. This shows the code is what discriminates: the same fixture
   * broken a second, earlier way reports the EARLIER code, and the fixture's own expectation
   * would no longer be met.
   */
  it('the failure_code, not just the verdict, is what the gate measures', () => {
    const fixture = load<VerificationFixture>(
      join(VERIFICATION_DIR, 'verification-wrong-version-number.json'),
    );
    expect(fixture.expected_failure_code).toBe('version_number_mismatch');

    const alsoWrongType = clone(fixture.owner_response) as JsonRecord;
    alsoWrongType['entity_type'] = 'something_else_entirely';
    const code = comparePinToOwnerResponse(fixture.pinned_version_ref, alsoWrongType);

    expect(code).toBe('entity_type_mismatch'); // the earlier compared field wins...
    expect(code).not.toBe(fixture.expected_failure_code); // ...and the fixture would go red.
  });

  it('COMPARED_FIELDS precedence is pinned, so a reorder changes a reported code', () => {
    const names = COMPARED_FIELDS.map(([field]) => field);
    expect(names).toEqual([
      'owner_context',
      'entity_type',
      'entity_id',
      'version_id',
      'version_number',
      'resource_scope',
      'resource_tenant_id',
      'schema_ref',
      'content_hash',
    ]);
  });

  it('and it is the SAME order merged Python compares in', () => {
    const source = readFileSync(
      join(REPOSITORY_ROOT, 'src', 'research_contracts', 'canonical', 'verification.py'),
      'utf-8',
    );
    const pattern = /\("([a-z_]+)", "([a-z_]+)"\),/g;
    const pythonPairs = [...source.matchAll(pattern)].map((match) => [match[1], match[2]]);
    // Non-vacuity first: an unparsed source would make the comparison trivially equal.
    expect(pythonPairs.length).toBe(COMPARED_FIELDS.length);
    expect(pythonPairs).toEqual(COMPARED_FIELDS.map(([field, code]) => [field, code]));
  });
});

/**
 * The instance-validation seam.
 *
 * Python pairs the JSON Schema layer with the released `x-datacompany-cross-field` rules
 * (`structural.py`) and calls the pair `validate_instance` / `assert_valid_instance`. Both
 * halves now exist in this port: `structural.ts` is the evaluator and it is installed HERE,
 * as the default, so a consumer doing the obvious thing cannot silently miss an interval or
 * equality invariant.
 *
 * The injection seam survives for one reason only: proving falsifiability. A test can swap
 * the evaluator for a planted one and watch every dependent fixture go red, which is the
 * only way to show the seam is genuinely on the validation path rather than a decorative
 * export. `crossFieldRulesAreEvaluated()` reports whether the released evaluator is the one
 * installed, so a suite that ran with a stub cannot report itself as parity.
 */

import { CrossFieldError, SchemaValidationError } from './errors';
import { validateSchemaOnly } from './registry';
import { evaluateCrossFieldRules } from './structural';

/** Returns the human-readable failures of the released cross-field rules of `schemaRef`. */
export type CrossFieldEvaluator = (instance: unknown, schemaRef: string) => string[];

const RELEASED_EVALUATOR: CrossFieldEvaluator = evaluateCrossFieldRules;

let evaluator: CrossFieldEvaluator = RELEASED_EVALUATOR;

/**
 * Replace the released cross-field rule evaluator.
 *
 * Test-only. Production code has no reason to call it: the released evaluator is already
 * installed, and replacing it can only weaken the contract.
 */
export function registerCrossFieldEvaluator(next: CrossFieldEvaluator): void {
  evaluator = next;
}

/** Restore the released evaluator. */
export function resetCrossFieldEvaluator(): void {
  evaluator = RELEASED_EVALUATOR;
}

/** True while the RELEASED evaluator is installed, so a caller cannot assume a stub ran. */
export function crossFieldRulesAreEvaluated(): boolean {
  return evaluator === RELEASED_EVALUATOR;
}

/** Return the failures of every released cross-field rule declared by `schemaRef`. */
export function checkCrossFieldRules(instance: unknown, schemaRef: string): string[] {
  return evaluator(instance, schemaRef);
}

/** Return every released failure of `instance` against `schemaRef`. */
export function validateInstance(instance: unknown, schemaRef: string): string[] {
  return [...validateSchemaOnly(instance, schemaRef), ...checkCrossFieldRules(instance, schemaRef)];
}

/**
 * Raise on the first released failure of `instance` against `schemaRef`.
 *
 * Schema failures raise `SchemaValidationError` and cross-field failures raise
 * `CrossFieldError`, so a caller can still tell the two layers apart.
 */
export function assertValidInstance(instance: unknown, schemaRef: string): void {
  const errors = validateSchemaOnly(instance, schemaRef);
  if (errors.length > 0) {
    throw new SchemaValidationError(
      `instance does not validate against ${schemaRef}: ${errors.join('; ')}`,
    );
  }
  const failures = checkCrossFieldRules(instance, schemaRef);
  if (failures.length > 0) {
    throw new CrossFieldError(
      `instance violates released cross-field rules of ${schemaRef}: ${failures.join('; ')}`,
    );
  }
}

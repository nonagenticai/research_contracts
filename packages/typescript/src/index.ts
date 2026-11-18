/**
 * TypeScript parity port of the DataCompany canonical hash engine (FND-005).
 *
 * The Python reference is `src/research_contracts/canonical/`. The language-neutral
 * fixtures under `fixtures/canonical-hash/v1/` are the oracle for both implementations;
 * neither is the authority for the other.
 *
 * The port is now whole: `structural.ts` evaluates the released `x-datacompany-cross-field`
 * rules and is installed as `validation.ts`'s default evaluator, and `verification.ts`
 * reproduces the owner-resolver comparison and receipt construction. All 113 committed
 * checks run in both languages.
 */

export * from './errors';
export * from './jcs';
export * from './json';
export * from './hashView';
export * from './hashProfile';
export * from './registry';
export * from './structural';
export * from './validation';
export * from './engine';
export * from './verification';

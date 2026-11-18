/**
 * Jest configuration for the TypeScript canonical-hash parity suite.
 *
 * `roots` deliberately covers BOTH `src/` and `test/`. A config whose roots list
 * only `src/` while a `test/` directory exists silently runs zero of those tests
 * and still reports green -- an empty measurement reported as a passing one.
 *
 * `tsconfig.json` sets `rootDir` to the repository root, NOT to this package, so that the
 * committed `generated/typescript/` bindings are inside the type-check program and
 * `tsc --noEmit` really checks them. `tsconfig.build.json` narrows `rootDir` back to
 * `./src` for emit, so the published layout is unchanged. The explanation lives here
 * rather than in tsconfig.json because the repository-wide contract lint parses every
 * `.json` file as strict JSON and a `//` comment makes it unparseable.
 */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/src', '<rootDir>/test'],
  testMatch: ['**/__tests__/**/*.test.ts', '**/?(*.)+(spec|test).ts'],
  // Fail loudly instead of reporting a green run over nothing.
  passWithNoTests: false,
  collectCoverageFrom: ['src/**/*.ts', '!src/**/*.d.ts'],
};

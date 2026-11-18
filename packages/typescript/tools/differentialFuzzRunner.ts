/**
 * The TypeScript half of the P8 differential fuzz.
 *
 * Deliberately dumb: a corpus of generated cases in, one result per case out. All
 * generation, comparison, shrinking and reporting lives in
 * `src/research_contracts/tooling/differential_fuzz.py`, so there is exactly ONE
 * implementation of the generator and the comparator. A second generator, ported, would
 * only prove that the port of the generator agrees with itself.
 *
 * The corpus is read with `parseCanonicalJson`, not bare `JSON.parse`. That is load-bearing
 * twice over:
 *
 * 1. a generated case carrying an integer literal past 2^53 must arrive here as a `bigint`,
 *    the way Python's `json.loads` hands its side an exact `int`. Bare `JSON.parse` would
 *    round it away before any engine code ran, and the two engines would silently "agree"
 *    about a value neither of them could see;
 * 2. `JSON.parse` is not a pure function of its argument on Node >= 24, so a case earlier in
 *    this loop could rename a member of a case later in it -- which it did, reddening this
 *    gate on 5 of 200 measured seeds. `parseCanonicalJson` owns the parse now; see
 *    `src/json.ts`. Nothing else in this file holds state between cases, and the harness
 *    re-hashes the corpus reversed and case-by-case on every run to keep it that way.
 *
 *     node dist-tools/tools/differentialFuzzRunner.js <corpus.jsonl> <results.jsonl>
 *
 * An empty corpus is an error, not an empty success: a runner that emits zero results for
 * zero cases lets the whole gate render green over nothing.
 */

import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';

import { buildHashView, type HashProfile } from '../src/hashView';
import { canonicalize } from '../src/jcs';
import { parseCanonicalJson } from '../src/json';

interface FuzzCase {
  case_id: string;
  category: string;
  layer: 'jcs' | 'hash_view';
  allow_binary_float: boolean;
  value: unknown;
  profile: HashProfile | null;
}

type FuzzResult =
  | { case_id: string; ok: true; canonical_base64: string; digest: string }
  | { case_id: string; ok: false; error: string };

/** The name Python's `type(exc).__name__` would report for the same failure. */
function errorName(error: unknown): string {
  if (error instanceof Error) {
    // Every canonical error sets `name` explicitly; the fixtures pin those exact strings.
    return error.name;
  }
  return typeof error;
}

function evaluate(item: FuzzCase): FuzzResult {
  try {
    const subject =
      item.layer === 'hash_view'
        ? buildHashView(item.value, item.profile as HashProfile)
        : item.value;
    const bytes = canonicalize(subject, { allowBinaryFloat: item.allow_binary_float === true });
    return {
      case_id: item.case_id,
      ok: true,
      canonical_base64: Buffer.from(bytes).toString('base64'),
      digest: `sha256:${createHash('sha256').update(bytes).digest('hex')}`,
    };
  } catch (error) {
    return { case_id: item.case_id, ok: false, error: errorName(error) };
  }
}

export function runCorpus(text: string): FuzzResult[] {
  const lines = text.split('\n').filter((line) => line.trim().length > 0);
  if (lines.length === 0) {
    throw new Error(
      'the differential-fuzz corpus is empty; a runner that emits zero results for zero ' +
        'cases would let the gate render green over nothing',
    );
  }
  return lines.map((line) => evaluate(parseCanonicalJson(line) as unknown as FuzzCase));
}

function main(argv: string[]): number {
  const [corpusPath, resultsPath] = argv;
  if (corpusPath === undefined || resultsPath === undefined) {
    process.stderr.write('usage: differentialFuzzRunner.js <corpus.jsonl> <results.jsonl>\n');
    return 2;
  }
  const results = runCorpus(readFileSync(corpusPath, 'utf-8'));
  writeFileSync(
    resultsPath,
    `${results.map((result) => JSON.stringify(result)).join('\n')}\n`,
    'utf-8',
  );
  return 0;
}

if (require.main === module) {
  try {
    process.exitCode = main(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
    process.exitCode = 1;
  }
}

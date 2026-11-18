/**
 * Released cross-field rules that JSON Schema 2020-12 cannot express.
 *
 * TypeScript port of `src/research_contracts/canonical/structural.py`. JSON Schema has no
 * way to compare two instance locations, so the half-open non-empty interval rule, the
 * receipt ownership/tenant equalities and the hash-manifest uniqueness/disjointness rules
 * are declared in the schema as `x-datacompany-cross-field` and evaluated here. The rules stay
 * schema-driven: this module contains no hardcoded field names.
 *
 * The vocabulary this evaluates is written down normatively in `EXTENSIONS.md`; neither
 * implementation is the authority for the other, and the committed fixtures under
 * `fixtures/canonical-references/v1/` are the oracle for both.
 *
 * PARITY NOTE on failure-message text, RE-MEASURED and NARROWED 2026-08-04. This note used
 * to say "every message produced for a rule that a committed fixture actually exercises is
 * byte-identical to Python's, because the fixtures assert against it through
 * `expected_error_contains`". That is FALSE as written, and the reasoning inverted cause and
 * effect: what the fixtures assert is a chosen SUBSTRING, not the message. Measured on the
 * same rule and the same instance, this port and Python still differ on `disjoint`'s overlap
 * message (`"a" appears in both` versus `'a' appears in both`; `true` versus `True`), on
 * `unique_by`'s duplicate message (`null` versus `None`) and on the non-array-target message
 * (`"notalist"` versus `'notalist'`) -- because Python spells the interpolated value with
 * `repr()`, which is Python source syntax no other language reproduces, and this port renders
 * it as RFC 8785 canonical JSON.
 *
 * That divergence is REAL, is reachable on `run-manifest:1` -- the one released `disjoint`
 * rule that can fire, whose members are UUID STRINGS -- and is NOT closed here. It survives
 * unnoticed because the corpus is built around it: the committed fixture that exercises that
 * rule asserts only the rule name and `must be disjoint`, and the operator vectors
 * deliberately use the number `7`, which both languages render as `7`. Both facts are
 * disclosed in `fixtures/canonical-cross-field/v1/operator-vectors.json` rather than left for
 * a reader to discover. The fix is to route both engines' rendered values through
 * `rendering.json_text` (spelled `jsonText` here), and it is not taken here because it spans
 * EXTENSIONS.md sections 4.1, 4.4 and 4.5 at once.
 *
 * What IS byte-identical, by construction rather than by assertion, is every message added
 * with section 4.5's and section 4.2's closures: the missing-member-key message and the
 * uncomparable-operand message interpolate POINTERS only. That is why `missingMemberKey`
 * renders the key pointer through the same `?? ''` fallback Python spells `or ""`, and why
 * `uncomparable` names no value even though it has one to hand.
 *
 * CLOSED 2026-07-30 (decision F). Neither engine used to validate the ANNOTATIONS
 * themselves, so a malformed `x-datacompany-cross-field` failed DIFFERENTLY in the two
 * languages. Measured against both engines before the fix:
 *
 * | declaration | Python | this port |
 * |---|---|---|
 * | `{}` | `[]` -- falsy, silently no rules | `[]` -- not an array, same |
 * | `"equal"` | `AttributeError` | **`[]`** -- not an array, silently no rules |
 * | `[null]` | `AttributeError` | `TypeError` |
 * | `[["equal"]]` | `AttributeError` | `CrossFieldError: unknown ... undefined` |
 * | `[{"rule":"equal"}]` (no operand) | `KeyError: 'left'` | a failure naming `undefined` |
 *
 * This port was the worse half: a bare string was skipped in SILENCE, producing no rules and
 * no error, which is the vacuity class -- the contract reads as enforced and enforces
 * nothing. It cost no check at the time only because no released schema was in any of these
 * shapes, which is a fact about today's corpus, not a property of the engine.
 *
 * Closing it required NO new normative semantics, which is why it did not need an owner:
 * `schemas/meta/datacompany-extension-vocabulary.v1.schema.json` already rejected every shape
 * above, under a gate proven falsifiable one mutation at a time. What was missing was the
 * engines consulting it. Both now raise `CrossFieldError` on all of them -- see
 * `declaredRules` below.
 */

import { CrossFieldError, UnstableFloatError, UnsupportedTypeError } from './errors';
import { canonicalizeToString } from './jcs';
import { resolvePointer, resolveRef } from './registry';
import { jsonText, jsonType } from './rendering';

type JsonRecord = Record<string, unknown>;

/**
 * The propositions a cross-field rule can fail to DECIDE, as opposed to fail. A named type so
 * a fourth spelling is a compile error rather than a silent third wording of one message;
 * Python spells the same set as a `Literal`.
 */
type Undecidable = 'equality' | 'uniqueness' | 'disjointness';

/** Distinguishes "the pointer names nothing" from "the pointer names `null`". */
export const MISSING = Symbol('missing');

/**
 * The released `rfc3339_utc_z` representation: a UTC instant with the trailing `Z` and
 * optional fractional seconds of arbitrary precision.
 */
const RFC3339_UTC_Z =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$/u;

const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31] as const;

/**
 * A comparable instant, or `null` when the value is not a released timestamp.
 *
 * `[seconds since the epoch, fractional digits]`. The fraction keeps every digit it was
 * given and is compared as a trailing-zero-stripped digit string, which for such strings
 * orders identically to the numeric fraction. Neither half is a binary float, so no
 * precision is lost and the two engines agree exactly -- whereas rounding to a fixed number
 * of decimals would make two distinct high-precision instants compare equal and let an
 * inverted interval through.
 */
type Instant = readonly [number, string];

function isLeapYear(year: number): boolean {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

/**
 * Mirrors Python's `datetime(...)` constructor rejecting an impossible date, which
 * `structural.py` turns into "not a released instant" rather than a crash.
 */
function isRealDate(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12 || day < 1) {
    return false;
  }
  const limit = month === 2 && isLeapYear(year) ? 29 : DAYS_IN_MONTH[month - 1];
  return day <= limit;
}

function instant(value: unknown): Instant | null {
  if (typeof value !== 'string') {
    return null;
  }
  const match = RFC3339_UTC_Z.exec(value);
  if (match === null) {
    return null;
  }
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  if (!isRealDate(year, month, day) || hour > 23 || minute > 59 || second > 60) {
    return null;
  }
  // `Date.UTC` is exact for every instant the released timestamp pattern can express, and
  // is not a binary-float computation over the seconds value.
  const seconds = Date.UTC(year, month - 1, day, hour, minute, second) / 1000;
  return [seconds, (match[7] ?? '').replace(/0+$/u, '')];
}

/** Total order over instants, matching Python's tuple comparison. */
function compareInstants(left: Instant, right: Instant): number {
  if (left[0] !== right[0]) {
    return left[0] < right[0] ? -1 : 1;
  }
  if (left[1] === right[1]) {
    return 0;
  }
  return left[1] < right[1] ? -1 : 1;
}

/**
 * The language-neutral identity of a JSON value: its RFC 8785 canonical text.
 *
 * `repr` cannot do this job -- it is Python source syntax that no other language
 * reproduces, and it is insertion-order dependent, so `{"a":1,"b":2}` and `{"b":2,"a":1}`
 * (the same JSON value) produced two different markers. Merged Python uses the same
 * canonical bytes for exactly this reason.
 *
 * `allowBinaryFloat` is on because this is an identity marker, not a hashed input: a binary
 * float in an instance must not turn a validation call that returns a list of failures into
 * a thrown `UnstableFloatError`. The hash path still rejects it.
 */
function identityMarker(value: unknown): string {
  return canonicalizeToString(value, { allowBinaryFloat: true });
}

/**
 * Whether two JSON values are the SAME VALUE, language-neutrally (EXTENSIONS.md section 4.2).
 *
 * `===` cannot do this job and neither could Python's `==`. `===` is reference identity for
 * objects and arrays, so `{"a":1,"b":2}` and `{"b":2,"a":1}` -- one JSON value written twice
 * -- are unequal, and so are two structurally identical arrays; `==` accepts `"1" == 1`,
 * which no other reading admits. Python's `==` is a third answer again: `bool` IS an `int`
 * there, so `true == 1` and `0 == false` both held and the released `equal` rule reported
 * `{"left": true, "right": 1}` as HOLDING while this port reported it VIOLATED. That was a
 * live cross-language split on a released operator, not a hypothetical one -- this port had
 * already moved to canonical bytes and Python had not.
 *
 * RFC 8785 canonical bytes is what section 4.2 prescribes -- "A second implementation MUST
 * use RFC 8785 canonical-byte equality" -- and it is the comparator D1 already moved
 * `unique_by`, `disjoint` and the rule-dedup marker to. Both engines now use it, so `equal`
 * is decided by the same bytes the hash is.
 */
function sameValue(left: unknown, right: unknown): boolean {
  return identityMarker(left) === identityMarker(right);
}

/** Whether `value` has RFC 8785 canonical bytes at all. */
function comparable(value: unknown): boolean {
  try {
    identityMarker(value);
  } catch (error) {
    if (error instanceof UnstableFloatError || error instanceof UnsupportedTypeError) {
      return false;
    }
    throw error;
  }
  return true;
}

/**
 * Failures for the operands that have no canonical bytes, so no equality to decide.
 *
 * `allowBinaryFloat` is NOT a blanket permit, and reading it as one is what made the first
 * version of the section 4.2 closure a regression in Python: it admits a finite non-integral
 * float and does nothing for `NaN`, `+/-Infinity` or a lone surrogate. `evaluateCrossFieldRules`
 * RETURNS a failure list, so an operand it cannot canonicalize must be a recorded failure and
 * never an escaping throw -- section 4.1 already decided the identical question the identical
 * way, an interval bound that is not a released instant being "a recorded failure, never a
 * comparison". "Call them unequal" is the wrong answer too: having no canonical bytes is a
 * different fact from differing.
 *
 * The message names no VALUE on purpose. The two engines' own exception text for the same
 * input already differs (`NaN` here, `nan` in Python), and rendering the value would import
 * the wider `repr`-versus-canonical divergence recorded at the top of this file. Pointers are
 * byte-identical in both languages.
 *
 * THE REACHABLE SET IS NOT THE SAME IN THE TWO LANGUAGES, and that is a property of the
 * PARSERS rather than of either engine. `JSON.parse` collapses an integer literal outside the
 * exact double range to the nearest double before this code ever runs, so `9007199254740993`
 * arrives here as `9007199254740992` and canonicalizes cleanly, where Python's `json.loads`
 * yields the exact `int` and refuses it. `NaN` and `+/-Infinity` are the mirror image:
 * reachable from Python's `json.loads` on its DEFAULT settings, unreachable from `JSON.parse`,
 * and reachable here only from a value built in code. Only a lone surrogate is symmetric. The
 * surviving divergence is pinned as a declared per-engine expectation in
 * `fixtures/canonical-cross-field/v1/operator-vectors.json`; no engine change removes it.
 */
function uncomparable(
  name: string,
  operands: readonly (readonly [string, unknown])[],
  role: Undecidable,
): string[] {
  return operands
    .filter(([, value]) => !comparable(value))
    .map(([pointer]) => uncomparableText(name, pointer, role));
}

/** The one place the uncomparable-operand message is spelled, in either language. */
function uncomparableText(name: string, pointer: string, role: Undecidable): string {
  return (
    `${name}: ${pointer} is not a value RFC 8785 can canonicalize, so the ${role} ` +
    'cannot be decided'
  );
}

function isPlainObject(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * RFC 6901 section 4: `array-index = %x30 / ( %x31-39 *(%x30-39) )`. Exactly `0`, or a
 * non-zero digit followed by ASCII digits.
 *
 * The comment that used to sit here claimed parity with Python's `list[int(token)]`,
 * "negative indices included, so the two engines answer identically for every pointer either
 * can be handed". That was FALSE in both directions. `int()` accepts a sign, surrounding
 * whitespace, PEP 515 underscores and every Unicode decimal digit, so `"+0"`, `" 0"`, `"0_0"`
 * and the Arabic-Indic zero U+0660 all resolved to element 0 in Python while `/^-?\d+$/u`
 * rejected all four; and `-1` wrapped around here while Python's guard was `IndexError`
 * rather than a grammar. `{"rule":"equal","left":"/a/+0","right":"/b"}` against `{"a":[5],"b":5}` therefore
 * PASSED in Python and FAILED here -- one engine reporting a released rule as holding where
 * the other reported it violated, on the same instance.
 *
 * Both engines now implement the RFC grammar itself, which is narrower than either previous
 * behaviour: it also rejects leading zeros (`"00"`) and negative indices, neither of which
 * RFC 6901 admits and neither of which any released rule uses. Parity is now by
 * construction rather than by assertion.
 */
const ARRAY_INDEX = /^(?:0|[1-9][0-9]*)$/u;

/** Resolve an RFC 6901 pointer against an instance, or return `MISSING`. */
export function pointerInto(instance: unknown, pointer: string): unknown {
  let node: unknown = instance;
  for (const raw of pointer.replace(/^\/+/u, '').split('/')) {
    const token = raw.split('~1').join('/').split('~0').join('~');
    if (isPlainObject(node)) {
      if (!Object.hasOwn(node, token)) {
        return MISSING;
      }
      node = node[token];
    } else if (Array.isArray(node)) {
      if (!ARRAY_INDEX.test(token)) {
        return MISSING;
      }
      const index = Number(token);
      if (index >= node.length) {
        return MISSING;
      }
      node = node[index];
    } else {
      return MISSING;
    }
  }
  return node;
}

function memberKey(member: unknown, keyPointer: string | undefined): unknown {
  return keyPointer === undefined ? member : pointerInto(member, keyPointer);
}

export interface CrossFieldRule {
  rule?: string;
  name?: string;
  scope?: string;
  [key: string]: unknown;
}

const APPLICATOR_BRANCHES = ['allOf', 'anyOf', 'oneOf', 'then', 'else'] as const;

/**
 * Keywords with no single well-defined instance location, so `scope: relative` cannot
 * rescue them either: `contains` applies to SOME unidentified element, `propertyNames`
 * applies to a property NAME string rather than to a value, and `contentSchema` applies to
 * the DECODED contents of a string -- a document this instance does not contain. A rule
 * under one of these is unevaluable at any scope and fails closed. Mirrors Python's
 * `structural._UNLOCATABLE_KEYWORDS`.
 *
 * `$defs` and the pre-2020 `definitions` are deliberately absent from every family here: a
 * bag of subschemas sits at no instance location, so a rule inside one is applied by nothing
 * until a `$ref` composes it -- and where one does, this collector reaches the rule through
 * that `$ref` unblocked. Blocking the bag would make a rule inside a `$def` raise even when
 * it IS composed, because the walk reaches the same node by both routes. See Python's
 * `structural._DEFINITION_BAG_KEYWORDS` for the full justification and the measurement that
 * bounds it.
 */
const UNLOCATABLE_KEYWORDS = ['contains', 'propertyNames', 'contentSchema'] as const;

/**
 * Members that are not 2020-12 keywords, so a 2020-12 validator reads no subschema there and
 * applies nothing. A rule under one is dropped by the SPECIFICATION and not merely by this
 * collector -- silently, twice over -- so it fails closed rather than being ignored as an
 * unknown member. Mirrors Python's `structural._LEGACY_SCHEMA_KEYWORDS`.
 */
const LEGACY_SCHEMA_KEYWORDS = ['additionalItems'] as const;

/**
 * Applicators this collector does not descend into, whose subschema takes ONE schema.
 * `dependentSchemas` takes a map and is handled beside them.
 *
 * A rule declared under any of these used to be dropped in SILENCE: the collector never
 * visited the node, so `evaluateCrossFieldRules` reported no failures at all while the schema
 * read as enforced. That is the vacuity class -- invisible, and strictly worse than either
 * alternative. Failing closed turns it into an authoring error that names itself.
 *
 * `not` and `dependentSchemas` are genuinely in-place applicators and COULD be collected
 * branches; `if` is evaluated in place too, and `unevaluatedProperties`/`unevaluatedItems`
 * address child locations that depend on annotation results this engine does not compute.
 * Adding any of them to `APPLICATOR_BRANCHES` is a behaviour EXPANSION and needs a decision.
 * Failing closed is the conservative, reversible half of it, and it costs nothing today: no
 * released schema declares a rule under any of the five. Mirrors Python's
 * `structural._UNCOLLECTED_SCHEMA_KEYWORDS`.
 *
 * `unevaluatedItems` was MISSING here, and from the Python tuple, while its direct sibling in
 * the same `unevaluated` vocabulary was present -- the silent drop this family exists to
 * eliminate, in the engine that eliminates it.
 */
const UNCOLLECTED_SCHEMA_KEYWORDS = [
  'if',
  'not',
  'unevaluatedProperties',
  'unevaluatedItems',
] as const;
const UNCOLLECTED_MAP_KEYWORDS = ['dependentSchemas'] as const;

const UNCOLLECTED_REASON =
  'an applicator this engine does not collect cross-field rules from. A rule declared ' +
  'there is silently dropped -- it reports no failure against any instance while the ' +
  'schema reads as enforced -- so it fails closed instead. Declare the rule at the root ' +
  'of the composed schema, or under one of ' +
  `${APPLICATOR_BRANCHES.join('/')}, which this engine collects.`;

/** Why each blocked keyword blocks, keyed by the keyword itself so the diagnostic names it. */
const BLOCKED_KEYWORD_REASON: Record<string, string> = {
  contains:
    'a keyword with no single instance location -- it applies to some unidentified ' +
    'element -- so no rule scope can evaluate it.',
  propertyNames:
    'a keyword with no single instance location -- it applies to a property NAME string ' +
    'rather than to a value -- so no rule scope can evaluate it.',
  contentSchema:
    'a keyword with no single instance location -- it applies to the DECODED contents of a ' +
    'string, a document this instance does not contain and this engine never materialises ' +
    "-- so no rule scope can evaluate it. 2020-12's content vocabulary is " +
    'annotation-only besides, so a validator asserts nothing there either.',
  additionalItems:
    'not a 2020-12 keyword at all. 2019-09 used it for the elements past a tuple; 2020-12 ' +
    'replaced that pairing with prefixItems plus items, and a 2020-12 validator reads no ' +
    'subschema here, so the rule is dropped by the specification and not merely by this ' +
    'engine. Move it under items.',
  items:
    "an ARRAY-valued 'items', which is the 2019-09 tuple form. 2020-12 requires 'items' to " +
    'be a single schema and spells the tuple as prefixItems, so a 2020-12 validator reads ' +
    'no subschema in this array and the rule is dropped by the specification. Move it under ' +
    'prefixItems.',
  ...Object.fromEntries(
    [...UNCOLLECTED_SCHEMA_KEYWORDS, ...UNCOLLECTED_MAP_KEYWORDS].map((keyword) => [
      keyword,
      UNCOLLECTED_REASON,
    ]),
  ),
};

/**
 * The released rule scopes. `absolute` is the default and the meaning every rule released
 * before D3 carries: operands resolve against the instance root. `relative` resolves them
 * against the location the rule was reached at, which at a document root is the same thing.
 */
const SCOPE_ABSOLUTE = 'absolute';
const SCOPE_RELATIVE = 'relative';

/**
 * One derivable step from a parent instance location to the child locations a subschema
 * applies at. A step is a PLAN, not a location: `['items', 0]` names every element of
 * whatever array is found there, so a step expands against a real instance to zero, one or
 * many concrete pointers.
 */
type Step =
  | readonly ['key', string]
  | readonly ['index', number]
  | readonly ['items', number]
  | readonly ['pattern', string]
  | readonly ['additional', readonly string[], readonly string[]];

export interface CrossFieldRuleSite {
  readonly rule: CrossFieldRule;
  readonly steps: readonly Step[];
}

/** Encode a raw member name as an RFC 6901 reference token. */
function escapeToken(token: string): string {
  return token.split('~').join('~0').split('/').join('~1');
}

/**
 * `patternProperties` matching, compiled with ECMA-262 semantics.
 *
 * No flag is passed on purpose. Python's `registry.ecma_262_pattern` translates a released
 * pattern into Python `re` aiming at ECMA-262 semantics WITHOUT unicode mode, so a bare
 * `new RegExp` is the closest parity; adding `u` would reject patterns Python accepts and
 * open a divergence class in the one direction that matters here.
 */
function patternMatcher(pattern: string): RegExp {
  return new RegExp(pattern);
}

/**
 * Expand a collected step plan into the concrete instance pointers it addresses.
 *
 * A step that addresses nothing in THIS instance contributes no location, so the rule is
 * simply not evaluated there -- the same thing JSON Schema does with the subschema the rule
 * was declared under. That is not the fail-open case the interval and uniqueness rules guard
 * against, where the rule DOES apply and its named target is missing.
 */
function locations(instance: unknown, steps: readonly Step[]): string[] {
  let bases = [''];
  for (const step of steps) {
    const next: string[] = [];
    for (const base of bases) {
      const node = base === '' ? instance : pointerInto(instance, base);
      if (node === MISSING) {
        continue;
      }
      if (step[0] === 'key') {
        if (isPlainObject(node) && Object.hasOwn(node, step[1])) {
          next.push(`${base}/${escapeToken(step[1])}`);
        }
      } else if (step[0] === 'index') {
        if (Array.isArray(node) && step[1] < node.length) {
          next.push(`${base}/${step[1]}`);
        }
      } else if (step[0] === 'items') {
        if (Array.isArray(node)) {
          for (let index = step[1]; index < node.length; index += 1) {
            next.push(`${base}/${index}`);
          }
        }
      } else if (step[0] === 'pattern') {
        if (isPlainObject(node)) {
          const matches = patternMatcher(step[1]);
          for (const key of Object.keys(node)) {
            if (matches.test(key)) {
              next.push(`${base}/${escapeToken(key)}`);
            }
          }
        }
      } else if (isPlainObject(node)) {
        const [, named, patterns] = step;
        const compiled = patterns.map(patternMatcher);
        for (const key of Object.keys(node)) {
          if (!named.includes(key) && !compiled.some((rx) => rx.test(key))) {
            next.push(`${base}/${escapeToken(key)}`);
          }
        }
      }
    }
    bases = next;
    if (bases.length === 0) {
      break;
    }
  }
  return bases;
}

/**
 * The operands each operator indexes directly, as required/optional member names.
 *
 * Mirrors Python's `structural._OPERANDS`, which in turn is cross-checked against
 * `schemas/meta/datacompany-extension-vocabulary.v1.schema.json` in both directions by
 * `tests/test_extension_vocabulary.py`. It is re-stated in both engines rather than read
 * from the meta-schema at runtime so that this port does not need to ship a JSON Schema
 * validator just to reject a malformed annotation.
 */
const OPERANDS: Record<string, { required: readonly string[]; optional: readonly string[] }> = {
  half_open_interval: { required: ['from', 'to'], optional: [] },
  equal: { required: ['left', 'right'], optional: [] },
  equal_when_both_present: { required: ['left', 'right'], optional: [] },
  unique_by: { required: ['at'], optional: ['key'] },
  disjoint: { required: ['left', 'right'], optional: ['left_key', 'right_key'] },
};

/** Members every rule may carry regardless of operator. */
const COMMON_MEMBERS = ['rule', 'name', 'scope', '$comment'] as const;

/** The lexical form of an operand pointer, mirroring the meta-schema's `instance_pointer`. */
const POINTER = /^(\/([^/~]|~[01])*)+$/u;

/**
 * Return a node's declared rules, refusing any declaration that is not well formed.
 *
 * DECISION F. This port was the worse half of the divergence documented at the top of this
 * file: `Array.isArray` returned false for a bare string `"equal"` and the declaration was
 * skipped in SILENCE, producing no rules and no error, where Python at least crashed. A
 * silent no-op on a rule declaration is the vacuity class -- the contract reads as enforced
 * and enforces nothing.
 *
 * No new normative semantics were invented to close it: the meta-schema already rejected
 * every shape below.
 */
function declaredRules(schema: JsonRecord, schemaRef: string): CrossFieldRule[] {
  const declared = schema['x-datacompany-cross-field'];
  if (declared === undefined) {
    return [];
  }
  const where = `${schemaRef}: x-datacompany-cross-field`;
  if (!Array.isArray(declared)) {
    throw new CrossFieldError(
      `${where} must be an array of rule objects, not a JSON ${jsonType(declared)}. A ` +
        'non-array declaration is not a rule this engine can evaluate.',
    );
  }
  if (declared.length === 0) {
    throw new CrossFieldError(
      `${where} is empty. An empty rule list is indistinguishable from a rule deleted by ` +
        "mistake, so it is rejected rather than treated as 'no rules'.",
    );
  }
  declared.forEach((rule, index) => {
    validateRule(rule, `${where}/${index}`);
  });
  return declared as CrossFieldRule[];
}

/** Throw `CrossFieldError` unless `rule` is a well-formed rule object. */
function validateRule(rule: unknown, where: string): void {
  if (!isPlainObject(rule)) {
    throw new CrossFieldError(`${where} is not a rule object, but a JSON ${jsonType(rule)}.`);
  }
  const kind = rule['rule'];
  if (typeof kind !== 'string' || !Object.hasOwn(OPERANDS, kind)) {
    throw new CrossFieldError(
      `${where} declares rule ${jsonText(kind)}, which is not a released cross-field ` +
        `operator (${Object.keys(OPERANDS).sort().join(', ')}).`,
    );
  }
  const scope = rule['scope'] ?? SCOPE_ABSOLUTE;
  if (scope !== SCOPE_ABSOLUTE && scope !== SCOPE_RELATIVE) {
    throw new CrossFieldError(
      `${where} declares scope ${jsonText(scope)}; the released scopes are ` +
        `${jsonText(SCOPE_ABSOLUTE)} and ${jsonText(SCOPE_RELATIVE)}.`,
    );
  }
  if (Object.hasOwn(rule, 'name') && (typeof rule['name'] !== 'string' || rule['name'] === '')) {
    throw new CrossFieldError(`${where} declares a name that is not a non-empty string.`);
  }
  const { required, optional } = OPERANDS[kind];
  const missing = required.filter((member) => !Object.hasOwn(rule, member)).sort();
  if (missing.length > 0) {
    throw new CrossFieldError(
      `${where} is a ${jsonText(kind)} rule missing the operand(s) ` +
        `${missing.join(', ')}, which the evaluator indexes directly.`,
    );
  }
  const known = new Set<string>([...COMMON_MEMBERS, ...required, ...optional]);
  const unknown = Object.keys(rule)
    .filter((member) => !known.has(member))
    .sort();
  if (unknown.length > 0) {
    throw new CrossFieldError(
      `${where} carries ${unknown.join(', ')}, which ${jsonText(kind)} does not read. ` +
        'An operand belonging to a different operator is silently ignored, so it is ' +
        'rejected here.',
    );
  }
  const present = [...required, ...optional.filter((member) => Object.hasOwn(rule, member))];
  for (const member of present.sort()) {
    const operand = rule[member];
    if (typeof operand !== 'string' || operand.length < 2 || !POINTER.test(operand)) {
      throw new CrossFieldError(
        `${where} operand ${member}=${jsonText(operand)} is not an RFC 6901 pointer ` +
          "of the released form (a non-empty sequence of '/'-prefixed reference tokens).",
      );
    }
  }
}

const collectionCache = new Map<string, readonly CrossFieldRuleSite[]>();

function collect(schemaRef: string): readonly CrossFieldRuleSite[] {
  const cached = collectionCache.get(schemaRef);
  if (cached !== undefined) {
    return cached;
  }
  const sites: CrossFieldRuleSite[] = [];
  const seen = new Set<string>();

  function walk(
    schema: unknown,
    refs: ReadonlySet<string>,
    baseId: string,
    steps: readonly Step[],
    blocked: string | null,
  ): void {
    if (!isPlainObject(schema)) {
      return;
    }
    const id = schema['$id'];
    const currentBase = typeof id === 'string' ? id : baseId;
    for (const rule of declaredRules(schema, schemaRef)) {
      const label = rule.name ?? rule.rule;
      if (blocked !== null) {
        throw new CrossFieldError(
          `${schemaRef}: released cross-field rule ${JSON.stringify(label)} is declared ` +
            `under '${blocked}', ${BLOCKED_KEYWORD_REASON[blocked]}`,
        );
      }
      if (steps.length > 0 && rule.scope !== SCOPE_RELATIVE) {
        throw new CrossFieldError(
          `${schemaRef}: released cross-field rule ${JSON.stringify(label)} is declared ` +
            'below a child keyword, but released rule pointers are instance-root-absolute, ' +
            'so this engine cannot evaluate it. Declare the rule at the root of the ' +
            'composed schema with absolute pointers instead, or declare it "scope": ' +
            '"relative" to resolve its operands against the location it is reached at.',
        );
      }
      const marker = `${identityMarker(rule)}\x00${JSON.stringify(steps)}`;
      if (!seen.has(marker)) {
        seen.add(marker);
        sites.push({ rule, steps });
      }
    }
    const ref = schema['$ref'];
    if (typeof ref === 'string') {
      const [target, targetBase] = resolveRef(ref, currentBase);
      const absolute = ref.startsWith('#') ? `${targetBase}${ref}` : ref;
      if (!refs.has(absolute)) {
        walk(target, new Set([...refs, absolute]), targetBase, steps, blocked);
      }
    }
    for (const branch of APPLICATOR_BRANCHES) {
      const node = schema[branch];
      if (Array.isArray(node)) {
        for (const subschema of node) {
          walk(subschema, refs, currentBase, steps, blocked);
        }
      } else if (isPlainObject(node)) {
        walk(node, refs, currentBase, steps, blocked);
      }
    }

    // Each child keyword below moves the instance location, so it extends the step plan.
    const named = schema['properties'];
    if (isPlainObject(named)) {
      for (const [member, subschema] of Object.entries(named)) {
        walk(subschema, refs, currentBase, [...steps, ['key', member]], blocked);
      }
    }
    const patterned = schema['patternProperties'];
    if (isPlainObject(patterned)) {
      for (const [pattern, subschema] of Object.entries(patterned)) {
        walk(subschema, refs, currentBase, [...steps, ['pattern', pattern]], blocked);
      }
    }
    const prefix = schema['prefixItems'];
    if (Array.isArray(prefix)) {
      prefix.forEach((subschema, index) => {
        walk(subschema, refs, currentBase, [...steps, ['index', index]], blocked);
      });
    }
    const rest = schema['items'];
    if (isPlainObject(rest)) {
      const start = Array.isArray(prefix) ? prefix.length : 0;
      walk(rest, refs, currentBase, [...steps, ['items', start]], blocked);
    } else if (Array.isArray(rest)) {
      // The 2019-09 tuple form. A 2020-12 validator applies nothing here, so a rule inside is
      // dropped by the specification; blocked rather than ignored.
      for (const subschema of rest) {
        walk(subschema, refs, currentBase, steps, blocked ?? 'items');
      }
    }
    const extra = schema['additionalProperties'];
    if (isPlainObject(extra)) {
      const step: Step = [
        'additional',
        isPlainObject(named) ? Object.keys(named) : [],
        isPlainObject(patterned) ? Object.keys(patterned) : [],
      ];
      walk(extra, refs, currentBase, [...steps, step], blocked);
    }
    // Every keyword below blocks the rules beneath it. The outermost blocking keyword wins,
    // so the diagnostic names the one an author would have to move the rule out of first
    // rather than an inner keyword they never wrote.
    for (const keyword of [
      ...UNLOCATABLE_KEYWORDS,
      ...LEGACY_SCHEMA_KEYWORDS,
      ...UNCOLLECTED_SCHEMA_KEYWORDS,
    ]) {
      const node = schema[keyword];
      if (isPlainObject(node)) {
        walk(node, refs, currentBase, steps, blocked ?? keyword);
      }
    }
    for (const keyword of UNCOLLECTED_MAP_KEYWORDS) {
      const node = schema[keyword];
      if (isPlainObject(node)) {
        for (const subschema of Object.values(node)) {
          walk(subschema, refs, currentBase, steps, blocked ?? keyword);
        }
      }
    }
  }

  const base = schemaRef.split('#')[0];
  walk(resolvePointer(schemaRef), new Set([schemaRef]), base, [], null);
  const frozen = Object.freeze(sites);
  collectionCache.set(schemaRef, frozen);
  return frozen;
}

/**
 * Every evaluable rule reachable from `schemaRef`, paired with the step plan locating it.
 *
 * A rule declared at the composed root carries an empty plan and is evaluated once against
 * the instance root. A `"scope": "relative"` rule reached through a child keyword carries the
 * plan that locates it, and is evaluated once per instance location that plan addresses.
 */
export function collectCrossFieldRuleSites(schemaRef: string): CrossFieldRuleSite[] {
  return [...collect(schemaRef)];
}

/**
 * Collect every distinct evaluable `x-datacompany-cross-field` rule under `schemaRef`.
 *
 * A rule's operand pointers are RFC 6901 pointers resolved against a base, and `scope`
 * chooses the base (D3, option B; mirrored from Python):
 *
 * - `absolute` -- the default, and the meaning of every rule released before D3 -- binds them
 *   to the INSTANCE root, so such a rule is only evaluable where it is reached without
 *   changing the instance location. Reached below a child keyword it would silently assert a
 *   proposition about the wrong object, so the collector throws instead.
 * - `relative` binds them to the location the rule was reached at. At a document root the two
 *   readings coincide, which is why adding `scope` left every released rule's meaning
 *   unchanged; below a child keyword the rule is evaluated once per addressed location.
 *
 * Neither reading is available under `contains`, `propertyNames` or `contentSchema`, which
 * have no single instance location; a rule there fails closed at any scope. A rule under
 * `if`, `not`, `dependentSchemas`, `unevaluatedProperties` or `unevaluatedItems` fails closed
 * too, for the different reason that this collector does not descend into them: it would
 * otherwise be dropped in silence. A rule under `additionalItems` or an array-valued `items`
 * fails closed for a third reason -- those are not 2020-12 keywords, so the specification
 * itself applies nothing there. See `UNCOLLECTED_SCHEMA_KEYWORDS`, `UNLOCATABLE_KEYWORDS` and
 * `LEGACY_SCHEMA_KEYWORDS`; `$defs`/`definitions` are the deliberate non-blocking case.
 *
 * This returns the distinct rules -- one rule reached at several locations is one entry here
 * and several entries in `collectCrossFieldRuleSites`.
 */
export function collectCrossFieldRules(schemaRef: string): CrossFieldRule[] {
  const distinct: CrossFieldRule[] = [];
  const seen = new Set<string>();
  for (const { rule } of collect(schemaRef)) {
    const marker = identityMarker(rule);
    if (!seen.has(marker)) {
      seen.add(marker);
      distinct.push(rule);
    }
  }
  return distinct;
}

/** Return the failures of every released cross-field rule declared by `schemaRef`. */
export function evaluateCrossFieldRules(instance: unknown, schemaRef: string): string[] {
  const failures: string[] = [];
  for (const { rule, steps } of collect(schemaRef)) {
    for (const base of locations(instance, steps)) {
      failures.push(...evaluateAt(instance, rule, base));
    }
  }
  return failures;
}

/**
 * Evaluate one rule at one instance location.
 *
 * Every operand pointer is rendered into the failure text joined to `base`, so a rule at the
 * instance root (`base === ''`) produces exactly the text it produced before D3 -- the
 * released fixtures pin that text through `expected_error_contains` -- and the same rule at a
 * nested location names the full absolute path it actually looked at, which is what makes N
 * failures under `items` distinguishable from each other.
 */
function evaluateAt(instance: unknown, rule: CrossFieldRule, base: string): string[] {
  const kind = rule.rule;
  const name = String(rule.name ?? kind);
  if (kind === 'half_open_interval') {
    return checkHalfOpenInterval(instance, rule, name, base);
  }
  if (kind === 'equal') {
    const leftAt = `${base}${String(rule['left'])}`;
    const rightAt = `${base}${String(rule['right'])}`;
    const left = pointerInto(instance, leftAt);
    const right = pointerInto(instance, rightAt);
    if (left === MISSING || right === MISSING) {
      return [`${name}: ${leftAt} and ${rightAt} must both be present and equal`];
    }
    const bad = uncomparable(
      name,
      [
        [leftAt, left],
        [rightAt, right],
      ],
      'equality',
    );
    if (bad.length > 0) {
      return bad;
    }
    if (!sameValue(left, right)) {
      return [`${name}: ${leftAt} and ${rightAt} must both be present and equal`];
    }
    return [];
  }
  if (kind === 'equal_when_both_present') {
    const leftAt = `${base}${String(rule['left'])}`;
    const rightAt = `${base}${String(rule['right'])}`;
    const left = pointerInto(instance, leftAt);
    const right = pointerInto(instance, rightAt);
    if (left === MISSING || right === MISSING) {
      return [];
    }
    const bad = uncomparable(
      name,
      [
        [leftAt, left],
        [rightAt, right],
      ],
      'equality',
    );
    if (bad.length > 0) {
      return bad;
    }
    if (!sameValue(left, right)) {
      return [`${name}: ${leftAt} and ${rightAt} must be equal when both present`];
    }
    return [];
  }
  if (kind === 'unique_by') {
    return checkUniqueBy(instance, rule, name, base);
  }
  if (kind === 'disjoint') {
    return checkDisjoint(instance, rule, name, base);
  }
  throw new CrossFieldError(`unknown released cross-field rule ${jsonText(kind)}`);
}

/**
 * `[from, to)` must be non-empty, with an omitted `to` meaning positive infinity.
 *
 * Bounds are compared as parsed instants, never as raw strings. The released
 * `rfc3339_utc_z` representation permits fractional seconds, and `.` (0x2E) sorts before
 * `Z` (0x5A), so a lexicographic comparison rejected the valid interval
 * `[…T00:00:00Z, …T00:00:00.5Z)` and ACCEPTED the inverted `[…T00:00:00.5Z, …T00:00:00Z)`.
 * On the flagship non-empty-interval invariant, that second half is a fail-open gate. A
 * JavaScript port comparing with `>` would fail open in the same two ways, so this is the
 * single place where doing the obviously-easy thing diverges from the contract.
 */
function checkHalfOpenInterval(
  instance: unknown,
  rule: CrossFieldRule,
  name: string,
  base = '',
): string[] {
  const fromPointer = `${base}${String(rule['from'])}`;
  const toPointer = `${base}${String(rule['to'])}`;
  const start = pointerInto(instance, fromPointer);
  const end = pointerInto(instance, toPointer);
  if (start === MISSING) {
    return [`${name}: ${fromPointer} is required to bound the interval`];
  }
  // Checked before the omitted-upper-bound shortcut: an explicit null lower bound is
  // invalid whether or not an upper bound happens to be present.
  if (start === null) {
    return [`${name}: null is not a released encoding for an interval bound`];
  }
  const lower = instant(start);
  if (end === MISSING) {
    // An omitted upper bound means positive infinity, but the lower bound still has to be a
    // released instant for the interval to mean anything at all.
    return unparseable(name, [[fromPointer, start, lower]]);
  }
  if (end === null) {
    return [`${name}: null is not a released encoding for an interval bound`];
  }
  const upper = instant(end);
  const bad = unparseable(name, [
    [fromPointer, start, lower],
    [toPointer, end, upper],
  ]);
  if (bad.length > 0 || lower === null || upper === null) {
    return bad;
  }
  if (compareInstants(upper, lower) <= 0) {
    return [
      `${name}: interval [${String(start)}, ${String(end)}) is empty or inverted; a half-open ` +
        'interval must be non-empty',
    ];
  }
  return [];
}

function unparseable(
  name: string,
  bounds: readonly (readonly [string, unknown, Instant | null])[],
): string[] {
  return bounds
    .filter(([, , parsed]) => parsed === null)
    .map(
      ([pointer, value]) =>
        `${name}: ${pointer} is ${identityMarker(value)}, which is not a released ` +
        'rfc3339_utc_z instant, so the interval cannot be compared',
    );
}

/**
 * No two members of the array at `at` may share a value at the member key.
 *
 * `uniqueItems` cannot express this: two declarations for the same pointer that differ in
 * any other member are distinct objects and pass it.
 */
function checkUniqueBy(
  instance: unknown,
  rule: CrossFieldRule,
  name: string,
  base = '',
): string[] {
  const at = `${base}${String(rule['at'])}`;
  const members = pointerInto(instance, at);
  if (!Array.isArray(members)) {
    // Fail loudly. Returning [] made a missing, null or non-list target read as "the
    // uniqueness rule holds", and `checkCrossFieldRules` is a public, schema-independent
    // entry point, so nothing else was checking.
    return [absentTarget(name, at, members)];
  }
  const keyPointer = typeof rule['key'] === 'string' ? rule['key'] : undefined;
  const seen = new Map<string, number>();
  const failures: string[] = [];
  members.forEach((member, index) => {
    const value = memberKey(member, keyPointer);
    if (value === MISSING) {
      failures.push(missingMemberKey(name, at, index, 'uniqueness', keyPointer));
      return;
    }
    if (!comparable(value)) {
      failures.push(uncomparableText(name, `${at}/${index}`, 'uniqueness'));
      return;
    }
    const marker = identityMarker(value);
    const first = seen.get(marker);
    if (first !== undefined) {
      failures.push(
        `${name}: ${at}/${first} and ${at}/${index} both declare ${marker}; a pointer may be ` +
          'declared at most once',
      );
      return;
    }
    seen.set(marker, index);
  });
  return failures;
}

/**
 * Name a member of a set-like array that does not carry the key the rule compares by.
 *
 * Shared by `unique_by` and `disjoint` so the two cannot drift apart again: they used to
 * disagree about whether this is a fact worth reporting at all (EXTENSIONS.md section 4.5),
 * and the way that asymmetry survived is that each spelled its own answer in its own branch.
 *
 * `keyPointer` is always a declared pointer STRING here and never `undefined`: a member can
 * only fail to carry a key that was named, because `memberKey` with no pointer returns the
 * member itself and is never `MISSING`. That is load-bearing for parity rather than
 * cosmetic -- `String(undefined)` is `undefined` here and `None` in Python, for the same
 * failure of the same rule. `?? ''` rather than `String(...)` so that a hypothetical
 * unreachable call cannot reintroduce the divergence in either direction.
 */
function missingMemberKey(
  name: string,
  at: string,
  index: number,
  role: 'uniqueness' | 'disjointness',
  keyPointer: string | undefined,
): string {
  return `${name}: ${at}/${index} does not carry the ${role} key ${keyPointer ?? ''}`;
}

function absentTarget(name: string, pointer: string, value: unknown): string {
  const rendered = value === MISSING ? 'absent' : identityMarker(value);
  return (
    `${name}: ${pointer} is ${rendered}, not an array, so the rule cannot be evaluated; a ` +
    'released cross-field rule names a location that must be there'
  );
}

/**
 * The two named arrays may not share a value; each side may name a member key.
 *
 * A member that does not carry its side's declared key is a REPORTED FAILURE, exactly as in
 * `unique_by` step 2, and this is the whole of what EXTENSIONS.md section 4.5 recorded as
 * open. It used to be a silent SKIP on both sides in both engines: a right member of
 * `{"nope": 1}` under `right_key: "/p"` produced no failure at all, so "the two sets are
 * disjoint" could be true by vacuity, one member at a time -- while the structurally
 * identical question in `unique_by` was answered loudly.
 *
 * Nothing normative had to be invented to pick a side. `hashView` already decided the same
 * question for the same shape of data, fail-closed, in released code: it throws
 * `MissingOrderKeyError` because every member of a set-like array must carry its whole
 * released order key, and an absent key is not the same fact as a shared one.
 *
 * A member whose key is missing contributes no value to the comparison either -- it has none
 * to contribute -- so the left set is still built from the members that do carry the key. The
 * change is that the ones that do not are now named.
 */
function checkDisjoint(
  instance: unknown,
  rule: CrossFieldRule,
  name: string,
  base = '',
): string[] {
  const leftPointer = `${base}${String(rule['left'])}`;
  const rightPointer = `${base}${String(rule['right'])}`;
  const left = pointerInto(instance, leftPointer);
  const right = pointerInto(instance, rightPointer);
  // Same fail-open as unique_by: a missing or non-list side made "the two sets are
  // disjoint" true by vacuity rather than by evidence.
  const absent = (
    [
      [leftPointer, left],
      [rightPointer, right],
    ] as const
  )
    .filter(([, value]) => !Array.isArray(value))
    .map(([pointer, value]) => absentTarget(name, pointer, value));
  if (absent.length > 0) {
    return absent;
  }
  const leftKey = typeof rule['left_key'] === 'string' ? rule['left_key'] : undefined;
  const rightKey = typeof rule['right_key'] === 'string' ? rule['right_key'] : undefined;
  const failures: string[] = [];
  const leftValues = new Set<string>();
  (left as unknown[]).forEach((member, index) => {
    const value = memberKey(member, leftKey);
    if (value === MISSING) {
      failures.push(missingMemberKey(name, leftPointer, index, 'disjointness', leftKey));
      return;
    }
    if (!comparable(value)) {
      failures.push(uncomparableText(name, `${leftPointer}/${index}`, 'disjointness'));
      return;
    }
    leftValues.add(identityMarker(value));
  });
  (right as unknown[]).forEach((member, index) => {
    const value = memberKey(member, rightKey);
    if (value === MISSING) {
      failures.push(missingMemberKey(name, rightPointer, index, 'disjointness', rightKey));
      return;
    }
    if (!comparable(value)) {
      failures.push(uncomparableText(name, `${rightPointer}/${index}`, 'disjointness'));
      return;
    }
    const marker = identityMarker(value);
    if (leftValues.has(marker)) {
      failures.push(
        `${name}: ${marker} appears in both ${leftPointer} and ${rightPointer}/${index}; the ` +
          'two sets must be disjoint',
      );
    }
  });
  return failures;
}

/** Drop the memoized rule collections. Test-only. */
export function resetCrossFieldCache(): void {
  collectionCache.clear();
}

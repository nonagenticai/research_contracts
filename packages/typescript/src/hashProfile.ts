/**
 * Derivation and validation of the released hash-view manifest (`canonical-hash-profile.v1`).
 *
 * TypeScript port of `src/research_contracts/canonical/hash_profile.py`.
 *
 * The manifest is not hand-maintained prose: it is DERIVED from the schema annotations
 * (`x-datacompany-hash-excluded`, `x-datacompany-hash-exclusion-reason`, `x-datacompany-array`,
 * `x-datacompany-hash-opaque`, `x-datacompany-hash-declaration-only`) by walking the fully composed
 * schema. A released manifest
 * committed alongside a schema is therefore checkable against the schema itself, which is
 * what makes "adding or changing a path, normalization rule or collection kind is a schema
 * compatibility change" enforceable.
 *
 * Pointers use RFC 6901 syntax with `-` as the array-element token, for example
 * `/pack_refs/-/resolved_at`.
 */

import { HashProfileError, UnknownExclusionError } from './errors';
import type { ArrayDeclaration, ExcludedPointer, HashProfile } from './hashView';
import { escapeToken } from './hashView';
import { canonicalize, compareBytes } from './jcs';
import { resolvePointer, resolveRef } from './registry';
import { jsonText, jsonType } from './rendering';
import { validateInstance } from './validation';

export const HASH_PROFILE_SCHEMA_REF = 'urn:datacompany:canonical-hash-profile:1';

/**
 * The version of the derivation rules THIS engine implements. Mirrors
 * `hash_profile.DERIVATION_PROFILE_VERSION`; the two MUST move together, because a manifest
 * derived by one engine is verified by the other.
 *
 * `profile_version` names the rule set that produced a manifest, not a free label on it. A
 * manifest declaring some other version was produced by rules this engine does not
 * implement, so this engine's derivation is not evidence about it either way.
 *
 * Before this constant existed, `validateProfileAgainstSchema` passed the SUPPLIED manifest's
 * own `profile_version` straight back into `deriveHashProfile`, so the agreement check built
 * the expected value from the value under test and could never fire — in either language.
 * `EXTENSIONS.md` §5.2 prescribes "change both together with a `profile_version` bump" as the
 * remedy for the inconsistent exclusion cascade, and that bump was enforced nowhere.
 *
 * **1 -> 2 on 2026-08-04.** §5.2's remedy was taken: the exclusion cascade now filters
 * `arrays` by PREFIX like the other two members instead of by exact match. The observable
 * delta on the committed corpus is zero, measured with a positive control, and that is
 * deliberately not a reason to leave the number alone — `profile_version` names the RULE
 * SET, and the rule set changed.
 */
export const DERIVATION_PROFILE_VERSION = 2;

const APPLICATOR_BRANCHES = ['allOf', 'anyOf', 'oneOf', 'then', 'else'] as const;

/**
 * The only manifest members a domain schema may contribute to at the envelope's declared
 * composition point. Everything else -- exclusions, opaque subtrees, and every
 * serialization/digest rule -- is a property of the released envelope, not of a consumer.
 */
export const EXTENSIBLE_PROFILE_KEYS: ReadonlySet<string> = new Set([
  'included_pointers',
  'arrays',
]);

type JsonRecord = Record<string, unknown>;

let exclusionReasonCache: ReadonlySet<string> | null = null;

/** The released closed set of hash-exclusion reasons, read from the schema itself. */
export function exclusionReasons(): ReadonlySet<string> {
  if (exclusionReasonCache !== null) {
    return exclusionReasonCache;
  }
  const node = resolvePointer(`${HASH_PROFILE_SCHEMA_REF}#/$defs/exclusion_reason`) as JsonRecord;
  const values = node['enum'];
  if (!Array.isArray(values)) {
    throw new HashProfileError(
      `${HASH_PROFILE_SCHEMA_REF}#/$defs/exclusion_reason does not declare an enum`,
    );
  }
  exclusionReasonCache = new Set(values.map((value) => String(value)));
  return exclusionReasonCache;
}

/** Python's `sorted()` on strings is Unicode CODE POINT order. Stated, not assumed. */
export function compareCodePoints(left: string, right: string): number {
  const a = Array.from(left);
  const b = Array.from(right);
  const shared = Math.min(a.length, b.length);
  for (let index = 0; index < shared; index += 1) {
    const x = a[index].codePointAt(0) ?? 0;
    const y = b[index].codePointAt(0) ?? 0;
    if (x !== y) {
      return x < y ? -1 : 1;
    }
  }
  return a.length - b.length;
}

function sortedStrings(values: Iterable<string>): string[] {
  return [...values].sort(compareCodePoints);
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Order-insensitive structural equality, matching Python's `==` on JSON-shaped data. */
export function deepEqual(left: unknown, right: unknown): boolean {
  if (left === right) {
    return true;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
      return false;
    }
    return left.every((item, index) => deepEqual(item, right[index]));
  }
  if (isRecord(left) && isRecord(right)) {
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    if (leftKeys.length !== rightKeys.length) {
      return false;
    }
    return leftKeys.every((key) => Object.hasOwn(right, key) && deepEqual(left[key], right[key]));
  }
  return false;
}

/**
 * A language-neutral, member-order-independent sort key for a manifest entry.
 *
 * Mirrors `_canonical_order` in `hash_profile.py`: RFC 8785 canonical bytes with binary
 * floats permitted, because this key orders arbitrary manifest values and never enters a
 * hashed input.
 */
function canonicalOrder(value: unknown): Uint8Array {
  return canonicalize(value, { allowBinaryFloat: true });
}

/** A deterministic, key-order-independent rendering, used only in error messages. */
function stableKey(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableKey).join(',')}]`;
  }
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort(compareCodePoints)
      .map((key) => `${JSON.stringify(key)}:${stableKey(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

/**
 * The name every annotation in this vocabulary starts with. A member outside this prefix
 * belongs to somebody else and is not this engine's business: document 16 section 2.5
 * requires unknown extension values to be PRESERVED, and they are. What
 * `requireReleasedAnnotations` refuses is a name INSIDE the namespace this document owns,
 * at authoring time, which is the only place preservation and enforcement do not collide.
 */
const ANNOTATION_PREFIX = 'x-datacompany-';

/**
 * The released `x-datacompany-*` names, re-stated from
 * `schemas/meta/datacompany-extension-vocabulary.v1.schema.json` `#/$defs/vocabulary`.
 *
 * Mirrors Python's `hash_profile._VOCABULARY`, which `tests/test_extension_vocabulary.py`
 * cross-checks against the meta-schema in BOTH directions -- exactly as decision F does for
 * the cross-field operand table. Re-stated rather than read at runtime for the same reason:
 * the meta-schema is a JSON Schema document, and consulting it AS one would mean this port
 * shipping a validator to derive a manifest.
 *
 * `x-datacompany-composition-point` was in this set and read by NO code in either language until
 * 2026-08-04. It is now read twice: `requireReleasedCompositionPoint` refuses a value that
 * names no `$defs` entry of the document, and `mergeProfileExtensions` refuses an extension
 * offered to an envelope that declares no composition point at all.
 */
const VOCABULARY: readonly string[] = [
  'x-datacompany-array',
  'x-datacompany-composition-point',
  'x-datacompany-cross-field',
  'x-datacompany-hash-declaration-only',
  'x-datacompany-hash-excluded',
  'x-datacompany-hash-exclusion-reason',
  'x-datacompany-hash-opaque',
];

/**
 * The members an `x-datacompany-array` value may carry, re-stated from the meta-schema's
 * `#/$defs/array_annotation`. Only the member NAMES: what `kind` and `order_key` may CONTAIN
 * is `canonical-hash-profile.v1`'s `array_declaration`, which the derived manifest is
 * validated against anyway.
 */
/**
 * The three annotations both engines read with an IDENTITY comparison (`=== true` /
 * `is True`), which is why the meta-schema gives all three `const: true`: every other value
 * is a silent no-op that leaves the path exactly as it was.
 */
const IDENTITY_COMPARED_FLAGS: readonly string[] = [
  'x-datacompany-hash-declaration-only',
  'x-datacompany-hash-excluded',
  'x-datacompany-hash-opaque',
];

const ARRAY_REQUIRED_MEMBERS: readonly string[] = ['kind'];
const ARRAY_OPTIONAL_MEMBERS: readonly string[] = ['order_key'];

/**
 * Refuse the authoring-path fail-opens of `EXTENSIONS.md` §7.1-§7.4.
 *
 * Mirrors `hash_profile._require_released_annotations`, message text INCLUDED and asserted
 * against Python's own source by the parity suites. Every shape below produced a WEAKER
 * canonical hash view with no error anywhere: the derivation read the annotations it
 * recognised, ignored the rest, and returned a manifest indistinguishable from one for a
 * schema that had never carried them.
 *
 * - §7.1 an unregistered name in the `x-datacompany-` namespace (`x-datacompany-hash-exclude` is one
 *   letter short of an exclusion, survives every round trip, and is read by nothing).
 * - §7.2 `x-datacompany-hash-exclusion-reason` with no `x-datacompany-hash-excluded` beside it. Only
 *   this direction: the flag WITHOUT a reason already fails closed as `UnknownExclusionError`.
 * - §7.3 a non-object `x-datacompany-array`, dropped by the `isRecord` check exactly as Python
 *   dropped it on `isinstance(dict)`.
 * - §7.4 an `x-datacompany-array` carrying its own `pointer`, which the spread puts LAST so it
 *   re-targets the declaration at an unrelated path and still yields a valid entry.
 *
 * Scope, stated rather than implied: this runs on the nodes the DERIVATION WALK reaches. A
 * malformed annotation under `if`, `contains` or an unreferenced `$defs` entry is not reached
 * here and is not claimed to be; the corpus-wide obligation is the meta-schema sweep in
 * `tests/test_extension_vocabulary.py`, which is lexical and pins its node count.
 */
/**
 * The only fragment shape a composition point may carry. Re-stated from the meta-schema's
 * `#/$defs/composition_point` pattern, and deliberately only the PREFIX: what may follow it
 * is decided by RESOLVING the pointer against the document, which is stronger than the
 * pattern and needs no second copy of it.
 */
const COMPOSITION_POINT_PREFIX = '#/$defs/';

/**
 * Refuse an `x-datacompany-composition-point` that names nothing (`EXTENSIONS.md` §6.4).
 *
 * Mirrors `hash_profile._require_released_composition_point`, message text INCLUDED. Until
 * 2026-08-04 this annotation was read by no code in either language: `42`, `null` and
 * `"not-a-pointer"` were all accepted with no effect whatsoever, and so was a one-character
 * typo in a real pointer.
 *
 * Resolution, not a pattern match, is the check: the value is a document-relative `$ref`
 * fragment, so the honest question is whether it resolves, and `resolvePointer` is the same
 * resolver the derivation walk uses. A pattern would accept `#/$defs/domian_extension`.
 *
 * `baseId` rather than `schemaRef`: the walk carries the `$id` of the document the node
 * actually belongs to, and a `$ref` into another released schema reaches nodes whose
 * `#/$defs/...` are relative to THAT document.
 */
function requireReleasedCompositionPoint(
  point: unknown,
  pointer: string,
  schemaRef: string,
  baseId: string,
): void {
  if (typeof point !== 'string' || !point.startsWith(COMPOSITION_POINT_PREFIX)) {
    throw new HashProfileError(
      `${schemaRef}: ${jsonText(pointer)} declares x-datacompany-composition-point as ` +
        `${jsonText(point)}. A composition point names the $defs entry at which a domain ` +
        `schema attaches, so it must be a document-relative pointer beginning ` +
        `${jsonText(COMPOSITION_POINT_PREFIX)}. Anything else names nothing and leaves the ` +
        'envelope with no stated extension point at all.',
    );
  }
  try {
    resolvePointer(`${baseId}${point}`);
  } catch {
    // The resolver's own message is deliberately NOT interpolated. `registry` renders its
    // diagnostics with `!r` in Python and with bare interpolation here, so embedding it
    // would make this refusal differ between the two engines for the same schema -- the
    // exact divergence §9 item 13 exists to forbid.
    throw new HashProfileError(
      `${schemaRef}: ${jsonText(pointer)} declares the composition point ` +
        `${jsonText(point)}, which resolves to no $defs entry of ${baseId}. The annotation ` +
        "is the envelope's own statement of where a consumer may attach, so a name that " +
        'resolves to nothing invites a domain schema to extend a point that does not exist.',
    );
  }
}

function requireReleasedAnnotations(
  schema: JsonRecord,
  pointer: string,
  schemaRef: string,
  baseId: string,
): void {
  const names = Object.keys(schema).filter((name) => name.startsWith(ANNOTATION_PREFIX));
  if (names.length === 0) {
    return;
  }

  const unregistered = sortedStrings(names.filter((name) => !VOCABULARY.includes(name)));
  if (unregistered.length > 0) {
    throw new HashProfileError(
      `${schemaRef}: ${jsonText(pointer)} carries ${jsonText(unregistered)}, which is not a ` +
        `released x-datacompany-* annotation. The released vocabulary is ` +
        `${jsonText(sortedStrings(VOCABULARY))}. A name outside it is preserved on round ` +
        'trip and read by nothing, so the hash view is derived as though the annotation had ' +
        'never been written.',
    );
  }

  // BEFORE the pairing check below, so that `x-datacompany-hash-excluded: false` beside a valid
  // reason is diagnosed as the no-op flag it is rather than as a pairing fault.
  for (const flag of IDENTITY_COMPARED_FLAGS) {
    if (Object.hasOwn(schema, flag) && schema[flag] !== true) {
      throw new HashProfileError(
        `${schemaRef}: ${jsonText(pointer)} declares ${flag} as ${jsonText(schema[flag])}. ` +
          `All three of ${jsonText(sortedStrings(IDENTITY_COMPARED_FLAGS))} are read with ` +
          'an identity comparison, so every value but the literal true is a silent no-op ' +
          'that leaves the path exactly as it was: false beside a valid exclusion reason ' +
          'hashes the member it reads as excluding. Write true, or omit the annotation.',
      );
    }
  }

  if (
    Object.hasOwn(schema, 'x-datacompany-hash-declaration-only') &&
    Object.hasOwn(schema, 'x-datacompany-hash-excluded')
  ) {
    throw new HashProfileError(
      `${schemaRef}: ${jsonText(pointer)} carries x-datacompany-hash-declaration-only AND ` +
        'x-datacompany-hash-excluded. They are contradictory acts on one pointer: an exclusion ' +
        'REMOVES a path and records the removal in excluded_pointers with a released ' +
        'reason, while declaration-only asserts there is no path there to remove. Keep ' +
        'whichever one is meant.',
    );
  }

  if (
    Object.hasOwn(schema, 'x-datacompany-hash-exclusion-reason') &&
    !Object.hasOwn(schema, 'x-datacompany-hash-excluded')
  ) {
    throw new HashProfileError(
      `${schemaRef}: ${jsonText(pointer)} carries x-datacompany-hash-exclusion-reason with no ` +
        "x-datacompany-hash-excluded beside it. The reason is read only inside the flag's " +
        'branch, so on its own it excludes nothing: the path stays in the hash view and ' +
        'excluded_pointers records no exclusion. Add x-datacompany-hash-excluded: true, or ' +
        'delete the reason.',
    );
  }

  if (Object.hasOwn(schema, 'x-datacompany-array')) {
    requireReleasedArrayDeclaration(schema['x-datacompany-array'], pointer, schemaRef);
  }

  if (Object.hasOwn(schema, 'x-datacompany-composition-point')) {
    requireReleasedCompositionPoint(
      schema['x-datacompany-composition-point'],
      pointer,
      schemaRef,
      baseId,
    );
  }
}

/** The `x-datacompany-array` half of `requireReleasedAnnotations` (§7.3, §7.4). */
function requireReleasedArrayDeclaration(
  declaration: unknown,
  pointer: string,
  schemaRef: string,
): void {
  const where = `${schemaRef}: x-datacompany-array at ${jsonText(pointer)}`;
  if (!isRecord(declaration)) {
    throw new HashProfileError(
      `${where} is a JSON ${jsonType(declaration)}, not an object. A non-object declaration ` +
        'is dropped at derivation, so the array keeps undeclared collection semantics until ' +
        'some instance happens to carry it, and an optional array that no instance carries ' +
        'loses them indefinitely with no gate going red.',
    );
  }
  const known = new Set([...ARRAY_REQUIRED_MEMBERS, ...ARRAY_OPTIONAL_MEMBERS]);
  const unknown = sortedStrings(Object.keys(declaration).filter((name) => !known.has(name)));
  if (unknown.length > 0) {
    throw new HashProfileError(
      `${where} carries ${jsonText(unknown)}; a released array declaration carries ` +
        `${jsonText(sortedStrings(known))} only. The declaration is merged into the manifest ` +
        'entry AFTER the derived pointer, so a pointer member re-targets the declaration at ' +
        'an unrelated path and the entry that reaches the manifest is still a valid ' +
        'array_declaration.',
    );
  }
  const missing = sortedStrings(
    ARRAY_REQUIRED_MEMBERS.filter((name) => !Object.hasOwn(declaration, name)),
  );
  if (missing.length > 0) {
    throw new HashProfileError(
      `${where} declares no ${missing.join(', ')}. An array declaration that names no ` +
        'collection kind declares nothing, and canonical-hash-profile.v1 closes the set of ' +
        'kinds it may name.',
    );
  }
}

/** Collects hash-view pointers from a composed schema. */
class Walker {
  readonly schemaRef: string;

  constructor(schemaRef: string) {
    this.schemaRef = schemaRef;
  }

  readonly included = new Set<string>();
  readonly excluded = new Map<string, string>();
  readonly arrays = new Map<string, ArrayDeclaration>();
  readonly opaque = new Set<string>();
  /**
   * D9. Pointers whose schema node exists only to CARRY an annotation. Collected here and
   * subtracted in `deriveHashProfile`, deliberately NOT suppressed inline at the
   * `properties` loop: the flag can arrive through a `$ref` or through any of
   * `APPLICATOR_BRANCHES`, i.e. after the loop that added the pointer has already run, so
   * an inline check would be composition-order dependent and the two engines could derive
   * different manifests from the same schema depending on how it was written.
   */
  readonly declarationOnly = new Set<string>();
  /**
   * Every pointer at which the walk reaches an `x-datacompany-composition-point`.
   *
   * POINTERS ONLY, never the values, and deliberately: at pointer `''` a schema can reach
   * SEVERAL, because `allOf`/`$ref` composition does not advance the pointer.
   * `run-manifest:1` is a released example -- it declares `#/$defs/manifest_extension` and
   * composes `stable-identity:1`, which declares `#/$defs/domain_extension`, so both arrive
   * at `''`. Collecting values would invite a reader to pick one, and which one is a
   * normative question nobody has decided.
   */
  readonly compositionPoints = new Set<string>();

  walk(schema: unknown, pointer: string, seen: ReadonlySet<string>, baseId: string): void {
    if (typeof schema === 'boolean' || !isRecord(schema)) {
      return;
    }
    const nextBaseId = typeof schema['$id'] === 'string' ? schema['$id'] : baseId;

    // Before anything is READ off this node, so that a node's own malformed annotation is
    // diagnosed at the node rather than after a `$ref` has carried the walk somewhere else.
    //
    // `nextBaseId` is the `$id` of the document this node belongs to, already updated above
    // from the node's own `$id`. `x-datacompany-composition-point` is document-relative, so it
    // is the only correct base to resolve it against.
    requireReleasedAnnotations(schema, pointer, this.schemaRef, nextBaseId);

    const ref = schema['$ref'];
    if (typeof ref === 'string') {
      const [target, targetBase] = resolveRef(ref, nextBaseId);
      // Python's cycle key is the TUPLE `(ref, pointer)`. A JS Map key must be a
      // primitive, so the two halves are joined with a NUL -- written as the ESCAPE
      // `\0`, never as a raw 0x00 byte: a literal NUL makes git classify this source
      // file as BINARY, so it stops diffing and stops being reviewable. NUL is chosen
      // because no URN and no RFC 6901 pointer can contain one, so the join is
      // unambiguous exactly the way the Python tuple is.
      const key = `${ref.startsWith('#') ? `${targetBase}${ref}` : ref}\0${pointer}`;
      if (!seen.has(key)) {
        this.walk(target, pointer, new Set([...seen, key]), targetBase);
      }
    }

    if (schema['x-datacompany-hash-excluded'] === true) {
      const reason = schema['x-datacompany-hash-exclusion-reason'];
      if (typeof reason !== 'string' || !exclusionReasons().has(reason)) {
        throw new UnknownExclusionError(
          `${pointer}: hash exclusion reason ${JSON.stringify(reason)} is not in the released ` +
            `set ${JSON.stringify(sortedStrings(exclusionReasons()))}`,
        );
      }
      this.excluded.set(pointer, reason);
    }

    const arrayDeclaration = schema['x-datacompany-array'];
    if (arrayDeclaration !== undefined) {
      // An isRecord narrowing until §7.3 closed, and that narrowing WAS the fail-open: a
      // non-object declaration failed it and was dropped in silence, exactly as Python's
      // isinstance-against-dict test dropped it. `requireReleasedAnnotations` has already proven, for
      // this same node, that a present declaration is an object carrying only released
      // members, so the narrowing could no longer evaluate false.
      //
      // Python spreads the declaration AFTER the pointer (`{"pointer": p, **decl}`) and this
      // keeps that precedence. It used to be §7.4's mechanism; it is safe now because the
      // annotation can no longer carry a `pointer` member at all.
      this.arrays.set(pointer, { pointer, ...(arrayDeclaration as object) } as ArrayDeclaration);
    }

    if (schema['x-datacompany-hash-opaque'] === true) {
      this.opaque.add(pointer);
    }

    // Identity comparison, exactly like the two flags above: `false`, `0`, `1` and `"true"`
    // are silent no-ops in Python and must be silent no-ops here. A truthiness "fix" would
    // make this engine suppress a pointer Python still declares.
    if (schema['x-datacompany-hash-declaration-only'] === true) {
      this.declarationOnly.add(pointer);
    }

    // PRESENCE, matching `requireReleasedAnnotations` above, which has already proven this
    // node's value well formed. A `!== undefined` test would drop an explicit `null` -- a
    // declared-but-broken point -- from the diagnostic that exists to say where
    // declarations are.
    if (Object.hasOwn(schema, 'x-datacompany-composition-point')) {
      this.compositionPoints.add(pointer);
    }

    if (Object.hasOwn(schema, 'items') || Object.hasOwn(schema, 'prefixItems')) {
      this.included.add(pointer);
      const items = schema['items'];
      if (items !== undefined && items !== null) {
        this.walk(items, `${pointer}/-`, seen, nextBaseId);
      }
      const prefixItems = schema['prefixItems'];
      if (Array.isArray(prefixItems)) {
        prefixItems.forEach((itemSchema, index) => {
          this.walk(itemSchema, `${pointer}/${index}`, seen, nextBaseId);
        });
      }
    }

    const properties = schema['properties'];
    if (isRecord(properties)) {
      for (const name of Object.keys(properties)) {
        const childPointer = `${pointer}/${escapeToken(name)}`;
        this.included.add(childPointer);
        this.walk(properties[name], childPointer, seen, nextBaseId);
      }
    }

    for (const branch of APPLICATOR_BRANCHES) {
      const node = schema[branch];
      if (Array.isArray(node)) {
        for (const subschema of node) {
          this.walk(subschema, pointer, seen, nextBaseId);
        }
      } else if (isRecord(node)) {
        this.walk(node, pointer, seen, nextBaseId);
      }
    }
    // "if" contributes no hash-view path of its own: it only selects a branch. Walking it
    // would import its narrowing "properties" as if they were declared members.
  }
}

/**
 * Derive the released hash-view manifest for `schemaRef` from its own annotations.
 *
 * The derived `profile_version` is always `DERIVATION_PROFILE_VERSION`. The `DeriveOptions`
 * parameter that used to carry an override is gone: its only caller was
 * `validateProfileAgainstSchema`, which passed the manifest under test's own value, and a
 * deriver that can be asked to stamp a version whose rules it does not implement produces a
 * manifest its own validator must reject.
 */
/**
 * Reject `x-datacompany-hash-declaration-only` anywhere it does not mean anything (D9).
 *
 * Mirrors `hash_profile._require_declaration_only_is_legally_placed`, message text INCLUDED
 * and asserted byte for byte by the parity suites: a schema rejected by one engine and
 * accepted by the other is a cross-language split, and two engines that refuse it with
 * different words are a divergence a consumer cannot reconcile. Pointer lists are rendered
 * with `JSON.stringify`, which Python reproduces exactly via
 * `json.dumps(separators=..., ensure_ascii=False)`; `repr` would have written `['/a']`
 * against this file's `["/a"]`, and the default `ensure_ascii=True` would have written
 * `"/caf\u00e9"` against this file's `"/café"`.
 *
 * This function carries the PLACEMENT rules only, and reads the RAW walk. The
 * "declare none or declare all" rule is a separate function that deliberately runs LATER,
 * against the DERIVED `included_pointers` -- see
 * `requireDeclarationOnlyDoesNotCollideWithADeclaredMember`. Describing both as one check
 * against the raw walk is what refused the signed opaque payload.
 *
 * Two placement rules, and they fail differently.
 *
 * 1. STRICTLY under an `x-datacompany-hash-opaque` pointer, never AT one. Outside an opaque
 *    subtree the flag would silently remove a member from the hash view -- which is
 *    `x-datacompany-hash-excluded`'s job, and that one carries a released closed reason and
 *    records the removal in `excluded_pointers`. Allowing it AT the opaque node would let
 *    both annotations sit on one node, satisfying the guard trivially.
 * 2. An opaque subtree may not both declare a member and carry the flag. The released rule
 *    on `bitemporal-assertion:1` `/value` is "declare none or declare all": a surviving
 *    declared sibling revokes the opacity in `hashView`, after which the declaration-only
 *    pointer -- deliberately absent from `included_pointers` -- raises `UndeclaredPathError`
 *    at hash time, far from the schema that caused it.
 *
 * Evaluated against the RAW walk, not the derived manifest: this is a statement about where
 * the annotation may be WRITTEN, not about what survives the exclusion cascade.
 */
function requireDeclarationOnlyIsLegallyPlaced(walker: Walker, schemaRef: string): void {
  // Two independent conditions, because "strictly under some opaque ancestor" alone was
  // WALK-PAST-ABLE ONE LEVEL DEEPER. A node carrying BOTH annotations satisfies the
  // ancestor test whenever it happens to sit inside another opaque subtree, so `/value`
  // opaque with `/value/inner` opaque-and-flagged was accepted -- the very bypass the
  // ancestor test exists to prevent, merely relocated. The pair is refused on one node
  // unconditionally, which is also what the meta-schema's `declaration_only_pairing`
  // forbids per node, so the two gates now agree instead of only appearing to.
  const both = sortedStrings([...walker.declarationOnly].filter((p) => walker.opaque.has(p)));
  if (both.length > 0) {
    throw new HashProfileError(
      `${schemaRef}: ${JSON.stringify(both)} carries x-datacompany-hash-declaration-only AND ` +
        'x-datacompany-hash-opaque on one node. They are incompatible acts on one pointer: ' +
        'x-datacompany-hash-opaque declares a subtree whose members are hashed as they ' +
        'arrive, and declaration-only says this pointer is not a hashed path at all. ' +
        'Allowing the pair would also make the placement rule below satisfiable by the ' +
        'node itself, so any author could suppress any pointer anywhere by writing ' +
        'x-datacompany-hash-opaque beside the flag. Mark the ENCLOSING payload opaque and ' +
        'leave the flag on the node that only carries annotations.',
    );
  }

  const misplaced = sortedStrings(
    [...walker.declarationOnly].filter((pointer) => {
      for (const opaque of walker.opaque) {
        if (pointer.startsWith(`${opaque}/`)) {
          return false;
        }
      }
      return true;
    }),
  );
  if (misplaced.length > 0) {
    throw new HashProfileError(
      `${schemaRef}: x-datacompany-hash-declaration-only at ${jsonText(misplaced)} is not ` +
        'strictly inside an x-datacompany-hash-opaque subtree. The annotation exists so that an ' +
        'array inside an opaque subtree can carry its released collection declaration ' +
        "without its pointer becoming a declared member and revoking the subtree's opacity; " +
        'outside an opaque subtree it would silently remove a member from the hash view, ' +
        "which is x-datacompany-hash-excluded's job and carries a released reason and an " +
        'excluded_pointers entry. Mark the enclosing payload x-datacompany-hash-opaque, or ' +
        'exclude the member with x-datacompany-hash-excluded and a reason.',
    );
  }
}

/**
 * Refuse an opaque subtree that both declares a member and carries the flag.
 *
 * "Declare none or declare all, and say which" -- the released rule on
 * `bitemporal-assertion:1` `/value`. A declared sibling revokes the opacity, after which
 * every member must be declared; a declaration-only pointer deliberately is not one, so the
 * shape would throw `UndeclaredPathError` at HASH time, far from the schema that caused it.
 *
 * `included` is the DERIVED list, after the exclusion cascade, and that is the whole
 * correctness of this function. It read the RAW `walker.included`, which counts an EXCLUDED
 * member as a declaration -- the opposite of what `hashView` implements ("Opacity is revoked
 * by a DECLARED MEMBER and by nothing else. An EXCLUSION is the opposite act."). The cost
 * was not theoretical: it refused the exact shape the two annotations exist for -- the
 * signed opaque payload, `/value` opaque with `/value/sig` excluded, plus one array --
 * while the runtime escape hatch hashed it correctly, so D9 was not closed for the
 * motivating case until this ran against the derived set.
 *
 * Grouped by each flag's NEAREST opaque ancestor: opaque subtrees nest, and the outer one's
 * opacity is legitimately revoked by the inner one's own root.
 *
 * FOUND BY MUTATION, then closed. This filter also skipped any declared pointer lying inside
 * some OTHER opaque subtree. It looked like the clause that made nested subtrees work and it
 * was a defect twice over: it made the "group by the outermost ancestor" mutation
 * unobservable, and it SUPPRESSED A REAL REFUSAL -- `/value` opaque with the flag at
 * `/value/tags` and a nested opaque `/value/nested` beside it is broken, because
 * `/value/nested` revokes `/value`'s opacity. Nearest-ancestor grouping alone makes nesting
 * legal, because the inner root is never strictly under itself.
 */
function requireDeclarationOnlyDoesNotCollideWithADeclaredMember(
  walker: Walker,
  included: readonly string[],
  schemaRef: string,
): void {
  const grouped = new Map<string, string[]>();
  for (const pointer of walker.declarationOnly) {
    let nearest = '';
    for (const opaque of walker.opaque) {
      if (pointer.startsWith(`${opaque}/`) && opaque.length >= nearest.length) {
        nearest = opaque;
      }
    }
    grouped.set(nearest, [...(grouped.get(nearest) ?? []), pointer]);
  }

  for (const opaque of sortedStrings(grouped.keys())) {
    const suppressed = sortedStrings(grouped.get(opaque) as string[]);
    // No declaration-only filter here: `included` has already had it applied, along with the
    // exclusion cascade. Re-applying either would hide which set actually decides.
    const declared = included.filter((pointer) => pointer.startsWith(`${opaque}/`));
    if (declared.length > 0) {
      throw new HashProfileError(
        `${schemaRef}: the opaque subtree ${jsonText(opaque)} both declares members ` +
          `${jsonText(declared)} and carries x-datacompany-hash-declaration-only at ` +
          `${jsonText(suppressed)}. A declared member revokes the subtree's opacity, ` +
          'after which every member must be declared -- and a declaration-only pointer ' +
          'deliberately is not one, so it would raise UndeclaredPathError at hash time. ' +
          "Declare NONE of the subtree's members and use x-datacompany-hash-declaration-only to " +
          'carry the array declarations -- marking the OUTERMOST node of each properties ' +
          'chain is enough, because the suppression cascades to everything beneath it -- or ' +
          'declare ALL of them as ordinary properties, in which case x-datacompany-array works ' +
          'without this annotation. An EXCLUDED member is not a declared one and does not ' +
          'appear here: an exclusion removes a path, it does not declare one.',
      );
    }
  }
}

export function deriveHashProfile(schemaRef: string): HashProfile {
  const walker = new Walker(schemaRef);
  const baseId = schemaRef.split('#')[0];
  walker.walk(resolvePointer(schemaRef), '', new Set<string>(), baseId);

  // Placement is a fact about the SCHEMA, so it is checked against the raw walk and
  // first: a misplaced flag must be diagnosed rather than silently applied below.
  requireDeclarationOnlyIsLegallyPlaced(walker, schemaRef);

  const excludedPointers = walker.excluded;
  const isUnderExclusion = (pointer: string): boolean => {
    for (const excluded of excludedPointers.keys()) {
      if (pointer === excluded || pointer.startsWith(`${excluded}/`)) {
        return true;
      }
    }
    return false;
  };

  // D9. A declaration-only node carries an annotation and declares no hashed path, so
  // neither it NOR anything the walk reached beneath it enters `included_pointers`. By
  // PREFIX, matching the released exclusion cascade and NOT the `arrays` exact-match quirk
  // below: an array of OBJECTS at `/value/tags` also yields `/value/tags/-/<member>` from
  // the items walk, and an exact filter would leave those behind -- making `/value` a
  // declared prefix again and revoking exactly the opacity this annotation preserves.
  const isDeclarationOnly = (pointer: string): boolean => {
    for (const suppressed of walker.declarationOnly) {
      if (pointer === suppressed || pointer.startsWith(`${suppressed}/`)) {
        return true;
      }
    }
    return false;
  };

  const included = sortedStrings(
    [...walker.included].filter(
      (pointer) => !isUnderExclusion(pointer) && !isDeclarationOnly(pointer),
    ),
  );

  // ...and only NOW the "declare none or declare all" rule, against the DERIVED list. It
  // used to read the raw `walker.included`, which counts an EXCLUDED member as a
  // declaration -- the opposite of what `hashView` implements.
  requireDeclarationOnlyDoesNotCollideWithADeclaredMember(walker, included, schemaRef);

  // Filtered by the exclusion cascade, by PREFIX, exactly like `included_pointers` and
  // `opaque_pointers` above -- since profile_version 2, 2026-08-04.
  //
  // Until then this block was BUG-COMPATIBLE on purpose and said so. `arrays` dropped only
  // an EXACT match against an excluded pointer, so an array nested under an excluded subtree
  // survived: excluding `/sig` dropped `/sig/parts` from `included_pointers` and `/sig/blob`
  // from `opaque_pointers` while leaving `{"pointer": "/sig/parts", ...}` in `arrays`. The
  // surviving entry was inert -- the excluded subtree is never visited -- but
  // `validateProfileAgainstSchema` compares `arrays` exactly, so a port that filtered all
  // three consistently (the obvious clean implementation) rejected every manifest Python
  // produced. `EXTENSIONS.md` §9 item 6 therefore ordered every port to reproduce the quirk;
  // that item was REWRITTEN IN PLACE, not deleted -- the checklist's numbering is
  // load-bearing, because items 8, 11, 12 and 13 are cited by number elsewhere in the
  // document -- and both engines changed together with the `profile_version` bump §5.2
  // prescribed.
  //
  // `arrays` is still NOT filtered by `declarationOnly` at all, and that is a different rule
  // that did not move. Carrying the collection declaration OUT of a subtree whose paths stay
  // undeclared is the whole purpose of the annotation (D9), and filtering here would make
  // `bitemporal-assertion.v1` `/value` ("Arrays inside it still require their own
  // ordered/set-like declaration") unsatisfiable again. "Make the filters consistent" is now
  // true of the exclusion cascade and still says nothing about this one.
  const filteredArrays: ArrayDeclaration[] = sortedStrings(walker.arrays.keys())
    .filter((pointer) => !isUnderExclusion(pointer))
    .map((pointer) => walker.arrays.get(pointer) as ArrayDeclaration);

  const profile: HashProfile = {
    profile_id: HASH_PROFILE_SCHEMA_REF,
    profile_version: DERIVATION_PROFILE_VERSION,
    schema_ref: schemaRef,
    serialization: 'rfc8785',
    encoding: 'utf-8',
    byte_order_mark: false,
    digest_algorithm: 'sha256',
    digest_prefix: 'sha256:',
    absent_vs_null: 'distinct',
    unicode_normalization: 'none',
    timestamp_representation: 'rfc3339_utc_z',
    decimal_representation: 'decimal_string',
    binary_float_policy: 'reject',
    included_pointers: included,
    excluded_pointers: sortedStrings(excludedPointers.keys()).map((pointer) => ({
      pointer,
      reason: excludedPointers.get(pointer) as string,
    })),
    // Filtered by `declarationOnly` as well, and this is NOT a no-op. The comment here used
    // to claim it could only ever be one, reasoning that the placement guard keeps every
    // flag strictly under an opaque pointer. That argument is about ANCESTORS and says
    // nothing about DESCENDANTS: `/value` opaque, `/value/inner` flagged and
    // `/value/inner/deeper` opaque puts an opaque pointer squarely under a declaration-only
    // one. Listing it would be the manifest asserting a path inside a subtree the same
    // manifest says contributes no paths. Dropping it changes no behaviour -- opacity
    // matches by prefix and the enclosing opaque pointer already covers it -- which is
    // exactly why it must be a rule with a test rather than a comment with an argument.
    opaque_pointers: sortedStrings(
      [...walker.opaque].filter((p) => !isUnderExclusion(p) && !isDeclarationOnly(p)),
    ),
    arrays: filteredArrays,
  };
  validateHashProfile(profile);
  return profile;
}

export interface ProfileExtensions {
  included_pointers?: string[];
  arrays?: ArrayDeclaration[];
  [key: string]: unknown;
}

/**
 * The clause that makes the non-extensible refusal TRUE about the schema it names.
 *
 * Mirrors `hash_profile._where_else_a_composition_point_was_found`, message text INCLUDED.
 * `mergeProfileExtensions` reads the annotation at the document root and nowhere else, but
 * the annotation is legal at any depth and the derivation walk shape-checks and resolves one
 * wherever it finds it. Two shapes were told "declares no x-datacompany-composition-point" while
 * declaring one: a point on a NESTED node, and a domain schema COMPOSING an envelope (the
 * envelope's point arrives at pointer `''`, since `allOf`/`$ref` do not advance the pointer,
 * but it is not a member of the composing document).
 *
 * Root-only is a decision, not an accident. "Extensible if the walk reaches a point at
 * pointer `''`" is AMBIGUOUS on a released schema: `run-manifest:1` declares
 * `#/$defs/manifest_extension` and composes `stable-identity:1`, which declares
 * `#/$defs/domain_extension`. Measured across the corpus the two rules agree on every
 * released schema (6 extensible, 12 not), so the ambiguity buys nothing.
 */
function whereElseACompositionPointWasFound(schemaRef: string): string {
  const walker = new Walker(schemaRef);
  try {
    walker.walk(resolvePointer(schemaRef), '', new Set<string>(), schemaRef.split('#')[0]);
  } catch {
    // Message enrichment on a path that is already failing: a schema this walk cannot
    // traverse is refused by `deriveHashProfile` anyway, and replacing the refusal with an
    // unrelated error would be worse than omitting the clause.
    return '';
  }
  if (walker.compositionPoints.size === 0) {
    return '';
  }
  return (
    ` The derivation walk does reach one at ${jsonText(sortedStrings(walker.compositionPoints))}` +
    ', which is a different statement: an extension contributes ROOT-relative RFC 6901 ' +
    'pointers, so the point that governs it is the one this document declares at its own ' +
    'root. A point reached through composition belongs to the envelope that declares it, ' +
    'and a schema composing an extensible envelope must declare its OWN.'
  );
}

/**
 * Merge a domain schema's declared additions into a released envelope manifest.
 *
 * Nothing may be removed, and no exclusion or opaque subtree may be added this way: those
 * are properties of the released envelope, not of a consumer.
 *
 * **Bound to `x-datacompany-composition-point` since 2026-08-04** (`EXTENSIONS.md` §6.4). This
 * function implemented the composition-point CONCEPT and was driven entirely by its
 * `extensions` argument, never consulting the envelope's declared point -- so every released
 * schema was extensible in practice whether or not it said so. An envelope that declares no
 * composition point is now non-extensible, which is a behaviour change for consumers and is
 * meant to be.
 *
 * What this does NOT claim to check is WHERE an extension attaches: the composition point
 * names a `$defs` entry in SCHEMA space, `included_pointers`/`arrays` are RFC 6901 pointers
 * in INSTANCE space, and every released composition point composes at the envelope root, so
 * a declared point induces no constraint on which instance pointers an extension may name.
 * The gate is presence, and presence is what §6.4 asked to become real.
 */
export function mergeProfileExtensions(
  profile: HashProfile,
  extensions: ProfileExtensions | null | undefined,
): HashProfile {
  if (extensions === null || extensions === undefined || Object.keys(extensions).length === 0) {
    return profile;
  }
  const unknown = Object.keys(extensions).filter((key) => !EXTENSIBLE_PROFILE_KEYS.has(key));
  if (unknown.length > 0) {
    throw new HashProfileError(
      'a domain extension may only add included_pointers and arrays, not ' +
        JSON.stringify(sortedStrings(unknown)),
    );
  }
  // BEFORE the composition-point read: `resolvePointer` below would throw
  // `SchemaValidationError` for an unreleased `schema_ref`, which is a different error with
  // a different message than the one already promised for that case (D7).
  requireReleasedSchemaRef(profile.schema_ref);
  // `as JsonRecord`, exactly as `exclusionReasons` casts: `canonical-hash-profile.v1`
  // constrains `schema_ref` to `^urn:datacompany:[a-z][a-z0-9-]*:[1-9][0-9]*$` and
  // `validateHashProfile` has enforced it, so there is no fragment and the resolution is
  // always the document root -- an isRecord branch here could never evaluate false.
  const schema = resolvePointer(profile.schema_ref) as JsonRecord;
  // PRESENCE, not `!== undefined`. An explicit `"x-datacompany-composition-point": null` is a
  // declared-but-broken point and must reach the shape message below, which is what
  // derivation does for the same schema; testing for `undefined` would silently report it
  // as "declares none" here and as a malformed value there -- reintroducing, in the two
  // messages, exactly the two-route asymmetry D7 is about. Pinned by
  // 'treats an explicit null as malformed, not as absent'; the distinction survived 23
  // mutations unasserted before that test existed.
  if (!Object.hasOwn(schema, 'x-datacompany-composition-point')) {
    // THE ROOT OF THIS DOCUMENT, and nowhere else -- named in the message rather than left
    // implicit, because the annotation is legal at any depth and a schema declaring a valid
    // point on a nested node used to be told it "declares no x-datacompany-composition-point".
    throw new HashProfileError(
      `${profile.schema_ref} declares no x-datacompany-composition-point at its document ` +
        'ROOT, so it is not extensible. A domain schema may contribute included_pointers ' +
        "and arrays only at an envelope's declared composition point: accepting the " +
        'extension would put pointers into a manifest the envelope never invited, and ' +
        'validate_profile_against_schema would then accept them as released.' +
        whereElseACompositionPointWasFound(profile.schema_ref) +
        ' Declare the composition point at the root of this schema, or drop the ' +
        'extension.',
    );
  }
  const point = schema['x-datacompany-composition-point'];
  // Re-checked here rather than trusted from derivation. A manifest reaching this function
  // need never have been produced by `deriveHashProfile` -- it is public API over any
  // well-formed `canonical-hash-profile.v1` -- so a schema carrying a broken composition
  // point would otherwise be extensible through this route while underivable through the
  // other. One helper, one message, both routes.
  requireReleasedCompositionPoint(point, '', profile.schema_ref, profile.schema_ref);
  const declared = new Set(profile.arrays.map((entry) => entry.pointer));
  const merged: HashProfile = {
    ...profile,
    included_pointers: sortedStrings(
      new Set([...profile.included_pointers, ...(extensions.included_pointers ?? [])]),
    ),
    // SORTED by pointer, exactly as `deriveHashProfile` sorts, rather than appended.
    // Appending made the two D9 routes byte-identical only by ACCIDENT: they agreed on
    // `bitemporal-assertion:1` because `/value/tags` happens to sort after `/basis_refs`.
    // An opaque `/aaa` with a flagged `/aaa/tags` beside a released array at `/zzz` derived
    // `['/aaa/tags', '/zzz']` and merged `['/zzz', '/aaa/tags']` -- the same manifest in two
    // byte sequences, and D9's closure is stated as a BYTE equality.
    // `validateProfileAgainstSchema` compares `arrays` per pointer so it never noticed,
    // which is why one representation had to become canonical here. No committed manifest
    // moves: every one is DERIVED, and derivation already sorted.
    arrays: [
      ...profile.arrays,
      ...(extensions.arrays ?? []).filter((entry) => !declared.has(entry.pointer)),
    // `compareCodePoints`, never JS `<`: `<` compares UTF-16 code UNITS where Python's
    // `sorted` compares code POINTS, and the two disagree for astral characters. That is
    // the G1 divergence class this repository already carries a fixture for.
    ].sort((a, b) => compareCodePoints(a.pointer, b.pointer)),
  };
  validateHashProfile(merged);
  return merged;
}

/** Validate a manifest against `canonical-hash-profile.v1` and its closed reason set. */
export function validateHashProfile(profile: unknown): void {
  const errors = validateInstance(profile, HASH_PROFILE_SCHEMA_REF);
  if (errors.length > 0) {
    throw new HashProfileError(
      `hash-view manifest is not a valid ${HASH_PROFILE_SCHEMA_REF}: ${errors.join('; ')}`,
    );
  }
  const manifest = profile as HashProfile;
  for (const entry of manifest.excluded_pointers) {
    if (!exclusionReasons().has(entry.reason)) {
      throw new UnknownExclusionError(
        `${entry.pointer}: unknown hash exclusion reason ${JSON.stringify(entry.reason)}`,
      );
    }
  }
  requireReleasedSchemaRef(manifest.schema_ref);
}

/**
 * Fail unless `schema_ref` names a schema the registry actually holds.
 *
 * ⚠️ DISCLOSED CROSS-LANGUAGE DIVERGENCE, in this function's own message text, and a CLASS
 * rather than one site. `EXTENSIONS.md` §9 item 13 requires both engines to refuse the same
 * input with byte-identical words, and this message does not. Two causes, both measured on
 * the same forged manifest: the quoting (`JSON.stringify` here against Python's `!r`), and
 * the INTERPOLATED resolver error -- `registry.resolvePointer` renders its diagnostics bare
 * and unquoted where `registry.py` uses `!r`, so this engine emits `unknown schema_ref
 * urn:…` against Python's `unknown schema_ref 'urn:…'`. That root cause reaches roughly
 * eleven sites across both engines. One of them, `validateProfileAgainstSchema`, diverges
 * STRUCTURALLY rather than by punctuation: it renders a contradicted value through the
 * key-sorted `stableKey` where Python uses `!r`, so lists and objects differ in shape.
 *
 * Nothing can catch it: `differential_fuzz` compares the error CLASS NAME only, never the
 * message, and `refusals.json` -- the record that does compare message bytes -- replays only
 * `deriveHashProfile` and `collectCrossFieldRules`. Left as residue in the shape
 * `structural.ts`'s opening PARITY NOTE established, because unifying it means editing
 * `registry`'s message text and that is a decision of its own. Disclosed rather than silent,
 * because `requireReleasedCompositionPoint` below refuses to interpolate the same resolver
 * error and calls doing so "the exact divergence §9 item 13 exists to forbid".
 *
 * The guard this replaces stated the right rule and checked nothing: it called
 * `schemaRegistry()`, which takes no argument, never read the manifest's own `schema_ref`,
 * and discarded the registry it built. A manifest naming
 * `urn:datacompany:definitely-not-released:1` validated cleanly and only failed much later,
 * inside the hash view builder, as an unrelated-looking resolution error.
 *
 * The resolution goes through `resolvePointer`, the SAME call `deriveHashProfile` uses, and
 * NOT through `schemaRegistry`. Python made that correction first: `schema_registry` is
 * memoised over its own build and can answer about a different enumeration than the deriver
 * walked, so a manifest gets checked against a tree that did not produce it. `schemaRegistry`
 * here is an Ajv instance built from the same cache and carries the same hazard. Keeping the
 * two ports on one rule is what makes cross-engine manifest verification mean anything.
 *
 * Resolvability is the whole check, deliberately. `canonical-hash-profile.v1` constrains
 * `schema_ref` to `^urn:datacompany:[a-z][a-z0-9-]*:[1-9][0-9]*$` and `validateHashProfile` has
 * already enforced that above, so there is no fragment to resolve and no non-object to guard
 * against; extra branches here would read as defence in depth while never evaluating true.
 */
function requireReleasedSchemaRef(schemaRef: string): void {
  try {
    resolvePointer(schemaRef);
  } catch (error) {
    throw new HashProfileError(
      `hash-view manifest declares schema_ref ${JSON.stringify(schemaRef)}, which is not a ` +
        'released schema. Nothing can resolve it, so the hash view it claims to describe ' +
        `could never be built: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

function byPointer(entries: ArrayDeclaration[]): Map<string, ArrayDeclaration> {
  return new Map(entries.map((entry) => [entry.pointer, entry]));
}

/**
 * Reject a manifest that contradicts the annotations of the schema it claims to hash.
 *
 * `validateHashProfile` only proves a manifest is *well formed*. A well-formed manifest can
 * still delete every exclusion or re-declare a released array, which would let two services
 * compute different "canonical" hashes for the same object. The schema's own annotations are
 * the authority, so a supplied manifest must be exactly the released derivation plus, at
 * most, the domain additions `mergeProfileExtensions` permits.
 */
export function validateProfileAgainstSchema(profile: unknown, schemaRef: string): void {
  validateHashProfile(profile);
  const manifest = profile as HashProfile;
  if (manifest.schema_ref !== schemaRef) {
    throw new HashProfileError(
      `hash-view manifest declares schema_ref ${JSON.stringify(manifest.schema_ref)}, ` +
        `which is not the hashed object's ${JSON.stringify(schemaRef)}`,
    );
  }
  if (manifest.profile_version !== DERIVATION_PROFILE_VERSION) {
    throw new HashProfileError(
      `hash-view manifest declares profile_version ${JSON.stringify(manifest.profile_version)}, ` +
        `but this engine implements derivation profile version ${DERIVATION_PROFILE_VERSION}. ` +
        'profile_version names the rule set that produced the manifest, so a manifest ' +
        'carrying another version cannot be checked against this derivation. Bumping it ' +
        'means bumping DERIVATION_PROFILE_VERSION and every released manifest in the same ' +
        'change.',
    );
  }
  const released = deriveHashProfile(schemaRef) as unknown as JsonRecord;
  const supplied = manifest as unknown as JsonRecord;

  for (const key of Object.keys(released)) {
    if (EXTENSIBLE_PROFILE_KEYS.has(key)) {
      continue;
    }
    let releasedValue = released[key];
    let suppliedValue = supplied[key];
    if (Array.isArray(releasedValue)) {
      // Ordered by RFC 8785 CANONICAL BYTES, byte-for-byte the key merged Python uses
      // (`_canonical_order` in hash_profile.py). The check is about the MULTISET of
      // entries, not their order, so any total order would decide equality identically --
      // but using the same key as Python makes that parity by construction rather than by
      // argument. It replaced a `repr` sort, under which two manifests that are the same
      // JSON but whose entries were written in different member order compared unequal and
      // the second was falsely rejected.
      suppliedValue = [...(Array.isArray(suppliedValue) ? suppliedValue : [])].sort((a, b) =>
        compareBytes(canonicalOrder(a), canonicalOrder(b)),
      );
      releasedValue = [...releasedValue].sort((a, b) =>
        compareBytes(canonicalOrder(a), canonicalOrder(b)),
      );
    }
    if (!deepEqual(suppliedValue, releasedValue)) {
      throw new HashProfileError(
        `hash-view manifest ${key} contradicts the released annotations of ${schemaRef}: ` +
          `${stableKey(supplied[key])} is not the derived ${stableKey(released[key])}. ` +
          'Only included_pointers and arrays may be extended, and only by ' +
          'mergeProfileExtensions.',
      );
    }
  }

  const suppliedIncluded = new Set(manifest.included_pointers);
  const missing = sortedStrings(
    (released['included_pointers'] as string[]).filter((p) => !suppliedIncluded.has(p)),
  );
  if (missing.length > 0) {
    throw new HashProfileError(
      `hash-view manifest drops released included pointers of ${schemaRef}: ` +
        JSON.stringify(missing),
    );
  }

  const declared = byPointer(manifest.arrays);
  for (const entry of released['arrays'] as ArrayDeclaration[]) {
    if (!deepEqual(declared.get(entry.pointer), entry)) {
      throw new HashProfileError(
        `hash-view manifest re-declares or drops the released array ` +
          `${JSON.stringify(entry.pointer)} of ${schemaRef}: ` +
          `${stableKey(declared.get(entry.pointer))} is not the derived ${stableKey(entry)}`,
      );
    }
  }
}

export type { ArrayDeclaration, ExcludedPointer, HashProfile };

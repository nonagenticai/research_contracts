/**
 * Steps 2-5 of the section 4.3 canonical hash algorithm: the semantic hash view.
 *
 * TypeScript port of `src/research_contracts/canonical/hash_view.py`.
 */

import {
  CanonicalError,
  DuplicateSetMemberError,
  MissingOrderKeyError,
  UndeclaredArrayError,
  UndeclaredPathError,
  UnstableFloatError,
} from './errors';
import { canonicalize, compareBytes, stableInteger, type CanonicalValue } from './jcs';

// `UndeclaredPathError` lives in `hash_view.py` in Python. It is declared centrally in
// `errors.ts` to avoid an import cycle and re-exported here so the import site matches.
export { UndeclaredPathError } from './errors';

/**
 * The RFC 6901 "append/any-index" array token used in hash-view path declarations.
 * Not a credential.
 */
const ARRAY_TOKEN = '-';

/**
 * Returned by `pointerAt` when the pointer does not resolve at all. Distinct from an
 * explicit `null`, which is a real value that two members can genuinely share.
 */
export const ABSENT = Symbol('absent');

const UTF8_DECODER = new TextDecoder('utf-8', { fatal: true });

export interface ArrayDeclaration {
  pointer: string;
  kind: 'ordered' | 'set';
  order_key?: string[];
}

export interface ExcludedPointer {
  pointer: string;
  reason: string;
}

export interface HashProfile {
  profile_id: string;
  profile_version: number;
  schema_ref: string;
  serialization: string;
  encoding: string;
  byte_order_mark: boolean;
  digest_algorithm: string;
  digest_prefix: string;
  absent_vs_null: string;
  unicode_normalization: string;
  timestamp_representation: string;
  decimal_representation: string;
  binary_float_policy: string;
  included_pointers: string[];
  excluded_pointers: ExcludedPointer[];
  opaque_pointers: string[];
  arrays: ArrayDeclaration[];
}

/** Escape an RFC 6901 reference token. `~` MUST be escaped before `/`. */
export function escapeToken(token: string): string {
  return token.split('~').join('~0').split('/').join('~1');
}

function unescapeToken(token: string): string {
  return token.split('~1').join('/').split('~0').join('~');
}

/**
 * A `{}`-shaped or null-prototype object. Arrays, `Date`, `Map` and class instances are
 * not objects for hash-view purposes.
 */
function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value) as object | null;
  return prototype === Object.prototype || prototype === null;
}

/**
 * Resolve `pointer` inside `value`, returning `ABSENT` when it does not resolve.
 *
 * DICT-ONLY, deliberately: Python's `_pointer_at` cannot descend into an array, so
 * `pointerAt({a: [1, 2]}, '/a/0')` is ABSENT, not `1`. That is load-bearing -- substituting
 * a "generic" RFC 6901 resolver would make some absent order keys resolve and change which
 * set members are considered distinct. An absent member, an untraversable node and an
 * explicit `null` are three different facts.
 */
export function pointerAt(value: unknown, pointer: string): unknown {
  if (pointer === '') {
    // D8: RFC 6901's whole-document pointer, which for a member-relative order key
    // addresses the MEMBER ITSELF. This is what makes a set of scalars declarable; only
    // `order_key_pointer` admits it, so it is unreachable from included/excluded pointers.
    return value;
  }
  if (!pointer.startsWith('/')) {
    // RFC 6901 section 3: a non-empty JSON Pointer BEGINS with '/'. Nothing that reaches
    // here can be relative -- `order_key_pointer` is `hash_view_pointer` plus `""`, and
    // `hash_view_pointer` pins `^(/([^/~]|~[01])*)+$` -- so a pointer without one is
    // malformed, and an order key that cannot be read is an ABSENT order key, which throws
    // `MissingOrderKeyError` rather than silently keying on something else.
    return ABSENT;
  }
  let node: unknown = value;
  // `pointer.split('/').slice(1)`, NOT `pointer.replace(/^\/+/, '').split('/')`.
  //
  // ⚠️ Stripping every leading slash discards EMPTY reference tokens, which RFC 6901
  // allows: `'//a'` is the two tokens `['', 'a']` -- the member named `''` and then its
  // member `'a'` -- and the released `hash_view_pointer` pattern `^(/([^/~]|~[01])*)+$`
  // accepts it, because `([^/~]|~[01])*` matches zero characters. Stripped, it collapsed
  // to the single token `['a']`, so an `order_key: ['//a']` resolved against `{a: 1}` -- a
  // member that does NOT carry the declared key -- and was accepted, while the member that
  // does carry it, `{'': {a: 1}}`, was reported absent.
  //
  // `hash_view.py` carries the identical fix. These two implementations are verified
  // byte-equivalent by the differential fuzzer, and a fix to one is a defect in the other
  // until it lands in both.
  for (const raw of pointer.split('/').slice(1)) {
    const token = unescapeToken(raw);
    if (!isPlainObject(node) || !Object.hasOwn(node, token)) {
      return ABSENT;
    }
    node = node[token];
  }
  return node;
}

/**
 * The parent pointer of every pointer that has one, plus the document root.
 *
 * The membership test is `pointer.slice(1).includes('/')`, not a leading-slash strip, for
 * the reason spelled out in `pointerAt`: a reference token may be EMPTY, so `'//a'` is two
 * tokens and its parent is `'/'`. Stripping read it as one token and gave it no parent at
 * all, which revoked the declaration of an object whose members the manifest does declare.
 */
function parentsOf(pointers: readonly string[]): Set<string> {
  const parents = new Set<string>(['']);
  for (const pointer of pointers) {
    if (pointer.startsWith('/') && pointer.slice(1).includes('/')) {
      parents.add(pointer.slice(0, pointer.lastIndexOf('/')));
    }
  }
  return parents;
}

class ViewBuilder {
  private readonly included: Set<string>;
  private readonly excluded: Set<string>;
  private readonly arrays: Map<string, ArrayDeclaration>;
  private readonly opaque: readonly string[];
  private readonly keepNulls: boolean;
  private readonly normalization: 'NFC' | 'NFD' | 'NFKC' | 'NFKD' | null;
  private readonly declaredPrefixes: Set<string>;
  private readonly includedPrefixes: Set<string>;

  constructor(profile: HashProfile) {
    this.included = new Set(profile.included_pointers);
    this.excluded = new Set(profile.excluded_pointers.map((entry) => entry.pointer));
    this.arrays = new Map(profile.arrays.map((entry) => [entry.pointer, entry]));
    this.opaque = [...profile.opaque_pointers];
    this.keepNulls = profile.absent_vs_null === 'distinct';
    const normalization = profile.unicode_normalization;
    this.normalization =
      normalization === 'none'
        ? null
        : (normalization.toUpperCase() as 'NFC' | 'NFD' | 'NFKC' | 'NFKD');

    this.declaredPrefixes = parentsOf([...this.included, ...this.excluded]);
    // The narrower half: the parents of the INCLUDED pointers alone. An exclusion is not a
    // declaration -- it removes a descendant from the hash view, it does not name one that
    // must be hashed -- so it is deliberately absent here. See `buildObject` for why the
    // two sets cannot be one.
    this.includedPrefixes = parentsOf([...this.included]);
  }

  private hasDeclaredChildren(pointer: string): boolean {
    return this.declaredPrefixes.has(pointer);
  }

  /** True when the manifest names a member of `pointer` as a hashed path. */
  private hasIncludedChildren(pointer: string): boolean {
    return this.includedPrefixes.has(pointer);
  }

  /** True when `pointer` is, or sits under, an explicitly opaque released subtree. */
  private isDeclaredOpaque(pointer: string): boolean {
    return this.opaque.some(
      (declared) => pointer === declared || pointer.startsWith(`${declared}/`),
    );
  }

  private text(value: string): string {
    return this.normalization === null ? value : value.normalize(this.normalization);
  }

  build(value: unknown, pointer: string): CanonicalValue {
    if (typeof value === 'boolean' || value === null) {
      return value;
    }
    if (typeof value === 'number') {
      const integral = stableInteger(value);
      if (integral === null) {
        throw new UnstableFloatError(
          `${pointer || '/'}: binary float ${String(value)} may not enter a hashed input; the ` +
            'released profile declares binary_float_policy=reject',
        );
      }
      // JSON has one number type: a schema-valid integer that a parser handed back as 2.0
      // is the integer 2, and RFC 8785 renders both identically.
      return integral;
    }
    if (typeof value === 'bigint') {
      // Python's `isinstance(value, int)` branch: carried through untouched here and
      // rejected by the serializer if it is out of the exact double range. An out-of-range
      // integer at an EXCLUDED pointer never reaches the serializer, in either language.
      return value;
    }
    if (typeof value === 'string') {
      return this.text(value);
    }
    if (Array.isArray(value)) {
      return this.buildArray(value, pointer);
    }
    if (isPlainObject(value)) {
      return this.buildObject(value, pointer);
    }
    throw new CanonicalError(`${pointer || '/'}: ${typeof value} is not JSON data`);
  }

  private buildObject(value: Record<string, unknown>, pointer: string): CanonicalValue {
    // Declare none or declare all, and say which: an object either has its members
    // declared one by one, or sits in a subtree the released schema explicitly marks
    // x-datacompany-hash-opaque. Silence is not a third option -- it used to mean "hash the
    // whole subtree undeclared", which failed open for every domain that shipped no
    // profile extensions at all.
    //
    // Opacity is revoked by a DECLARED MEMBER and by nothing else. The released `$comment`
    // on `bitemporal-assertion:1` `/value` states the rule as "the moment a domain declares
    // any member of value, it must declare all of them", and a declared member is an
    // INCLUDED pointer. An EXCLUSION is the opposite act: it takes a descendant out of the
    // hash view. Testing opacity against `hasDeclaredChildren` -- which is also true of the
    // parent of every excluded pointer -- made "exclude the signature from an opaque
    // payload" impossible: the exclusion injected the payload into the prefix set, opacity
    // was revoked, and every undeclared SIBLING of the signature then threw
    // `UndeclaredPathError`. An opaque subtree is hashed as an opaque unit MINUS its
    // explicitly excluded descendants, and its undeclared descendants stay legal.
    const declaredChildren = this.hasDeclaredChildren(pointer);
    const opaque = !this.hasIncludedChildren(pointer) && this.isDeclaredOpaque(pointer);
    if (!declaredChildren && !opaque) {
      throw new UndeclaredPathError(
        `${pointer || '/'}: the released hash-view manifest declares neither this ` +
          "object's members nor this subtree as opaque; declare every member, or mark " +
          'the subtree x-datacompany-hash-opaque in the schema',
      );
    }
    // A null prototype, so a member literally named `__proto__` -- which `JSON.parse`
    // produces as an ordinary own property -- is stored as data instead of silently
    // reassigning the object's prototype.
    const view = Object.create(null) as Record<string, CanonicalValue>;
    for (const name of Object.keys(value)) {
      const childPointer = `${pointer}/${escapeToken(name)}`;
      if (this.excluded.has(childPointer)) {
        continue;
      }
      if (!this.included.has(childPointer) && !opaque) {
        throw new UndeclaredPathError(
          `${childPointer}: not declared by the released hash-view manifest`,
        );
      }
      const child = value[name];
      if (child === null && !this.keepNulls) {
        continue;
      }
      view[name] = this.build(child, childPointer);
    }
    return view;
  }

  private buildArray(value: unknown[], pointer: string): CanonicalValue {
    const declaration = this.arrays.get(pointer);
    if (declaration === undefined) {
      throw new UndeclaredArrayError(
        `${pointer || '/'}: array has no released ordered/set-like declaration`,
      );
    }
    const elementPointer = `${pointer}/${ARRAY_TOKEN}`;
    const members = value.map((item) => this.build(item, elementPointer));
    if (declaration.kind === 'ordered') {
      return members;
    }

    const orderKey = declaration.order_key ?? [];
    const keyed: { bytes: Uint8Array; member: CanonicalValue }[] = [];
    // The duplicate map is keyed by the DECODED order-key text (UTF-8 decoding is
    // bijective, so equality is preserved) while ordering uses the RAW BYTES. Conflating
    // the two is exactly how the wrong sort order ships: UTF-8 byte order is Unicode CODE
    // POINT order, and a JS string sort is UTF-16 CODE UNIT order. They disagree for every
    // astral character compared against U+E000..U+FFFF.
    const seen = new Map<string, number>();
    for (const [index, member] of members.entries()) {
      const keyValues = orderKey.map((keyPointer) => pointerAt(member, keyPointer));
      const absent = orderKey.filter((_keyPointer, position) => keyValues[position] === ABSENT);
      if (absent.length > 0) {
        throw new MissingOrderKeyError(
          `${pointer}/${index}: set-like member does not carry the released order-key ` +
            `path(s) ${formatPointerList(absent)}; every member of a set-like array must ` +
            'carry its whole released order key, and an absent key is not the same fact as ' +
            'a shared one',
        );
      }
      const keyBytes = canonicalize(keyValues);
      const keyText = UTF8_DECODER.decode(keyBytes);
      const previous = seen.get(keyText);
      if (previous !== undefined) {
        throw new DuplicateSetMemberError(
          `${pointer}: set-like array members ${previous} and ${index} share the ` +
            `canonical order key ${keyText}`,
        );
      }
      seen.set(keyText, index);
      keyed.push({ bytes: keyBytes, member });
    }
    // Sort by the RAW UTF-8 BYTES of the canonicalized order key, unsigned, which is
    // Python's `keyed.sort(key=lambda entry: entry[0])` over `bytes`. This is Unicode CODE
    // POINT order. A `left.text < right.text` comparison here would be UTF-16 CODE UNIT
    // order and would put every astral character BEFORE U+E000..U+FFFF instead of after --
    // a different array order, different canonical bytes and a different digest, pinned by
    // `vectors/set-like-array-astral-vs-private-use-order-key.json`.
    keyed.sort((left, right) => compareBytes(left.bytes, right.bytes));
    return keyed.map((entry) => entry.member);
  }
}

/** Render a pointer list the way Python renders a `list[str]` in an error message. */
function formatPointerList(pointers: string[]): string {
  return `[${pointers.map((pointer) => `'${pointer}'`).join(', ')}]`;
}

/**
 * Return the semantic hash view of `instance` under a released manifest.
 *
 * Implements section 4.3 steps 2 through 5: keep the schema-declared semantic paths,
 * remove exactly the schema-marked non-hashable paths (nested target `content_hash` values
 * are ordinary declared members and stay in), enforce every array's released collection
 * kind, reject duplicate set members, and apply the released absent-versus-null and Unicode
 * rules without ever normalizing undeclared.
 */
export function buildHashView(instance: unknown, profile: HashProfile): CanonicalValue {
  return new ViewBuilder(profile).build(instance, '');
}

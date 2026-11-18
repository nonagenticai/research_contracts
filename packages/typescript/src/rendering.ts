/**
 * Language-neutral rendering of a JSON value into an engine's error message text.
 *
 * TypeScript port of `src/research_contracts/canonical/rendering.py`, function for function.
 *
 * `EXTENSIONS.md` §9 item 12 states the rule these two functions exist to keep: two engines
 * that refuse the same schema with different words are a divergence a consumer reading
 * either one cannot reconcile. It names the concrete trap -- Python's `repr` writes `['/a']`
 * where `JSON.stringify` writes `["/a"]` -- and the same trap has two more spellings that a
 * port reproduces only by accident:
 *
 * - a quoted scalar. `repr("nope")` is `'nope'` and `JSON.stringify("nope")` is `"nope"`.
 *   Decision F's own refusals were measured emitting both, one per language, for the same
 *   malformed rule.
 * - a type NAME. Python's `type(value).__name__` is `str`/`dict`/`NoneType`/`list` where
 *   `typeof` is `string`/`object`/`object`/`object`. Neither is the type system the value
 *   actually has: these values are parsed JSON, so the honest vocabulary is JSON's own --
 *   the six names the `type` keyword uses -- and it is the only one both languages spell
 *   identically.
 * - a NON-ASCII character. Python's `json.dumps` defaults to `ensure_ascii=True` and escapes
 *   every code point above U+007F into `\uXXXX`; `JSON.stringify` escapes nothing above the
 *   control range. A member named `café` renders as `["/café"]` there and `["/café"]`
 *   here, for the same refusal of the same schema. This port needs no code to get that
 *   right -- it is Python that must pass `ensure_ascii=False` -- but the divergence is
 *   invisible to every ASCII test, so `fixtures/canonical-annotations/v1/refusals.json`
 *   carries a non-ASCII case that both engines replay.
 */

/**
 * Render `value` as compact JSON, byte for byte as Python's
 * `json.dumps(value, separators=(",", ":"))` would.
 *
 * `JSON.stringify` returns `undefined` rather than a string for `undefined` and for a
 * function; neither can come out of `JSON.parse`, so the fallback is a named rendering
 * rather than the literal string "undefined" masquerading as JSON.
 */
export function jsonText(value: unknown): string {
  const rendered = JSON.stringify(value);
  return rendered === undefined ? 'null' : rendered;
}

/** Name `value`'s JSON type, using the six names JSON Schema's `type` keyword uses. */
export function jsonType(value: unknown): string {
  if (value === null) {
    return 'null';
  }
  if (Array.isArray(value)) {
    return 'array';
  }
  const kind = typeof value;
  if (kind === 'boolean' || kind === 'number' || kind === 'string') {
    return kind;
  }
  if (kind === 'object') {
    return 'object';
  }
  // Not reachable from a parsed JSON document, which is the only source these engines read.
  // Named rather than silently mapped onto one of the six above, because a value that is not
  // JSON at all is a different fault from a value of the wrong JSON type.
  return `non-JSON ${kind}`;
}

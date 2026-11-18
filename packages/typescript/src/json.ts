/**
 * A first-party JSON parser, because `JSON.parse` is neither faithful nor pure.
 *
 * TWO independent defects, both measured on this toolchain, force this file to own the
 * parse instead of delegating it.
 *
 * ## 1. `JSON.parse` destroys an integer literal past 2^53 before our code runs
 *
 * Python's `json.loads` yields an exact `int` for an integer literal of any magnitude, so
 * `jcs.es_number_to_string` can see `9007199254740993` and raise `UnstableFloatError`.
 * `JSON.parse` rounds the literal to the nearest double first:
 *
 *     JSON.parse('{"n":9007199254740993}').n === 9007199254740992   // true
 *
 * A port built on it would ACCEPT and happily hash an input the Python reference refuses,
 * and the two implementations would disagree about a value neither of them can see.
 *
 * This parser keeps the fact rather than failing early: an out-of-range integer literal is
 * materialized as a `bigint`, which `jcs.esNumberToString` rejects at SERIALIZATION time.
 * That reproduces Python exactly, including the case where the offending member sits at an
 * EXCLUDED pointer and is therefore dropped from the hash view before any serialization
 * happens -- Python does not raise there, and neither does this.
 *
 * ## 2. `JSON.parse` is not a pure function of its argument on Node >= 24
 *
 * V8 reuses object member names across parses. Once a document has been parsed whose
 * member at some position carries the source key `\\` -- two characters, decoding to one
 * backslash -- a LATER document of the same shape whose member at that position is any
 * escape sequence decoding to a SINGLE character is handed back the cached backslash
 * instead of its own name. Measured, with nothing of ours in the picture:
 *
 *     JSON.parse('{"a":1,"\\ufb00":2}')   // -> keys ["a", "ﬀ"]   (correct)
 *     JSON.parse('{"a":1,"\\\\":2}')      // poisons the shape
 *     JSON.parse('{"a":1,"\\ufb00":2}')   // -> keys ["a", "\\"]       (WRONG)
 *
 * Node 20.20.2 is clean; Node 24.16.0 and 25.8.1 both reproduce it, and CI runs Node 24.
 * The consequences were not academic: the P8 differential fuzz went red on 5 of 200
 * measured seeds at `--count 2048` (seeds 32, 58, 73, 106 and 20260808, on Node 24 and 25
 * alike) because a `string-escapes` case earlier in the SAME batch poisoned a
 * `structural` case later in it, and `registry.ts` loads every released schema through this
 * function, so a schema carrying a `\` member name could silently rename a member of the
 * next schema read.
 *
 * No option, flag or reviver avoids it -- it reproduces under `--jitless` and with a
 * reviver installed -- and re-parsing cannot repair it, because the corrupted key has
 * already lost the name it should have had. The only fix is to stop delegating.
 *
 * ## What this parser is
 *
 * A recursive-descent parser over the RFC 8259 / ECMA-404 grammar. On every value
 * `JSON.parse` accepts, it agrees with `JSON.parse` on the result, EXCEPT for the two
 * documented departures below:
 *
 * * an integer literal past +/-2^53 becomes a `bigint`, which is the whole point;
 * * NESTING DEPTH. Recursive descent runs out of JavaScript stack at a few thousand levels
 *   -- measured 7801 on this machine, and it moves with the ambient stack size -- where V8's
 *   iterative parser handles 400000 without complaint. Past that limit this parser throws
 *   `RangeError` ("Maximum call stack size exceeded"), NOT the `SyntaxError` every other
 *   refusal here raises; a port reading this file must not assume `SyntaxError` covers it.
 *   Python's `json.loads` gives up at 74402, so between roughly 7.8k and 74k the two
 *   canonical engines disagree about acceptance. Nothing in this repository goes near it:
 *   the deepest committed schema nests 14 levels and the fuzz generator builds three.
 *   Deliberately left alone -- an explicit depth cap would be a new refusal invented here
 *   rather than a rule the released contract states.
 *
 * Everything else is `JSON.parse` behaviour, and each of these is pinned by a test:
 *
 * * a `\uXXXX` escape naming an unpaired surrogate yields that lone surrogate, which the
 *   serializer then refuses -- the same fact Python's `json.loads` preserves;
 * * a duplicate member name keeps the FIRST position and the LAST value;
 * * a member literally named `__proto__` becomes an ordinary own data property instead of
 *   reassigning the object's prototype;
 * * the escape whitelist is exactly `" \ / b f n r t u` -- `\v`, `\0`, `\x41` and `\'` are
 *   all refused, as JSON requires and as JavaScript string literals do NOT;
 * * whitespace is exactly space, tab, CR and LF. U+00A0, U+FEFF, U+000B, U+000C and
 *   U+2028 are DATA, not separators, and a document padded with them is refused;
 * * a raw control character inside a string, a leading `+`, a leading zero, a trailing
 *   comma, `NaN` and `Infinity` are all refused, with a `SyntaxError` naming the offset.
 *
 * It holds no state between calls. `parseCanonicalJson(text)` depends on `text` and on
 * nothing else, which is the property the differential fuzz now asserts directly.
 *
 * COST, measured on this machine: 4.2x slower than `JSON.parse` across all 271 committed
 * `.json` files (3.9 MiB), 10.3x on a 20000-element integer array, 1.4x on a string-heavy
 * object. The ratio tracks how many NUMBERS a document holds, because every integral
 * literal pays a `BigInt()` construction to find out whether it is in exact range. Bought
 * deliberately: the released schemas the registry loads cost 0.063 ms each, 1.2 ms for all
 * 19 of them, which is not a budget anybody is spending -- and the alternative is a parser
 * whose answer depends on what it parsed last.
 */

import { MAX_EXACT_INTEGER_BIGINT, type CanonicalValue } from './jcs';

/** The `\x` escapes JSON defines, keyed by the code unit following the backslash. */
const SHORT_UNESCAPES: ReadonlyMap<number, string> = new Map([
  [0x22, '"'],
  [0x5c, '\\'],
  [0x2f, '/'],
  [0x62, '\b'],
  [0x66, '\f'],
  [0x6e, '\n'],
  [0x72, '\r'],
  [0x74, '\t'],
]);

const QUOTE = 0x22;
const BACKSLASH = 0x5c;
const LOWER_U = 0x75;

/** The four characters RFC 8259 admits between tokens. Nothing else is whitespace. */
function isWhitespace(code: number): boolean {
  return code === 0x20 || code === 0x09 || code === 0x0a || code === 0x0d;
}

function isDigit(code: number): boolean {
  return code >= 0x30 && code <= 0x39;
}

/** The value of one hex digit, or -1. Case-insensitive, as JSON requires. */
function hexValue(code: number): number {
  if (code >= 0x30 && code <= 0x39) {
    return code - 0x30;
  }
  if (code >= 0x61 && code <= 0x66) {
    return code - 0x61 + 10;
  }
  if (code >= 0x41 && code <= 0x46) {
    return code - 0x41 + 10;
  }
  return -1;
}

class JsonParser {
  private index = 0;

  constructor(private readonly text: string) {}

  parseDocument(): CanonicalValue {
    this.skipWhitespace();
    const value = this.parseValue();
    this.skipWhitespace();
    if (this.index !== this.text.length) {
      throw this.error('unexpected character after the end of the JSON document');
    }
    return value;
  }

  private error(message: string): SyntaxError {
    return new SyntaxError(`${message} at position ${this.index}`);
  }

  /** The code unit at the cursor, or -1 at the end of the text. */
  private peek(): number {
    return this.index < this.text.length ? this.text.charCodeAt(this.index) : -1;
  }

  private skipWhitespace(): void {
    while (this.index < this.text.length && isWhitespace(this.text.charCodeAt(this.index))) {
      this.index += 1;
    }
  }

  private expect(code: number, what: string): void {
    if (this.peek() !== code) {
      throw this.error(`expected ${what}`);
    }
    this.index += 1;
  }

  private parseValue(): CanonicalValue {
    const code = this.peek();
    if (code === 0x7b) {
      return this.parseObject();
    }
    if (code === 0x5b) {
      return this.parseArray();
    }
    if (code === QUOTE) {
      return this.parseString();
    }
    if (code === 0x2d || isDigit(code)) {
      return this.parseNumber();
    }
    if (this.text.startsWith('true', this.index)) {
      this.index += 4;
      return true;
    }
    if (this.text.startsWith('false', this.index)) {
      this.index += 5;
      return false;
    }
    if (this.text.startsWith('null', this.index)) {
      this.index += 4;
      return null;
    }
    throw this.error('expected a JSON value');
  }

  /**
   * Read a string literal.
   *
   * Escape-free runs are taken with one `slice`, so the character-at-a-time path only runs
   * for the parts that actually carry an escape.
   */
  private parseString(): string {
    this.expect(QUOTE, 'a string');
    let out = '';
    let chunkStart = this.index;
    for (;;) {
      if (this.index >= this.text.length) {
        throw this.error('unterminated string');
      }
      const code = this.text.charCodeAt(this.index);
      if (code === QUOTE) {
        out += this.text.slice(chunkStart, this.index);
        this.index += 1;
        return out;
      }
      if (code === BACKSLASH) {
        out += this.text.slice(chunkStart, this.index);
        this.index += 1;
        out += this.readEscape();
        chunkStart = this.index;
        continue;
      }
      if (code < 0x20) {
        throw this.error(
          `unescaped control character U+${code.toString(16).toUpperCase().padStart(4, '0')} ` +
            'in a string',
        );
      }
      this.index += 1;
    }
  }

  /** The character an escape sequence denotes. The cursor sits just past the backslash. */
  private readEscape(): string {
    const code = this.peek();
    if (code === -1) {
      throw this.error('unterminated escape sequence');
    }
    this.index += 1;
    if (code === LOWER_U) {
      let unit = 0;
      for (let digit = 0; digit < 4; digit += 1) {
        const value = hexValue(this.peek());
        if (value < 0) {
          throw this.error('a \\u escape needs four hexadecimal digits');
        }
        unit = unit * 16 + value;
        this.index += 1;
      }
      // `fromCharCode`, not `fromCodePoint`: an unpaired surrogate stays unpaired, which is
      // the fact `json.loads` preserves on the Python side and the serializer refuses.
      return String.fromCharCode(unit);
    }
    const short = SHORT_UNESCAPES.get(code);
    if (short === undefined) {
      throw this.error(`invalid escape sequence \\${String.fromCharCode(code)}`);
    }
    return short;
  }

  /**
   * Read a number literal.
   *
   * An INTEGER literal beyond +/-2^53 becomes a `bigint`; everything else -- including a
   * float literal of any magnitude, which is a genuine binary float in Python too --
   * becomes a `number`.
   */
  private parseNumber(): number | bigint {
    const start = this.index;
    if (this.peek() === 0x2d) {
      this.index += 1;
    }
    if (this.peek() === 0x30) {
      this.index += 1;
    } else if (isDigit(this.peek())) {
      while (isDigit(this.peek())) {
        this.index += 1;
      }
    } else {
      throw this.error('expected a digit');
    }
    let integral = true;
    if (this.peek() === 0x2e) {
      integral = false;
      this.index += 1;
      if (!isDigit(this.peek())) {
        throw this.error('expected a digit after the decimal point');
      }
      while (isDigit(this.peek())) {
        this.index += 1;
      }
    }
    if (this.peek() === 0x65 || this.peek() === 0x45) {
      integral = false;
      this.index += 1;
      if (this.peek() === 0x2b || this.peek() === 0x2d) {
        this.index += 1;
      }
      if (!isDigit(this.peek())) {
        throw this.error('expected a digit in the exponent');
      }
      while (isDigit(this.peek())) {
        this.index += 1;
      }
    }
    const literal = this.text.slice(start, this.index);
    if (integral) {
      const magnitude = BigInt(literal);
      if (magnitude > MAX_EXACT_INTEGER_BIGINT || magnitude < -MAX_EXACT_INTEGER_BIGINT) {
        return magnitude;
      }
    }
    return Number(literal);
  }

  private parseObject(): { [key: string]: CanonicalValue } {
    this.expect(0x7b, 'an object');
    const record = {} as { [key: string]: CanonicalValue };
    this.skipWhitespace();
    if (this.peek() === 0x7d) {
      this.index += 1;
      return record;
    }
    for (;;) {
      this.skipWhitespace();
      if (this.peek() !== QUOTE) {
        throw this.error('expected a string as the object member name');
      }
      const name = this.parseString();
      this.skipWhitespace();
      this.expect(0x3a, "':' after the object member name");
      this.skipWhitespace();
      const value = this.parseValue();
      // `defineProperty`, not assignment: a member literally named `__proto__` is DATA, and
      // assigning it would reassign the object's prototype instead of storing it. A repeated
      // name keeps its first position and takes its last value, as `JSON.parse` does.
      Object.defineProperty(record, name, {
        value,
        writable: true,
        enumerable: true,
        configurable: true,
      });
      this.skipWhitespace();
      const next = this.peek();
      if (next === 0x2c) {
        this.index += 1;
        continue;
      }
      if (next === 0x7d) {
        this.index += 1;
        return record;
      }
      throw this.error("expected ',' or '}'");
    }
  }

  private parseArray(): CanonicalValue[] {
    this.expect(0x5b, 'an array');
    const members: CanonicalValue[] = [];
    this.skipWhitespace();
    if (this.peek() === 0x5d) {
      this.index += 1;
      return members;
    }
    for (;;) {
      this.skipWhitespace();
      members.push(this.parseValue());
      this.skipWhitespace();
      const next = this.peek();
      if (next === 0x2c) {
        this.index += 1;
        continue;
      }
      if (next === 0x5d) {
        this.index += 1;
        return members;
      }
      throw this.error("expected ',' or ']'");
    }
  }
}

/**
 * Parse JSON text into the value the canonical engine has to judge.
 *
 * A pure function of `text`: no cache, no memo, no shared buffer, and -- unlike
 * `JSON.parse` on Node >= 24 -- no dependence on what was parsed before it. See the module
 * docstring for the measurement that made that a requirement rather than a nicety.
 */
export function parseCanonicalJson(text: string): CanonicalValue {
  return new JsonParser(text).parseDocument();
}

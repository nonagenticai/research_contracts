# D3 — decision brief: instance-relative cross-field rule pointers

**Status:** **CLOSED 2026-07-30 — option B.** Decided by George. `FND-002` task 4 is
unblocked.
**Owner:** still unassigned (`OWNERS.yaml` records `accountable_owner: UNASSIGNED`); the
decision was taken, the ownership question is separate and open.
**Evidence, before:** `tests/test_fnd002_task4_blocked.py` — 85 passing assertions stating the
blocker, of which 51 went red the moment D3 was implemented, exactly as designed.
**Evidence, after:** `tests/test_d3_relative_scope.py` — 160 checks stating the new semantics,
plus the regression guard that an un-opted-in rule still fails closed.

> **Two numbers in this brief were wrong and are corrected below.** The blast radius is
> **48 of 48** cells across **eight** rule-bearing schemas, not 30 across five; and the
> blocked-test file carried **85** assertions, not 55. Neither changes the decision — a wider
> blast radius argues harder for the additive fix — but the record has to be right. See §2.

---

## 1. What D3 actually is

A released cross-field rule's operands are **JSON Pointers resolved against the instance
root**. `structural._collect` therefore refuses to collect a rule it reached through a
keyword that *moves* the instance location, and raises `CrossFieldError` rather than
evaluating it against the wrong object:

```
urn:datacompany:d3-probe:1: released cross-field rule 'equal' is declared below a child
keyword, but released rule pointers are instance-root-absolute, so this engine cannot
evaluate it. Declare the rule at the root of the composed schema with absolute pointers
instead.
```

The failure is **closed**, not silent. That is the one good property here and it must be
preserved by whatever replaces it.

## 2. The wave-2 register understates the scope — by eight schemas, not five

The session plan and `EXTENSIONS.md` §6.1 both describe D3 as a property of
`pinned-version-ref:1#/$defs/singleton`. It is not. The raise is keyed on **the position a
rule is reached at**, never on which schema declared it, so it fires for *every* released
rule-bearing schema at *every* child-keyword position.

Measured, not inferred (`test_every_rule_bearing_schema_raises_at_every_child_position`).
**The table as first written listed five schemas and 30 cells. The parametrisation it cites
derives its schema list from the corpus and actually covered eight**, so the real figure is
**48 of 48**; the three omitted rows are added below in italics:

| Released schema carrying a root-level rule | `properties` | `items` | `prefixItems` | `additionalProperties` | `patternProperties` | `allOf`→`properties` |
|---|---|---|---|---|---|---|
| `bitemporal-assertion:1` | raise | raise | raise | raise | raise | raise |
| `bitemporal-assertion:1#/$defs/command` | raise | raise | raise | raise | raise | raise |
| `canonical-hash-profile:1` | raise | raise | raise | raise | raise | raise |
| `pinned-version-ref:1#/$defs/singleton` | raise | raise | raise | raise | raise | raise |
| `reference-verification-receipt:1` | raise | raise | raise | raise | raise | raise |
| *`page:1#/$defs/page_request`* | raise | raise | raise | raise | raise | raise |
| *`research-access-context:1`* | raise | raise | raise | raise | raise | raise |
| *`run-manifest:1`* | raise | raise | raise | raise | raise | raise |

**48 of 48 cells raise.** The false-positive control is the other half of the same test: the
same eight schemas at the four *in-place* positions (`$ref`, `allOf`, `anyOf`, `oneOf` at a
composed root) all collect **and evaluate** their rules and report real failures. So the
raise is about position, not about those schemas being broken.

The undercount mattered in one specific way: `page:1#/$defs/page_request` carries its own
`$comment` recording that it "is therefore validated as its OWN schema_ref, not composed as a
property of an operation request", and `research-access-context:1` and `run-manifest:1` carry
the same note. Those three constraints were D3 fallout that the brief did not attribute to
D3, and closing it removes all three.

## 3. Why this blocks task 4 specifically, in three independent ways

Task 4's own wording (`00-shared-foundation.md:322-329`) requires embedding three
rule-bearing shapes as members of an evidence schema:

| Task 4 clause | Shape it must embed | Raises because |
|---|---|---|
| "migrate document/evidence/rights/artifact references to compose the complete canonical ref shape" | `pinned-version-ref:1#/$defs/singleton` — the registered-singleton owner, whose released fixture is `fixtures/canonical-references/v1/valid/registered-singleton-ref.json` | one root-level `equal` |
| "define its action/use-basis-specific `EvidenceResolutionReceipt`" | `reference-verification-receipt:1` | one `equal`, one `equal_when_both_present` |
| evidence validity and recording intervals | `bitemporal-assertion:1` | two `half_open_interval` |

**A decision that unblocks only the singleton unblocks none of task 4.** Any one of the
three is sufficient to stop it.

## 4. The options

### Option A — instance-relative rule pointers (vocabulary version 2)

Rule operands become relative to the location the rule was *reached at*, and the collector
carries that location down through the child keywords, evaluating the rule once per matching
instance location (once per array element, once per matching pattern property, …).

- **Unblocks:** all three task-4 compositions, and every future one.
- **Cost:** changes the meaning of every existing rule operand, so it is a
  **vocabulary version 2** change. All five released rule-bearing schemas must be re-read
  under the new semantics — at a document root the relative and absolute readings coincide,
  so the released rules are unaffected *in value*, but that has to be asserted, not assumed.
- **Two-language cost:** the TypeScript port has no cross-field evaluator yet, so this is
  the cheapest moment in the project to change the semantics — nothing has to be un-ported.
- **Risk:** per-location evaluation multiplies failure messages. `unique_by` under an
  `items` would run once per element and report N failures where one is meant.

### Option B — an explicit `scope` member on the rule

Keep absolute pointers as the default and let a rule opt in:
`{"rule": "equal", "scope": "relative", "left": "/entity_id", "right": "/version_id"}`.

- **Unblocks:** the same three, once each released rule is annotated.
- **Cost:** additive, so it is a **minor** vocabulary bump rather than a version 2. Existing
  rules keep their meaning with no re-reading.
- **Risk:** two pointer languages in one member, distinguished by a sibling key. `EXTENSIONS.md`
  §1.4 already records that the repository has **three** lexically identical pointer
  languages and calls it "the single easiest thing for a second implementation to get
  wrong". This adds a fourth.

### Option C — leave the vocabulary alone; task 4 declares its rules at its own root

The evidence schema re-declares `equal /evidence_pin/entity_id /evidence_pin/version_id`
itself, with absolute pointers.

- **Unblocks:** task 4, with no engine or vocabulary change at all.
- **Cost:** it is exactly what `pinned-version-ref:1#/$defs/singleton`'s own `$comment`
  forbids — *"Consumers MUST NOT invent this mapping locally"* — and
  `00-shared-foundation.md:189` restates it: no schema may use a *"locally invented singleton
  mapping"*. Every composing schema re-states the rule at its own root, at its own pointer
  depth, and one that forgets is silently unguarded.
- **Proven mechanically hazardous:** `test_the_documented_workaround_is_not_one` composes a
  pin as a property and declares `equal /entity_id /version_id` at the composing root. The
  rule **evaluates**, reports **no failure**, and the nested pin genuinely violates the
  singleton equality — while the same rule *does* fire on the composing object's own
  members. It is not that the workaround is ugly; it silently asserts a different
  proposition that looks identical.

### Option D — task 4 embeds only rule-free shapes

Compose the plain `pinned-version-ref:1` root (which carries no rules) and move receipt and
bitemporal shapes to sibling top-level documents linked by pin rather than nested.

- **Unblocks:** a *reduced* task 4, today, with no vocabulary change.
- **Cost:** it re-shapes the domain model to fit an engine limitation. The evidence schema no
  longer *contains* its resolution receipt, so nothing structurally binds them and
  "positive and rejected verification produce the exact immutable receipts" becomes a
  runtime convention.

## 5. Recommendation, and what is *not* being recommended

**Option B**, on three grounds: it is additive rather than a version-2 re-reading; it is the
only option that keeps the released rules' meaning literally unchanged; and its one real
risk (a fourth pointer language) is a *documentation* problem, where Option C's risk is a
silent wrong answer that this repository has already reproduced under test.

If the fourth-pointer-language objection is decisive, **Option A** is the correct second
choice and now is the cheapest moment for it, because the TypeScript cross-field evaluator
does not exist yet.

**Options C and D are recorded so they are visibly rejected, not so they are available.**
C is forbidden by the released `$comment` and demonstrated to fail silently; D solves an
engine problem by editing the domain model.

## 6. What was implemented

Option B, as recommended. All 13 released rules across the eight schemas now declare
`"scope": "relative"`, which is meaning-preserving because the relative and absolute bases
coincide at a document root — asserted by
`test_relative_and_absolute_agree_exactly_at_a_document_root` over instances that make each
rule both fail and hold, requiring byte-identical failure text, rather than assumed.

Retained deliberately: an `absolute`-scoped rule below a child keyword still raises, and
`contains`/`propertyNames` raise at **any** scope. Failing closed was the one good property of
the old behaviour and option B does not weaken it.

Normative record: `EXTENSIONS.md` §1.3, §1.4, §3.1 and §6.1; the `scope` member is registered
in `schemas/meta/datacompany-extension-vocabulary.v1.schema.json`, which has
`unevaluatedProperties: false`, so an unregistered spelling is rejected at authoring time.

## 7. Two adjacent vocabulary gaps found while writing FND-002 tasks 2/3/6

Both are the same class as D3 — the vocabulary cannot express something the contract needs —
and both are recorded in `config/foundation-decisions.json` with options:

- **D8 (new).** A **set-like array of scalars cannot be declared at all**.
  `canonical-hash-profile.v1#/$defs/hash_view_pointer` requires a leading `/` and
  `minLength: 2`, so neither `"/"` nor RFC 6901's whole-document `""` is a legal `order_key`
  entry, and `hash_view._pointer_at` resolves an order key only inside a `dict` member.
  Consequence: five released foundation arrays that are semantically sets
  (`pack_refs`, `schema_refs`, `packages`, `numerical_library_versions`, `supported_locales`)
  are declared `ordered`. Duplicates are still rejected by `uniqueItems`; **member order is
  unguarded**, so two services holding the same collection in two orders compute two
  different canonical hashes. Proven both ways in
  `test_D8_a_set_like_array_of_scalars_cannot_be_declared_at_all`, with an object-member
  control that sorts correctly.
- **`unique_by` has no when-present sibling.** `equal` has `equal_when_both_present`;
  `unique_by` and `disjoint` do not. Since WS1 closed D2c, an absent target array is a loud
  failure, so any collection guarded by `unique_by` becomes *de facto* required. This forced
  `sort` to be required on `page:1#/$defs/page_request` (IMP-DEC-FND002-018). Here the forced
  outcome happens to be the more correct contract; it will not always be.

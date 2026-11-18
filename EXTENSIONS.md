# The `x-datacompany-*` extension vocabulary

**Vocabulary version: 1.2** (D3 added `scope` at 1.1; D9 added
`x-datacompany-hash-declaration-only` at 1.2 — see [§1.3](#13-versioning))
**Accountable owner: UNASSIGNED** — see [§0](#0-status).
**Normative status:** this document is the declaration required by
`DataCompany/16-datacompany-canonical-domain-data-model.md:113-119`. It is **descriptive of the
released Python engine** and **prescriptive for every other implementation**.

**Engine baseline: `377c1b6`** (WS1, the Python portability wave). Every behaviour below was
reproduced against that commit, not against the pre-WS1 engine this document was first
derived from. Line citations are `377c1b6` line numbers. Where WS1 closed a hole, the
**fixed** behaviour is what is specified — a normative document that documents a fixed bug
is worse than no document, because the TypeScript port is written against it. What WS1
closed and what it left open is itemised in
[§7.0](#70-what-ws1-377c1b6-closed-and-what-it-did-not).

WS2 (`25755f2`, the TypeScript hash engine) changed **no** Python engine file and **no**
schema, so nothing here is derived from it. Its one effect on this document is that the G1
sort divergence is now covered by a committed fixture rather than by nothing
([§3.3](#33-x-datacompany-array)); the fixture harness total is **113**.

---

## 0. Status

### 0.1 Ownership is unresolved and must be resolved before this vocabulary is released

`OWNERS.yaml` records `accountable_owner: UNASSIGNED` and `accountable_reviewer:
UNASSIGNED` for this repository, and no `CODEOWNERS` rule may be enabled until accountable
ownership is assigned. **This vocabulary therefore has no owner.** No owner is invented
here.

Two questions are open and are George's to close (wave-2 session plan, open question 3):

| # | Open question |
|---|---|
| **OQ-1** | **Who owns `x-datacompany-*`?** Document 16 section 2.5 requires an extension to declare an owner. Until one is assigned, the "declare their … owner" clause is **not met**, and this document records the gap rather than papering over it. |
| **OQ-2** | **Where does this vocabulary live?** It is placed in `research_contracts` by wave-2 decision H because the port needs a written target *now*. Whether it should instead be a section of document 16 — which is where every other canonical convention lives — is not decided. If it moves, the meta-schema and its test must move with it or the declaration stops being executable. |

Until OQ-1 closes, treat every "MUST" below as binding on implementations and **not** as
evidence that the extension is conformant with section 2.5. It is not: it fails that
section's owner clause by construction.

### 0.2 What is complete

| Section 2.5 clause | Status |
|---|---|
| MUST declare their **schema** | **Met, executably** — `schemas/meta/datacompany-extension-vocabulary.v1.schema.json`, enforced by `tests/test_extension_vocabulary.py` over every committed `*.schema.json`. |
| MUST declare their **vocabulary** | **Met** — [§2](#2-the-registry), a closed enum in the meta-schema. |
| MUST declare their **owner** | **NOT met** — OQ-1. |
| MUST declare their **version** | **Met** — vocabulary version 1.2, [§1.3](#13-versioning). |
| MUST declare their **validation rules** | **Met** — [§3](#3-the-annotations)–[§4](#4-the-cross-field-operators), plus the meta-schema. |
| MUST be additive and namespaced | **Met** — every name is under the `x-datacompany-` prefix and every annotation is ignorable by a plain JSON Schema 2020-12 validator. |
| MUST preserve unknown extension values | **Partially met, and this is a hazard** — see [§7.1](#71-an-unregistered-annotation-name-is-preserved-and-ignored). |

---

## 1. Scope

### 1.1 What these annotations are

JSON Schema 2020-12 cannot express two classes of rule this contract depends on:

1. **Cross-field comparisons.** No keyword compares two instance locations, so "the
   interval `[valid_from, valid_to)` is non-empty" and "the receipt's subject is owned by
   its consumer" cannot be schema keywords.
2. **Hash-view declarations.** The canonical content hash (shared foundation section 4.3)
   is computed over a *semantic view* of the instance, not the instance. Which paths are
   in that view, which are removed, which arrays are sets, and which subtrees are hashed
   verbatim are properties of the schema and must travel with it.

Both are carried as `x-datacompany-*` members on schema objects. A validator that does not
know them ignores them, which is exactly the additive-and-namespaced requirement — and is
also exactly why [§7](#7-ambiguities-defects-and-divergences-in-the-released-implementation)
matters: *silent ignoring is the failure mode of the whole design.*

### 1.2 Where the authority lives

The **released Python engine is the reference implementation**, and this document is
derived from it, not from intent:

| Concern | Source of truth |
|---|---|
| Cross-field collection and evaluation | `src/research_contracts/canonical/structural.py` |
| Hash-view manifest derivation from annotations | `src/research_contracts/canonical/hash_profile.py` |
| Hash-view construction from a manifest | `src/research_contracts/canonical/hash_view.py` |
| Canonical serialization (RFC 8785) | `src/research_contracts/canonical/jcs.py` |
| Manifest shape and the closed exclusion-reason set | `schemas/canonical/canonical-hash-profile.v1.schema.json` |
| Annotation shape | `schemas/meta/datacompany-extension-vocabulary.v1.schema.json` |

Where the implementation is ambiguous, self-contradictory, or fails open, this document
says so in [§7](#7-ambiguities-defects-and-divergences-in-the-released-implementation) and
does **not** invent a semantic to make the gap disappear.

### 1.3 Versioning

The vocabulary is versioned as a whole, not per annotation. **This is version 1.2.** Two
additive minor bumps have landed:

* **1.0 → 1.1**, D3 (option B, 2026-07-30): the `scope` member on a cross-field rule. Adding
  a member with a default that reproduces the previous meaning is a *minor* change by the
  first rule below, and it is minor rather than hash-affecting only because relative and
  absolute coincide at a document root — see
  [§6.1](#61-d3--closed-instance-relative-rule-pointers).
* **1.1 → 1.2**, D9 (2026-08-03): `x-datacompany-hash-declaration-only`
  ([§3.6](#36-x-datacompany-hash-declaration-only)). Adding a **name** is minor by the first rule
  below, and no rule released before it changed meaning: a schema that does not carry the new
  name derives the manifest it always derived. That was **measured**, not argued — all 18
  released schemas were re-derived before and after and the diff is empty, with two positive
  controls proving the diff harness detects a change when there is one
  ([§6.3.1](#631-d9--closed-the-schema-route-into-an-opaque-subtree)). The empty diff proves
  the addition is **inert on the committed corpus**, which is the blast-radius question; it is
  not evidence of correctness, since deleting the annotation would produce the same zero.

Neither of those bumped `DERIVATION_PROFILE_VERSION`, by the second rule below: neither
changed what an existing annotation means, so no previously computed `content_hash` was
invalidated and no committed manifest's bytes moved.

**`DERIVATION_PROFILE_VERSION` is 2 since 2026-08-04.**
[§5.2](#52-the-derivation-pipeline)'s exclusion cascade was changed — `arrays` is filtered by
prefix like the other two members instead of by exact match — which is a change to what
`x-datacompany-hash-excluded` *means* for a nested array. The observable delta on the committed
corpus is zero and every committed manifest was regenerated anyway: `profile_version` names
the rule set that produced a manifest, so a version that only moves when the bytes move is a
version no consumer can act on.

**The vocabulary version does not move with it, and the second rule below is why — read
carefully, because the first draft of this paragraph got it wrong.** It justified holding the
vocabulary at 1.2 on the grounds that "no name was added, removed or renamed", which is the
*first* rule's criterion and not an exemption the second offers; the second rule and the
practice were left disagreeing. The actual reason is the second rule's own **premise**. It
defines a canonical-hash-affecting change as one that "changes the bytes of the hash view and
therefore invalidates every previously computed `content_hash`", and §5.2's change does
neither — not merely on the committed corpus, but **for every instance of every schema**. An
`arrays` entry beneath an excluded pointer is never consulted, because the excluded subtree is
never visited, so removing it cannot move a byte. Measured, not argued: an instance carrying
`/sig/parts` out of order hashes identically under a manifest that retains the entry and one
that drops it, against a control that reports a difference when one exists. The premise fails,
so the consequent — a new vocabulary version, and invalidated content hashes — does not
attach. What *did* change is the rule set, and `profile_version` is the version that names it.

**[§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04)'s closure sits in the same
place and is the sharper case,** because it is explicitly a *behaviour change for consumers*:
twelve released schemas became non-extensible, previously-accepted annotation values are now
refused, and a domain schema composing an extensible envelope must now declare its own point.
None of that moves a hash-view byte — `x-datacompany-composition-point` contributes no pointer,
exclusion or ordering rule — so the second rule is silent about it too. **State the limit
rather than let it pass as covered:** these three rules govern the *canonical hash*, and they
have no bucket for a change that narrows what the engine *accepts at authoring time* while
leaving every hash identical. That kind of change is recorded where it is enforced — §6.4,
[§8](#8-where-the-meta-schema-is-deliberately-stricter-than-the-engine) and §9 item 14 — and
signalled by `profile_version`, which is the version a consumer can actually test, since the
refusals happen at derivation. Adding a fourth rule for it is a decision nobody has taken and
is not taken here.

- Adding a name, adding an operator, or widening an operand shape is a **minor** change
  and bumps the vocabulary version.
- Changing what an existing annotation *means* is a **canonical-hash-affecting** change:
  it changes the bytes of the hash view and therefore invalidates every previously
  computed `content_hash`. It is a schema compatibility change under
  `canonical-hash-profile.v1`'s own rule that "adding or changing a path, normalization
  rule or collection kind is a schema compatibility change", and it requires a new
  vocabulary version **and** a new `profile_version`.
- The annotation names carry no version suffix. A future version 2 that has to coexist
  with version 1 must therefore introduce new names; renaming in place would be
  indistinguishable from a typo, which the engine ignores in silence
  ([§7.1](#71-an-unregistered-annotation-name-is-preserved-and-ignored)).

### 1.4 Pointer syntax — four different pointer languages, identical lexically

This is the single easiest thing for a second implementation to get wrong.

| | Rule operands, `scope: absolute` | Rule operands, `scope: relative` | Hash-view manifest pointers |
|---|---|---|---|
| Resolved against | the **instance root** | the **location the rule was reached at** | the **instance root** |
| Resolved by | `structural._at` | `structural._at`, after `_locations` derives the base | `hash_view._pointer_at` / prefix matching |
| Array element token | **none**; `-` does not resolve | **none**; `-` does not resolve | `-` means "every element" |
| Numeric token | a real array index | a real array index | a literal object member name |
| Traverses arrays | yes, by index | yes, by index | no — `_pointer_at` returns absent on a non-`dict` node |
| Lexical form | `^(/([^/~]|~[01])*)+$` | `^(/([^/~]|~[01])*)+$` (identical) | `^(/([^/~]|~[01])*)+$` (identical) |

An implementation MUST NOT share one pointer resolver between the manifest language and the
rule languages. `/pack_refs/-` is a valid *manifest* pointer meaning every pin, and a *rule*
pointer that resolves to nothing.

The two rule languages share a resolver but **not** a base, and nothing in an operand's own
text distinguishes them: `/entity_id` is a legal operand under either scope and means a
different location under each. **The `scope` member is the only discriminator, and it MUST be
read before any operand is interpreted.** At a document root the two bases coincide (the base
is the empty pointer), which is what made adding `scope` a meaning-preserving change to every
rule released before D3 — see [§6.1](#61-d3--closed-instance-relative-rule-pointers).

Set-like array `order_key` entries are a fourth, **member-relative** pointer language:
resolved by `hash_view._pointer_at` against an individual array member, and traversing
objects only. Since D8 ([§6.2](#62-d8--closed-a-set-like-array-of-scalars-is-declarable)) it
is the one language that also admits RFC 6901's whole-document pointer `""`, which addresses
the array **member itself** and is what makes a set of scalars declarable. It is a separate
meta-schema definition (`order_key_pointer`) rather than a widening of `hash_view_pointer`,
so `""` stays illegal in `included_pointers`, `excluded_pointers` and `opaque_pointers`,
where "the whole instance" is not a path the hash view can include or exclude.

---

## 2. The registry

| Annotation | Version | Owner | May appear on | Read by | Affects the canonical hash |
|---|---|---|---|---|---|
| [`x-datacompany-cross-field`](#31-x-datacompany-cross-field) | 1 | UNASSIGNED | any schema object reachable from a validated `schema_ref` through `$ref` or an in-place applicator | `structural.py` | **No** (gates hashing, does not change bytes — [§5.1](#51-what-changes-the-bytes)) |
| [`x-datacompany-hash-excluded`](#32-x-datacompany-hash-excluded-and-x-datacompany-hash-exclusion-reason) | 1 | UNASSIGNED | any schema object that has a hash-view pointer | `hash_profile.py` | **Yes** — removes a path and its whole subtree |
| [`x-datacompany-hash-exclusion-reason`](#32-x-datacompany-hash-excluded-and-x-datacompany-hash-exclusion-reason) | 1 | UNASSIGNED | only beside `x-datacompany-hash-excluded: true` | `hash_profile.py` | **No** directly; **gates** the exclusion that does |
| [`x-datacompany-array`](#33-x-datacompany-array) | 1 | UNASSIGNED | a schema object describing an array | `hash_profile.py` | **Yes** — decides member order for a set-like array |
| [`x-datacompany-hash-opaque`](#34-x-datacompany-hash-opaque) | 1 | UNASSIGNED | a schema object describing a payload subtree | `hash_profile.py`, `hash_view.py` | **Yes** — admits undeclared members that would otherwise be rejected |
| [`x-datacompany-hash-declaration-only`](#36-x-datacompany-hash-declaration-only) | 1.2 | UNASSIGNED | a schema object **strictly inside** an `x-datacompany-hash-opaque` subtree | `hash_profile.py` | **Yes** — keeps a pointer OUT of `included_pointers`, which is what preserves the enclosing subtree's opacity |
| [`x-datacompany-composition-point`](#35-x-datacompany-composition-point) | 1 | UNASSIGNED | the root of an envelope schema | `hash_profile.py` | **No** — it gates *whether* an envelope may be extended, and contributes no byte of its own ([§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04)) |

Every entry's owner is UNASSIGNED for the reason in [§0.1](#01-ownership-is-unresolved-and-must-be-resolved-before-this-vocabulary-is-released). This is a
recorded gap, not a placeholder to be filled in by an implementer.

---

## 3. The annotations

### 3.1 `x-datacompany-cross-field`

**Purpose.** Declare rules comparing two or more instance locations, which JSON Schema
2020-12 cannot express.

**Value shape.** A non-empty JSON array of rule objects. Each rule object has:

| Member | Required | Meaning |
|---|---|---|
| `rule` | yes | one of the five operators in [§4](#4-the-cross-field-operators) |
| `name` | no | identifier used in the failure text; **defaults to the operator token**, so two unnamed rules of the same kind produce indistinguishable failures |
| `scope` | no | `absolute` (the default) or `relative`; chooses the base the operands resolve against ([§1.4](#14-pointer-syntax--four-different-pointer-languages-identical-lexically)) |
| `$comment` | no | prose, carried nowhere |
| operator operands | per operator | see [§4](#4-the-cross-field-operators) |

**Where it may legally appear.** At the root of the schema named by the `schema_ref` being
validated, or anywhere reachable from it through `$ref`, `allOf`, `anyOf`, `oneOf`, `then`
or `else` — the *in-place* applicators, which do not move the instance location. A rule of
either scope is evaluable at all of these, and `relative` there means exactly what `absolute`
means, because the base is the empty pointer.

Below `properties`, `patternProperties`, `items`, `prefixItems` or `additionalProperties` —
the keywords that **move** the instance location — the two scopes differ:

- `scope: relative` is evaluated **once per instance location the keyword addresses**: once
  per array element under `items`, once per matching member under `patternProperties`, and so
  on. Each failure names the full absolute path it looked at, so N failures under `items` are
  N findings rather than one finding repeated.
- `scope: absolute` (including a rule that simply omits `scope`) MUST NOT appear there.
  Its operands are instance-root-absolute, so evaluating it at a child location would
  silently address the wrong object. `structural._collect` walks the child keywords
  *specifically to detect this* and raises `CrossFieldError` rather than dropping the rule.
  **This is a hard failure at collection time and it is deliberately retained**: it is the
  property that kept D3 from becoming a silent hole, and option B changed nothing about it.

Neither scope may appear below `contains` or `propertyNames`. Those have no single instance
location for a relative pointer to be relative to — `contains` applies to *some* unidentified
element, and `propertyNames` applies to a property *name* rather than to a value — so a rule
there raises at **any** scope.

`$defs` is **not** a child keyword for this purpose: a definitions bag has no instance
location, so a rule inside one is collected only where that def is actually `$ref`-composed
at an evaluable position.

**Validation rules.**

1. Rules are collected once per `schema_ref` and **deduplicated by content**: the marker is
   the **RFC 8785 canonical bytes of the rule object** (`structural._identity_marker`), so two
   structurally identical rules reached by two composition paths are evaluated once —
   including when the two spellings differ only in member order, which any JSON round-trip
   can produce. (Before `377c1b6` the marker was `repr(sorted(rule.items()))`, which no
   other language reproduces.)
2. Every collected rule is evaluated on every `validate_instance` /
   `assert_valid_instance` call. `validate_schema_only` deliberately skips them and
   therefore **accepts instances the contract rejects**.
3. Failures accumulate into a list. `validate_instance` returns schema failures followed by
   cross-field failures; `assert_valid_instance` raises `SchemaValidationError` for the
   first layer and `CrossFieldError` for the second, so a caller can tell them apart.
4. **Fail closed on an unknown operator.** An unregistered `rule` value raises
   `CrossFieldError`. Two properties of *how* it fails are load-bearing and MUST be
   reproduced: the raise happens at **evaluation** time, not collection time (so
   `collect_cross_field_rules` happily returns an unknown rule), and it **discards every
   failure already collected in the same call** rather than appending to them.

**Effect on the canonical hash.** None directly. `compute_content_hash` calls
`assert_valid_instance` first, so a violating instance cannot be hashed at all — the rules
gate hashing without contributing a byte to it.

**Released uses.** `bitemporal-assertion:1` (two `half_open_interval`, plus one more on
`#/$defs/command`), `reference-verification-receipt:1` (`equal`,
`equal_when_both_present`), `canonical-hash-profile:1` (two `unique_by`, two `disjoint`),
`pinned-version-ref:1#/$defs/singleton` (one `equal`), `page:1#/$defs/page_request` (one
`unique_by`), `research-access-context:1` (one `half_open_interval`), `run-manifest:1`
(one `disjoint`) and `evidence-location-version:1` (one `equal`, binding the typed alias
`evidence_location_id` to the envelope's `entity_id` — IMP-DEC-FND002-034). All 14 released
rules declare `"scope": "relative"`; the 13 that predate FND-002 task 4 were annotated by D3.

Note what is NOT here, and cannot be: `locator-selector:1` declares no rule anywhere, because
a per-selector-kind invariant is inexpressible. Rule collection is static over the whole schema
tree — `then` and every `oneOf` branch are walked unconditionally — so a rule declared inside
one guard's `then` is collected once and evaluated for **every** instance whatever its
`selector_type`. Measured in both engines; asserted by
`test_a_selector_cross_field_rule_would_fire_across_every_branch`. The row-addressing exclusive
choice and the target-ref exclusive choice are therefore plain JSON Schema (IMP-DEC-FND002-028),
and integer span ordering is recorded as inexpressible rather than worked around
(IMP-DEC-FND002-031).

---

### 3.2 `x-datacompany-hash-excluded` and `x-datacompany-hash-exclusion-reason`

**Purpose.** Remove a path, and everything under it, from the semantic hash view. The
paired reason makes the removal auditable and closed: a path may only be removed for one of
seven released reasons.

**Value shape.**

- `x-datacompany-hash-excluded`: the JSON literal `true`. **Nothing else has any effect.**
  `hash_profile._Walker.walk` tests `is True`, an identity comparison, so `false`, `0`, `1`,
  `"true"` and `null` are all silent no-ops that leave the path *inside* the hash view.
  A member that is not excluded MUST omit the annotation rather than write `false`.
- `x-datacompany-hash-exclusion-reason`: one of the closed set in
  `canonical-hash-profile.v1#/$defs/exclusion_reason`, read at runtime as
  `hash_profile.exclusion_reasons()`:
  `own_content_hash`, `signature`, `transport_envelope`, `resolution_observation`,
  `projection_or_cache`, `aggregate_version`, `recorded_until`.

**Where they may legally appear.** On any schema object the profile walker reaches with a
hash-view pointer: a `properties` entry, an `items`/`prefixItems` subschema, or a `$ref`
target composed at such a position. The two MUST appear together.

**Validation rules.**

1. `x-datacompany-hash-excluded: true` **without** a reason, or with a reason outside the
   closed set, raises `UnknownExclusionError` during derivation. Verified: the failure text
   names `None` as the offending reason. This direction **fails closed**.
2. A reason **without** the flag is silently discarded and the path stays in the hash view.
   This direction **fails open** — see [§7.2](#72-a-lone-exclusion-reason-is-discarded-in-silence).
3. Exclusion **cascades to the subtree**: `derive_hash_profile` drops every included
   pointer equal to or prefixed by an excluded pointer, and does the same for opaque
   pointers. At hash time, `hash_view._ViewBuilder._build_object` skips an excluded child before it
   looks at anything else, so nothing under it is ever visited.
4. **A nested target's `content_hash` is not excluded by this rule.** `pinned-version-ref`
   deliberately leaves `content_hash` in the view; only the object's *own* `content_hash`
   carries `own_content_hash`. Shared foundation section 4.3 step 3.

**Effect on the canonical hash. Yes — this is the annotation that changes the bytes.**
Adding, removing or re-pointing an exclusion changes the hash view and therefore every
`content_hash` of every instance of that schema.

**Released uses.** `stable-identity:1` `/aggregate_version` (`aggregate_version`);
`immutable-version:1` `/content_hash` (`own_content_hash`) and `/content_hash_signatures`
(`signature`); `bitemporal-assertion:1` `/recorded_until` (`recorded_until`);
`pinned-version-ref:1` `/resolved_at` (`resolution_observation`), which cascades to every
composed pin — `/pack_refs/-/resolved_at`, `/provenance_refs/-/resolved_at`,
`/profile_ref/resolved_at`, `/decision_ref/resolved_at`, `/subject_ref/resolved_at`,
`/subject_local_ref/resolved_at`, `/pinned_version_ref/resolved_at`. `transport_envelope`
and `projection_or_cache` are released reasons with **no released use**.

---

### 3.3 `x-datacompany-array`

**Purpose.** Declare an array's collection semantics. RFC 8785 preserves array order and
has no notion of a set, so without this declaration two services holding the same set in
two orders compute two different "canonical" hashes. An array with no declaration is
therefore rejected outright.

**Value shape.** A JSON object:

| Member | Required | Meaning |
|---|---|---|
| `kind` | yes | `"ordered"` or `"set"` |
| `order_key` | **iff `kind` is `"set"`** | non-empty, unique array of **member-relative** JSON Pointers |

`pointer` MUST NOT appear. `hash_profile._Walker.walk` builds the manifest entry as
`{"pointer": <derived>, **annotation}`, so an annotation carrying `pointer` **overrides the
walker's derived location** and silently re-targets the declaration at an unrelated path.
Verified: an annotation of `{"pointer": "/somewhere_else", "kind": "ordered"}` on the
property `/a` derives `{"pointer": "/somewhere_else", "kind": "ordered"}`. The meta-schema
closes this with `additionalProperties: false`; nothing in the engine does.

**Where it may legally appear.** On the schema object describing the array itself — the one
carrying `items` or `prefixItems` — including through a `$ref` (`set_of_pins` is declared
once and composed at four pointers).

**Validation rules.**

1. The value must be a JSON **object**. `hash_profile._Walker.walk` tests `isinstance(dict)`, so a
   string, array or boolean is **silently dropped** and the declaration is lost. The loss
   surfaces only if an instance actually carries that array, as `UndeclaredArrayError` at
   hash time. See [§7.3](#73-a-non-object-x-datacompany-array-is-dropped-in-silence).
2. `order_key` is required for `kind: "set"` and forbidden for `kind: "ordered"`, enforced
   by `canonical-hash-profile.v1#/$defs/array_declaration` after derivation and by the
   meta-schema before it.
3. **At most one declaration per pointer**, enforced by the `unique_by` rule
   `one_array_declaration_per_pointer` on the manifest — `uniqueItems` cannot express it,
   because two declarations of the same pointer differing in `kind` are distinct objects.
4. Every member of a set-like array MUST carry **every** `order_key` path. An absent path
   raises `MissingOrderKeyError`, deliberately distinct from a duplicate: an absent key is
   a fault, not evidence that two members are the same member. Two members that both carry
   an explicit `null` there **are** duplicates and fail as such.
5. Two set members with the same canonical order key raise `DuplicateSetMemberError`.

**Effect on the canonical hash. Yes, for `kind: "set"`.** Members are sorted by the
**UTF-8 bytes of the RFC 8785 canonicalization of the ordered list of order-key values**
(`hash_view._ViewBuilder._build_array`), then serialized in that order. For `kind: "ordered"` the
annotation changes no bytes but its **absence** makes the instance unhashable.

> **Porting hazard (G1, wave-2 plan §1.4) — now covered by a fixture.** This byte sort is
> *code-point* order, while RFC 8785 object member names sort by *UTF-16 code unit*
> (`jcs.utf16_sort_key`). The two disagree for astral characters. Both are correct as written and
> neither may be changed — changing either invalidates every existing content hash — but a
> port that reuses one comparator for both produces a different digest for an order key
> containing a non-BMP character.
>
> This document originally recorded "no fixture covers this today". That is **no longer
> true**: WS2 (`25755f2`) added
> `fixtures/canonical-hash/v1/vectors/set-like-array-astral-vs-private-use-order-key.json`
> to discriminate the two orders, taking the `hash/vectors` suite from 15 to 16 and the
> harness total to 113. A port that gets this wrong now fails a committed check rather than
> passing in silence.

**Released uses.** `pinned-version-ref:1#/$defs/set_of_pins`,
`{"kind": "set", "order_key": ["/owner_context", "/entity_type", "/entity_id", "/version_id"]}`,
composed at `/pack_refs`, `/provenance_refs` (`immutable-version:1`) and `/basis_refs`
(`bitemporal-assertion:1`). **No released schema declares `kind: "ordered"`.**

---

### 3.4 `x-datacompany-hash-opaque`

**Purpose.** Declare that a subtree is hashed **exactly as it arrives**, member by member,
without every member having to be declared. This is the escape hatch for an open domain
payload.

It exists because the alternative failed open. Silence used to mean "hash the whole subtree
undeclared", which meant every domain that shipped no profile extensions at all had its
payload hashed with no declaration behind it. The released rule is **declare none or
declare all, and say which**: an object either has its members declared one by one, or sits
in a subtree explicitly marked opaque. An object that is neither raises
`UndeclaredPathError`.

**Value shape.** The JSON literal `true`. `hash_profile._Walker.walk` tests `is True`, exactly as
for `x-datacompany-hash-excluded`; every other value is a silent no-op.

**Where it may legally appear.** On the schema object describing the subtree root — in
practice, the envelope's open payload point.

**Validation rules.**

1. Opacity is **inherited by the whole subtree**: `hash_view._ViewBuilder._is_declared_opaque` matches
   the declared pointer and any pointer prefixed by it.
2. **Declared children win over opacity — and only *included* children are declarations.**
   `hash_view.py` computes `opaque = not _has_included_children(pointer) and
   _is_declared_opaque(pointer)`. The moment a domain declares one member of the subtree,
   opacity is revoked and **every** member must be declared. An *exclusion* is the opposite
   act — it removes a descendant rather than declaring one — so it does not revoke opacity.
   Until 2026-08-02 this read "included *or* excluded", and that was the defect: excluding a
   signature from an opaque payload injected the payload into the prefix set, revoked its
   opacity, and made every undeclared sibling raise `UndeclaredPathError` — breaking the
   motivating case for the two annotations existing together. This is stated in the released `$comment` on
   `bitemporal-assertion:1` `/value`, and it is what keeps the **schema-annotation** route to
   declaring an array inside an opaque subtree blocked
   ([§6.3](#63-d4--closed-as-refuted-at-a-narrower-scope-than-it-was-written)). D4 itself is
   **closed as refuted**: the *profile-extension* route supplies the collection kind without
   adding a declared child, so the subtree stays opaque. Only the annotation route is shut.
3. Opacity does **not** waive the array declaration. An array inside an opaque subtree
   still raises `UndeclaredArrayError` without an `x-datacompany-array` entry for its pointer.
   Verified.
4. An exclusion beats opacity: `derive_hash_profile` drops any opaque pointer equal to or
   under an excluded pointer, and the manifest's `disjoint` rule
   `an_opaque_subtree_is_not_also_excluded` rejects a manifest that claims both.
5. Opacity on a **scalar** is harmless and inert — `_build_object` is the only reader, so a
   marked string is simply hashed as a string. Verified.

**Effect on the canonical hash. Yes.** It admits members that would otherwise raise, so it
strictly *widens* the hashed input. Removing an opaque declaration makes previously
hashable instances unhashable; adding one makes previously rejected instances hashable.
Both are compatibility changes.

**Released uses — three nodes, two shapes.** `bitemporal-assertion:1` `/value`, the open
domain payload this annotation was written for; and `/counts/exclusion_reasons` in **both**
`inclusion-set-export:1` and `inclusion-set-export:2`, a tally whose member names are the
review's own exclusion reason codes. The second shape is the first arriving from the other
direction: not an open payload a domain may extend, but a closed integer map whose KEYS are
data. Declaring its members is not merely inconvenient there, it is impossible — the key
set is a per-review configuration — so without the annotation every export carrying a
single reason code raises `UndeclaredPathError`.

It appears twice for that one shape because `:2` inherits `:1`'s counts block verbatim and
`:1` **stays released beside it**: a hash already sealed under `:1` is verified by resolving
that export's own recorded `schema_ref`, so retiring the document would not tidy the
registry, it would make every existing `:1` seal unverifiable.

---

### 3.5 `x-datacompany-composition-point`

**Purpose (as declared).** Name the `$defs` entry at which a domain schema attaches its own
fields to a released envelope, so that "where does a consumer extend this?" is a property of
the envelope rather than a convention.

**Value shape (as observed).** A document-relative JSON-Schema pointer string. The six
released uses spell **four** distinct targets — see the released-uses list below. This
paragraph read "All three released uses are the literal `"#/$defs/domain_extension"`" until
2026-08-04; both halves of that were wrong, and it is the same undercount §6.4 carried.

**Where it may legally appear.** At the root of an envelope schema — and the two rules below
disagree about how hard that is, which is worth stating precisely rather than summarising.

* Rule 1 is evaluated **wherever the derivation walk finds the annotation**, at any depth, in
  whatever document the node belongs to. A nested declaration is shape-checked and resolved
  exactly like a root one; nothing refuses it for being nested.
* Rule 2 reads **the document root and nowhere else**. So a schema declaring a valid point on
  a nested node derives cleanly *and* is non-extensible, which is a real combination and not
  an oversight. The refusal says which of the two it is and names where the declaration
  actually is, because "declares no `x-datacompany-composition-point`" was false about exactly
  that schema until 2026-08-04.

Root-only for rule 2 is a decision with a measured reason. Reading it wherever the walk
reaches pointer `""` would also make a schema extensible by *composing* an extensible
envelope — but it is **ambiguous on a released schema**: `run-manifest:1` declares
`#/$defs/manifest_extension` and composes `stable-identity:1`, which declares
`#/$defs/domain_extension`, so two points arrive at `""` and which one a consumer attaches at
is undecided. Both readings agree on every released schema (6 extensible, 13 not), so the
ambiguity buys nothing. **The consequence for consumers is real and is stated here rather
than left to be discovered: a domain schema written as `allOf: [{"$ref": <envelope>}]` is
non-extensible until it declares its own composition point**, even though the envelope it
composes declares one.

**Validation rules — two, since 2026-08-04.** This section read "**There are none.**" and
recorded that `42`, `null` and `"not-a-pointer"` were all accepted with no effect whatsoever.
[§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04) was decided and implemented
instead of retired, so:

1. `hash_profile._require_released_composition_point` refuses, at derivation, a value that is
   not a string beginning `#/$defs/`, **and one that does not resolve to a `$defs` entry of
   the document it is written in**. Resolution rather than a pattern match is the whole point
   of the second half: `"#/$defs/domian_extension"` satisfies the meta-schema's
   `composition_point` pattern exactly and names nothing, and only a resolver can see that.
2. `hash_profile.merge_profile_extensions` refuses an extension offered to an envelope that
   declares **no** composition point. It implemented the composition-point *concept* — a
   domain may contribute `included_pointers` and `arrays` and nothing else — while being
   driven by its `extensions` argument and never consulting this member, so every released
   schema was extensible in practice whether or not it said so. A schema without the
   annotation is now non-extensible.

What is **not** checked, stated rather than implied: *where* an extension attaches. The
composition point names a `$defs` entry in schema space; `included_pointers` and `arrays` are
RFC 6901 pointers in instance space, and every released composition point composes at the
envelope root, so a declared point induces no constraint on which instance pointers an
extension may name. The gate is presence and resolvability.

**Effect on the canonical hash. None** — it gates *whether* an envelope may be extended and
contributes no pointer, exclusion or ordering rule of its own.

**Released uses — six, in four spellings.** `#/$defs/domain_extension` on
`bitemporal-assertion:1`, `immutable-version:1` and `stable-identity:1`;
`#/$defs/problem_extension` on `problem-details:1`; `#/$defs/context_extension` on
`research-access-context:1`; `#/$defs/manifest_extension` on `run-manifest:1`. The other
**twelve** released schemas declare none and are therefore non-extensible; each was checked
individually and each is intentionally so — see
[§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04).

### 3.6 `x-datacompany-hash-declaration-only`

**Purpose.** Declare that a schema node is reached **only to carry annotations** and does not
declare a hashed path. Its `x-datacompany-array` still reaches the derived manifest; its pointer,
and every pointer beneath it, stays out of `included_pointers`. That is what lets an array
**inside** an `x-datacompany-hash-opaque` subtree carry the ordered/set-like declaration two
released `$comment`s require, without the `properties` chain that reaches it turning the
subtree into a declared prefix and revoking the opacity.

It exists because those two released statements were jointly unsatisfiable from any committed
schema — that is defect `D9`, closed by this annotation
([§6.3.1](#631-d9--closed-the-schema-route-into-an-opaque-subtree)):

> `bitemporal-assertion.v1` `/value`: "Arrays inside it still require their own ordered/set-like declaration."

> `canonical-hash-profile.v1` `arrays`: "An array that is not declared here has undeclared collection semantics and is rejected, **including inside an opaque subtree**."

**Value shape.** The JSON literal `true`. `hash_profile._Walker.walk` tests `is True`, exactly as
for `x-datacompany-hash-excluded` and `x-datacompany-hash-opaque`; every other value is a silent
no-op. The meta-schema pins `const: true`.

**Where it may legally appear.** On any schema object **strictly under** a node marked
`x-datacompany-hash-opaque` — never on the opaque node itself, and never outside an opaque
subtree. Both are **derivation errors**, not conventions: see the validation rules below.

**Validation rules.**

1. **The suppression cascades by prefix.** The flagged pointer and every pointer at or under
   it are removed from `included_pointers`, matching the released exclusion cascade
   (`hash_profile.py:_at_or_under`). This is load-bearing rather than tidy: an array *of
   objects* at `/value/tags` also yields `/value/tags/-/id` and `/value/tags/-/label` from
   the `items` walk, and an exact-match filter would leave those in — making `/value` a
   declared prefix again and revoking exactly the opacity the annotation preserves.
2. <a id="d9-arrays-rule"></a>**`arrays` is NEVER filtered by it.** That is the whole point:
   carrying a collection declaration *out* of a subtree whose paths stay undeclared is what
   the flag exists for, and filtering here would make both released `$comment`s quoted above
   unsatisfiable again. **This is the one canonical statement of the rule** —
   [§5.2](#52-the-derivation-pipeline) step 5, [§9](#9-porting-checklist) item 6 and §9 item
   12 link here instead of restating it, because it *was* restated in four places and only
   three of them moved when the hazard below changed sign.

   **The hazard inverted on 2026-08-04, and the old wording is recorded rather than quietly
   replaced.** This rule read: *"Do **not** copy §5.2's released `arrays` exact-match quirk
   here."* There is no quirk any more — §5.2's exclusion cascade filters `arrays` by prefix
   like everything else, under `profile_version` 2 — so that sentence now warns against
   copying something that does not exist, in the annotation's own normative rule list, which
   is exactly where a port author looks. **The danger points the other way now:** "the
   filters are consistent" is true of the *exclusion* cascade and says nothing about this
   one, so a reader who generalises one step further and filters `arrays` by
   `declaration_only` breaks D9 — in the direction that still looks green, because every
   committed manifest stays byte-identical. Both engines carry a comment at the filter
   saying so, and the call-site counts are pinned (`arrays` must be reached by the exclusion
   predicate and *not* by the declaration-only one) in
   `packages/typescript/test/coverage.test.ts`, "the exclusion cascade filters ALL THREE
   members by prefix, and declaration-only is a separate rule".
3. **It is collected during the walk and applied afterwards, never suppressed inline.** The
   flag can arrive through a `$ref` or through any of `allOf`/`anyOf`/`oneOf`/`then`/`else`
   — that is, *after* the `properties` loop that added the child pointer has already run. An
   inline check therefore derives a manifest that depends on how the schema was **written**
   rather than on what it means, and two implementations composing in different orders
   diverge in silence. Pinned by
   `test_the_same_declaration_derives_the_same_manifest_through_every_composition`.
4. **Outside an opaque subtree, derivation raises `HashProfileError`.** There it would
   silently remove a member from the hash view with no recorded reason and no
   `excluded_pointers` entry — a second, reasonless spelling of `x-datacompany-hash-excluded`.
   The message names that difference, because "rejected" alone sends an author looking for a
   typo.
5. **The flag and `x-datacompany-hash-opaque` may never sit on one node — unconditionally.**
   Allowing the pair would satisfy rule 4's "under an opaque pointer" trivially, so any
   author could suppress any pointer anywhere by writing `x-datacompany-hash-opaque` beside the
   flag. This rule was first written as "strictly under, never *at*", and that was
   **walk-past-able one level deeper**: a node carrying both annotations satisfies the
   ancestor test whenever it happens to sit inside *another* opaque subtree, so `/value`
   opaque with `/value/inner` opaque-and-flagged derived cleanly — the same bypass, merely
   relocated. The pair check now runs first and does not consult ancestors at all. The
   meta-schema forbids the pair per node as well, so the two gates agree.
6. **An opaque subtree may not both declare a member and carry the flag.** The released
   "declare none or declare all" rule: a declared sibling revokes the opacity, after which
   every member must be declared — and a declaration-only pointer deliberately is not one, so
   the shape would raise `UndeclaredPathError` at *hash* time, far from the schema that
   caused it. Diagnosed at derivation, naming both annotations. Grouped by each flag's
   **nearest** opaque ancestor, because opaque subtrees nest and an inner opaque root is a
   legitimate declared member of the outer one.
   **An EXCLUDED member is not a declared one**, and getting this wrong broke the motivating
   case: the rule was evaluated against the raw walk, where an excluded member is still a
   `properties` name, so `/value` opaque with `/value/sig` excluded and `/value/tags` flagged
   — the signed open payload the two annotations exist for *together*, plus the one array D9
   is about — was **refused**, while the runtime escape hatch hashed it correctly. D9 was
   therefore not closed for that shape at all. The rule now runs against the derived
   `included_pointers`, which is what
   [§3.4](#34-x-datacompany-hash-opaque) rule 2 already says decides opacity: "an *exclusion* is
   the opposite act".
7. **`opaque_pointers` is filtered by the flag too.** An opaque declaration *beneath* a
   declaration-only pointer would be the manifest asserting a path inside a subtree the same
   manifest says contributes no paths. Behaviourally inert — the enclosing opaque pointer
   already covers it by prefix — and therefore a rule with a test rather than a comment with
   an argument.
8. **One flag per `properties` chain is enough.** Because rule 1 cascades, marking the
   *outermost* node of a chain suppresses everything beneath it, and the `x-datacompany-array`
   further down needs no flag of its own. This is why the meta-schema does **not** require an
   annotation beside the flag — the flag-bearing node routinely carries only `properties`.
   See [§8](#8-where-the-meta-schema-is-deliberately-stricter-than-the-engine).

**Effect on the canonical hash. Yes, indirectly and decisively.** It changes nothing about
how a value is serialized; it changes which paths are `included_pointers`, and therefore
whether `hash_view._ViewBuilder._build_object` treats the enclosing subtree as opaque. Adding or removing
it on a released schema is a schema compatibility change under `canonical-hash-profile.v1`'s
own rule.

**Released uses. None.** No committed schema carries it — measured by
`test_no_released_schema_uses_the_annotation_so_no_committed_manifest_moved`, which walks the
corpus for the *key* rather than grepping for the *name* (`run-manifest.v1` discusses the
annotation in a `$comment` and carries it nowhere; a text census reported that schema as a
user). That measurement is the evidence behind **this annotation** not bumping
`DERIVATION_PROFILE_VERSION`, and it goes red the day a released schema adopts the
annotation, reopening the question deliberately rather than by omission. (The constant did
move, 1 → 2 on 2026-08-04, for [§5.2](#52-the-derivation-pipeline)'s exclusion cascade —
a different rule, and this measurement says nothing about it either way.)

**Committed vectors.** `fixtures/canonical-hash/v1/declaration-only/` — five self-contained
fixtures, each carrying its own probe schema, replayed by
`tests/test_declaration_only_annotation.py` and
`packages/typescript/test/declarationOnly.test.ts`. Two pin the capability (including the
byte-identical runtime-route manifest that *is* the closure of D9); three pin the refusals.

---

## 4. The cross-field operators

Five operators exist. `structural.check_cross_field_rules` dispatches on `rule` and raises
`CrossFieldError` on anything else.

Two general rules apply to all five:

- **Operands are indexed, not looked up.** `rule["from"]`, `rule["left"]`, `rule["at"]` are
  direct subscripts. A rule missing an operand raises a bare `KeyError` **out of** the
  failure-collection path — not a `CrossFieldError`, not a recorded failure. Verified. The
  meta-schema's per-operator `required` lists are that contract written down.
- **A pointer that does not resolve yields a distinguished "missing" marker**, which each
  operator interprets differently. `structural._at` returns it for a missing object member,
  a non-integer or out-of-range array index, or a traversal through a scalar. **An explicit
  `null` is a real value and is never "missing".**

### 4.1 `half_open_interval`

Assert that `[from, to)` is a non-empty half-open interval. This is the flagship invariant
of document 16 section 3.4.

| Operand | Required | Meaning |
|---|---|---|
| `from` | yes | instance pointer to the lower bound |
| `to` | yes | instance pointer to the upper bound |

Note that **both keys are required in the rule**. "An absent `to` means positive infinity"
is a statement about the **instance member the `to` pointer addresses**, never about the
`to` key of the rule itself.

**Released bound representation. Both bounds MUST be `rfc3339_utc_z` instants.** Since
`377c1b6` this operator is **not type-agnostic**: `structural._instant` accepts only
`(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z`, anchored with `\Z` — not
`$`, because Python's `$` also matches before a trailing newline (B7). Anything else is a
**recorded failure**, never a comparison. The pattern matches
`stable-identity:1#/$defs/timestamp` and the manifest's `timestamp_representation`.

Evaluation, in the exact order the engine applies it (`structural._check_half_open_interval`):

1. `from` resolves to missing → failure,
   `"<name>: <from> is required to bound the interval"`. **The lower bound is mandatory.**
2. `from` is `null` → failure, `"null is not a released encoding for an interval bound"`.
   **This is checked before the omitted-upper-bound shortcut**, so a `null` lower bound is
   rejected whether or not an upper bound is present. (Before `377c1b6` the order was
   reversed and `{"valid_from": null}` with no `valid_to` passed with zero failures — D2b.)
3. `to` resolves to missing → **positive infinity**. The interval is open-ended and cannot
   be empty, but **the lower bound must still parse as an instant**; if it does not, that
   is still a failure.
4. `to` is `null` → failure, same message as step 2. **`null` is not a spelling of
   infinity**; the released encoding for infinity is absence, and
   `bitemporal-assertion:1`'s `$comment` on `valid_to` says so explicitly.
5. Either bound that does not parse → failure,
   `"<name>: <pointer> is <value>, which is not a released rfc3339_utc_z instant, so the
   interval cannot be compared"`, emitted **once per unparseable bound**. A syntactically
   well-formed but non-existent date (month 13) also lands here, via the `datetime`
   constructor. No comparison is attempted, so mismatched types can no longer raise (D2).
6. Otherwise the interval is non-empty iff `upper > lower` — evaluated as
   `if upper <= lower: fail` on the parsed instants.

**The comparable instant is a portable pair, and a port MUST reproduce it exactly.**
`_instant` returns `(seconds since 1970-01-01T00:00:00Z, fractional digits with trailing
zeros stripped)`, compared as a tuple: integer seconds first, then the fraction **as a
digit string**. For trailing-zero-stripped digit strings, lexicographic order equals
numeric order, so `.5 > .45` and `.5 == .50 == .500`; `.0` strips to the empty string and
therefore equals no fraction at all. Neither half is a binary float, so no precision is
lost and two distinct high-precision instants cannot round into equality.

> **Closed by WS1 (D0).** Before `377c1b6` the engine applied Python `>` directly, which on
> two strings is a **lexicographic** comparison; since `.` (0x2E) sorts before `Z` (0x5A) it
> **rejected** the valid 0.5-second interval `00:00:00Z → 00:00:00.5Z` and **accepted** the
> inverted `00:00:00.5Z → 00:00:00Z`. Both directions re-verified against `377c1b6`: the
> valid interval now passes and the inverted one now fails. No fixture used fractional
> seconds, so all 111 pre-WS1 checks stayed green over it — a port written against the old
> behaviour would have baked a fail-open gate into the two-language contract.

**Released uses.** `bitemporal-assertion:1`: `valid` (`/valid_from` → `/valid_to`) and
`recorded` (`/recorded_at` → `/recorded_until`); and `valid` again on `#/$defs/command`.

### 4.2 `equal`

Assert that two locations are both present and equal.

| Operand | Required |
|---|---|
| `left` | yes |
| `right` | yes |

Fails if either resolves to missing, or if the two values are unequal. **Presence is part of
the assertion**: an absent pair is a failure, not a vacuous pass.

**Equality is the RFC 8785 canonical bytes of the two values**, exactly as member identity is
in [§4.4](#44-unique_by) and [§4.5](#45-disjoint). Two values are equal when their canonical
bytes are equal and unequal otherwise, in every implementation.

An operand that has **no** canonical bytes is a **recorded failure and never a comparison**,
one per offending operand, left before right:
`"<name>: <pointer> is not a value RFC 8785 can canonicalize, so the equality cannot be
decided"`. The equality verdict is not reached. This is [§4.1](#41-half_open_interval)'s rule
for an unparseable interval bound, applied to the same question: having no canonical bytes is
a different fact from differing, and `validate_instance` **returns** failures, so an operand
it cannot canonicalize must never become an escaping raise. `NaN`, `±Infinity`, an integer
outside the exact IEEE-754 double range and a lone surrogate are all in this class, and all
four reach a Python engine through `json.loads` on its **default** settings.

> **CLOSED 2026-08-04 — and it was never an open question, only an unimplemented one.** The
> paragraph that used to sit here recorded the divergence and then *prescribed the answer* in
> the same breath: "**A second implementation MUST use RFC 8785 canonical-byte equality**,
> which agrees with Python on every value the released schemas permit and is the same
> comparator `unique_by` and `disjoint` are being moved to (D1)." The Python engine used
> `==` anyway. That is [§7.5](#75-a-malformed-x-datacompany-cross-field--closed-2026-07-30-decision-f)'s
> shape exactly: an unimplemented check is not an undecided question, and "flagged for a spec
> decision" was the wrong label for a rule the document had already written down.
>
> What made it concrete rather than pedantic is that the TypeScript port had **already**
> moved. Measured against both engines before the fix, on the same rule and the same
> instance: `{"left": true, "right": 1}` and `{"left": 0, "right": false}` were reported
> **HOLDING** by Python and **VIOLATED** by the port — Python's `bool` IS an `int`, which no
> other language reproduces. `{"left": 1, "right": 1.0}` held in both and `{"left": "1",
> "right": 1}` was violated in both. A port written with JavaScript `==` would accept
> `"1" == 1` that neither engine accepts, and one written with `===` would reject
> `{"a":1,"b":2}` against `{"b":2,"a":1}` — one JSON value written twice. Three languages,
> three answers, one released rule; that is a live cross-language split, not a hypothetical.
>
> **Blast radius: zero, measured rather than argued.** All 40 present operand pairs that the
> three released `equal`/`equal_when_both_present` sites produce over the whole committed
> corpus compare identically under `==` and under canonical bytes. The measurement carries a
> positive control that *does* diverge — `true`/`1` and `0`/`false` — because a zero
> measurement without one is an absent measurement. No committed manifest byte and no
> committed fixture changed, and this is a validation rule, so no derivation-profile version
> moves.
>
> **One divergence survives, and it is in the PARSERS rather than in either engine.** Python's
> `json.loads` yields an integer literal exactly; `JSON.parse` collapses one outside the exact
> double range to the nearest double before any engine code runs. So
> `{"left": 9007199254740993, "right": 9007199254740992}` — two different JSON integers — is
> an undecidable equality in Python and a **holding** rule in the port, which sees one value
> twice. `NaN` and `Infinity` are the mirror image: `json.loads` accepts the bare tokens by
> default and `JSON.parse` rejects them outright. Neither engine can remove either, so the
> integer case is committed as an explicitly declared per-engine expectation and the count of
> such declarations is pinned as an equality in both suites — a second one cannot be admitted
> by quietly adding a key. Carry an integer of that magnitude as a released decimal string,
> which is what the canonicalizer's own refusal says.
>
> **Five vectors a port cannot get wrong in silence** are committed to
> `fixtures/canonical-cross-field/v1/operator-vectors.json` and replayed by both engines
> against the exact failure list: `true`/`1` and `0`/`false` must **fail** (rules out Python
> `==`), `"1"`/`1` must **fail** (rules out JavaScript `==`), `1`/`1.0` must **pass** (rules
> out comparing the source text), and `{"a":1,"b":2}`/`{"b":2,"a":1}` must **pass** (rules
> out JavaScript `===`). Two further vectors pin the presence half of each operator, so an
> engine that satisfied the list by rejecting every pair is red.

**Released uses.** `reference-verification-receipt:1`:
`subject_local_ref_is_owned_by_consumer` (`/consumer_context` = `/subject_local_ref/owner_context`).
`pinned-version-ref:1#/$defs/singleton`: `/entity_id` = `/version_id` — evaluable as a
composed member since D3 ([§6.1](#61-d3--closed-instance-relative-rule-pointers)).

### 4.3 `equal_when_both_present`

Assert equality **only** when both locations resolve. If either is missing, the rule passes.

| Operand | Required |
|---|---|
| `left` | yes |
| `right` | yes |

The difference from `equal` is exactly the presence requirement. Note that `null` is
present: `{"left": null, "right": null}` passes as equal, and `{"left": null, "right": 1}`
fails. Verified.

**Released use.** `reference-verification-receipt:1`: `no_cross_tenant_receipt`
(`/subject_local_ref/resource_tenant_id` = `/pinned_version_ref/resource_tenant_id`) — the
tenant IDs are absent for a global-scoped subject, which is why this operator exists.

### 4.4 `unique_by`

No two members of an array may share a value at a member key.

| Operand | Required | Meaning |
|---|---|---|
| `at` | yes | instance pointer to the array |
| `key` | no | member-relative pointer; **omit to compare whole members** |

Evaluation:

1. If `at` does not resolve to a JSON **array**, that is a **failure**:
   `"<name>: <at> is <absent|value>, not an array, so the rule cannot be evaluated; a
   released cross-field rule names a location that must be there"`. Missing, `null`, `{}`
   and a string all fail. Verified against `377c1b6`. (Before it, all four returned no
   failures — defect D2c — and the fail-open was reachable because
   `check_cross_field_rules` is a public, schema-independent entry point.)
2. A member that does not carry `key` is a **failure**:
   `"<at>/<i> does not carry the uniqueness key <key>"`.
3. Two members with the same key value are a failure naming both indices. The first
   occurrence is remembered; each later duplicate is reported once.

**Member identity is the RFC 8785 canonical bytes of the key value**
(`structural._identity_marker`), canonicalized with `allow_binary_float=True` — this is an
identity marker, not a hashed input, so a binary float must not turn a call that returns a
list of failures into a raised `UnstableFloatError`. The hash path still rejects it.

> **Closed by WS1 (D1).** Before `377c1b6` the marker was `repr(value)`, which is Python
> source syntax no other language reproduces and is object-insertion-order dependent:
> `{"a":1,"b":2}` and `{"b":2,"a":1}` were **not** flagged as duplicates. Re-verified
> against `377c1b6`: the same pair now reports
> `"unique_by: /xs/0 and /xs/1 both declare {'b': 2, 'a': 1}; a pointer may be declared at
> most once"`. Note the *failure text* still renders the value with Python `repr`; only the
> **comparison** is canonical bytes. A port must match the comparison, not the prose.

**Released uses.** `canonical-hash-profile:1`: `one_array_declaration_per_pointer`
(`/arrays` by `/pointer`) and `one_exclusion_per_pointer` (`/excluded_pointers` by
`/pointer`). Both exist because `uniqueItems` cannot express them — two declarations for
the same pointer that differ in `kind` are distinct objects and pass `uniqueItems`, and the
hash view keys arrays by pointer, so the last one silently wins.

### 4.5 `disjoint`

Two arrays may not share a value. Each side may name its own member key.

| Operand | Required | Meaning |
|---|---|---|
| `left` | yes | instance pointer to the first array |
| `right` | yes | instance pointer to the second array |
| `left_key` | no | member-relative pointer into a left member |
| `right_key` | no | member-relative pointer into a right member |

Evaluation:

1. If **either** side is not a JSON array, that is a **failure**, with the same
   `_absent_target` message as [§4.4](#44-unique_by) step 1. **Both** sides are reported
   when both are bad — the failures accumulate rather than short-circuiting. Verified
   against `377c1b6`. (Before it, either side being non-list returned no failures — D2c.)
2. A left member that does not carry `left_key` is a **failure**:
   `"<name>: <left>/<i> does not carry the disjointness key <left_key>"`. The members that
   do carry it contribute their values to the left set.
3. A right member that does not carry `right_key` is the same **failure** against `<right>`,
   and each right member whose value is in the left set is a failure naming the value and
   the right index. Failure **order** is part of the contract: the left walk is reported
   first, then the right, each in index order.

A side that declares **no** key cannot produce the step 2/3 failure at all — the member is
compared whole, so there is no key for it to be missing.

That protects the **left** side of the two released rules below, and only the left side. Both
declare `right_key: "/pointer"`, so their **right** side can now report a failure it did not
report before: `{"included_pointers": ["/a"], "excluded_pointers": [{"nope": 1}]}` produces
two `does not carry the disjointness key /pointer` lines that `377c1b6` did not produce. The
first version of this closure claimed those two rules were untouched; that claim was wrong,
and the correction is recorded rather than quietly applied. The impact is bounded — `pointer`
is `required` under `additionalProperties: false`, so a manifest in that state already fails
the schema layer — but `check_cross_field_rules` is a public, schema-independent entry point,
which is the same reason D2c was closed, so the shape is measured rather than argued away and
carries its own vector.

**Member identity is the RFC 8785 canonical bytes of the compared value**, same as
[§4.4](#44-unique_by). Closed by WS1 (D1).

> **CLOSED 2026-08-04 — `disjoint` reports it, aligned onto `unique_by`, in both engines.**
> Until this landed, a member missing its key was a **reported failure** in `unique_by` (step
> 2) and a **silent skip** in `disjoint` (steps 2 and 3): a right member of `{"nope": 1}`
> under `right_key: "/p"` produced no failure at all, so "the two sets are disjoint" could be
> true by vacuity, one member at a time — while WS1 had made the *whole array* missing fail
> loudly, which only sharpened the asymmetry.
>
> **The side was not picked here; the repository had already picked it, in released code, for
> the identical question.** The hash view refuses a set-like array whose member lacks its
> order key — `MissingOrderKeyError` — because *every member of a set-like array must carry
> its whole released order key, and an absent key is not the same fact as a shared one*. That
> is "absent versus present" on the same shape of data, decided fail-closed and shipped. A
> set-membership test that silently drops the members it cannot read is not a
> set-membership test, and fail-open is the class this document exists to eliminate, so
> `disjoint` was aligned onto `unique_by` rather than the reverse. No new normative semantics
> were available to invent.
>
> **Blast radius: zero, measured rather than argued.** Every committed fixture was crossed
> with every released `disjoint` rule: 23 array pairs actually evaluated, 466 members
> inspected, **none** of which lacks its key — so no committed fixture depended on the skip.
> The positive control plants `{"nope": 1}` into a real corpus instance and is seen in 23 of
> 23, because a zero measurement without one is an absent measurement.
>
> **The same closure covers the member key having no canonical bytes at all.** `unique_by`
> and `disjoint` both called the canonicalizer on a member key unguarded, so a lone surrogate
> — or `NaN`, `±Infinity`, or an integer past the exact double range — made
> `check_cross_field_rules` *raise* where it is documented to return failures. That is
> [§4.2](#42-equal)'s rule, and it is applied here to both operators at once rather than to
> `disjoint` alone: fixing one would have re-opened the very asymmetry this section was
> closed to remove. The message is [§4.2](#42-equal)'s with the proposition named —
> `"…so the uniqueness cannot be decided"` / `"…so the disjointness cannot be decided"` — and
> the member is named, skipped, and contributes no value, exactly as one missing its key is.
> Measured before extending, so that no committed fixture's asserted text could move: 10835
> evaluations of the five released `unique_by`/`disjoint` sites over every JSON object in the
> corpus, **zero** of which raise today, under a positive control confirming that a lone
> surrogate in a member key does.
>
> Both directions are committed to `fixtures/canonical-cross-field/v1/operator-vectors.json`
> and replayed by both engines against the exact failure list: a missing key on the left, on
> the right, on both (which pins the order), a missing key that used to hide a *real*
> overlap, and — the control an engine that rejected everything would fail — a well-formed
> disjoint pair that still passes, plus a side with no declared key that still reports
> nothing.

**Released uses.** `canonical-hash-profile:1`:
`a_pointer_is_either_included_or_excluded` (`/included_pointers` vs `/excluded_pointers` by
`/pointer`) and `an_opaque_subtree_is_not_also_excluded` (`/opaque_pointers` vs
`/excluded_pointers` by `/pointer`). Both are asymmetric: the left side is an array of bare
strings with no key, the right side an array of objects with `right_key`.

---

## 5. Effect on the canonical hash, in one place

### 5.1 What changes the bytes

| Annotation | Changes hash bytes | How |
|---|---|---|
| `x-datacompany-hash-excluded` | **yes** | removes the pointer and its whole subtree from the view |
| `x-datacompany-array` (`kind: set`) | **yes** | fixes member order by the order key |
| `x-datacompany-array` (`kind: ordered`) | no | but its absence makes the instance **unhashable** |
| `x-datacompany-hash-opaque` | **yes** | admits members that would otherwise raise |
| `x-datacompany-hash-declaration-only` | **yes** | keeps a pointer out of `included_pointers`, which is what preserves the enclosing subtree's opacity |
| `x-datacompany-hash-exclusion-reason` | no | gates the exclusion that does |
| `x-datacompany-cross-field` | no | gates hashing; contributes no byte |
| `x-datacompany-composition-point` | no | gates whether the envelope may be extended at all; contributes no byte |

### 5.2 The derivation pipeline

`derive_hash_profile(schema_ref)` walks the fully composed schema and emits a
`canonical-hash-profile.v1` manifest. **A committed manifest is never trusted:**
`validate_profile_against_schema` re-derives from the annotations and rejects any
disagreement, because a well-formed manifest that deletes an exclusion or re-declares a
released array would let two services compute two different "canonical" hashes for the same
object.

A domain schema may extend the manifest **only** with `included_pointers` and `arrays`
(`EXTENSIBLE_PROFILE_KEYS`), and **only if the envelope declares an
[`x-datacompany-composition-point`](#35-x-datacompany-composition-point)** (since 2026-08-04; twelve
of the eighteen released schemas declare none and are non-extensible). Exclusions, opaque
subtrees and every serialization or digest rule are properties of the released envelope and
may not be contributed by a consumer.

**The walk collects; the derivation filters.** `_Walker` gathers four sets —
`included`, `excluded`, `arrays`, `opaque` — plus `declaration_only` since vocabulary 1.2,
and `derive_hash_profile` applies the filters afterwards, in this order:

1. `_require_declaration_only_is_legally_placed` refuses the `hash-opaque` pair and a
   misplaced `x-datacompany-hash-declaration-only`
   ([§3.6](#36-x-datacompany-hash-declaration-only) rules 4–5). It runs against the **raw walk**,
   because it is a statement about where an annotation may be *written*, not about what
   survives the cascade.
2. `included_pointers` = `included` minus everything at-or-under an exclusion, minus
   everything at-or-under a declaration-only pointer. **Both by prefix.**
3. `_require_declaration_only_does_not_collide_with_a_declared_member` applies
   [§3.6](#36-x-datacompany-hash-declaration-only) rule 6 — against the list from step 2, **not**
   the raw walk. That ordering is the whole correctness of the rule: an excluded member is
   still a `properties` name in the raw walk, and counting it as a declaration refuses the
   signed opaque payload.
4. `opaque_pointers` = `opaque` minus everything at-or-under an exclusion, minus everything
   at-or-under a declaration-only pointer.
5. `arrays` = every collected declaration, minus everything at-or-under an exclusion — **by
   prefix, exactly like steps 2 and 4** (`profile_version` 2, 2026-08-04; see the record
   below). **Never** filtered by declaration-only: that is a separate rule and its one
   canonical statement is [§3.6 rule 2](#d9-arrays-rule).

The order is load-bearing twice over: step 1 must precede step 2 so a misplaced flag is
diagnosed rather than silently applied, and step 3 must follow step 2 so it reads the set
that actually decides opacity.

`merge_profile_extensions` **sorts `arrays` by pointer**, exactly as derivation does. It
appended until 2026-08-03, which made the two D9 routes byte-identical only by accident of
where the extra pointer happened to sort; `validate_profile_against_schema` compares `arrays`
per pointer, so nothing noticed. No committed manifest moved — every one is derived, and
derivation already sorted.

Manifest lists are compared **after sorting by RFC 8785 canonical bytes**
(`hash_profile._canonical_order`). Before `377c1b6` the sort key was `repr`, which renders
an object's members in insertion order, so two manifests that were the same JSON but whose
entries were written `{"pointer": …, "reason": …}` and `{"reason": …, "pointer": …}` sorted
differently and the second was **falsely rejected** as contradicting the released
annotations (B2). Any JSON round-trip can reorder members, so a port MUST sort by canonical
bytes.

> **CLOSED 2026-08-04 — the inconsistent exclusion cascade, fixed and versioned.**
> `included_pointers` and `opaque_pointers` were filtered by
> `pointer == excluded or pointer.startswith(excluded + "/")` while `arrays` was filtered by
> **exact match only** (`hash_profile.derive_hash_profile`), so an array nested under an
> excluded subtree **survived in the manifest**: excluding `/sig` dropped `/sig/parts` from
> `included_pointers` and `/sig/blob` from `opaque_pointers` but left
> `{"pointer": "/sig/parts", "kind": "ordered"}` in `arrays`. The surviving entry was inert —
> the excluded subtree is never visited — but `validate_profile_against_schema` compares
> `arrays` exactly, so **a port that filtered consistently rejected every manifest the Python
> engine produced**, and [§9](#9-porting-checklist) item 6 had to order every port to
> reproduce the quirk. This section offered two remedies: reproduce it, or *change both
> together with a `profile_version` bump*. The second was taken.
>
> **Both engines now filter `arrays` by prefix, and `DERIVATION_PROFILE_VERSION` moved
> 1 → 2** in the same change as every committed manifest. The bump is the part worth reading
> twice, because the delta argued against it: **no committed schema declares an array at or
> under an exclusion**, so the fix changes zero manifest bytes. That was measured across all
> 18 released schemas, with a positive control — planting the exact shape above onto
> `bitemporal-assertion:1` reproduces `/sig/parts` surviving before the change and dropping
> after — and the honest reading of the empty diff is that the fix is **inert on this
> corpus**, not that it is correct; disabling the `arrays` exclusion filter entirely produces
> the same zero, for the same reason. Bumping anyway is the point. `profile_version` names
> the *rule set* that produced a manifest, and the rule set changed; a version that moves
> only when the bytes move cannot tell a consumer which cascade derived the manifest in front
> of it, which is the one question it exists to answer. `DERIVATION_PROFILE_VERSION` is
> pinned in code precisely so that this bump could not be a quiet one: editing it immediately
> failed every committed manifest still carrying `1`, forcing a single reviewable change
> touching the code, both engines and all seven manifests together.
>
> **Do not generalise the fixed cascade to the declaration-only one.** The
> `x-datacompany-hash-declaration-only` filter added at vocabulary 1.2 is by **prefix**, on
> purpose and with its own test
> (`test_the_suppression_cascades_by_prefix_and_not_by_exact_match`): an array *of objects*
> under an exact-match filter leaks its member pointers and revokes the opacity the
> annotation exists to preserve. That warning is now *more* load-bearing, not less: "make the
> filters consistent" has become true of the exclusion cascade, and a reader who generalises
> it one step further breaks the D9 capability in the one direction that still looks green.
> The two rules are independent and always were, and the rule about `arrays` has exactly one
> canonical statement — [§3.6 rule 2](#d9-arrays-rule) — which this paragraph deliberately
> does not restate.

---

## 6. Known gaps — every numbered defect is closed, and so is the one open question

D3, D8, D4 and D9 are all closed and are kept here rather than deleted, because the *shape*
of each defect is the reason its fix looks the way it does — and because a defect that
vanishes from the record is indistinguishable from one that was quietly forgotten.

D4 is the odd one out: it was **refuted**, not fixed. It was recorded as needing new
rule-vocabulary capability and therefore an owner, and it needed neither. What was missing
was a test, not a capability. §6.3 has been narrowed to the statement that is still true.

**Nothing in this section is open any more.** The heading's exception —
[§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04), the one decision that had
not been taken — was taken on 2026-08-04 and implemented in both engines, at the full option
rather than by retiring the annotation. `D9` — the runtime-extension escape hatch D4 was refuted *through* —
closed on 2026-08-03 and `config/foundation-decisions.json` now carries **no open defects at
all**; [§6.3.1](#631-d9--closed-the-schema-route-into-an-opaque-subtree) records what was
taken, what was measured, and the two register options that were **not** taken.

### 6.1 D3 — CLOSED: instance-relative rule pointers

**Decided 2026-07-30 as option B** (`docs/D3-DECISION-BRIEF.md`): rules gain an optional
`scope` member. This section is kept rather than deleted, because the *shape* of the defect
is the reason the fix looks the way it does.

**What the defect was.** The raise was keyed on **the position a rule is reached at**, never
on which schema declared it, so it fired for every released rule-bearing schema at every
child-keyword position. Measured, not inferred: **48 of 48** cells — eight released
rule-bearing schemas × six child positions — with the same eight schemas at the four in-place
positions all collecting and evaluating correctly, which is the control proving the raise was
positional. (The brief and the wave-2 register both stated this as 30 of 30 across five
schemas; that undercount omitted `page:1#/$defs/page_request`, `research-access-context:1` and
`run-manifest:1`, and is corrected here.)

That mattered because `FND-002` task 4 has to embed three rule-bearing shapes as members —
`pinned-version-ref:1#/$defs/singleton`, `reference-verification-receipt:1` and
`bitemporal-assertion:1` — so any one of them blocked it, and a fix that unblocked only the
singleton would have unblocked none of it.

**Why not the obvious workaround.** Re-declaring the rule at each composing schema's root
does not reproduce it. A root-level `equal /entity_id /version_id` on the composing schema
addresses the *composing* instance's members, not the nested pin's: it evaluates, reports
nothing, and asserts an unrelated proposition while looking identical. That is also the
"consumers MUST NOT invent this mapping locally" failure the `$comment` on `#/$defs/singleton`
exists to prevent.

**What landed.** `scope: relative` resolves a rule's operands against the location it was
reached at, and the collector evaluates it once per addressed instance location. It is an
**additive minor** vocabulary change rather than a version 2, because at a document root the
relative and absolute bases coincide — so annotating the 13 rules released at that time left every one of
their meanings unchanged. That equivalence is asserted, not assumed:
`test_relative_and_absolute_agree_exactly_at_a_document_root` evaluates each released rule
both ways over instances that make it fail and hold, and requires byte-identical failure text.

**What was deliberately kept.** An `absolute`-scoped rule below a child keyword still raises.
The fail-closed property was the one good thing about the old behaviour and option B does not
weaken it; `contains` and `propertyNames` raise at any scope, since neither has a single
instance location.

**Cost accepted.** A fourth lexically identical pointer language
([§1.4](#14-pointer-syntax--four-different-pointer-languages-identical-lexically)). The
alternative (option A, relative-by-default) would have re-read every released operand, and
option C was demonstrated to fail silently under test.

### 6.2 D8 — CLOSED: a set-like array of scalars is declarable

**Decided 2026-07-30.** `hash_view_pointer` required a leading `/` and `minLength: 2`, so
neither `"/"` nor RFC 6901's whole-document `""` was a legal `order_key` entry — and there
was no third spelling of "the member itself". `hash_view._pointer_at` resolved an order key
only inside a `dict` member, so a scalar member always yielded the absent marker.

A set of scalars therefore could not be declared **at all**, and seven released declarations
that are semantically sets shipped `ordered`. `uniqueItems` still rejected duplicates, but
member **order was unguarded**: two services holding the same collection in two orders
computed two different content hashes.

**Scope, corrected.** The decisions register named five arrays. It counted `pack_refs`, which
is a `$ref` alias for `release-ref:1#/$defs/release_ref_list` rather than its own
declaration, and it missed `use_modes` and `data_classes` on `capability-status:1`
entirely. The real figure is **seven declarations**, and it is now recomputed from the corpus
by `test_no_released_array_is_an_ordered_collection_of_scalars` rather than listed by hand.

**What landed.** A new `order_key_pointer` definition admitting `""`, resolved by both
engines to the member itself; all seven arrays re-declared `kind: set` with `order_key: [""]`.

**This is canonical-hash-affecting**, and that is the point: any instance whose members were
not already in sorted order now hashes differently, which is precisely the divergence being
closed. Taken as a forward-only change because no DataCompany service is deployed yet.
`fixtures/foundation/v1/manifests/run-manifest.v1.profile.json` was regenerated and the delta
is exactly four arrays flipping `ordered` → `set`, nothing else.

### 6.3 D4 — CLOSED as REFUTED, at a narrower scope than it was written

**Withdrawn 2026-07-31 (`research_contracts#16`).** D4 was recorded as "an opaque subtree
containing an array is unhashable — declaring one flips `_has_declared_children` and then
*every* member must be declared", and was escalated as a capability gap needing a
rule-vocabulary decision and an owner. **The second clause is false.**
`_ViewBuilder._declared_prefixes` is derived from `included_pointers | excluded_pointers`
alone and never from `arrays`, so an `arrays`-only *profile extension* supplies the
collection kind without adding a declared child: the subtree stays opaque and its undeclared
members still pass. The capability existed; the test did not.

Two things survive the refutation, and neither was closed by `#16`:

1. **The schema-annotation route is still blocked** — that is the mechanism described below,
   and it remains accurate at that narrower scope.
2. **The route `#16` used is the escape hatch this section already flagged.** The block
   below called it "worse than the gap" and said any decision on D4 "must close or bless
   this path explicitly". `#16` blessed it *implicitly*, by depending on it. That was
   carried as defect `D9` and **closed on 2026-08-03** — see §6.3.1.

The mechanism, as it stood until D9 closed. It is **still true of an UNFLAGGED
`properties` chain**, which is why the D4 residue test below stays green; what changed is
that an author can now say the chain declares no path
([§3.6](#36-x-datacompany-hash-declaration-only)):

`bitemporal-assertion:1` `/value` is opaque, and its own `$comment` states that arrays
inside it still need their own ordered/set-like declaration. Those two requirements are
unsatisfiable **through schema annotations**:

- to attach an `x-datacompany-array` at `/value/tags`, the domain schema must reach it through
  a `properties` chain;
- `hash_profile._Walker` adds **every** `properties` name to `included_pointers`;
- `/value/tags` in `included_pointers` makes `/value` a declared prefix;
- `hash_view._ViewBuilder._build_object` then sets `opaque = False`, and every other member of `/value` must
  be declared.

Verified end to end: the annotated schema derives `opaque_pointers: ["/value"]` **and**
`included_pointers` containing `/value/tags`, and hashing
`{"value": {"tags": [...], "other": 1}}` raises
`UndeclaredPathError: /value/other: not declared by the released hash-view manifest`.
Without the array declaration, the same instance raises `UndeclaredArrayError`. The subtree
is unhashable either way — **unless the array node carries
`x-datacompany-hash-declaration-only`**, which is the whole of D9's fix and the only thing that
changed here.

> **Escape hatch.** `merge_profile_extensions(profile, {"arrays": [{"pointer": "/value/tags", "kind": "ordered"}]})`
> succeeds and hashes the instance with opacity intact — verified. It works because
> `merge_profile_extensions` accepts caller-supplied extensions directly and
> `validate_profile_against_schema` only checks that the *released* arrays are present
> unchanged, permitting extras. So the manifest can be extended at runtime in a way **no
> schema annotation can express**, which breaks the property the whole derivation design
> rests on: that a committed manifest is checkable against the schema.

#### 6.3.1 D9 — CLOSED: the schema route into an opaque subtree

**Closed 2026-08-03** by `x-datacompany-hash-declaration-only`
([§3.6](#36-x-datacompany-hash-declaration-only)), vocabulary 1.2. Recorded in
`config/foundation-decisions.json` under `resolved_defects`.

D9 was: *a runtime profile extension can declare an array that no schema annotation can
express.* `rc#16` refuted D4 by taking exactly that route, so the escape hatch the block
above called "worse than the gap" became the evidence for a closed defect. The block also
said any decision on D4 "must close or bless this path explicitly"; `#16` blessed it
*implicitly*, by depending on it, and D9 carried that forward.

**What was taken.** A new registered annotation whose pointer does not enter
`included_pointers`, so both routes agree **from the schema side** — the register's option
(a), in its narrow form. A flagged node is still walked and its `x-datacompany-array` still
reaches the manifest; only its pointer, and everything beneath it, is suppressed. The
enclosing `x-datacompany-hash-opaque` subtree therefore keeps its opacity, and the runtime escape
hatch stops being the only route.

**The closure is an equality, not a capability.** "Both routes work" would be satisfied by
two routes that disagree. What is asserted is that the manifest derived from an annotated
schema is **byte-identical under RFC 8785** to the manifest
`merge_profile_extensions` produces from the runtime route — against the released
`bitemporal-assertion:1` `/value`, the exact shape the defect was written about
(`test_the_two_routes_agree_byte_for_byte_on_the_released_opaque_subtree`, and the same
assertion in the TypeScript port). Two committed fixtures carry that equality as data.

**What was NOT taken, and why. Both alternatives were measured, not judged.**

* **Option (c) — "ratify runtime-only array declarations and tighten
  `validate_profile_against_schema` to accept only the extras `EXTENSIBLE_PROFILE_KEYS`
  names" — was recorded as "the smallest, and the one `#16` implicitly assumed". It is
  already enforced, and would have changed nothing.** Verified twice over: an unknown
  top-level manifest key is rejected by `canonical-hash-profile.v1`'s
  `additionalProperties: false` through `validate_hash_profile`
  (`HashProfileError: … Additional properties are not allowed ('bogus_key' was unexpected)`),
  and a non-extensible extension key is rejected inside `merge_profile_extensions`
  (`a domain extension may only add included_pointers and arrays, not ['excluded_pointers']`).
  There was no looseness left to tighten. **This corrects the register**, which named (c) as
  the smallest available change; the smallest available change was a no-op, which is why the
  durable route was taken instead.
* **Option (a) in its *blanket* form — "suppress every pointer under an opaque subtree" — is
  disqualified.** It erases `/value/other` along with `/value/tags`, which destroys a
  released capability: declaring **all** members of an opaque subtree, thereby revoking its
  opacity, works today and is mandated by `bitemporal-assertion:1` `/value` itself ("the
  moment a domain declares any member of value, it must declare all of them"). The narrow
  form implemented here suppresses only what an author explicitly flags, so that capability
  is untouched — and
  `test_a_declared_member_of_an_opaque_subtree_still_revokes_opacity`
  (`tests/test_hash_view_opaque_exclusion.py`) is its false-positive control.
* **Option (b) — "a derivation rule that opacity survives array-only declarations" — is the
  blanket form wearing a different name.** "Array-only" is not a property the walker can
  observe: it would have to infer that a `properties` name exists *solely* to reach an
  annotation, which is precisely the fact the author now states outright.

**What the fix cost, measured.** Nothing in the committed corpus. All 18 released schemas
were re-derived before and after and the manifests are byte-identical; this change did not
bump `DERIVATION_PROFILE_VERSION`, by [§1.3](#13-versioning)'s own rule, which reserves a
`profile_version` bump for changing what an **existing** annotation means. **A zero measurement needs a positive
control**, and it has two: planting the new annotation on `bitemporal-assertion:1` `/value`
moves the diff (adding `/value/tags` to `arrays` and, correctly, *not* to
`included_pointers`), and deleting the released `x-datacompany-hash-excluded` on
`stable-identity:1` `/aggregate_version` moves it a second, independent way. The empty diff
is therefore a zero, not an absent measurement.

**What that zero does and does not prove.** It proves the change is **inert on the committed
corpus** — no released schema uses the annotation, so no committed manifest moves. It does
**not** prove the change is correct: *deleting the annotation entirely* produces exactly the
same empty diff, for exactly the same reason. Correctness rests on the two-route byte
equality and the fixture corpus, not on this measurement. The delta is the blast-radius
answer; it was never the correctness answer, and it should not be quoted as one.

**Beyond the corpus, and labelled as such.** Two rules in
[§3.6](#36-x-datacompany-hash-declaration-only) go further than anything the corpus states, and
are **decisions taken by the repository owner**, who asked for the durable fix over the
smallest: (i) the flag is legal *only* strictly inside an opaque subtree, and (ii) an opaque
subtree may not both declare a member and carry the flag. Neither is derivable from document
`16` or the shared-foundation plan. Both convert a shape that would fail confusingly at
*hash* time — or, for (i), not fail at all — into a named refusal at derivation. They are
recorded with the same status in `config/foundation-decisions.json`.

**What an independent refutation changed, 2026-08-03.** The design held — no fail-open was
found, the annotation cannot weaken a hash view, revoke an exclusion, or make two distinct
instances hash alike, and the zero manifest delta was reproduced with three further positive
controls. Five things were wrong anyway, and all five were *the fix not reaching as far as
the prose claimed*:

* **The motivating shape did not work.** Rule 6 was evaluated against the raw walk, so an
  EXCLUDED member counted as a declared one and the signed opaque payload — `/value` opaque,
  `/value/sig` excluded, `/value/tags` flagged — was refused, leaving the runtime escape
  hatch as the only route for exactly the case D9 exists for. Fixed by running the rule
  against the derived `included_pointers`, and pinned by a committed fixture.
* **Rule 5 was walk-past-able one level deeper** (the `hash-opaque` pair inside another
  opaque subtree). Now unconditional.
* **The `opaque_pointers` no-filter argument was false**, and the filter is now a rule.
* **The byte equality was an accident of sort order**, since `merge_profile_extensions`
  appended where derivation sorted. Merging now sorts.
* **The "byte-identical message text" parity was ASCII-only**, because `json.dumps` escapes
  non-ASCII and `JSON.stringify` does not. Fixed with `ensure_ascii=False` and a non-ASCII
  fixture both engines assert against.

Two of those — the excluded-member rule and the sort order — were **unpinned in both
directions**: two different fixes each left all 1251 tests green. Each now has a committed
fixture and a mutation proving the fixture fires.

**The knock-on.** `run-manifest.v1` `/inputs/parameters` refused opacity **because** of D9,
and its `$comment` said in so many words that "no schema annotation can supply that
declaration inside an opaque subtree". That sentence has been replaced with what is now
true, and pinned by
`test_the_run_manifest_comment_no_longer_claims_the_route_is_impossible`. The schema's
**shape is deliberately unchanged**: converting `parameters` to an opaque bag changes which
paths reach `included_pointers` and is therefore canonical-hash-affecting — a separate
decision with its own evidence, not a consequence of the annotation existing.

### 6.4 `x-datacompany-composition-point` is IMPLEMENTED (2026-08-04)

**The decision recorded here was "give it an implementation, or retire it". It was taken as
*implement*, at the full option.** This section used to read: *it satisfies none of its
apparent purpose. Nothing validates that the named `$defs` entry exists, that a domain schema
attaches there, or that a schema without the annotation is non-extensible.* All three were
true. A declarative-only annotation in a vocabulary whose entire purpose is enforcement is a
liability — it reads as a constraint and is not one — and that is what was fixed rather than
recorded again.

**First, a correction to this section's own measurement.** It said "Three released envelopes
declare it and three do not, and nothing notices." Both numbers were wrong. Re-measured
across the registry rather than from prose: **six declare it and twelve do not**, in four
spellings, not one —

| Envelope | Declared composition point |
|---|---|
| `bitemporal-assertion:1` | `#/$defs/domain_extension` |
| `immutable-version:1` | `#/$defs/domain_extension` |
| `stable-identity:1` | `#/$defs/domain_extension` |
| `problem-details:1` | `#/$defs/problem_extension` |
| `research-access-context:1` | `#/$defs/context_extension` |
| `run-manifest:1` | `#/$defs/manifest_extension` |

Every one of the six resolves to a `$defs` entry that exists. [§3.5](#35-x-datacompany-composition-point)
carried the same undercount ("all three released uses are the literal
`#/$defs/domain_extension`") and is corrected there too. The undercount is worth naming: a
section arguing that nothing notices an omission was itself miscounting the omissions.

**What was implemented, in both engines with byte-identical message text.**

1. **Resolution, at derivation.** `hash_profile._require_released_composition_point` refuses a
   value that is not a string beginning `#/$defs/`, and refuses one that does not resolve to a
   `$defs` entry of the document it is written in. This closes the **typo hole**, which is the
   half a pattern cannot close: `"#/$defs/domian_extension"` satisfies the meta-schema's
   `composition_point` regex exactly, survives every round trip, and addresses nothing. Four
   cases and one accepted control are committed to
   `fixtures/canonical-annotations/v1/refusals.json` under section `8.row7`, message included,
   and replayed by both engines.
2. **`merge_profile_extensions` is bound to the annotation.** It implemented the
   composition-point *concept* while being driven by its `extensions` argument and never
   consulting this member, so every released schema was extensible in practice whether or not
   it said so. An envelope that declares no composition point is now **non-extensible**.

**What is deliberately NOT implemented, and why it is a limit rather than an omission.**
"A domain schema attaches *there*" is not checkable from a manifest. The composition point
names a `$defs` entry in **schema** space; `included_pointers` and `arrays` are RFC 6901
pointers in **instance** space, and every released composition point is composed into the
envelope at its root, so a declared point induces no constraint on which instance pointers an
extension may name. A positional check would read stricter than it is — the exact failure
mode this section was written about — so the gate is presence and resolvability, stated
plainly.

**⚠️ This is a behaviour change for consumers.** Twelve released schemas became
non-extensible. Each was checked individually for whether it is *intentionally* so or merely
missing the annotation, and the discriminator is derived from the six that declare one rather
than assumed: a composition point is a bare placeholder `$defs` entry (`{"type": "object"}`
plus a `$comment` naming it as the attachment point). The detector finds that placeholder in
**6 of 6** declarers and in **0 of 12** non-declarers, and no candidate is a near miss.

**The 6/6 half is a sanity check, not a control, and calling it one was wrong.** It cannot
fail: the placeholder exists *because* a composition point names it, so a declarer trivially
has one and 6/6 is guaranteed by construction. Only the **0/12** half is a measurement — it
is the half that could have come back non-zero and did not. What the 6/6 half does establish
is narrower and still worth having: the detector runs, reads the right documents and is not
globbing to nothing.

| Non-declaring schema | Shape | Verdict |
|---|---|---|
| `locator-selector:1` | `$defs`-only bundle, no root object | intentional — not an envelope; derives no manifest at all |
| `page:1` | `$defs`-only bundle, no root object | intentional — same |
| `release-ref:1` | `$defs`-only bundle, no root object | intentional — same |
| `typed-refs:1` | `$defs`-only bundle, no root object | intentional — same |
| `canonical-hash-profile:1` | root `additionalProperties: false` | intentional — the manifest schema itself; an extensible manifest format would make every other rule here unenforceable |
| `model-conformance-record:1` | root `additionalProperties: false` | intentional — sealed record |
| `capability-status:1` | `allOf` + `unevaluatedProperties: false` | intentional — sealed envelope, no placeholder `$defs` |
| `evidence-location-candidate:1` | `allOf` + `unevaluatedProperties: false` | intentional — same |
| `evidence-location-version:1` | `allOf` + `unevaluatedProperties: false` | intentional — same |
| `identity-ref:1` | `allOf` + `unevaluatedProperties: false` | intentional — same |
| `pinned-version-ref:1` | `allOf` + `unevaluatedProperties: false` | intentional — same |
| `reference-verification-receipt:1` | `allOf` + `unevaluatedProperties: false` | intentional — same |

The four `$defs`-only bundles are the strongest evidence in the table and were found by a
second, independent measurement: they do not derive a manifest **at all** on `main` either
(`derive_hash_profile` refuses them for an empty `included_pointers`), so "non-extensible" was
already their state and this change did not move them. Note also that sealing is *not* the
discriminator — three of the six declarers seal with `unevaluatedProperties: false` and three
do not — which is why the placeholder `$defs` entry, not the seal, is what the verdicts rest
on.

`tests/test_extension_vocabulary.py`'s `DECLARATIVE_ONLY` set is now **empty**: every
registered name in the vocabulary is read by the engine. Its drift test still runs in both
directions, and it is a stronger statement than the one it replaces.

---

## 7. Ambiguities, defects and divergences in the released implementation

Every item below was reproduced against **`377c1b6`**. None is a design proposal.

### 7.0 What WS1 (`377c1b6`) closed, and what it did not

This document was first derived from the pre-WS1 engine. WS1 rewrote exactly the internals
it describes, so every item was re-run. The result:

| Finding | Status after `377c1b6` |
|---|---|
| D0 — interval bounds compared lexicographically | **CLOSED.** Parsed instants; both directions re-verified ([§4.1](#41-half_open_interval)). |
| D2 — mismatched bound types raise `TypeError` | **CLOSED.** Now a recorded failure with a named message. |
| D2b — `null` lower bound with absent upper bound passes | **CLOSED.** The null check moved ahead of the shortcut. |
| D1 — member identity via `repr()` | **CLOSED.** RFC 8785 canonical bytes, in `unique_by`, `disjoint` **and** the rule-dedup marker. |
| D2c — `unique_by`/`disjoint` fail open on a non-array target | **CLOSED.** Loud failure, both sides reported. |
| B2 — manifest lists sorted by `repr` | **CLOSED.** Sorted by canonical bytes ([§5.2](#52-the-derivation-pipeline)). |
| B7 — Python `$` matches before a trailing newline | **CLOSED** for released schema `pattern`s, via `registry.CanonicalValidator`, and inside the new interval parser via `\Z`. |
| **§7.1** unregistered annotation name ignored | **CLOSED** 2026-08-03: both engines raise `HashProfileError` at derivation. |
| **§7.2** lone exclusion reason discarded | **CLOSED** 2026-08-03, same route. |
| **§7.3** non-object `x-datacompany-array` dropped | **CLOSED** 2026-08-03, same route. |
| **§7.4** `x-datacompany-array` re-targets itself | **CLOSED** 2026-08-03, same route. |
| **§7.5** malformed rules raise `KeyError`/`AttributeError` | **CLOSED** 2026-07-30 (decision F): both engines raise `CrossFieldError`. |
| **§7.6** unknown operator discards collected failures | **CLOSED** 2026-08-03 by decision: refused at COLLECTION, so no failure is ever collected to discard. |
| **§4.5** `unique_by` reports / `disjoint` skips a member missing its key | **CLOSED** 2026-08-04: `disjoint` reports it too, in both engines, and both operators additionally report — rather than raise on — a member key with no canonical bytes. Derived from the hash view's released `MissingOrderKeyError`, not decided here. The NEW missing-key message is byte-identical across the engines by construction; `disjoint`'s *overlap* message still is not — see the residual row below. |
| **residual** — `repr` vs canonical rendering in `unique_by`/`disjoint`/interval diagnostics | **OPEN**, and now measured rather than assumed. Python interpolates the offending value with `repr` and the port with RFC 8785 canonical text: `'a'` vs `"a"`, `True` vs `true`, `None` vs `null`, `'notalist'` vs `"notalist"`. Reachable on `run-manifest:1`, the one released `disjoint` rule that can fire. Invisible to the corpus because the fixture that exercises it asserts only the rule name and `must be disjoint`. Fix: route both engines through `json_text`/`jsonText`; it spans §4.1, §4.4 **and** §4.5, so it is not taken with §4.5 alone. |
| **§5.2** exclusion cascade filters `arrays` by exact match only | **CLOSED** 2026-08-04. Both engines filter `arrays` by prefix; `DERIVATION_PROFILE_VERSION` 1 → 2 and every committed manifest regenerated in the same change. Zero byte delta on the corpus, with a positive control — the fix is inert here, not unproven ([§5.2](#52-the-derivation-pipeline)). |
| **§6.4** `x-datacompany-composition-point` read by no code | **CLOSED** 2026-08-04 as *implement*, not retire. Both engines resolve the declared `$defs` entry at derivation (closing the typo hole a pattern cannot see) and gate `merge_profile_extensions` on the annotation, so a schema declaring none is non-extensible ([§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04)). |
| **§4.2** what `equal` means across languages | **CLOSED** 2026-08-04: both operators compare RFC 8785 canonical bytes, which is what §4.2 already prescribed while the engine did not implement it. The port had already moved, so this was a LIVE split until it landed. |
| D3 | **CLOSED** 2026-07-30 as option B ([§6.1](#61-d3--closed-instance-relative-rule-pointers)). |
| D4 | **CLOSED** 2026-07-31 as REFUTED ([§6.3](#63-d4--closed-as-refuted-at-a-narrower-scope-than-it-was-written)); the escape hatch it was refuted through was carried as register defect `D9` and **CLOSED 2026-08-03** by `x-datacompany-hash-declaration-only` ([§6.3.1](#631-d9--closed-the-schema-route-into-an-opaque-subtree)). |

Seven of the ten items this document originally recorded as fail-open or divergent are the
**annotation-authoring** holes, and WS1 fixed none of them — it fixed the *evaluation*
paths. That is the gap the meta-schema exists to cover ([§8](#8-where-the-meta-schema-is-deliberately-stricter-than-the-engine)),
and six of the seven are now closed by the engines *consulting* it: §7.5 on 2026-07-30
(decision F, the cross-field side) and §7.1–§7.4 + §7.6 on 2026-08-03 (the derivation side).
The residue §8 still covers is smaller and is enumerated there, re-measured rather than
inherited.

### 7.1 An unregistered annotation name is preserved and ignored — CLOSED 2026-08-03

`x-datacompany-hash-exclude` (one letter short) is a valid JSON Schema member, is preserved on
round-trip, and is read by nothing. The path stays in the hash view and no error is raised
anywhere. Verified.

This is the interaction between section 2.5's "MUST preserve unknown extension values" and
this vocabulary's enforcement purpose: **preservation and enforcement pull in opposite
directions.** The resolution taken here is that unknown values in the `x-datacompany-`
namespace are preserved at runtime (nothing strips them) but **rejected at authoring
time**. Values in any other namespace are untouched.

**Closed**, by the route [§7.5](#75-a-malformed-x-datacompany-cross-field--closed-2026-07-30-decision-f)
established and for the same reason: the meta-schema already rejected this, so no owner and
no new normative semantics were needed — what was missing was the *derivation consulting
it*. `hash_profile._require_released_annotations` now refuses any `x-datacompany-*` member whose
name is outside `#/$defs/vocabulary`, as a catchable `HashProfileError`, in both engines and
with byte-identical text. The name set is re-stated in code rather than read from the
meta-schema at runtime — decision F's precedent, so the port needs no JSON Schema validator
— and `test_the_engine_vocabulary_matches_the_meta_schema` derives it back out of the
declaration and compares in **both** directions.

`x-datacompany-composition-point` is *in* that set, and being a registered name was never an
implementation: it was accepted by this check while its value was constrained by nothing
whatsoever. That is no longer where it stands —
[§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04) was decided and implemented
on 2026-08-04 — and the committed control has been rewritten to assert what it now measures:
a composition point whose `$defs` entry **exists** still derives.

### 7.2 A lone exclusion reason is discarded in silence — CLOSED 2026-08-03

`x-datacompany-hash-exclusion-reason: "signature"` with no `x-datacompany-hash-excluded: true`
derives an empty `excluded_pointers`. Verified. The reason is read only inside the flag's
branch. A schema author who deletes the flag and leaves the reason silently re-admits a
signature to the hash view.

**Closed.** The derivation now refuses the reason without the flag. Only that direction is
added: the flag *without* a reason already failed closed, as `UnknownExclusionError` against
the released closed reason set, and that behaviour and its message are unchanged.

### 7.3 A non-object `x-datacompany-array` is dropped in silence — CLOSED 2026-08-03

`"set"`, `["set"]` and `true` all derive `arrays: []`. Verified. The declaration is lost at
derivation time and only resurfaces as `UndeclaredArrayError` if some instance actually
carries that array — so an optional array can lose its collection semantics indefinitely
without any gate going red.

**Closed.** A present `x-datacompany-array` that is not an object is a `HashProfileError`. The
`isinstance`/`isRecord` test that used to *be* the drop is gone from both engines rather
than left beside the new guard: after the guard it could no longer evaluate false, and a
condition that cannot fire reads as defence in depth while being untestable. The two
tripwires in `packages/typescript/test/coverage.test.ts` that recorded this fail-open as
shared behaviour were **rewritten, not deleted** — both stayed green through the closure,
because the source strings they pinned are still there, so each was re-stated to what is now
true and given the behavioural half it never had.

### 7.4 `x-datacompany-array` may re-target itself — CLOSED 2026-08-03

See [§3.3](#33-x-datacompany-array). `{"pointer": …}` in the annotation overrides the derived
location, with no error.

**Closed.** The annotation's members must be exactly the meta-schema's `array_annotation`
members — `kind` required, `order_key` optional, nothing else — which is that file's
`additionalProperties: false` and `required: ["kind"]` re-stated under the same
bidirectional drift test as §7.1's vocabulary. Only the member *names* are re-stated: what
`kind` and `order_key` may **contain** stays `canonical-hash-profile.v1`'s
`array_declaration`, which the meta-schema `$ref`s and which the derived manifest is
validated against, so there is no third copy to drift.

The merge order is deliberately **unchanged**: the derivation still builds
`{"pointer": <derived>, **annotation}` with the annotation last, in both engines. That
precedence was §7.4's mechanism and it is now unreachable, because the member that exploited
it cannot be written. Changing the precedence instead would have been a cross-language
divergence risk for no gain.

### 7.5 A malformed `x-datacompany-cross-field` — CLOSED 2026-07-30 (decision F)

- `{}` → falsy, treated as no rules at all, silently.
- `"equal"` → iterated character by character, raising `AttributeError: 'str' object has no
  attribute 'get'`.
- `[null]`, `[["equal"]]` → `AttributeError` from the same line.
- A rule missing an operand → bare `KeyError`.

None of these is a `CrossFieldError`, so none is catchable as a contract failure. Verified
against `377c1b6`. WS1 moved *where* the `AttributeError` surfaces — the rule-dedup marker
is no longer `repr(sorted(rule.items()))`, so the first non-object rule now reaches
`rule.get("rule")` in `check_cross_field_rules` instead of failing during collection — but
the class and the uncatchability are unchanged.

**Now a two-language divergence.** The TypeScript port (`packages/typescript/src/structural.ts`)
cannot reproduce Python's `AttributeError`/`KeyError`, because those are artefacts of duck
typing rather than decisions. Measured against both engines:

| declaration | Python | TypeScript |
|---|---|---|
| `{}` | `[]` — falsy, silently no rules | `[]` — not an array, same |
| `"equal"` | `AttributeError` | **`[]`** — silently no rules |
| `[null]` | `AttributeError` | `TypeError` |
| `[["equal"]]` | `AttributeError` | `CrossFieldError: unknown … undefined` |
| `[{"rule":"equal"}]` (no operand) | `KeyError: 'left'` | a failure naming `undefined` |

The `"equal"` row was the one that mattered: Python raised where TypeScript **silently
evaluated nothing** — a rule declaration that reads as enforced and enforces nothing.

**Closed.** This needed **no owner and no new normative semantics**, which is why it did not
wait for one: the meta-schema in `schemas/meta/datacompany-extension-vocabulary.v1.schema.json`
already rejected every shape in the table, under a gate proven falsifiable one mutation at a
time (`test_the_meta_schema_rejects_each_malformed_annotation`). What was missing was the
*engines consulting it*. The earlier reading — that closing this required deciding what a
malformed annotation MUST do — mistook an unimplemented check for an undecided question.

Both engines now reject a declaration that is not an array, an empty array, a non-object
member, an unregistered operator, an unreleased `scope`, a missing operand, an operand
belonging to a different operator, or an operand that is not a released pointer — each as a
catchable `CrossFieldError`. The per-operator operand table is re-stated in both engines
rather than read from the meta-schema at runtime, so the port needs no JSON Schema validator;
`test_the_engine_operand_table_matches_the_meta_schema` derives the table *from* the
meta-schema and compares, in both directions, so the restatement cannot drift.

Both sweeps carry a well-formed control, because an engine that rejected *every* declaration
would otherwise satisfy them.

### 7.6 An unknown operator discards already-collected failures — CLOSED 2026-08-03

A schema declaring `[{"rule": "equal", …}, {"rule": "nope"}]` validated against an instance
that violates the first rule raises `CrossFieldError: unknown released cross-field rule
'nope'` and the `equal` failure is lost. Verified. The failure is closed, so this is a
reporting defect rather than a hole — but a port that collects the unknown-operator failure
into the list instead of raising would report a **different** result. That cross-language
ambiguity is the defect, and it is what needed deciding.

**Re-measured 2026-08-03.** The symptom no longer reproduces as written, and the reason
matters: decision F moved the refusal to `_validate_rule`, which runs while the rules are
being **collected** — before any instance is examined. Against the schema and the violating
instance above, both engines now raise from the collection path, with byte-identical text
(`… x-datacompany-cross-field/1 declares rule "nope", which is not a released cross-field
operator (…)`), and *no failure has been collected*, so there is nothing to discard. The
`unknown released cross-field rule` raise at the end of the evaluator's dispatch survives as
a backstop that the collection guard makes unreachable; `test_the_operator_set_matches_the_engine_dispatch`
is what keeps the dispatch and the operand table from disagreeing and making it reachable.

**DECIDED: fail closed at collection; never collect an unknown operator as a failure.** An
unknown operator is an *authoring* fault, not an instance fault. Reporting it beside the
instance failures — the alternative §7.6 names — was **rejected** on two grounds: it would
let a consumer read an unenforceable rule as an enforced one that merely passed for this
instance, and it would make the reported result depend on whether the instance happened to
violate a rule declared *before* it, which is precisely the cross-language ambiguity being
closed. A port MUST refuse the schema and MUST NOT return a partial failure list.

Both halves are pinned in both engines: the refusal is byte-identical for an instance that
violates the sibling rule and for one that satisfies it, and the well-formed control —
two valid rules, both violated — still reports **two** failures, so an engine that refused
every multi-rule declaration could not satisfy the test.

### 7.7 The evaluation-path fail-opens are closed, and so are the authoring-path ones

D0, D1, D2, D2b, D2c, B2 and B7 were live on the pre-WS1 engine and are **closed** in
`377c1b6`; each is re-verified above and the fixed behaviour is what this document
specifies. See the table in [§7.0](#70-what-ws1-377c1b6-closed-and-what-it-did-not).

What WS1 did not touch is the **authoring** side: nothing in the engine validated the
annotations themselves. §7.1–§7.6 are all of that shape, and **all six are now closed** —
§7.5 on 2026-07-30 by decision F, §7.1–§7.4 and §7.6 on 2026-08-03. This paragraph used to
read "five of the six survive"; that sentence is what the 2026-08-03 change made false, and
it is re-measured here rather than quietly deleted.

Every one of the six was closed the same way: by making both engines **consult** the
meta-schema — re-stating its rules in code, under drift tests that derive them back out of
the declaration and compare in both directions — rather than by either engine growing a JSON
Schema validator of its own. None of the six needed an owner and none introduced normative
semantics; the meta-schema already rejected every shape, under a gate proven falsifiable one
mutation at a time. The earlier reading, that closing them required deciding what a malformed
annotation MUST do, mistook an unimplemented check for an undecided question. §7.6 is the one
exception and the exception is narrow: nothing there failed open, and what it needed was a
decision about *reporting*, which is recorded in that section.

A port must reproduce all six closed behaviours — a malformed `x-datacompany-cross-field` is a
catchable `CrossFieldError`, and a malformed annotation on a walked node is a catchable
`HashProfileError`, in both engines and with byte-identical message text — and must **not**
re-implement the `AttributeError`/`KeyError`/silent-drop fail-opens the tables above record
against `377c1b6` as if they were faithful. What the meta-schema still catches and the
engines still do not is enumerated, re-measured, in
[§8](#8-where-the-meta-schema-is-deliberately-stricter-than-the-engine).

---

## 8. Where the meta-schema is deliberately stricter than the engine

`schemas/meta/datacompany-extension-vocabulary.v1.schema.json` is a gate, not a description of
what the engine tolerates. It rejects **eight** things at authoring time.

This is a table of MEASUREMENTS, and prose like that rots silently. It had. The sentence
that used to stand here — "It rejects seven things at authoring time. **Four of them the
engine still accepts**" — was stale in *both* numbers: D9 had added an eighth row that was
never counted, and the per-row verdicts had not been re-run since decision F. So the probes
this table claims were run are now **committed**, in
`tests/test_extension_vocabulary.py::test_section_8_row_8_says_what_the_engine_actually_does`
and `::test_section_8_counts_the_rows_its_table_actually_has`, and the table is asserted
against them in both directions: a row claiming a refusal the engine does not make is red,
and a row claiming an acceptance the engine no longer makes is red. Neither the code nor the
prose can move alone.

| Meta-schema rule | Does the ENGINE refuse it? |
|---|---|
| unknown `x-datacompany-*` name rejected | **Yes, since 2026-08-03** ([§7.1](#71-an-unregistered-annotation-name-is-preserved-and-ignored)). Was ignored in silence. |
| `hash-excluded` / `hash-opaque` / `hash-declaration-only` must be literal `true` | **Yes, since 2026-08-04.** Was a silent no-op — see the correction below. |
| reason required iff flag present | **Yes, since 2026-08-03** ([§7.2](#72-a-lone-exclusion-reason-is-discarded-in-silence)), in the reason-without-flag direction; the flag-without-reason direction was already `UnknownExclusionError`. |
| `x-datacompany-array` must be an object, `additionalProperties: false` | **Yes, since 2026-08-03** ([§7.3](#73-a-non-object-x-datacompany-array-is-dropped-in-silence), [§7.4](#74-x-datacompany-array-may-re-target-itself)). |
| per-operator operands required | **Yes, since decision F** ([§7.5](#75-a-malformed-x-datacompany-cross-field--closed-2026-07-30-decision-f)). Was a bare `KeyError`. |
| `cross-field` must be a non-empty array of objects | **Yes, since decision F.** Was an `AttributeError`, or a silent no-op. |
| `composition-point` must be a `#/$defs/...` pointer | **Yes, since 2026-08-04** ([§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04)), and **more strictly than the meta-schema**: the engines RESOLVE the pointer, so `#/$defs/domian_extension` — which this pattern accepts — is refused. Was read by no code at all. |
| `hash-declaration-only` may not sit beside `hash-excluded` or `hash-opaque` | **Yes** for the `hash-excluded` pair, since 2026-08-04, and **Yes** for the `hash-opaque` pair since D9's repair — see the correction below. |

So of the eight: **none**. Every one of the eight rules is refused in both engines with
byte-identical text. This sentence read "**one row the engine deliberately does not
enforce** — `composition-point`, and only that one" until 2026-08-04, and "and **half of one
more**" before D9's repair landed: row 8's `hash-opaque` half was the half. The last one to
go was `composition-point`, and it went past parity rather than up to it — the engines
**resolve** the pointer where the meta-schema can only match its shape, so
`#/$defs/domian_extension` is accepted there and refused here ([§8.1](#81-and-the-two-places-the-engine-is-stricter-than-the-meta-schema)
now has a second entry). Row 8 and this count are both checked against the engine by
`test_section_8_row_8_says_what_the_engine_actually_does` and
`test_section_8_counts_the_rows_its_table_actually_has`, which is what turns each such change
from something a reader had to notice into something that goes red.

**Correction C1 — row 8 was recorded falsely.** It used to read "the engine catches the
`hash-opaque` pair (as a misplaced flag)". Measured: a node carrying *both* annotations,
where that node is itself strictly under **another** `x-datacompany-hash-opaque` pointer,
derives **cleanly**. The placement guard asks whether the flag is strictly under *some*
opaque pointer; the enclosing subtree satisfies it, and the node's own
`x-datacompany-hash-opaque` is never examined. The engine catches the pair only in the special
case of a node with no other opaque ancestor — the bypass was merely relocated one level
deeper. The false half was load-bearing: it made the row read as one the meta-schema and the
engine already agreed on, so nobody looked.

**Both halves are now refused, in two different places, and the split is deliberate.** The
`hash-excluded` half is refused by `hash_profile._require_released_annotations`, because it
is a **per-node** fact: two contradictory acts written on one node, which a check that sees
one node at a time can decide. The `hash-opaque` half is refused by the declaration-only
**placement guard** in `hash_profile` — named descriptively rather than by symbol because
that guard is now two functions and a citation naming one half would rot — because it is a
fact about the **composed walk**. Refusing either one in both places, with two messages,
would be exactly the cross-language divergence this section's closures exist to remove.

The coupling that caught this is worth keeping in view:
`test_section_8_row_8_says_what_the_engine_actually_does` measures both halves against the
engine and asserts this table states what it measured. When the `hash-opaque` half went from
accepted to refused, the row went **red** until it was corrected — which is precisely what
the old prose could not do, and why the row is worded as a measurement rather than as a
promise.

One thing C1 does not change: this row is a place the **meta-schema** is stricter, which is
the ordinary direction for this section, not the exception
[§8.1](#81-and-the-two-places-the-engine-is-stricter-than-the-meta-schema) describes. §8.1's
"one place the ENGINE is stricter" is about the **placement** rules of
[§3.6](#36-x-datacompany-hash-declaration-only), which are facts about the composed walk that no
per-node schema can evaluate. It is not about this pairing rule, which *is* a per-node fact
and which the meta-schema states directly; reading §8.1 as covering both is how the false
half survived as long as it did.

**Correction C2 — the literal-`true` row was left open on a bad argument.** It was recorded
here as needing "a decision rather than an unimplemented check", on the reasoning that
closing it would change what the three `is True` reads mean. That was wrong, and it is the
same mistake §7.5's closure names: mistaking an unimplemented check for an undecided
question. It needs no change to any identity comparison.
`_require_released_annotations` already runs *before* anything is read off the node, so
refusing a flag that is present and not literally `true` leaves all three `is True` reads
byte-identical and simply means they never see another value. Structurally it is §7.2 with a
value test where §7.2 has a presence test — and §7.2 was closed. Measured before closing:
`x-datacompany-hash-excluded: false` beside a valid reason derived `excluded_pointers: []` and
left the signature **in** the hash view, which is §7.2's outcome reached by writing the flag
wrongly instead of by deleting it. Closed 2026-08-04 in both engines, for all three flags.

**Correction C3 — the `composition-point` row was the last "constrains something with no
implementation behind it", and it is not that any more.** It was recorded here as induced
from *three* committed uses, flagged as such both in this section and in the meta-schema's
own `$comment`, and left open on the grounds that giving it an implementation was a decision
nobody had taken. Two things were wrong. The count was six, not three, in four spellings not
one — the same undercount [§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04)
carried and now corrects. And the decision *was* takeable: it was taken on 2026-08-04, as
implement rather than retire, and the row above now reads **Yes** in both engines. The
`pattern` here is retained as the authoring-time shape gate and is unchanged; what the
engines added is **resolution**, which is the half no per-node pattern can express.


### 8.1 …and the two places the ENGINE is stricter than the meta-schema

**The second one landed 2026-08-04 and is stated first because it is the shorter.**
`x-datacompany-composition-point`'s value is constrained here by a `pattern`, which can decide
that a string *looks like* `#/$defs/<name>` and can decide nothing else. The engines
**resolve** it against the document, so `#/$defs/domian_extension` — a one-character typo
that satisfies the pattern exactly, survives every round trip, and addresses nothing — is
accepted by the meta-schema and refused by both engines. That is not a gap in the
meta-schema: whether a `$defs` entry exists is a fact about the *document*, and this
meta-schema is applied to one annotated *node* at a time. It is the same structural limit
the declaration-only rules below run into, in its mildest form.

`x-datacompany-hash-declaration-only` is the older and larger one, and reverses the usual
direction for the same underlying reason. Three of its rules
([§3.6](#36-x-datacompany-hash-declaration-only) rules 4–6) are facts about the **composed walk**
— where the flag sits relative to an `x-datacompany-hash-opaque` ancestor, and whether that
ancestor also has a declared member — and no meta-schema applied to one node can evaluate
them. They are enforced in `derive_hash_profile`, in both engines, with byte-identical
message text.

Two corrections landed here after an independent refutation, and both were cases of this
document describing a stricter engine than the one that shipped.

* **The `hash-opaque` pair was NOT caught by the engine.** The placement rule was "strictly
  under an `x-datacompany-hash-opaque` pointer", and a node carrying *both* annotations satisfies
  that the moment it sits inside another opaque subtree — so `/value` opaque with
  `/value/inner` opaque-and-flagged derived cleanly, which is exactly the bypass rule 5's
  rationale says it prevents. The pair is now refused **unconditionally**, ahead of the
  ancestor test, so the engine and the meta-schema agree on this rule instead of only
  appearing to.
* **The `opaque_pointers` cascade.** The engine did not filter `opaque_pointers` by
  declaration-only, on a written argument that such a filter "could only ever be a no-op".
  The argument was about *ancestors* and said nothing about *descendants*: `/value` opaque,
  `/value/inner` flagged and `/value/inner/deeper` opaque puts an opaque pointer squarely
  under a declaration-only one, and the manifest listed it. It is filtered now. The change is
  behaviourally inert — opacity matches by prefix, and the enclosing pointer already covers
  everything beneath the flag — which is why it needed a test rather than a comment.

One rule was **written first and then deleted**, and the deletion is the honest part. The
meta-schema originally required `x-datacompany-array` or `x-datacompany-cross-field` beside the flag,
on the reasoning that a node "reached only to carry annotations" which carries none is a
declaration that declares nothing. That rule **rejected a legal shape**: because the
suppression cascades by prefix, the intended way to declare a deep array is one flag on the
*outermost* node of the `properties` chain, and that node carries only `properties`. The
false-positive control caught it. What remains is the limit, recorded rather than replaced by
a rule that reads strict and is wrong: **a declaration-only node that reaches no annotation
is not detected.** It is inert — its member still hashes through the enclosing opacity — and
the shapes that are *not* inert are the three the engine refuses.

The meta-schema's own `pattern` keywords are evaluated with `registry.CanonicalValidator`,
not the stock `Draft202012Validator`, so its anchors mean what JSON Schema says they mean.
Under Python's `$` semantics `"#/$defs/domain_extension\n"` would satisfy
`composition_point` — the same B7 fail-open WS1 closed for the released schemas, which a
gate written to catch fail-opens must not itself reproduce. A mutation case pins it.

The meta-schema references `canonical-hash-profile.v1` for the closed exclusion-reason set
and for the array `kind`/`order_key` shapes rather than restating them, and
`tests/test_extension_vocabulary.py` asserts that no reason string is restated — so the
two cannot drift.

---

## 9. Porting checklist

A second-language implementation is conformant when it reproduces all of:

1. Collection: `$ref` + `allOf`/`anyOf`/`oneOf`/`then`/`else` only; hard failure on a rule
   below a child keyword; content-based deduplication; `$defs` traversed only through
   `$ref`.
2. All five operators with the exact operand names, presence semantics and failure
   ordering of [§4](#4-the-cross-field-operators).
3. Interval bounds parsed as `rfc3339_utc_z` and compared as the
   `(epoch_seconds, trailing-zero-stripped fraction digits)` pair, never lexicographically;
   an unparseable bound is a recorded failure, never a comparison
   ([§4.1](#41-half_open_interval)).
4. Member identity as **RFC 8785 canonical bytes**, never a language-specific
   representation — in `unique_by`, `disjoint` **and** the rule-dedup marker
   ([§3.1](#31-x-datacompany-cross-field), [§4.4](#44-unique_by), [§4.5](#45-disjoint)).
5. Fail closed on an unknown operator; fail closed on a non-array `unique_by`/`disjoint`
   target, reporting **both** sides of a `disjoint` when both are bad.
6. Manifest derivation reproducing the exclusion cascade — `included_pointers`,
   `opaque_pointers` **and `arrays`** all filtered by prefix
   (`p === excluded || p.startsWith(excluded + "/")`) — and comparing manifest lists after
   sorting by canonical bytes ([§5.2](#52-the-derivation-pipeline)). This item read
   "**including** the `arrays` exact-match quirk" until 2026-08-04, when the quirk was fixed
   in both engines under `profile_version` 2; a port written to that instruction now derives
   a `arrays` set the reference engine rejects, which is the failure the instruction existed
   to prevent, with the sign flipped. Do **not** carry the prefix rule across to the
   `x-datacompany-hash-declaration-only` cascade — [§3.6 rule 2](#d9-arrays-rule) is the
   canonical statement of why.
7. Set-member ordering by the **UTF-8 bytes** of the canonicalized order key, kept distinct
   from RFC 8785's **UTF-16 code unit** member-name ordering ([§3.3](#33-x-datacompany-array)).
8. `is True` semantics for the two boolean annotations — or, better, reject everything but
   `true` at load time, as the meta-schema does.
9. **ECMA-262 `pattern` semantics**, where `$` asserts end of input and `.` excludes all
   four line terminators. A native JavaScript engine gets this for free; a Python port must
   not. Items 3–7 are all implemented in `377c1b6`, so a port that matches this list agrees
   with Python **by construction** rather than by coincidence.
10. **`scope` on a cross-field rule.** A port MUST read it before interpreting any operand:
    `relative` resolves against the location the rule was reached at and is evaluated once
    per addressed location; `absolute` (the default) resolves against the instance root and
    MUST still raise below a child keyword. A port that ignores `scope` throws where the
    contract now evaluates; one that treats every rule as relative evaluates the absolute
    ones against the wrong object and reports nothing. Both directions are pinned in
    `packages/typescript/test/references.test.ts`.
11. **An `arrays`-only profile extension.** `merge_profile_extensions` MUST accept a
    caller-supplied `arrays` entry that declares a collection *inside an opaque subtree*
    without adding a declared child, leaving the subtree opaque and its undeclared members
    passing. This is required behaviour, not a workaround: it is the route that refuted D4,
    and both engines pin it —
    `test_an_arrays_only_extension_declares_a_collection_inside_an_opaque_subtree`
    (`tests/test_canonical_hash.py`) and `declares a collection inside an opaque subtree via
    an arrays-only extension` (`packages/typescript/test/hashView.test.ts`).
12. **`x-datacompany-hash-declaration-only`, and the equality that closed `D9`**
    ([§3.6](#36-x-datacompany-hash-declaration-only),
    [§6.3.1](#631-d9--closed-the-schema-route-into-an-opaque-subtree)). This item previously
    read "reproduce the asymmetry rather than paper over it by inventing a local annotation";
    the annotation is now **released**, so a port MUST implement *this* one and MUST NOT
    invent another — either direction is the same cross-language split. Concretely, a port
    must reproduce all of:

    * collect the flag with an **identity** check (`=== true` / `is True`), like the other
      two boolean annotations;
    * **post-filter, never suppress inline.** The flag can arrive through a `$ref` or an
      `allOf`/`anyOf`/`oneOf`/`then`/`else` branch *after* the `properties` loop has added
      the pointer, so an inline check is composition-order dependent and diverges from a port
      that composes differently;
    * filter `included_pointers` by **prefix** (`p === f || p.startsWith(f + "/")`), so an
      array of objects does not leak its member pointers;
    * **never** filter `arrays` by it — [§3.6 rule 2](#d9-arrays-rule), the canonical
      statement, including why the `arrays` EXCLUSION filter becoming a prefix filter in
      2026-08-04's `profile_version` 2 (item 6) does **not** reach this cascade;
    * **never** filter `opaque_pointers` by it — the placement rule makes that a no-op;
    * raise on a flag that is not **strictly** under an `x-datacompany-hash-opaque` pointer, and
      on an opaque subtree that both declares a member and carries the flag, grouping each
      flag by its **nearest** opaque ancestor so nested opaque subtrees are not refused;
    * **use the same message text.** Two engines that refuse the same schema with different
      words are a divergence a consumer reading either one cannot reconcile. Pointer lists
      are rendered with `JSON.stringify`, which Python reproduces exactly via
      `json.dumps(..., separators=(",", ":"))` — `repr` would have written `['/a']` against
      `["/a"]`.

    Replay `fixtures/canonical-hash/v1/declaration-only/` to check all of it. Each fixture is
    self-contained: it carries its own probe schema, the expected manifest as **RFC 8785
    canonical bytes**, and — for the two `derives` fixtures — the runtime-route extension
    whose merged manifest must be byte-identical. That equality **is** the closure of `D9`; a
    port that reproduces the capability but not the equality has only relocated the defect.

13. **The authoring-time refusals** ([§7.1](#71-an-unregistered-annotation-name-is-preserved-and-ignored)–[§7.4](#74-x-datacompany-array-may-re-target-itself),
    [§7.6](#76-an-unknown-operator-discards-already-collected-failures--closed-2026-08-03)).
    A port MUST refuse, at DERIVATION and as a catchable `HashProfileError`, every one of:
    an `x-datacompany-*` member whose name is outside the released vocabulary; an
    `x-datacompany-hash-exclusion-reason` with no `x-datacompany-hash-excluded` beside it; an
    `x-datacompany-array` that is not an object; and an `x-datacompany-array` carrying any member
    other than `kind` (required) and `order_key`. It MUST refuse an unknown cross-field
    operator while COLLECTING, never as a collected failure, so no partial failure list can
    exist. And it MUST do all of it with the same message text, which means routing every
    rendered value through one helper rather than through `repr`/`typeof`/`str(type(...))`:
    Python's `json.dumps` needs BOTH `separators=(",", ":")` and **`ensure_ascii=False`**, or
    a member named `café` renders as `["/caf\u00e9"]` against `JSON.stringify`'s
    `["/café"]` — the same class as item 12's `['/a']` versus `["/a"]`, and the one no ASCII
    test can see. `fixtures/canonical-annotations/v1/refusals.json` is the replayable record:
    every case carries its probe schema, the error class by name and the exact message, plus
    `accepted: true` controls without which an engine that refused every annotated node would
    satisfy the whole file.

    What a port MUST NOT do is re-implement these as a JSON Schema validation of each node
    against the meta-schema. The reason given here until 2026-08-04 — "that would give
    `x-datacompany-composition-point` an implementation and reopen item 14 by accident" — is now
    **false**: item 14 says a port MUST implement it. The prohibition stands on its own
    remaining ground, which was always the stronger half. A meta-schema sweep enforces
    whatever that document happens to say, so the two engines' refusals would drift with it
    silently and in step with nothing; it also cannot express the rules that are facts about
    the composed **walk** rather than about a node ([§8.1](#81-and-the-two-places-the-engine-is-stricter-than-the-meta-schema)),
    and would still miss the composition point's resolvability, which no `pattern` can
    decide. The rules are re-stated, deliberately and narrowly, and the drift tests are what
    keep the restatement honest.

14. **`x-datacompany-composition-point`, which a port MUST now implement**
    ([§6.4](#64-x-datacompany-composition-point-is-implemented-2026-08-04)). This item read "the
    one thing still undecided … a port MUST NOT give it an implementation without reopening
    that decision"; the decision was taken on 2026-08-04, as implement, and the prohibition is
    reversed for the reason it was written — an annotation that constrains something in one
    language and nothing in the other is a split of the same kind as item 12's, and that is
    now the split a port creates by *omitting* it. Concretely, a port must reproduce both
    halves:

    * at DERIVATION, refuse a value that is not a string beginning `#/$defs/`, and refuse one
      that does not **resolve** to a `$defs` entry of the document the node belongs to —
      resolved against the walk's current base `$id`, never against the entry schema, because
      a `$ref` into another released document reaches nodes whose pointers are relative to
      *that* document. Resolution, not a pattern match: `#/$defs/domian_extension` satisfies
      the meta-schema's regex and names nothing, and only resolution sees it;
    * in `mergeProfileExtensions`, refuse an extension offered to an envelope that declares no
      composition point, testing **presence** rather than a null-valued read so that an
      explicit `null` reaches the malformed-value message rather than the non-extensible one.
      Twelve of the eighteen released schemas declare none and are non-extensible.

    …and with the same message text, through the same rendering helper as item 13, which
    means **not** interpolating the resolver's own error: `registry` renders its diagnostics
    with `!r` in Python and with bare interpolation in the port, so embedding it is a
    two-language divergence hiding inside a single refusal. `fixtures/canonical-annotations/v1/refusals.json`
    section `8.row7` carries the four refusals and the accepted control that keeps a
    refuse-everything implementation from satisfying them.

    Registering the NAME is still not giving it an implementation — item 13's vocabulary check
    accepts it and constrains its value not at all — which is why these two rules are separate
    from that one.

---

## 10. Related files

| Path | Role |
|---|---|
| `schemas/meta/datacompany-extension-vocabulary.v1.schema.json` | the executable declaration |
| `tests/test_extension_vocabulary.py` | conformance, non-vacuity and falsifiability gates |
| `src/research_contracts/canonical/structural.py` | cross-field collection and evaluation |
| `packages/typescript/src/structural.ts` | the second language of the same, installed as `validation.ts`'s default evaluator |
| `packages/typescript/src/verification.ts` | the second language of `verification.py` |
| `packages/typescript/test/references.test.ts` | the 11 + 22 reference checks, each invalid one **for its declared reason** |
| `packages/typescript/test/verification.test.ts` | the 14 verification checks, exact `result` + `failure_code` |
| `src/research_contracts/canonical/hash_profile.py` | manifest derivation from annotations; the §7.1-§7.4 authoring-time refusals; and §6.4's composition-point rules — resolution at derivation, and the extensibility gate in `merge_profile_extensions` |
| `src/research_contracts/canonical/rendering.py` | the one JSON rendering both engines' message text goes through (§9 item 13) |
| `packages/typescript/src/rendering.ts` | the same, in the second language |
| `fixtures/canonical-annotations/v1/refusals.json` | the replayable authoring-refusal record: probe schema, error class, exact message, and the accepted controls |
| `packages/typescript/test/authoringRefusals.test.ts` | that record replayed by the port, plus the §7.1-§7.4 and §7.6 reproductions |
| `src/research_contracts/canonical/hash_view.py` | hash view construction |
| `schemas/canonical/canonical-hash-profile.v1.schema.json` | manifest shape, closed reason set |
| `fixtures/canonical-hash/v1/declaration-only/` | the five committed `x-datacompany-hash-declaration-only` vectors, replayed by both engines |
| `tests/test_declaration_only_annotation.py` | the D9 closure, its guards and the two-route equality |
| `packages/typescript/test/declarationOnly.test.ts` | the same, in the second language, over the same fixtures |
| `OWNERS.yaml` | records that ownership is UNASSIGNED |

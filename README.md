# Research contracts

**Lifecycle:** `candidate`
**Candidate/release status:** candidate

This repository is the language-neutral source for research contract schemas and
canonical fixtures. JSON Schema 2020-12 is authoritative.

FND-002/FND-005 are landed: the six canonical envelope schemas, the
`canonical-hash-profile.v1` manifest, a first-party RFC 8785 (JCS) serializer and
the content-hash engine live under `src/research_contracts/canonical/`, with
golden fixtures under `fixtures/canonical-hash/v1/` and
`fixtures/canonical-references/v1/`.

## Governance (IMP-DEC-001, Python half, ratified 2026-08-08)

The FND-001 inputs that used to be `UNASSIGNED` are assigned. See
[`OWNERS.yaml`](OWNERS.yaml) for the exact wording:

- accountable contract owner and reviewer: `georgiedekker` (a self-review, recorded
  as one rather than dressed up as two-party review);
- `IMP-DEC-001`, **Python half**: distribution `research-contracts`, import package
  `research_contracts`; this repository is its published source;
- schema/version policy: semver on the schema `$id`.

Still deferred, and asserted as deferred by the governance gate:

- `IMP-DEC-001-NPM` — the npm scope and package name for the TypeScript engine. No
  npm publish step may be added while it reads `UNASSIGNED`, and closing it means
  editing `governance.py`, not only the YAML.
- Per-annotation owners for the `x-datacompany-*` vocabulary in `EXTENSIONS.md`, and the
  eighteen per-schema owners in `config/deferred-schema-owners.json`. `IMP-DEC-001`
  named packages, not vocabulary or individual schemas.

No file under `examples/` is review or release evidence, and no model-conformance
record exists yet under `review-records/` — the governance gate now
reports what is on file rather than requiring the directory to be empty.

**First consumer:** `evidence_review_service` (8810) seals its inclusion-set export
with the FND-005 canonical hash. Until that landed, every gate in this repository
guarded a contract nothing imported.

## Gates

Every gate in this repository has been falsified: for each one there is a test
that fails when the gate is removed or weakened. That is the point of the
repository — a gate that cannot fail is worthless.

| Script | What it binds |
|---|---|
| `scripts/lint_contracts.py` | JSON Schema 2020-12 compilation, `$id` uniqueness, and the pre-ADR regulatory denylist over **every** `*.json`/`*.yaml`/`*.yml` document and file name in the repository |
| `scripts/check_draft_governance.py` | `OWNERS.yaml` parsed as YAML (not grepped) and asserted to be explicitly **assigned**: no placeholder at any depth outside `deferred_decisions`, and every still-open decision still reading `UNASSIGNED`. `review-records/` must exist, must not be a symlink, and is enumerated and reported |
| `scripts/record_model_conformance.py` | exact-byte canonical-model conformance records; `model_path` binds `--model-file` |
| `scripts/verify_canonical_fixtures.py` | FND-002/FND-005: replays every committed canonical fixture (references, verification receipts, RFC 8785 vectors, golden content hashes, mutations, rejections, hash-profile manifests) against the released engine. Exit 0 means every fixture is release-checkable; a run that enumerates **no** fixtures is exit 2, not a pass |
| `scripts/generate_*_client.py` | blocked while the source OpenAPI contracts are not frozen |
| `scripts/pip-audit.sh` | CVE audit of the `uv.lock`-resolved dependency set |

All of them are invoked by [`.github/workflows/ci-public.yml`](.github/workflows/ci-public.yml);
`tests/test_script_entry_points.py` fails if a script exists but is not wired.

## Local validation

```bash
uv sync --all-groups

uv run ruff check --no-cache src scripts tests generated
uv run ruff format --no-cache --check src scripts tests generated
uv run ty check src scripts tests generated
uv run bandit -q -r src scripts -ll
./scripts/pip-audit.sh

uv run python scripts/lint_contracts.py
uv run python scripts/check_draft_governance.py
uv run python scripts/verify_canonical_fixtures.py
uv run pytest
```

Never pipe a gate through `tail`, `grep` or `head` — the shell reports the
filter's exit code, not the gate's.

## The canonical model

Records name the canonical model by a path relative to a **model root**:

```
DataCompany/16-datacompany-canonical-domain-data-model.md
```

The model root is resolved in this order: `--model-root`, the
`RESEARCH_CONTRACTS_MODEL_ROOT` environment variable, then the nearest ancestor
directory of this repository that actually contains that file (which is what
makes the gate work from a `git worktree` checkout). `--model-file` must resolve
to exactly that path; a disagreeing `--model-file` is refused before any bytes
are hashed.

```bash
uv run python scripts/record_model_conformance.py digest \
  --model-file ../DataCompany/16-datacompany-canonical-domain-data-model.md
```

This hashes the live model file's exact bytes. It does not hash rendered or
newline-normalized Markdown.

### Examples

`examples/valid/model-conformance-record.example.json` names the real merged
model: repository `nonagenticai/DataCompany`, revision
`a471ca95d4d03ffeba8f41ad026552b79e98a4de`, digest
`sha256:ef2c93a3372b7137f15ecda1b06ef6d5b6282c901fac39e8e8369a902331a432`. Those
three values are verified against the real bytes. It is still **not** review
evidence: `reviewed_by` is a fixture identity, it lives under `examples/` rather
than `review-records/`, and it does not resolve `IMP-DEC-001`.

`examples/invalid/*.json` are digest-consistent with the frozen synthetic fixture
`tests/fixtures/canonical-model.md`, so each one fails for exactly the single
defect in its file name rather than incidentally on a digest mismatch. The test
suite and CI materialise a temporary model root containing those fixture bytes
before validating them.

That consistency is now **asserted**, by `scripts/check_file_hygiene.py` and by
`tests/test_file_hygiene.py`, rather than only stated here. It used to be stated
only here, and the pre-commit `end-of-file-fixer` hook — a rewriting hook with no
CI counterpart — silently normalised the fixture's trailing newline, turning 183
bytes into 182 and its digest into one that reproduces exactly and exists in no
revision. Every check stayed green. The whitespace rules are enforced as a check
that fails and names the file; nothing rewrites a tracked file during a commit.

## Conformance record creation

Record creation requires explicit review metadata and an explicit immutable
model source revision. Placeholder values are rejected in any letter case and
with any surrounding whitespace (`UNASSIGNED`, `unassigned`, `" UNASSIGNED"`,
`TBD`, `ACCOUNTABLE_REVIEWER`, …).

```bash
uv run python scripts/record_model_conformance.py create \
  --model-file ../DataCompany/16-datacompany-canonical-domain-data-model.md \
  --output review-records/FND-001.v1.json \
  --package-id FND-001 \
  --artifact-kind schema \
  --model-section 1 \
  --model-section 3 \
  --model-source-revision <immutable-revision> \
  --package-version contracts=1.0.0 \
  --disposition conforms \
  --reviewed-by <accountable-reviewer> \
  --reviewed-at 2026-07-30T00:00:00Z
```

The script refuses to overwrite an existing record. Writing any record into
`review-records/` fails `scripts/check_draft_governance.py` while the
governance blockers are unassigned — that is intended.

## Pre-ADR regulatory denylist

[`config/pre-adr-regulatory-denylist.json`](config/pre-adr-regulatory-denylist.json)
is enforced across every JSON/YAML document and file name in the repository, in
every key position (`$defs`, `required`, `patternProperties`, `properties`,
`description`, `enum`, `const`, `title`, `$id`) and on word boundaries — so
`illegal_event_count` is not an activation but `RegulatoryInstrument` is.

The ten forbidden tokens are pinned a second time in
`src/research_contracts/tooling/denylist.py`. Deleting entries from the JSON
alone fails the gate: erosion of this list requires the accepted
`ADR-DATACOMPANY-REGULATORY-MODEL` decision, not a quiet edit.

## License

Apache 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

## Licensing

This repository is a library of JSON Schemas, fixtures and validation tooling. It
contains no licence gate and no licence server: importing `research_contracts` or
running any script here makes no licensing network call, requires no key or token,
and has no "unset" mode to configure. Nothing is enforced at runtime.

"""P8 -- the differential fuzz harness, and the proof that it can fail.

Three obligations, and the third is the one that matters:

1. the corpus is REPRODUCIBLE -- a run is a pure function of its seed;
2. the harness is NON-VACUOUS -- a run that would measure nothing exits 2, and the
   comparator really compares (a doctored result stream is caught);
3. the corpus DISCRIMINATES -- for every category the P8 obligation names, perturbing the
   Python engine in the way that category exists to catch makes the generated cases produce
   different output.

Obligation 3 is the whole point. A fuzz harness that generates 512 instances, hashes them
twice and reports green proves nothing unless those 512 instances would have SEPARATED two
engines that disagree. Wave 1's finding was that gates were never falsified; a fuzz gate is
the easiest gate in the repository to write in a form that cannot fail, because a generator
that quietly stops emitting astral member names still reports "512 cases passed".

Each perturbation below is applied to the PYTHON engine and the corpus is re-hashed. The
cross-engine half -- perturbing the TypeScript engine and watching the real gate go red --
is exercised by hand and recorded in the pull request; it cannot run here because the
``gates`` job has no Node toolchain, and a test that skipped when Node was absent would
reproduce exactly the defect this file exists to prevent.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from conftest import WORKFLOW

from research_contracts.canonical import hash_view, jcs
from research_contracts.tooling import differential_fuzz as fuzz

# Captured BEFORE any monkeypatch: a perturbation that delegates to the module attribute
# it is replacing would recurse forever.
_REAL_STABLE_INTEGER = jcs.stable_integer
_REAL_ES_NUMBER_TO_STRING = jcs.es_number_to_string
_REAL_CANONICALIZE = jcs.canonicalize

CORPUS_SEED = 4242
CORPUS_SIZE = 300


@pytest.fixture(scope="module")
def corpus() -> list[dict[str, Any]]:
    return fuzz.generate_corpus(CORPUS_SEED, CORPUS_SIZE)


@pytest.fixture(scope="module")
def records(
    corpus: list[dict[str, Any]], tmp_path_factory: pytest.TempPathFactory
) -> list[dict[str, Any]]:
    """The corpus as the two engines actually see it: read back from the wire text."""
    path = tmp_path_factory.mktemp("fuzz") / "corpus.jsonl"
    fuzz.write_corpus(corpus, path)
    return fuzz.read_corpus(path)


@pytest.fixture(scope="module")
def baseline(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return fuzz.engine_results(records)


def _in_category(records: list[dict[str, Any]], category: str) -> list[int]:
    return [index for index, record in enumerate(records) if record["category"] == category]


def _detects(
    records: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    category: str,
) -> list[str]:
    """Case ids in ``category`` whose result changed under the perturbation in effect."""
    perturbed = fuzz.engine_results(records)
    return [
        records[index]["case_id"]
        for index in _in_category(records, category)
        if perturbed[index] != baseline[index]
    ]


# --------------------------------------------------------------------------
# 1. Reproducibility
# --------------------------------------------------------------------------


def test_the_corpus_is_a_pure_function_of_its_seed() -> None:
    """A fuzz run that cannot be replayed is not evidence."""
    first = fuzz.generate_corpus(99, 60)
    second = fuzz.generate_corpus(99, 60)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_a_different_seed_explores_different_ground() -> None:
    """Falsifiable control for the test above: the seed must actually be read."""
    first = fuzz.generate_corpus(99, 60)
    second = fuzz.generate_corpus(100, 60)
    assert json.dumps(first, sort_keys=True) != json.dumps(second, sort_keys=True)


def test_every_required_category_is_generated(corpus: list[dict[str, Any]]) -> None:
    present = {case["category"] for case in corpus}
    assert present == set(fuzz.REQUIRED_CATEGORIES)


def test_the_obligation_categories_are_all_declared() -> None:
    """The seven categories P8 names verbatim, asserted from the table, not from prose."""
    named = {
        "non-bmp-keys",
        "lone-surrogates",
        "negative-zero",
        "integers-past-2-53",
        "exponent-boundaries",
        "unicode-normalization",
        "absent-vs-null",
    }
    assert named <= set(fuzz.REQUIRED_CATEGORIES)


# --------------------------------------------------------------------------
# 2. Non-vacuity
# --------------------------------------------------------------------------


def test_a_zero_case_run_is_a_hard_error_not_a_pass() -> None:
    """An empty measurement is not a zero measurement."""
    assert fuzz.main(["--count", "0"]) == 2


def test_a_count_too_small_to_cover_every_category_is_refused() -> None:
    """A category that generates nothing is a silent hole, so the run is refused."""
    with pytest.raises(fuzz.EmptyCorpusError):
        fuzz.generate_corpus(1, len(fuzz.REQUIRED_CATEGORIES) - 1)
    assert fuzz.main(["--count", str(len(fuzz.REQUIRED_CATEGORIES) - 1)]) == 2


def test_an_empty_corpus_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(fuzz.EmptyCorpusError):
        fuzz.read_corpus(path)


def test_a_missing_typescript_runner_is_an_error_not_a_skip(tmp_path: Path) -> None:
    """A gate that cannot run must fail loudly; a silent skip is a permanent green."""
    with pytest.raises(fuzz.TypeScriptRunnerError, match="does not exist"):
        fuzz.locate_runner(tmp_path)


def test_a_stale_typescript_build_is_refused(tmp_path: Path) -> None:
    """A stale build fuzzes yesterday's TypeScript against today's Python and calls it parity."""
    package = tmp_path / "packages/typescript"
    (package / "src").mkdir(parents=True)
    (package / "tools").mkdir(parents=True)
    runner = tmp_path / fuzz.TS_RUNNER_RELATIVE
    runner.parent.mkdir(parents=True)
    runner.write_text("// built\n", encoding="utf-8")
    assert fuzz.locate_runner(tmp_path) == runner

    source = package / "src" / "jcs.ts"
    source.write_text("// edited after the build\n", encoding="utf-8")
    import os

    built_at = runner.stat().st_mtime
    os.utime(source, (built_at + 60, built_at + 60))
    with pytest.raises(fuzz.TypeScriptRunnerError, match="stale"):
        fuzz.locate_runner(tmp_path)


def test_the_wire_format_preserves_the_facts_the_categories_depend_on(tmp_path: Path) -> None:
    """A lossy transport would make the two engines agree about a value neither can see."""
    cases = [
        fuzz._case("t/0", "structural", {"\ud800": 1, "n": 2**53 + 1, "z": -0.0, "e": 1e21}),
    ]
    path = tmp_path / "corpus.jsonl"
    fuzz.write_corpus(cases, path)
    text = path.read_text(encoding="utf-8")
    assert "\\ud800" in text, "a lone surrogate must survive as an escape, not as UTF-8"
    assert "9007199254740993" in text, "an out-of-range integer must survive as its literal"
    assert "-0.0" in text, "-0 must survive with its sign; -0 as an int literal loses it"
    value = fuzz.read_corpus(path)[0]["value"]
    assert value["n"] == 2**53 + 1
    assert math.copysign(1.0, value["z"]) == -1.0


# --------------------------------------------------------------------------
# 2b. The comparator really compares
# --------------------------------------------------------------------------


def test_identical_streams_produce_no_mismatch(baseline: list[dict[str, Any]]) -> None:
    """Control: without this, every assertion below could be a comparator that always fails."""
    assert fuzz.compare(baseline, list(baseline)) == []


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("canonical_base64", "AAAA", "different canonical JSON bytes"),
        ("digest", "sha256:" + "0" * 64, "different content hash"),
    ],
)
def test_a_doctored_result_is_caught(
    baseline: list[dict[str, Any]], field: str, replacement: str, reason: str
) -> None:
    doctored = [dict(result) for result in baseline]
    target = next(index for index, result in enumerate(doctored) if result["ok"])
    doctored[target][field] = replacement
    mismatches = fuzz.compare(baseline, doctored)
    assert [mismatch.reason for mismatch in mismatches] == [reason]


def test_a_different_error_class_is_caught(baseline: list[dict[str, Any]]) -> None:
    doctored = [dict(result) for result in baseline]
    target = next(index for index, result in enumerate(doctored) if not result["ok"])
    doctored[target]["error"] = "SomeOtherError"
    assert [m.reason for m in fuzz.compare(baseline, doctored)] == ["different error class"]


def test_one_engine_succeeding_where_the_other_refuses_is_caught(
    baseline: list[dict[str, Any]],
) -> None:
    doctored = [dict(result) for result in baseline]
    target = next(index for index, result in enumerate(doctored) if not result["ok"])
    doctored[target] = {
        "case_id": doctored[target]["case_id"],
        "ok": True,
        "canonical_base64": "AAAA",
        "digest": "sha256:" + "0" * 64,
    }
    assert [m.reason for m in fuzz.compare(baseline, doctored)] == [
        "one engine succeeded, the other failed"
    ]


def test_a_truncated_result_stream_is_caught(baseline: list[dict[str, Any]]) -> None:
    """The exact shape of a silently-partial run: fewer results than cases, still 'no failures'."""
    mismatches = fuzz.compare(baseline, list(baseline[:-3]))
    assert len(mismatches) == 3
    assert {m.reason for m in mismatches} == {"the TypeScript runner produced no result"}


def test_an_unrequested_result_is_caught(baseline: list[dict[str, Any]]) -> None:
    extra = [*baseline, {"case_id": "never/generated", "ok": True}]
    assert [m.reason for m in fuzz.compare(baseline, extra)] == [
        "the TypeScript runner produced an unrequested result"
    ]


# --------------------------------------------------------------------------
# 3. The corpus DISCRIMINATES -- one perturbation per obligation category
# --------------------------------------------------------------------------


def _lenient_string(value: str) -> str:
    """A serializer that accepts a lone surrogate instead of refusing it."""
    out = ['"']
    for character in value:
        code_point = ord(character)
        short = jcs._SHORT_ESCAPES.get(code_point)
        if short is not None:
            out.append(short)
        elif code_point < 0x20 or 0xD800 <= code_point <= 0xDFFF:
            out.append(f"\\u{code_point:04x}")
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


def _es_number_with_exponent_switch_at_20(value: float) -> str:
    """`es_number_to_string` with the ECMAScript 21-digit switch point moved to 20."""
    if isinstance(value, int):
        if abs(value) > jcs.MAX_EXACT_INTEGER:
            raise jcs.UnstableFloatError(f"integer {value} exceeds the exact double range")
        value = float(value)
    if value == 0.0:
        return "0"
    if value < 0:
        return "-" + _es_number_with_exponent_switch_at_20(-value)
    digits, n = jcs._shortest_decimal(value)
    k = len(digits)
    if k <= n <= 20:
        return digits + "0" * (n - k)
    if 0 < n <= 20:
        return digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return "0." + "0" * -n + digits
    exponent = n - 1
    sign = "+" if exponent >= 0 else "-"
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{mantissa}e{sign}{abs(exponent)}"


def _signed_zero_number(value: float) -> str:
    """`es_number_to_string` that leaks the sign of -0, which ECMAScript never does."""
    if not isinstance(value, int) and value == 0.0 and math.copysign(1.0, value) < 0:
        return "-0"
    return _REAL_ES_NUMBER_TO_STRING(value)


def _profile_override(**overrides: Any) -> Any:
    """A hash-view engine that silently rewrites the released manifest before applying it."""
    real = hash_view.build_hash_view

    def patched(instance: Any, profile: dict[str, Any]) -> Any:
        return real(instance, {**profile, **overrides})

    return patched


def _utf16_order_keys(value: Any, **kwargs: Any) -> bytes:
    """Set-like order keys compared as UTF-16 code units instead of UTF-8 bytes.

    This is the G1 divergence exactly: UTF-8 byte order is Unicode CODE POINT order, a
    JavaScript string sort is UTF-16 CODE UNIT order, and they disagree for every astral
    character compared against U+E000..U+FFFF.
    """
    text = _REAL_CANONICALIZE(value, **kwargs).decode("utf-8")
    return text.encode("utf-16-be", errors="surrogatepass")


PERTURBATIONS: list[tuple[str, str, str, Any]] = [
    # (category, module attribute path, description, replacement)
    (
        "non-bmp-keys",
        "canonical.jcs.utf16_sort_key",
        "member names sorted by code point instead of UTF-16 code unit",
        lambda name: name.encode("utf-8"),
    ),
    (
        "integers-past-2-53",
        "canonical.jcs.MAX_EXACT_INTEGER",
        "the exact-integer bound raised past 2^53",
        2**70,
    ),
    (
        "exponent-boundaries",
        "canonical.jcs.es_number_to_string",
        "the ECMAScript exponent switch point moved from 21 to 20",
        _es_number_with_exponent_switch_at_20,
    ),
    (
        "negative-zero",
        "canonical.jcs.es_number_to_string",
        "-0 rendered with its sign, which ECMAScript never does",
        _signed_zero_number,
    ),
    (
        "negative-zero",
        "canonical.jcs.stable_integer",
        "-0.0 treated as an unstable float instead of the integer 0",
        lambda value: (
            None
            if (value == 0.0 and math.copysign(1.0, value) < 0)
            else _REAL_STABLE_INTEGER(value)
        ),
    ),
    (
        "lone-surrogates",
        "canonical.jcs._serialize_string",
        "a lone surrogate accepted instead of refused",
        _lenient_string,
    ),
    (
        "string-escapes",
        "canonical.jcs._SHORT_ESCAPES",
        "U+2028 escaped, as several JavaScript serializers wrongly do",
        {**jcs._SHORT_ESCAPES, 0x2028: "\\u2028"},
    ),
    (
        "unicode-normalization",
        "tooling.differential_fuzz.build_hash_view",
        "the declared Unicode normalization form silently dropped",
        _profile_override(unicode_normalization="none"),
    ),
    (
        "absent-vs-null",
        "tooling.differential_fuzz.build_hash_view",
        "the absent-versus-null rule inverted",
        _profile_override(absent_vs_null="distinct"),
    ),
    (
        "structural",
        "tooling.differential_fuzz.build_hash_view",
        "the released hash exclusions ignored",
        _profile_override(excluded_pointers=[]),
    ),
    (
        "set-like-order-keys",
        "canonical.hash_view.canonicalize",
        "set-like order keys compared as UTF-16 code units instead of UTF-8 bytes",
        _utf16_order_keys,
    ),
]


@pytest.mark.parametrize(
    ("category", "attribute", "description", "replacement"),
    PERTURBATIONS,
    ids=[f"{entry[0]}::{entry[2]}" for entry in PERTURBATIONS],
)
def test_the_generated_corpus_detects_a_perturbed_engine(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    category: str,
    attribute: str,
    description: str,
    replacement: Any,
) -> None:
    """The falsifiability proof: break the engine, and this category must notice.

    A green fuzz run only means something if the cases it generates would separate two
    engines that disagree. Each perturbation here is a real divergence somebody could ship
    -- code-point member-name ordering, a widened 2^53 bound, the wrong exponent switch
    point, a leaked ``-0`` sign, an accepted lone surrogate, an escaped U+2028, a dropped
    normalization form, an inverted absent-versus-null rule, ignored exclusions, and
    UTF-16-ordered set members. Every one of them must change what this corpus produces.
    """
    module_name, _, name = attribute.rpartition(".")
    import importlib

    module = importlib.import_module(f"research_contracts.{module_name}")
    monkeypatch.setattr(module, name, replacement)
    detected = _detects(records, baseline, category)
    assert detected, (
        f"{CORPUS_SIZE} generated cases did not notice that {description}. The "
        f"{category!r} generator is not producing input that discriminates, so a green "
        "fuzz run over it would prove nothing."
    )


def test_a_no_op_perturbation_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
) -> None:
    """False-positive control for the suite above.

    Without it, ``_detects`` returning a non-empty list for EVERY input -- a comparator that
    is simply broken -- would read as eleven passing falsifiability proofs.
    """
    monkeypatch.setattr(
        jcs, "utf16_sort_key", lambda name: name.encode("utf-16-be", "surrogatepass")
    )
    for category in fuzz.REQUIRED_CATEGORIES:
        assert _detects(records, baseline, category) == [], category


# --------------------------------------------------------------------------
# Shrinking
# --------------------------------------------------------------------------


def test_shrinking_reduces_a_failing_case_to_the_member_that_matters() -> None:
    """On a mismatch the report must carry a minimal instance, not the raw generated one."""
    case = fuzz._case(
        "shrink/0",
        "structural",
        {"noise": [1, 2, 3], "more": "padding", "poison": {"deep": "POISON"}},
    )

    def evaluate(batch: list[dict[str, Any]]) -> list[bool]:
        return [
            "POISON" in json.dumps(candidate["value"], ensure_ascii=True) for candidate in batch
        ]

    minimal = fuzz.shrink(case, evaluate)
    assert minimal["value"] == "POISON"


def test_shrinking_stops_when_no_candidate_still_fails() -> None:
    """Control: a shrinker that accepted every candidate would report an unrelated instance."""
    case = fuzz._case("shrink/1", "structural", {"a": 1, "b": 2})
    assert fuzz.shrink(case, lambda batch: [False] * len(batch))["value"] == {"a": 1, "b": 2}


# --------------------------------------------------------------------------
# CI wiring
# --------------------------------------------------------------------------


def test_ci_asserts_the_zero_case_run_is_an_error() -> None:
    """The non-vacuity guard must be exercised in CI, not merely implemented.

    ``test_script_entry_points`` already proves ``scripts/differential_fuzz.py`` appears in a
    real ``run:`` command. This proves the workflow also PROBES it: a fuzz job that only ever
    runs the happy path cannot tell a working gate from one that reports green over nothing.
    """
    import yaml

    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    commands = [
        step.get("run", "")
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step.get("run"), str)
    ]
    probes = [
        command
        for command in commands
        if "differential_fuzz.py --count 0" in command and 'test "$status" -eq 2' in command
    ]
    assert probes, (
        "no CI step runs the differential fuzz with --count 0 and asserts exit 2; "
        "the non-vacuity guard is unproven in CI"
    )


# --------------------------------------------------------------------------
# Purity: a case's result must be a property of the CASE, not of the batch
# --------------------------------------------------------------------------
#
# This section exists because the engine really was impure. On Node >= 24 `JSON.parse` is
# not a pure function of its argument: a `string-escapes` case whose member name is the
# source text ``\\`` poisons V8's member-name reuse, and a later case of the same shape whose
# member name is any escape decoding to one character is handed back the backslash instead.
# The P8 fuzz went red on 5 of 200 measured seeds, and because the shrinker re-runs
# candidates in a different batch, it "minimized" the failure to an instance the two engines
# agree on and the report printed two identical digests under the heading "the two canonical
# engines disagree". `packages/typescript/src/json.ts` no longer delegates to `JSON.parse`;
# these tests are what stops the class coming back.


def _pure_case(case_id: str, digest: str) -> dict[str, Any]:
    return {"case_id": case_id, "ok": True, "canonical_base64": "AA==", "digest": digest}


def _three_cases() -> list[dict[str, Any]]:
    return [
        fuzz._case("purity/0", "structural", {"a": 1}),
        fuzz._case("purity/1", "structural", {"b": 2}),
        fuzz._case("purity/2", "structural", {"c": 3}),
    ]


def _honest_run(cases: list[dict[str, Any]], stem: str = "probe") -> list[dict[str, Any]]:
    """An engine that answers for the case in front of it and nothing else."""
    assert stem, "every probe must name where its streams go, so --keep keeps them all"
    return [_pure_case(case["case_id"], f"sha256:{case['case_id']}") for case in cases]


def test_a_pure_engine_reports_no_impurity() -> None:
    cases = _three_cases()
    batch = _honest_run(cases)
    assert fuzz.check_purity(cases, batch, _honest_run, sample=3) == []


def test_a_result_that_changes_under_reordering_is_caught() -> None:
    """The axis that catches cross-case leakage: the poisoner and its victim swap places."""
    cases = _three_cases()
    batch = _honest_run(cases)

    def leaky(batch_in: list[dict[str, Any]], stem: str) -> list[dict[str, Any]]:
        results = _honest_run(batch_in, stem)
        # "purity/2" is answered wrongly unless "purity/0" ran before it, which is exactly
        # the shape of the real defect.
        order = [case["case_id"] for case in batch_in]
        if "purity/2" in order and order.index("purity/2") < order.index("purity/0"):
            results[order.index("purity/2")]["digest"] = "sha256:POISONED"
        return results

    findings = fuzz.check_purity(cases, batch, leaky, sample=0)
    assert [(finding.case_id, finding.probe) for finding in findings] == [
        ("purity/2", "reversed corpus order")
    ]
    assert findings[0].batch != findings[0].again


def test_a_result_that_changes_when_the_case_is_alone_is_caught() -> None:
    """The second axis: a leak that survives reordering because it needs company at all."""
    cases = _three_cases()
    batch = _honest_run(cases)

    def only_wrong_alone(batch_in: list[dict[str, Any]], stem: str) -> list[dict[str, Any]]:
        results = _honest_run(batch_in, stem)
        if len(batch_in) == 1:
            results[0]["digest"] = "sha256:LONELY"
        return results

    findings = fuzz.check_purity(cases, batch, only_wrong_alone, sample=3)
    assert {finding.case_id for finding in findings} == {"purity/0", "purity/1", "purity/2"}
    assert {finding.probe for finding in findings} == {"the case alone"}


def test_a_missing_result_in_the_isolation_probe_is_an_impurity_not_a_pass() -> None:
    """A runner that answers for fewer cases than it was given must not read as pure.

    The reordering probe is answered HONESTLY here on purpose. An earlier version of this
    test let the runner return nothing for every probe, so the reorder half raised all the
    findings and the test passed no matter what the isolation half did with an empty
    stream -- a green test guarding nothing. The precondition the name claims has to be
    supplied: only the single-case probe comes back empty.
    """
    cases = _three_cases()
    batch = _honest_run(cases)

    def silent_when_alone(batch_in: list[dict[str, Any]], stem: str) -> list[dict[str, Any]]:
        return [] if len(batch_in) == 1 else _honest_run(batch_in, stem)

    findings = fuzz.check_purity(cases, batch, silent_when_alone, sample=1)
    assert findings, "an empty probe stream was accepted as agreement"
    assert [finding.probe for finding in findings] == ["the case alone"]
    assert all(finding.again is None for finding in findings)


def test_the_reorder_probe_still_runs_with_the_isolation_sample_switched_off() -> None:
    """``--purity-sample 0`` must narrow the check, not disable it."""
    cases = _three_cases()
    batch = _honest_run(cases)
    calls: list[int] = []

    def counting(batch_in: list[dict[str, Any]], stem: str) -> list[dict[str, Any]]:
        calls.append(len(batch_in))
        return _honest_run(batch_in, stem)

    fuzz.check_purity(cases, batch, counting, sample=0)
    assert calls == [3]


def test_every_probe_writes_to_its_own_stem_so_keep_keeps_them_all() -> None:
    """A --keep run that overwrote one probe file N times would leave nothing to triage."""
    cases = _three_cases()
    stems: list[str] = []

    def recording(batch_in: list[dict[str, Any]], stem: str) -> list[dict[str, Any]]:
        stems.append(stem)
        return _honest_run(batch_in, stem)

    fuzz.check_purity(cases, _honest_run(cases), recording, sample=3)
    assert stems[0] == "purity-reversed"
    assert len(set(stems)) == len(stems)


def test_the_isolation_sample_is_deterministic_and_spans_the_corpus() -> None:
    # Distinct dicts, not `[...] * 10`: list multiplication aliases the same objects and
    # renaming them would leave three ids repeated ten times.
    cases = [fuzz._case(f"purity/{index:03d}", "structural", {"a": index}) for index in range(30)]
    first = fuzz.isolation_sample(cases, 5)
    assert first == fuzz.isolation_sample(cases, 5)
    sampled = [case["case_id"] for case in first]
    assert sampled[0] == "purity/000"
    assert sampled[-1] == "purity/029"
    assert len(first) == 5
    assert fuzz.isolation_sample(cases, 0) == []
    assert fuzz.isolation_sample(cases, 500) == cases


# --------------------------------------------------------------------------
# Reporting: a re-run that does not reproduce must never be printed as the failure
# --------------------------------------------------------------------------


#: Sentinel workspaces. Never created, never written to -- the report is a pure function of
#: the path it is handed, and these only have to be recognisable in the rendered text.
KEPT_DIR = Path("/kept-by-the-fuzz")
SCRATCH_DIR = Path("/a-temporary-directory")


def _report_case() -> dict[str, Any]:
    return fuzz._case("structural/01620", "structural", {"a": 1})


AGREEING = {
    "case_id": "structural/01620",
    "ok": True,
    "canonical_base64": "AA==",
    "digest": "sha256:same",
}
BATCH_PYTHON = {
    "case_id": "structural/01620",
    "ok": True,
    "canonical_base64": "AA==",
    "digest": "sha256:same",
}
BATCH_TS = {"case_id": "structural/01620", "ok": False, "error": "UndeclaredPathError"}


def test_a_reproducing_case_reports_the_isolated_pair_plainly() -> None:
    """Control: the ordinary report is unchanged when the re-run really does reproduce."""
    report = fuzz._render(
        _report_case(),
        BATCH_PYTHON,
        BATCH_TS,
        seed=1,
        count=2,
        reproduced_in_isolation=True,
    )
    assert "the two canonical engines disagree" in report
    assert "DOES NOT REPRODUCE ON ITS OWN" not in report
    assert "  python          : " in report
    assert "NOT the failure" not in report


def test_a_rerun_that_does_not_reproduce_says_so_and_shows_the_batch_evidence() -> None:
    report = fuzz._render(
        _report_case(),
        AGREEING,
        AGREEING,
        seed=1,
        count=2,
        reproduced_in_isolation=False,
        batch_python=BATCH_PYTHON,
        batch_typescript=BATCH_TS,
        workspace=KEPT_DIR,
        kept=True,
    )
    assert "DOES NOT REPRODUCE ON ITS OWN" in report
    assert "not a pure function of a single case" in report
    assert "batch python    : " in report
    assert "batch typescript: " in report
    assert "UndeclaredPathError" in report
    assert report.count("NOT the failure") == 2
    assert f"{KEPT_DIR}/typescript.jsonl" in report


def test_a_rerun_that_does_not_reproduce_names_the_keep_flag_when_nothing_was_kept() -> None:
    report = fuzz._render(
        _report_case(),
        AGREEING,
        AGREEING,
        seed=1,
        count=2,
        reproduced_in_isolation=False,
        batch_python=BATCH_PYTHON,
        batch_typescript=BATCH_TS,
        workspace=SCRATCH_DIR,
        kept=False,
    )
    assert "NOT KEPT" in report
    assert "--keep" in report


def test_a_shrunk_instance_the_batch_never_ran_says_the_batch_outcome_is_unavailable() -> None:
    """Honesty in the other direction: do not attribute the raw case's outcome to a
    minimized value the batch never hashed."""
    report = fuzz._render(
        _report_case(),
        AGREEING,
        AGREEING,
        seed=1,
        count=2,
        reproduced_in_isolation=False,
        batch_python=None,
        batch_typescript=None,
        workspace=SCRATCH_DIR,
        kept=False,
    )
    assert "NOT AVAILABLE" in report
    assert "the batch never ran it" in report


def test_two_identical_outcomes_are_never_printed_as_a_plain_disagreement() -> None:
    """The defect this section exists for, stated as an invariant.

    The old report printed a python and a typescript line carrying the same digest under
    the heading "the two canonical engines disagree", and said nothing about the batch. Any
    report whose displayed pair agrees must carry the isolation banner.
    """
    report = fuzz._render(
        _report_case(),
        AGREEING,
        AGREEING,
        seed=1,
        count=2,
        reproduced_in_isolation=False,
        batch_python=BATCH_PYTHON,
        batch_typescript=BATCH_TS,
        workspace=SCRATCH_DIR,
        kept=False,
    )
    displayed = [line for line in report.splitlines() if "sha256:same" in line]
    assert displayed, "the isolated outcomes were not displayed at all"
    assert all("NOT the failure" in line or "batch python" in line for line in displayed)


def test_the_impurity_report_names_every_probe_and_where_the_evidence_is() -> None:
    findings = [
        fuzz.Impurity("structural/01620", "reversed corpus order", BATCH_TS, AGREEING),
        fuzz.Impurity("string-escapes/00819", "the case alone", AGREEING, BATCH_TS),
    ]
    report = fuzz._render_impurity(findings, 20260808, 2048, KEPT_DIR, True)
    assert "DIFFERENTIAL FUZZ IMPURITY" in report
    assert "structural/01620" in report
    assert "string-escapes/00819" in report
    assert "reversed corpus order" in report
    assert "the case alone" in report
    assert f"{KEPT_DIR}/corpus.jsonl" in report
    assert "shrinking is meaningless" in report


# --------------------------------------------------------------------------
# The purity gate's FATAL PATH, driven through main()
# --------------------------------------------------------------------------
#
# Every test above drives `check_purity` through a fake. None of them drove `main()`, so
# deleting the branch that acts on its findings -- `if impurities:` -> `if False and
# impurities:` -- left all 45 Python tests and all 719 jest tests green while silently
# reopening the false-green class the gate exists to close. A detector nothing consults is
# not a gate. These three tests consult it, and the third one proves the gate does not
# swallow what it is not for.
#
# No Node here on purpose: the `gates` job has no Node toolchain, and a test that skipped
# when Node was absent would reproduce the defect this file exists to prevent. The
# TypeScript runner is replaced with a Python fake of the SAME SIGNATURE, so the fake cannot
# be narrower than the thing it stands in for.

MAIN_COUNT = 40


def _install_fake_runner(
    monkeypatch: pytest.MonkeyPatch, answer: Any, tmp_path: Path
) -> list[list[str]]:
    """Replace the TypeScript half with ``answer``, and record the order of every batch."""
    seen: list[list[str]] = []
    runner = tmp_path / fuzz.TS_RUNNER_RELATIVE
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text("// a fake; run_typescript is replaced too\n", encoding="utf-8")
    monkeypatch.setattr(fuzz, "locate_runner", lambda root: runner)

    def fake_run_typescript(
        runner_path: Path,
        corpus: Path,
        results: Path,
        *,
        node: str = "node",
    ) -> list[dict[str, Any]]:
        records = fuzz.read_corpus(corpus)
        seen.append([record["case_id"] for record in records])
        return answer(records)

    monkeypatch.setattr(fuzz, "run_typescript", fake_run_typescript)
    return seen


def _agreeing(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A TypeScript engine that agrees with Python on everything."""
    return fuzz.engine_results(records)


def test_main_exits_1_and_reports_when_the_engine_is_impure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fatal path. An engine whose answer depends on the batch must redden the run."""
    victim = "structural/00000"

    def impure(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = _agreeing(records)
        order = [record["case_id"] for record in records]
        # Wrong only when the victim is NOT first, which is what an order-dependent leak
        # looks like: the full corpus is answered one way, the reversed corpus another.
        if victim in order and order.index(victim) != 0:
            results[order.index(victim)] = {
                "case_id": victim,
                "ok": False,
                "error": "UndeclaredPathError",
            }
        return results

    _install_fake_runner(monkeypatch, impure, tmp_path)
    status = fuzz.main(["--count", str(MAIN_COUNT), "--seed", "7", "--no-shrink"])
    captured = capsys.readouterr()
    assert status == 1
    assert "DIFFERENTIAL FUZZ IMPURITY" in captured.err
    assert "not a pure function of one case" in captured.err
    assert victim in captured.err


def test_main_exits_0_when_the_engine_is_pure_and_agrees(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Control. Without this the test above would pass against a gate that ALWAYS fires."""
    _install_fake_runner(monkeypatch, _agreeing, tmp_path)
    status = fuzz.main(["--count", str(MAIN_COUNT), "--seed", "7"])
    captured = capsys.readouterr()
    assert status == 0
    assert "differential fuzz passed" in captured.out
    assert "IMPURITY" not in captured.err


def test_main_still_reports_a_genuine_divergence_from_a_pure_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Running the purity check FIRST must not swallow the mismatch it runs ahead of.

    A deterministic engine divergence is pure -- the same case gets the same wrong answer
    in every batch and alone -- so it passes the purity probes and reaches the comparator.
    """
    victim = "structural/00000"

    def pure_but_wrong(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = _agreeing(records)
        for index, record in enumerate(records):
            if record["case_id"] == victim:
                results[index] = {"case_id": victim, "ok": False, "error": "UnsupportedTypeError"}
        return results

    _install_fake_runner(monkeypatch, pure_but_wrong, tmp_path)
    status = fuzz.main(["--count", str(MAIN_COUNT), "--seed", "7", "--no-shrink"])
    captured = capsys.readouterr()
    assert status == 1
    assert "IMPURITY" not in captured.err
    assert "DIFFERENTIAL FUZZ MISMATCH" in captured.err
    assert "cases disagree" in captured.err


def test_the_purity_probes_really_ran_inside_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run that never re-hashed anything would pass the two tests above vacuously."""
    seen = _install_fake_runner(monkeypatch, _agreeing, tmp_path)
    assert fuzz.main(["--count", str(MAIN_COUNT), "--seed", "7"]) == 0
    assert len(seen) == 1 + 1 + fuzz.DEFAULT_PURITY_SAMPLE, seen
    assert seen[0] == list(reversed(seen[1])), "the second batch was not the corpus reversed"
    assert all(len(batch) == 1 for batch in seen[2:]), "the isolation probes were not isolated"

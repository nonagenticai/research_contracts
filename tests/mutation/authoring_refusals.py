#!/usr/bin/env python3
"""Mutation harness for the authoring-time refusals (EXTENSIONS.md sections 7.1-7.4, 7.6, 8).

A test that stays green under its own mutation does not ship. Each entry names the guard it
breaks, the exact source edit that breaks it, and the test selector that MUST go red. The
source is restored whether the run passes or throws.

Committed rather than kept in a scratch directory, for two reasons. A reviewer cannot
reproduce a mutation result they cannot run; and the scratch version had a defect worth
designing out permanently -- two mutations had been appended into a SECOND list literal
after the real list closed, so `--only M28` matched nothing, the loop body never executed,
no failure was recorded, and the harness printed "every mutation fired". A sweep that
reports success without executing anything is the exact defect class these mutations exist
to catch. :func:`main` now refuses a filter that selects nothing, and refuses a run of fewer
than :data:`MINIMUM_MUTATIONS`.

A second, quieter way to report a verdict about code that never ran is CPython's bytecode
cache, which validates a ``.pyc`` on ``(mtime in whole seconds, source size)`` alone: two
same-length mutations of one file inside one second alias, and the later one is scored on
the earlier one's bytecode. Every Python invocation therefore gets a fresh, empty
``PYTHONPYCACHEPREFIX`` -- see :func:`run` for why ``PYTHONDONTWRITEBYTECODE`` does not
close this and why the jest branch needs nothing.

It lives under ``tests/`` and NOT under ``scripts/`` on purpose: everything in
``scripts/`` is enumerated by ``tests/test_script_entry_points.py`` and must be invoked
by a CI step, and this must never be one. It rewrites tracked source files, and a CI job
that mutates the tree it is verifying is a worse idea than no CI job at all. It is a
reviewer's tool, kept beside the tests it mutates.

Usage::

    uv run python tests/mutation/authoring_refusals.py          # every mutation
    uv run python tests/mutation/authoring_refusals.py M12      # one, by label prefix
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HP = ROOT / "src/research_contracts/canonical/hash_profile.py"
ST = ROOT / "src/research_contracts/canonical/structural.py"
RD = ROOT / "src/research_contracts/canonical/rendering.py"
DOC = ROOT / "EXTENSIONS.md"
TS_HP = ROOT / "packages/typescript/src/hashProfile.ts"
TS_ST = ROOT / "packages/typescript/src/structural.ts"
FIXTURE = ROOT / "fixtures/canonical-annotations/v1/refusals.json"

#: Non-vacuity floor. A harness that runs nothing must not report success.
MINIMUM_MUTATIONS = 25

#: ``(label, file, old, new, runner, selector)``.
MUTATIONS: list[tuple[str, Path, str, str, str, str]] = [
    (
        "M1 neuter the meta-schema consultation ENTIRELY (the whole 7.1-7.4 closure)",
        HP,
        "    names = [name for name in schema if name.startswith(_ANNOTATION_PREFIX)]\n"
        "    if not names:\n        return",
        "    names = [name for name in schema if name.startswith(_ANNOTATION_PREFIX)]\n"
        "    if names:\n        return",
        "py",
        "tests/test_extension_vocabulary.py",
    ),
    (
        "M2 widen _VOCABULARY with a name the meta-schema does not declare (7.1 drift test)",
        HP,
        '        "x-datacompany-array",\n        "x-datacompany-composition-point",',
        '        "x-datacompany-array",\n        "x-datacompany-hash-exclude",\n'
        '        "x-datacompany-composition-point",',
        "py",
        "tests/test_extension_vocabulary.py::test_the_engine_vocabulary_matches_the_meta_schema",
    ),
    (
        "M3 drop the unregistered-name refusal only (7.1 reproduction)",
        HP,
        "    unregistered = sorted(name for name in names if name not in _VOCABULARY)",
        "    unregistered = sorted(name for name in names if name not in _VOCABULARY | {'zzz'})\n"
        "    unregistered = []",
        "py",
        "tests/test_extension_vocabulary.py::"
        "test_7_1_a_misspelled_annotation_name_no_longer_derives_a_weaker_hash_view",
    ),
    (
        "M4 drop the lone-reason refusal only (7.2 reproduction)",
        HP,
        '    if "x-datacompany-hash-exclusion-reason" in schema and "x-datacompany-hash-excluded" not in schema:',
        "    if False:",
        "py",
        "tests/test_extension_vocabulary.py::"
        "test_7_2_a_lone_exclusion_reason_no_longer_derives_an_empty_exclusion_set",
    ),
    (
        "M5 restore the isinstance drop (7.3 reproduction)",
        HP,
        "    if not isinstance(declaration, dict):\n        raise HashProfileError(",
        "    if not isinstance(declaration, dict):\n        return\n    if False:\n        raise HashProfileError(",
        "py",
        "tests/test_extension_vocabulary.py::"
        "test_7_3_a_non_object_array_declaration_is_no_longer_dropped",
    ),
    (
        "M6 drop the array member check (7.4 reproduction)",
        HP,
        "    unknown = sorted(members - _ARRAY_REQUIRED_MEMBERS - _ARRAY_OPTIONAL_MEMBERS)",
        "    unknown = []",
        "py",
        "tests/test_extension_vocabulary.py::"
        "test_7_4_an_array_declaration_may_no_longer_retarget_itself",
    ),
    (
        "M7 widen _ARRAY_OPTIONAL_MEMBERS beyond the meta-schema (7.3/7.4 drift test)",
        HP,
        '_ARRAY_OPTIONAL_MEMBERS: frozenset[str] = frozenset({"order_key"})',
        '_ARRAY_OPTIONAL_MEMBERS: frozenset[str] = frozenset({"order_key", "pointer"})',
        "py",
        "tests/test_extension_vocabulary.py::"
        "test_the_engine_array_member_table_matches_the_meta_schema",
    ),
    (
        "M8 make the derivation refuse EVERY annotated node (the false-positive control)",
        HP,
        "    unregistered = sorted(name for name in names if name not in _VOCABULARY)",
        "    unregistered = sorted(names)",
        "py",
        "tests/test_extension_vocabulary.py::test_the_derivation_accepts_the_unmutated_probe",
    ),
    (
        "M9 move the unknown-operator refusal out of collection into evaluation (7.6)",
        ST,
        '    kind = rule.get("rule")\n    if kind not in _OPERANDS:',
        '    kind = rule.get("rule")\n    if False:',
        "py",
        "tests/test_extension_vocabulary.py::"
        "test_7_6_an_unknown_operator_refuses_before_any_failure_can_be_collected",
    ),
    (
        "M10 collect only the first rule of a declaration (7.6 control)",
        ST,
        '    for index, rule in enumerate(declared):\n        _validate_rule(rule, f"{where}/{index}")\n    return declared',
        '    for index, rule in enumerate(declared):\n        _validate_rule(rule, f"{where}/{index}")\n    return declared[:1]',
        "py",
        "tests/test_extension_vocabulary.py::test_7_6_the_control_two_well_formed_rules_both_report",
    ),
    (
        "M11 reword one refusal message (the recorded-refusal replay)",
        HP,
        '"not a released x-datacompany-* annotation. The released vocabulary is "',
        '"not a released x-datacompany-* annotation name. The released vocabulary is "',
        "py",
        "tests/test_extension_vocabulary.py::test_the_engine_reproduces_the_recorded_refusal",
    ),
    (
        "M12 restore ensure_ascii=True, which only the non-ASCII case can see",
        RD,
        'rendered = json.dumps(value, separators=(",", ":"), ensure_ascii=False)',
        'rendered = json.dumps(value, separators=(",", ":"))',
        "py",
        "tests/test_extension_vocabulary.py::test_the_engine_reproduces_the_recorded_refusal",
    ),
    (
        "M13 stop reading x-datacompany-hash-opaque at all (the declarative-only drift test)",
        HP,
        '        if schema.get("x-datacompany-hash-opaque") is True:\n            self.opaque.add(pointer)',
        "        if False:\n            self.opaque.add(pointer)",
        "py",
        "tests/test_extension_vocabulary.py::"
        "test_the_declarative_only_set_matches_what_the_engine_actually_reads",
    ),
    (
        "M20 START reading composition-point (the other direction of the same drift test)",
        HP,
        '        if schema.get("x-datacompany-hash-declaration-only") is True:',
        '        _ = schema.get("x-datacompany-composition-point")\n'
        '        if schema.get("x-datacompany-hash-declaration-only") is True:',
        "py",
        "tests/test_extension_vocabulary.py::"
        "test_the_declarative_only_set_matches_what_the_engine_actually_reads",
    ),
    (
        "M14 relabel ONE 7.3 case in the refusal record (its section-coverage guard)",
        FIXTURE,
        '"section": "7.3"',
        '"section": "7.9"',
        "py",
        "tests/test_extension_vocabulary.py::test_the_refusal_record_measures_something",
    ),
    (
        "M21 drop the literal-true refusal (section 8 row 2)",
        HP,
        "        if flag in schema and schema[flag] is not True:",
        "        if flag in schema and schema[flag] is not True and False:",
        "py",
        "tests/test_declaration_only_annotation.py::test_only_the_literal_true_has_an_effect",
    ),
    (
        "M22 make the literal-true refusal a TRUTHINESS test (the divergence it replaces)",
        HP,
        "        if flag in schema and schema[flag] is not True:",
        "        if flag in schema and not schema[flag]:",
        "py",
        "tests/test_extension_vocabulary.py::test_the_engine_reproduces_the_recorded_refusal",
    ),
    (
        "M23 drop the declaration-only/hash-excluded pairing (section 8 row 8)",
        HP,
        '    if "x-datacompany-hash-declaration-only" in schema and "x-datacompany-hash-excluded" in schema:',
        '    if False and "x-datacompany-hash-excluded" in schema:',
        "py",
        "tests/test_extension_vocabulary.py::test_section_8_row_8_says_what_the_engine_actually_does",
    ),
    (
        "M24 let the section 8 table claim an acceptance the engine does not make",
        DOC,
        "and **Yes** for the `hash-opaque` pair since D9's repair",
        "and **No** for the `hash-opaque` pair since D9's repair",
        "py",
        "tests/test_extension_vocabulary.py::test_section_8_row_8_says_what_the_engine_actually_does",
    ),
    (
        "M25 delete a row from the section 8 table without touching the count sentence",
        DOC,
        "| `composition-point` must be a `#/$defs/...` pointer |",
        "x| `composition-point` must be a `#/$defs/...` pointer |",
        "py",
        "tests/test_extension_vocabulary.py::test_section_8_counts_the_rows_its_table_actually_has",
    ),
    (
        "M26 break the row-8 control so 'refused' would measure the surrounding shape",
        HP,
        "    unregistered = sorted(name for name in names if name not in _VOCABULARY)",
        "    unregistered = sorted(names)",
        "py",
        "tests/test_extension_vocabulary.py::test_the_row_8_probes_are_not_refused_for_some_other_reason",
    ),
    (
        "M27 restore ensure_ascii=True, now visible on the D9 GUARD path too",
        RD,
        'rendered = json.dumps(value, separators=(",", ":"), ensure_ascii=False)',
        'rendered = json.dumps(value, separators=(",", ":"))',
        "py",
        "tests/test_extension_vocabulary.py::test_the_engine_reproduces_the_recorded_refusal",
    ),
    (
        "M15 neuter the port's meta-schema consultation entirely",
        TS_HP,
        "  const names = Object.keys(schema).filter((name) => name.startsWith(ANNOTATION_PREFIX));\n  if (names.length === 0) {\n    return;\n  }",
        "  const names = Object.keys(schema).filter((name) => name.startsWith(ANNOTATION_PREFIX));\n  if (names.length >= 0) {\n    return;\n  }",
        "ts",
        "test/authoringRefusals.test.ts",
    ),
    (
        "M16 reword the port's 7.4 message (the byte-identity replay)",
        TS_HP,
        "`${where} carries ${jsonText(unknown)}; a released array declaration carries ` +",
        "`${where} carries ${jsonText(unknown)}; a released array declaration accepts ` +",
        "ts",
        "test/authoringRefusals.test.ts",
    ),
    (
        "M17 restore the port's isRecord drop (the rewritten 7.3 tripwire)",
        TS_HP,
        "    if (arrayDeclaration !== undefined) {",
        "    if (isRecord(arrayDeclaration)) {",
        "ts",
        "test/coverage.test.ts",
    ),
    (
        "M18 make the port's derivation refuse every annotated node (its control)",
        TS_HP,
        "  const unregistered = sortedStrings(names.filter((name) => !VOCABULARY.includes(name)));",
        "  const unregistered = sortedStrings(names);",
        "ts",
        "test/authoringRefusals.test.ts",
    ),
    (
        "M19 render a JSON type with typeof again in the port (decision F parity)",
        TS_ST,
        "throw new CrossFieldError(`${where} is not a rule object, but a JSON ${jsonType(rule)}.`);",
        "throw new CrossFieldError(`${where} is not a rule object, but a JSON ${typeof rule}.`);",
        "ts",
        "test/authoringRefusals.test.ts",
    ),
    (
        "M28 drop the port's literal-true refusal (section 8 row 2, TypeScript half)",
        TS_HP,
        "    if (Object.hasOwn(schema, flag) && schema[flag] !== true) {",
        "    if (false && Object.hasOwn(schema, flag) && schema[flag] !== true) {",
        "ts",
        "test/authoringRefusals.test.ts",
    ),
    (
        "M29 drop the port's declaration-only/hash-excluded pairing (row 8, TypeScript half)",
        TS_HP,
        "    Object.hasOwn(schema, 'x-datacompany-hash-declaration-only') &&\n"
        "    Object.hasOwn(schema, 'x-datacompany-hash-excluded')",
        "    false &&\n    Object.hasOwn(schema, 'x-datacompany-hash-excluded')",
        "ts",
        "test/authoringRefusals.test.ts",
    ),
    (
        "M30 leave an unpaired surrogate RAW, which ensure_ascii=False reintroduced",
        RD,
        '    if not any("\\ud800" <= character <= "\\udfff" for character in rendered):\n        return rendered',
        "    if True:\n        return rendered",
        "py",
        "tests/test_extension_vocabulary.py",
    ),
]


def run(runner: str, selector: str) -> tuple[int, str]:
    """Invoke one runner over one mutated tree.

    The Python branch gets its OWN EMPTY bytecode cache. CPython validates a cached ``.pyc``
    against ``(source mtime truncated to whole SECONDS, source byte length)`` and nothing
    else -- not a content hash, unless the ``.pyc`` was written in checked-hash mode, which
    nothing here does. Two mutations of one file that produce the same byte length and are
    written inside the same second are therefore indistinguishable to that check. The second
    run then silently executes the FIRST mutation's bytecode, and the harness records the
    first mutation's verdict under the second's label: a mutation reported RED for a guard it
    never actually broke.

    No entry in :data:`MUTATIONS` can trigger this TODAY, and that was measured rather than
    assumed: of the 16 consecutive pairs over one file, none produce equal mutant lengths,
    and no ``.py`` mutant is the same length as the file it replaces. Both halves of the
    precondition are one edit away from being met, though -- the gap between consecutive
    writes of one file measured 1 to 5 seconds, median 2 -- so this is a trap laid for the
    next mutation appended, not a defect being repaired. It is closed here rather than
    documented because a reader cannot see byte lengths in a diff.

    ``PYTHONDONTWRITEBYTECODE=1`` is NOT sufficient and was rejected on measurement, not on
    taste. It suppresses WRITING a cache, never READING one already on disk -- and the
    preceding mutation, or any ordinary ``pytest`` run before the harness started, is what
    put it there. Reproduced directly: with two same-length mutations of ``hash_profile.py``
    stamped to one second, ``PYTHONDONTWRITEBYTECODE=1`` still replayed the first's failure
    set for the second. Only a cache directory that does not yet contain the module forces a
    compile from the bytes actually on disk, so each invocation gets a fresh
    ``PYTHONPYCACHEPREFIX`` tree, discarded with the mutation it belongs to.

    The jest branch needs no equivalent: ts-jest keys its transform cache on the file's
    CONTENTS, so two same-length mutants hash differently and cannot alias. Adding an
    isolation knob there would be a no-op that implied a defect that does not exist.
    """
    if runner == "py":
        with tempfile.TemporaryDirectory(prefix="mutation-pycache-") as pycache:
            proc = subprocess.run(
                ["uv", "run", "pytest", selector],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPYCACHEPREFIX": pycache},
            )
            return proc.returncode, proc.stdout + proc.stderr
    proc = subprocess.run(
        ["npx", "jest", selector],
        cwd=ROOT / "packages/typescript",
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


#: pytest exits 4 for usage errors -- a typo'd selector is "no tests ran", NOT a failing
#: assertion -- and jest exits 1 for "no tests found" as readily as for a failure. Mapping
#: any nonzero exit to RED made both look like a fired mutation. That is the same
#: "reports an unrun mutation as fired" shape this harness already shipped once, in a second
#: spelling, so the outcome is now read from the runner's own count line rather than from
#: its exit code alone.
_PYTEST_USAGE_ERROR = 4


def summarise(runner: str, output: str) -> str:
    """Name WHICH tests failed, not merely that something did.

    "exit 1" is the same byte whichever guard broke, so a bare exit code cannot tell a
    mutation that fired its own guard from one whose verdict was inherited -- the failure
    SET is the only thing that distinguishes them, and it is what caught the bytecode-cache
    aliasing this harness is now isolated against. Reading it also removes an older
    imprecision: the previous scan returned the first line containing " passed", which for a
    failing run was sometimes a sentence out of a test's own docstring rather than a result.
    """
    lines = [line.strip() for line in output.splitlines()]
    if runner == "py":
        # `FAILED <node id> - <error>`. Splitting on whitespace would truncate a
        # parametrised id at its first space, which several ids here contain.
        failed = {
            line.removeprefix("FAILED ").split(" - ", 1)[0]
            for line in lines
            if line.startswith("FAILED ")
        }
        if failed:
            return "; ".join(sorted(failed))[:600]
    # jest prints "Test Suites:" BEFORE "Tests:", and both carry " failed", so the count
    # line has to be named rather than pattern-matched.
    counts = [line for line in lines if line.startswith("Tests:")]
    if counts:
        return counts[0][:150]
    return next((line for line in lines if " passed" in line or " failed" in line), "")[:150]


def outcome(runner: str, code: int, output: str) -> tuple[bool, str]:
    """Return ``(the mutation fired, why)``.

    Fired means TESTS RAN AND FAILED. Three other things produce a nonzero exit and none of
    them is evidence about the mutation: a usage error, a collection error, and a selector
    that matched nothing.
    """
    if runner == "py":
        if code == _PYTEST_USAGE_ERROR or "no tests ran" in output:
            return False, "pytest ran NO TESTS (usage error or a selector matching nothing)"
        if "error" in output and " failed" not in output:
            return False, "pytest failed during COLLECTION, so no assertion was evaluated"
        if code != 0 and " failed" not in output:
            return False, f"exit {code} with no failure count; not an assertion failure"
        return code != 0, ""
    if "No tests found" in output or "Your test suite must contain at least one test" in output:
        return False, "jest ran NO TESTS"
    if code != 0 and "Tests:" not in output:
        return False, f"exit {code} with no jest summary; the suite did not run"
    return code != 0, ""


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    selected = [m for m in MUTATIONS if only is None or m[0].startswith(only)]
    if only is not None and not selected:
        print(f"no mutation matches {only!r}; nothing ran", file=sys.stderr)
        return 2
    if only is None and len(selected) < MINIMUM_MUTATIONS:
        print(
            f"{len(selected)} mutations found, {MINIMUM_MUTATIONS} expected; a harness that "
            "measures less than it did is not a passing harness",
            file=sys.stderr,
        )
        return 2

    executed = 0
    failures: list[str] = []
    for label, path, old, new, runner, selector in selected:
        text = path.read_text(encoding="utf-8")
        if old not in text:
            print(f"!! {label}: ANCHOR NOT FOUND in {path.name}")
            failures.append(label)
            continue
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        try:
            code, output = run(runner, selector)
        finally:
            path.write_text(text, encoding="utf-8")
        executed += 1
        fired, why = outcome(runner, code, output)
        verdict = "RED" if fired else ("*** DID NOT RUN ***" if why else "*** STILL GREEN ***")
        print(f"{label}\n    -> {verdict} (exit {code})")
        print(f"    {why or summarise(runner, output)}\n")
        if not fired:
            failures.append(label)

    if executed != len(selected):
        print(f"executed {executed} of {len(selected)} selected mutations", file=sys.stderr)
        return 1
    if failures:
        print(f"MUTATIONS THAT DID NOT FIRE: {failures}", file=sys.stderr)
        return 1
    print(f"all {executed} mutations executed and fired")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Mutation harness for the cross-field operator vectors (EXTENSIONS.md §4.2 and §4.5).

A test that stays green under its own mutation does not ship. Each entry names the guard it
breaks, the exact source edit that breaks it, and the test selector that MUST go red. The
source is restored whether the run passes or throws.

Committed rather than kept in a scratch directory, for the reason the sibling harness beside
it gives: a reviewer cannot reproduce a mutation result they cannot run. It lives under
``tests/`` and NOT under ``scripts/`` on purpose -- everything in ``scripts/`` is enumerated
by ``tests/test_script_entry_points.py`` and must be invoked by a CI step, and a CI job that
mutates the tree it is verifying is a worse idea than no CI job at all.

The mutations come in matched TRIPLES wherever the guard has more than one failure direction,
because a vector set can be one-sided in two opposite ways and only one of them is obvious.
For §4.2 that is: restore the Python coercion (M1), reject every pair (M2), accept every pair
(M3). M2 is the one a clean corpus cannot motivate -- without the ``failures: []`` control
vectors, an engine that reported every equality as violated would satisfy every failing
vector in the record. For §4.5 the same shape is M8 (report every member as missing its key)
beside M5/M6 (report none).

Every mutation is run against BOTH engines' suites where the guard exists in both, because a
Python-only closure derives a result the other engine cannot (EXTENSIONS.md §9).

Usage::

    uv run python tests/mutation/cross_field_operators.py          # every mutation
    uv run python tests/mutation/cross_field_operators.py M4       # one, by label prefix
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: A PRIVATE bytecode cache directory PER MUTATION, and it is not hygiene -- it is the fix
#: for a measured defect in this harness that made one mutation report another's result.
#:
#: CPython validates a cached ``.pyc`` against exactly two facts about its source: the mtime
#: in WHOLE SECONDS and the size in bytes. A mutation harness rewrites one source file over
#: and over, and two different mutations of the same file are very often the same size --
#: ``"uniqueness"`` -> ``"disjointness"`` and ``member`` -> ``_MISSING`` both add exactly two
#: bytes here -- so two consecutive mutants written inside one second are INDISTINGUISHABLE
#: to the cache and the second run executes the FIRST one's bytecode.
#:
#: That is not hypothetical: it happened on the first full run of this file. M10 was recorded
#: RED "because" the no-declared-key vector failed, which is M9's failure; run alone, M10
#: reddens the ``unique_by`` vector instead. Both happened to be red either way, so the
#: verdict survived -- but the mechanism is verdict-blind. A mutation whose predecessor was
#: GREEN would be reported green, and a mutation the predecessor's bytecode already breaks
#: would be reported red without ever running. Reproduced deterministically by stamping the
#: second mutant with the first's mtime and size, which is the same state the race reaches.
#:
#: ``PYTHONPYCACHEPREFIX`` moves the whole cache tree out of the repository, so a per-label
#: directory is a guaranteed cold cache with no in-tree ``__pycache__`` to fall back to.
#: :data:`DISTINCT_OUTCOME_PAIRS` is the falsification: it names the two mutations that
#: actually collided, and the run fails if their failure sets are ever equal again.
PYCACHE_ROOT = Path(tempfile.gettempdir()) / "cross-field-mutation-pycache"


def _slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", label)[:60] or "unlabelled"


ST = ROOT / "src/research_contracts/canonical/structural.py"
TS_ST = ROOT / "packages/typescript/src/structural.ts"
FIXTURE = ROOT / "fixtures/canonical-cross-field/v1/operator-vectors.json"

PY_SELECTOR = "tests/test_cross_field_operator_vectors.py"
TS_SELECTOR = "crossFieldOperatorVectors"

#: An EQUALITY over the mutation set, not a floor.
#:
#: It WAS a floor -- 16, against 20 actual -- which meant four mutations could be deleted while
#: the harness still printed "all N executed and fired". The vector record next door pins its
#: case count as an equality for precisely that reason, and a mutation harness is the last
#: place that argument should be weakened: the way a mutation suite dies is one entry at a
#: time, and every step but the last is invisible to a floor.
EXPECTED_MUTATIONS = 35

#: ``(label, file, old, new, runner, selector)``.
MUTATIONS: list[tuple[str, Path, str, str, str, str]] = [
    # ------------------------------------------------------------------ §4.2, Python ---
    (
        "M1 restore Python == in the equality comparator (the §4.2 defect itself)",
        ST,
        "    return _identity_marker(left) == _identity_marker(right)",
        "    return left == right",
        "py",
        PY_SELECTOR,
    ),
    (
        "M2 reject EVERY pair -- the mutation only the passing control vectors can catch",
        ST,
        "    return _identity_marker(left) == _identity_marker(right)",
        "    return False",
        "py",
        PY_SELECTOR,
    ),
    (
        "M3 accept EVERY pair -- the fail-open direction, caught by the failing vectors",
        ST,
        "    return _identity_marker(left) == _identity_marker(right)",
        "    return True",
        "py",
        PY_SELECTOR,
    ),
    (
        "M4 drop the comparator from `equal` alone, leaving equal_when_both_present fixed",
        ST,
        '            return [f"{name}: {left_at} and {right_at} must both be present and equal"]\n'
        "        return []\n"
        '    if kind == "equal_when_both_present":',
        '            return [f"{name}: {left_at} and {right_at} must both be present and equal"]\n'
        "        return []\n"
        '    if kind == "equal_when_both_present_DISABLED":',
        "py",
        PY_SELECTOR,
    ),
    (
        "M4b drop it from equal_when_both_present alone -- the operator §4.2 also names",
        ST,
        '            return [f"{name}: {left_at} and {right_at} must be equal when both present"]',
        '            return [f"{name}: {left_at} and {right_at} MUST BE EQUAL when both present"]',
        "py",
        PY_SELECTOR,
    ),
    # ------------------------------------------------------------------ §4.2, port ---
    (
        "M-T1 comparator -> JavaScript === in the port (object member order diverges)",
        TS_ST,
        "  return identityMarker(left) === identityMarker(right);",
        "  return (left as never) === (right as never);",
        "ts",
        TS_SELECTOR,
    ),
    (
        "M-T2 reject EVERY pair in the port",
        TS_ST,
        "  return identityMarker(left) === identityMarker(right);",
        "  return false;",
        "ts",
        TS_SELECTOR,
    ),
    # ------------------------------------------------------------------ §4.5, Python ---
    (
        "M5 restore the SILENT SKIP on the disjoint LEFT walk (§4.5 step 2)",
        ST,
        '            failures.append(_missing_member_key(name, left_at, index, "disjointness", left_key))\n            continue',
        "            continue",
        "py",
        PY_SELECTOR,
    ),
    (
        "M6 restore the SILENT SKIP on the disjoint RIGHT walk (§4.5 step 3)",
        ST,
        '            failures.append(_missing_member_key(name, right_at, index, "disjointness", right_key))\n            continue',
        "            continue",
        "py",
        PY_SELECTOR,
    ),
    (
        "M7 report the RIGHT walk before the LEFT one -- failure order is contract text",
        ST,
        '            failures.append(_missing_member_key(name, right_at, index, "disjointness", right_key))',
        '            failures.insert(0, _missing_member_key(name, right_at, index, "disjointness", right_key))',
        "py",
        PY_SELECTOR,
    ),
    (
        "M8 report EVERY member as missing its key -- the §4.5 reject-everything direction",
        ST,
        "    return member if key_pointer is None else _at(member, key_pointer)",
        "    return _MISSING",
        "py",
        PY_SELECTOR,
    ),
    (
        "M9 make a side with NO declared key report its members -- breaks both released rules",
        ST,
        "    return member if key_pointer is None else _at(member, key_pointer)",
        "    return _MISSING if key_pointer is None else _at(member, key_pointer)",
        "py",
        PY_SELECTOR,
    ),
    (
        "M10 align unique_by onto disjoint's WORD instead of the reverse (released text moves)",
        ST,
        '_missing_member_key(name, at, index, "uniqueness", key_pointer)',
        '_missing_member_key(name, at, index, "disjointness", key_pointer)',
        "py",
        PY_SELECTOR,
    ),
    (
        "M11 reword the shared message by one article -- the exactness control",
        ST,
        "does not carry the {role} key {key_pointer or ''}",
        "does not carry {role} key {key_pointer or ''}",
        "py",
        PY_SELECTOR,
    ),
    # ------------------------------------------------------------------ §4.5, port ---
    (
        "M-T3 restore the silent skip on the port's disjoint LEFT walk",
        TS_ST,
        "      failures.push(missingMemberKey(name, leftPointer, index, 'disjointness', leftKey));\n      return;",
        "      return;",
        "ts",
        TS_SELECTOR,
    ),
    (
        "M-T4 restore the silent skip on the port's disjoint RIGHT walk",
        TS_ST,
        "      failures.push(missingMemberKey(name, rightPointer, index, 'disjointness', rightKey));\n      return;",
        "      return;",
        "ts",
        TS_SELECTOR,
    ),
    (
        "M-T5 report the port's RIGHT walk first -- the two engines would order differently",
        TS_ST,
        "      failures.push(missingMemberKey(name, rightPointer, index, 'disjointness', rightKey));",
        "      failures.unshift(missingMemberKey(name, rightPointer, index, 'disjointness', rightKey));",
        "ts",
        TS_SELECTOR,
    ),
    (
        "M-T6 reword the port's shared message -- byte-identity across engines",
        TS_ST,
        "does not carry the ${role} key ${keyPointer ?? ''}",
        "does not carry ${role} key ${keyPointer ?? ''}",
        "ts",
        TS_SELECTOR,
    ),
    # ------------------------------- §4.2, the uncomparable-operand regression guard ---
    (
        "M14 let an uncomparable operand RAISE again -- the regression the refuter found",
        ST,
        "    except UnstableFloatError, UnsupportedTypeError:\n        return False",
        "    except UnstableFloatError:\n        return False",
        "py",
        PY_SELECTOR,
    ),
    (
        "M15 call an uncomparable operand UNEQUAL instead of undecidable",
        ST,
        "        if not _comparable(value)",
        "        if False and not _comparable(value)",
        "py",
        PY_SELECTOR,
    ),
    (
        "M16 guard `equal` only, leaving equal_when_both_present able to raise",
        ST,
        "        if left is _MISSING or right is _MISSING:\n            return []\n        uncomparable",
        "        if left is _MISSING or right is _MISSING:\n            return []\n        never_mind",
        "py",
        PY_SELECTOR,
    ),
    (
        "M-T7 let an uncomparable operand throw out of the port",
        TS_ST,
        "    if (error instanceof UnstableFloatError || error instanceof UnsupportedTypeError) {",
        "    if (error instanceof UnstableFloatError && error instanceof UnsupportedTypeError) {",
        "ts",
        TS_SELECTOR,
    ),
    # ------------------- the extension: unique_by and disjoint had the SAME defect ---
    (
        "M21 leave unique_by RAISING on a member key with no canonical bytes",
        ST,
        '        if not _comparable(value):\n            failures.append(_uncomparable_text(name, f"{at}/{index}", "uniqueness"))\n            continue\n',
        "",
        "py",
        PY_SELECTOR,
    ),
    (
        "M22 leave the disjoint LEFT walk raising",
        ST,
        '        if not _comparable(value):\n            failures.append(_uncomparable_text(name, f"{left_at}/{index}", "disjointness"))\n            continue\n',
        "",
        "py",
        PY_SELECTOR,
    ),
    (
        "M23 leave the disjoint RIGHT walk raising",
        ST,
        '        if not _comparable(value):\n            failures.append(_uncomparable_text(name, f"{right_at}/{index}", "disjointness"))\n            continue\n',
        "",
        "py",
        PY_SELECTOR,
    ),
    (
        "M24 name the wrong proposition in unique_by (the role word is not decorative)",
        ST,
        'f"{at}/{index}", "uniqueness")',
        'f"{at}/{index}", "disjointness")',
        "py",
        PY_SELECTOR,
    ),
    (
        "M25 report an uncomparable RIGHT member before the LEFT walk's failures",
        ST,
        '            failures.append(_uncomparable_text(name, f"{right_at}/{index}", "disjointness"))',
        '            failures.insert(0, _uncomparable_text(name, f"{right_at}/{index}", "disjointness"))',
        "py",
        PY_SELECTOR,
    ),
    (
        "M-T8 leave the port's unique_by raising",
        TS_ST,
        "    if (!comparable(value)) {\n      failures.push(uncomparableText(name, `${at}/${index}`, 'uniqueness'));\n      return;\n    }\n",
        "",
        "ts",
        TS_SELECTOR,
    ),
    (
        "M-T9 leave the port's disjoint RIGHT walk raising",
        TS_ST,
        "    if (!comparable(value)) {\n      failures.push(uncomparableText(name, `${rightPointer}/${index}`, 'disjointness'));\n      return;\n    }\n",
        "",
        "ts",
        TS_SELECTOR,
    ),
    # ------------------------------------------- the record's own non-vacuity guards ---
    (
        "M12 shrink the record to one section -- the per-section partition must notice",
        FIXTURE,
        '"sections": ["4.2", "4.5"],',
        '"sections": ["4.2"],',
        "py",
        PY_SELECTOR,
    ),
    (
        "M13 point the record at a port suite that does not exist (both-engines-or-neither)",
        FIXTURE,
        '"packages/typescript/test/crossFieldOperatorVectors.test.ts"',
        '"packages/typescript/test/somethingElse.test.ts"',
        "py",
        PY_SELECTOR,
    ),
    (
        "M17 admit a SECOND per-engine divergence by copying the declared one's key",
        FIXTURE,
        '"right": [{ "q": 8 }]\n      },\n      "expect": { "failures": [] }',
        '"right": [{ "q": 8 }]\n      },\n      "expect": { "failures": [], "failures_port": ["x"], '
        '"port_divergence": "a second declared divergence, long enough to clear the '
        'justification floor without being one" }',
        "py",
        PY_SELECTOR,
    ),
    (
        "M18 strip the JUSTIFICATION from the declared per-engine divergence",
        FIXTURE,
        '"port_divergence": "`JSON.parse` collapses',
        '"port_divergence_removed": "`JSON.parse` collapses',
        "py",
        PY_SELECTOR,
    ),
    (
        "M19 make the declared divergence state the SAME expectation for both engines",
        FIXTURE,
        '"failures_port": [],',
        '"failures_port": ["left_equals_right: /left is not a value RFC 8785 can canonicalize, so the equality cannot be decided"],',
        "py",
        PY_SELECTOR,
    ),
    (
        "M20 drop the released-shape right_key vector's rule to a left-keyed one",
        FIXTURE,
        '"right_key": "/pointer"',
        '"left_key": "/pointer"',
        "py",
        PY_SELECTOR,
    ),
]


def run(runner: str, selector: str, label: str = "") -> tuple[int, str]:
    if runner == "py":
        result = subprocess.run(
            [sys.executable, "-m", "pytest", selector],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPYCACHEPREFIX": str(PYCACHE_ROOT / _slug(label))},
        )
    else:
        result = subprocess.run(
            ["npx", "jest", selector],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(ROOT / "packages" / "typescript"),
        )
    return result.returncode, result.stdout + result.stderr


def outcome(runner: str, code: int, output: str) -> tuple[bool, str]:
    """Did the mutation FIRE, or did the run merely fail to happen?

    A collection error, a selector matching nothing and a usage error all exit non-zero
    without a single assertion being evaluated. Counting those as RED is how a harness
    reports success for a suite that never ran.
    """
    if runner == "py":
        if "no tests ran" in output:
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


def _collision_pairs() -> list[tuple[str, str]]:
    """Consecutive same-file mutations whose mutants are the SAME SIZE, DERIVED not listed.

    These are the pairs a leaking bytecode cache can confuse, because CPython validates a
    ``.pyc`` on ``(source mtime in whole seconds, source size)`` alone -- so a same-size pair
    written inside one second is indistinguishable to it. Each such pair MUST redden a
    different set of tests; if two of them ever report the identical failure set, the cache
    isolation on :data:`PYCACHE_ROOT` has regressed.

    This was a HAND-LISTED table naming only ``("M9", "M10")``, and the hand list was wrong in
    the usual direction: ``M4``/``M4b`` are a second same-size consecutive pair on the same
    file -- both shrink it by ten bytes -- and were unnamed. Deriving it from the actual
    mutant sizes means a third pair is covered the day it is written, and it is the same
    correction this session had to make four times over: a scope somebody counted by hand was
    smaller than the corpus.
    """
    pairs: list[tuple[str, str]] = []
    for current, following in pairwise(MUTATIONS):
        label, path, old, new, runner, _ = current
        next_label, next_path, next_old, next_new, _, _ = following
        if runner != "py" or path != next_path:
            continue
        text = path.read_text(encoding="utf-8")
        if old not in text or next_old not in text:
            continue
        this_size = len(text.replace(old, new, 1).encode("utf-8"))
        next_size = len(text.replace(next_old, next_new, 1).encode("utf-8"))
        if this_size == next_size:
            pairs.append((label.split()[0], next_label.split()[0]))
    return pairs


#: Non-vacuity: the derivation must find SOMETHING, or the guard below is satisfied by an
#: empty list -- which is how a guard stops guarding without anyone noticing.
MINIMUM_COLLISION_PAIRS = 1

#: The pair that ACTUALLY collided, on 2026-08-04, and produced the wrong recorded result.
#: Asserted to still be in the derived set, because that is the case the guard is known to
#: catch; a derivation that no longer contains it has stopped covering the observed defect.
#:
#: The COUNT is deliberately not pinned. M4/M4b were a second same-size pair when the refuter
#: found them, and they stopped being one when the uncomparable-operand fix moved both anchors
#: -- a legitimate edit. Pinning the count would make every anchor edit red for a reason that
#: has nothing to do with what is being guarded; pinning the known collision does not.
REQUIRED_COLLISION_PAIR = ("M9", "M10")

FAILED_ID = re.compile(r"^FAILED (\S+)", re.MULTILINE)


def failed_ids(output: str) -> frozenset[str]:
    return frozenset(FAILED_ID.findall(output))


def summarise(output: str) -> str:
    lines = [
        line.strip()
        for line in output.splitlines()
        if line.startswith(("FAILED", "Tests:", "  ●"))
        or line.strip().startswith(("1 failed", "assert"))
    ]
    return " | ".join(lines[:4]) or output.strip().splitlines()[-1][:160]


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    selected = [m for m in MUTATIONS if only is None or m[0].startswith(only)]
    if only is not None and not selected:
        print(f"no mutation matches {only!r}; nothing ran", file=sys.stderr)
        return 2
    if only is None and len(selected) != EXPECTED_MUTATIONS:
        print(
            f"{len(selected)} mutations found, {EXPECTED_MUTATIONS} expected; a harness that "
            "measures less than it did is not a passing harness, and one that silently "
            "measures more is not a reviewed one",
            file=sys.stderr,
        )
        return 2

    executed = 0
    failures: list[str] = []
    reddened: dict[str, frozenset[str]] = {}
    for label, path, old, new, runner, selector in selected:
        text = path.read_text(encoding="utf-8")
        if old not in text:
            print(f"!! {label}: ANCHOR NOT FOUND in {path.name}")
            failures.append(label)
            continue
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        try:
            code, output = run(runner, selector, label)
        finally:
            path.write_text(text, encoding="utf-8")
        executed += 1
        reddened[label.split()[0]] = failed_ids(output)
        fired, why = outcome(runner, code, output)
        verdict = "RED" if fired else ("*** DID NOT RUN ***" if why else "*** STILL GREEN ***")
        print(f"{label}\n    -> {verdict} (exit {code})")
        print(f"    {why or summarise(output)}\n")
        if not fired:
            failures.append(label)

    if executed != len(selected):
        print(f"executed {executed} of {len(selected)} selected mutations", file=sys.stderr)
        return 1
    collisions = _collision_pairs()
    print(f"same-size consecutive mutation pairs (derived): {collisions}")
    if only is None and len(collisions) < MINIMUM_COLLISION_PAIRS:
        print(
            f"the same-size collision scan found {len(collisions)} pairs, expected at least "
            f"{MINIMUM_COLLISION_PAIRS}; a guard with nothing to guard is not a guard",
            file=sys.stderr,
        )
        return 1
    if only is None and REQUIRED_COLLISION_PAIR not in collisions:
        print(
            f"{REQUIRED_COLLISION_PAIR} is the pair that actually collided and it is no longer "
            f"same-size, so the isolation guard no longer covers the observed defect: "
            f"{collisions}",
            file=sys.stderr,
        )
        return 1
    for first, second in collisions:
        if first not in reddened or second not in reddened:
            continue
        if reddened[first] == reddened[second]:
            print(
                f"{first} and {second} reddened the SAME tests ({sorted(reddened[first])}). "
                "They cannot: they break different guards. The bytecode cache is leaking one "
                "mutation's compiled source into the next run -- see PYCACHE_ROOT.",
                file=sys.stderr,
            )
            return 1
    if failures:
        print(f"MUTATIONS THAT DID NOT FIRE: {failures}", file=sys.stderr)
        return 1
    print(f"all {executed} mutations executed and fired")
    return 0


if __name__ == "__main__":
    sys.exit(main())

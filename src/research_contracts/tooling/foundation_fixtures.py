"""FND-002 tasks 2/3/6 foundation fixture harness.

Replays every committed fixture under ``fixtures/foundation/v1`` against the released
engine, exactly as ``canonical_fixtures`` does for the canonical tier:

* ``valid/`` must validate, schema layer **and** cross-field rules;
* ``invalid/`` must fail, and fail for the reason the fixture itself names;
* ``hash/`` must reproduce golden canonical bytes **and** the golden digest;
* ``mutations/`` must change or preserve the digest as declared;
* ``manifests/`` must still be **derivable** from the schema annotations.

This is a SEPARATE harness from ``canonical_fixtures``, deliberately and not for tidiness.
That module pins the canonical corpus with an equality in ``EXPECTED_CHECKS``, and the
TypeScript suite re-derives per-suite counts by parsing its source. Adding foundation
suites there would move a number two other gates read, in a repository where several
sessions land concurrently. The two corpora are pinned independently and neither can
silently absorb the other's drift.

Every guard `canonical_fixtures` learned the hard way is reproduced here rather than
re-earned: a suite directory that does not exist is an error and not an empty glob, each
suite declares a floor, and the run total is an equality. Deleting fixtures must go red.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..canonical import (
    CanonicalError,
    build_hash_view,
    canonical_json_bytes,
    canonical_sha256,
    compute_content_hash,
    derive_hash_profile,
    validate_hash_profile,
    validate_instance,
)
from ..canonical.registry import schema_failure_codes
from .errors import ContractError
from .paths import REPOSITORY_ROOT

COVERAGE_EXIT = 2
FAILURES_EXIT = 1

FIXTURES_ROOT = REPOSITORY_ROOT / "fixtures"
FOUNDATION_RELATIVE = Path("foundation/v1")


@dataclass(frozen=True)
class Suite:
    """One fixture directory and the number of checks it must contribute."""

    name: str
    relative: Path
    minimum: int


SUITES: tuple[Suite, ...] = (
    Suite("foundation/valid", FOUNDATION_RELATIVE / "valid", 30),
    Suite("foundation/invalid", FOUNDATION_RELATIVE / "invalid", 58),
    Suite("foundation/hash", FOUNDATION_RELATIVE / "hash", 2),
    Suite("foundation/mutations", FOUNDATION_RELATIVE / "mutations", 6),
    Suite("foundation/manifests", FOUNDATION_RELATIVE / "manifests", 2),
)

#: Pinned total for the FOUNDATION corpus. Independent of ``canonical_fixtures``'s
#: ``EXPECTED_CHECKS``; the two are asserted to be disjoint by the test suite so a fixture
#: cannot be counted twice or migrate between corpora unnoticed.
EXPECTED_FOUNDATION_CHECKS = sum(suite.minimum for suite in SUITES)


def load(path: Path) -> Any:
    """Read a fixture, reporting an unreadable or malformed one as a diagnosis."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{path}: {exc}") from exc


def files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json"))


def check_validity(root: Path, failures: list[str], counts: dict[str, int]) -> None:
    checked = 0
    for path in files(root / "valid"):
        fixture = load(path)
        try:
            errors = validate_instance(fixture["instance"], fixture["schema_ref"])
        except CanonicalError as exc:
            failures.append(f"{path.name}: expected valid, validation raised {exc}")
            checked += 1
            continue
        if errors:
            failures.append(f"{path.name}: expected valid, got {errors}")
        checked += 1
    counts["foundation/valid"] = checked

    checked = 0
    for path in files(root / "invalid"):
        fixture = load(path)
        try:
            errors = validate_instance(fixture["instance"], fixture["schema_ref"])
        except CanonicalError as exc:
            # A raise is not the same fact as a recorded failure. An invalid fixture that
            # blows the engine up is a defect in the schema, not evidence that the contract
            # rejected the instance, so it is never counted as a pass.
            failures.append(f"{path.name}: expected a recorded failure, validation raised {exc}")
            checked += 1
            continue
        if not errors:
            failures.append(f"{path.name}: expected invalid, but it validated")
        else:
            rendered = " | ".join(errors)
            for expected in fixture["expected_error_contains"]:
                if expected not in rendered:
                    failures.append(
                        f"{path.name}: failed, but not for the named reason {expected!r}: "
                        f"{rendered}"
                    )
        failures.extend(_neutral_failure_errors(path, fixture))
        checked += 1
    counts["foundation/invalid"] = checked


def _neutral_failure_errors(path: Path, fixture: dict[str, Any]) -> list[str]:
    """Check the LANGUAGE-NEUTRAL half of an invalid fixture's declaration.

    ``expected_error_contains`` pins ``jsonschema``'s English prose and can only ever be
    replayed by ``jsonschema`` -- that is defect D2f. ``expected_schema_failures`` pins the
    RFC 6901 pointer and the JSON Schema 2020-12 keyword instead, which the TypeScript suite
    asserts against Ajv from the same committed file.

    The declared set is the INTERSECTION of what both conforming validators report, and the
    assertion is containment rather than equality. The two engines genuinely differ in
    incidental applicator noise -- Ajv additionally surfaces the failed ``if``, and
    ``jsonschema`` additionally cascades an ``unevaluatedProperties`` failure whenever a
    nested member fails -- while agreeing exactly on the pointer and keyword that identify
    the defect. Pinning the intersection captures the agreement; demanding equality would
    pin one engine's reporting style as the contract.

    A NON-EMPTY declaration is required for every fixture that is not marked
    ``cross_field_only``: an empty list would make the containment check vacuously true,
    which is the whole failure class this repository exists to eliminate.
    """
    declared = [
        (entry["pointer"], entry["keyword"]) for entry in fixture["expected_schema_failures"]
    ]
    if fixture.get("cross_field_only") is True:
        if declared:
            return [
                f"{path.name}: is marked cross_field_only but declares schema failures "
                f"{declared}; a cross-field-only fixture is one the schema layer ACCEPTS"
            ]
        return []
    if not declared:
        return [
            f"{path.name}: declares no expected_schema_failures and is not marked "
            "cross_field_only, so the containment check below would be vacuously true"
        ]
    observed = set(schema_failure_codes(fixture["instance"], fixture["schema_ref"]))
    missing = [entry for entry in declared if entry not in observed]
    if missing:
        return [
            f"{path.name}: declared schema failure(s) {missing} were not reported; observed "
            f"{sorted(observed)}"
        ]
    return []


def set_pointer(document: Any, pointer: str, value: Any) -> None:
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer.lstrip("/").split("/")]
    node = document
    for token in tokens[:-1]:
        node = node[int(token)] if isinstance(node, list) else node[token]
    last = tokens[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def check_hash(root: Path, failures: list[str], counts: dict[str, int]) -> None:
    checked = 0
    for path in files(root / "hash"):
        fixture = load(path)
        try:
            profile = derive_hash_profile(fixture["schema_ref"])
            view = build_hash_view(fixture["instance"], profile)
            canonical = canonical_json_bytes(view)
        except CanonicalError as exc:
            failures.append(f"{path.name}: {exc}")
            checked += 1
            continue
        # Bytes first, digest second, and BOTH. A matching digest over different canonical
        # bytes would be a collision or a coincidence, never proof of the same algorithm.
        if canonical.decode("utf-8") != fixture["expected_hash_view_canonical_json"]:
            failures.append(f"{path.name}: hash-view canonical JSON differs")
        digest = canonical_sha256(view)
        if digest != fixture["expected_content_hash"]:
            failures.append(
                f"{path.name}: expected {fixture['expected_content_hash']}, got {digest}"
            )
        checked += 1
    counts["foundation/hash"] = checked

    checked = 0
    for path in files(root / "mutations"):
        case = load(path)
        base_path = root / "hash" / f"{case['base_fixture']}.json"
        if not base_path.is_file():
            raise ContractError(
                f"{path}: names base fixture {case['base_fixture']!r}, which does not exist at "
                f"{base_path}. A mutation case whose base is missing would otherwise be skipped."
            )
        base = load(base_path)
        mutated = json.loads(json.dumps(base["instance"]))
        for mutation in case["mutations"]:
            set_pointer(mutated, mutation["pointer"], mutation["value"])
        try:
            digest = compute_content_hash(mutated, base["schema_ref"])
        except CanonicalError as exc:
            failures.append(f"{path.name}: mutated instance could not be hashed: {exc}")
            checked += 1
            continue
        same = digest == base["expected_content_hash"]
        if (case["expect"] == "unchanged") != same:
            failures.append(f"{path.name}: expected the hash to be {case['expect']}, it was not")
        checked += 1
    counts["foundation/mutations"] = checked

    checked = 0
    for path in files(root / "manifests"):
        manifest = load(path)
        try:
            validate_hash_profile(manifest)
        except CanonicalError as exc:
            failures.append(f"{path.name}: {exc}")
            checked += 1
            continue
        # DERIVED, never read back. Comparing a committed manifest to itself would pass over
        # a manifest that had quietly dropped an exclusion.
        if manifest != derive_hash_profile(manifest["schema_ref"]):
            failures.append(
                f"{path.name}: the committed manifest drifted from its schema annotations"
            )
        checked += 1
    counts["foundation/manifests"] = checked


def coverage_errors(fixtures_root: Path, counts: dict[str, int]) -> list[str]:
    """Every way the run failed to cover the fixture tree it claims to cover."""
    errors: list[str] = []
    for suite in SUITES:
        directory = fixtures_root / suite.relative
        if not directory.is_dir():
            errors.append(
                f"{directory}: suite {suite.name!r} is missing — a missing directory globs to "
                "[] and reads as a clean run"
            )
            continue
        observed = counts.get(suite.name, 0)
        if observed < suite.minimum:
            errors.append(
                f"suite {suite.name!r} ran {observed} checks, below its floor of "
                f"{suite.minimum}: fixtures were deleted, renamed out of *.json, or failed to "
                "enumerate"
            )
    total = sum(counts.values())
    if not errors and total != EXPECTED_FOUNDATION_CHECKS:
        errors.append(
            f"the harness ran {total} checks but {EXPECTED_FOUNDATION_CHECKS} are pinned in "
            "EXPECTED_FOUNDATION_CHECKS: adding or removing a foundation fixture has to be an "
            "explicit, reviewable edit to the pinned coverage"
        )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay every committed foundation fixture.")
    parser.add_argument(
        "--fixtures-root",
        type=Path,
        default=FIXTURES_ROOT,
        help="fixture tree to replay; defaults to the tree in this repository",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fixtures_root = args.fixtures_root.expanduser().resolve()
    root = fixtures_root / FOUNDATION_RELATIVE

    failures: list[str] = []
    counts: dict[str, int] = {}
    load_error: ContractError | None = None
    try:
        check_validity(root, failures, counts)
        check_hash(root, failures, counts)
    except ContractError as exc:
        load_error = exc

    coverage = coverage_errors(fixtures_root, counts)
    total = sum(counts.values())

    if load_error is not None:
        print(load_error, file=sys.stderr)
    for failure in failures:
        print(failure, file=sys.stderr)
    for error in coverage:
        print(error, file=sys.stderr)

    if load_error is not None or failures:
        print(f"{len(failures)} foundation fixture failures out of {total}", file=sys.stderr)
        return FAILURES_EXIT
    if coverage:
        print(f"foundation fixture coverage is not intact: {total} checks ran", file=sys.stderr)
        return COVERAGE_EXIT

    print(f"foundation fixtures passed: {total} checks")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

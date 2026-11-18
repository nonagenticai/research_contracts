"""FND-002/FND-005 canonical fixture harness.

Replays every committed canonical fixture against the released engine:

* ``fixtures/canonical-references/v1/valid`` must validate;
* ``fixtures/canonical-references/v1/invalid`` must fail, with the error each fixture names;
* ``fixtures/canonical-references/v1/verification`` must produce the exact receipt;
* ``fixtures/canonical-hash/v1/rfc8785`` must be reproduced byte for byte;
* ``fixtures/canonical-hash/v1/vectors`` must reproduce their golden canonical bytes and hash;
* ``fixtures/canonical-hash/v1/mutations`` must change or preserve the hash as declared;
* ``fixtures/canonical-hash/v1/rejected`` must raise the named error;
* ``fixtures/canonical-hash/v1/manifests`` must still match their schema annotations.

**Coverage is asserted, not hoped for.** The previous "zero checks is exit 2"
guard was unreachable: ``check_rfc8785`` read three hardcoded filenames, so the
counter was either at least two or the harness died on ``FileNotFoundError``,
and every other suite used ``directory.glob("*.json")`` — which returns ``[]``
for a missing directory, with no error at all. Deleting 107 of the 109 fixtures
still printed green ("34 checks", exit 0), and dropping the three adversarial
suites (``invalid``/``rejected``/``mutations``) printed "98 checks", exit 0.

So each suite now declares a directory that must exist and a floor it must
clear, and the run total is pinned in :data:`EXPECTED_CHECKS`. A deleted,
renamed, emptied or quietly grown suite is a failure that names itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
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
    es_number_to_string,
    merge_profile_extensions,
    validate_hash_profile,
    validate_instance,
    verify_reference,
)
from .errors import ContractError
from .paths import REPOSITORY_ROOT

COVERAGE_EXIT = 2
FAILURES_EXIT = 1

#: Default fixture tree. ``--fixtures-root`` overrides it, which is what makes
#: the coverage floors themselves testable against a constructed tree.
FIXTURES_ROOT = REPOSITORY_ROOT / "fixtures"

HASH_RELATIVE = Path("canonical-hash/v1")
REF_RELATIVE = Path("canonical-references/v1")

#: The three RFC 8785 fixtures are read by name, so they are pinned by name.
RFC8785_STRUCTURAL = ("structural-sample.json", "property-name-ordering.json")
RFC8785_NUMBERS = "number-serialization.json"


@dataclass(frozen=True)
class Suite:
    """One fixture directory and the number of checks it must contribute.

    ``minimum`` is a floor, not a target: deleting fixtures from a suite has to
    fail, and it did not before.
    """

    name: str
    relative: Path
    minimum: int


SUITES: tuple[Suite, ...] = (
    Suite("references/valid", REF_RELATIVE / "valid", 11),
    Suite("references/invalid", REF_RELATIVE / "invalid", 22),
    # 13 -> 14: verification-owner-content-does-not-validate, added with the fix that makes
    # an owner response the consumer cannot hash produce a REJECTED receipt instead of an
    # escaping SchemaValidationError and no receipt at all.
    Suite("references/verification", REF_RELATIVE / "verification", 14),
    Suite("hash/rfc8785", HASH_RELATIVE / "rfc8785", 34),
    # 16 since 2026-07-30: `set-like-array-astral-vs-private-use-order-key` was added to
    # discriminate UTF-8 byte (code-point) set-member order from UTF-16 code-unit order.
    # No previously committed vector contained an astral character in an order key, so the
    # divergence described in the wave-2 register as G1 was invisible to this suite.
    Suite("hash/vectors", HASH_RELATIVE / "vectors", 16),
    Suite("hash/mutations", HASH_RELATIVE / "mutations", 8),
    Suite("hash/rejected", HASH_RELATIVE / "rejected", 3),
    Suite("hash/manifests", HASH_RELATIVE / "manifests", 5),
)

#: Pinned total. Every committed fixture is replayed exactly once, so this is an
#: equality, not a floor: a fixture that disappears *or* appears has to be an
#: explicit, reviewable edit here rather than a silent change in a number nobody
#: reads.
EXPECTED_CHECKS = sum(suite.minimum for suite in SUITES)


def load(path: Path) -> Any:
    """Read a fixture, reporting an unreadable or malformed one as a diagnosis.

    A missing, unreadable or corrupt fixture is a condition this harness has
    diagnosed; surfacing it as a raw ``PermissionError``/``JSONDecodeError``
    traceback claims "the gate has a bug", which is a different and misleading
    claim.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{path}: {exc}") from exc


def files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json"))


def profile_for(fixture: dict[str, Any]) -> dict[str, Any]:
    return merge_profile_extensions(
        derive_hash_profile(fixture["schema_ref"]), fixture.get("profile_extensions")
    )


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


def pinned_resolver(fixture: dict[str, Any], failures: list[str], name: str) -> Any:
    """Return an owner resolver that answers only its fixture's exact pin.

    ``verification.py`` states the rule the resolver call has to obey: resolve by exact
    ``entity_id`` and ``version_id``, never fall back to latest. The old resolver here was
    ``lambda *_, _f=fixture: _f["owner_response"]`` -- it discarded both arguments, so it
    answered any call whatsoever and swapping the two arguments at the call site left all
    checks green. A test that cannot fail is not evidence.
    """
    pin = fixture["pinned_version_ref"]
    expected = (pin["entity_id"], pin["version_id"])

    def resolve(entity_id: str, version_id: str) -> Any:
        if (entity_id, version_id) != expected:
            failures.append(
                f"{name}: the owner resolver was called with {(entity_id, version_id)!r}, not "
                f"the pin's exact {expected!r}; resolution is by exact entity_id/version_id, "
                "in that order, and never falls back to latest"
            )
            return None
        return fixture["owner_response"]

    return resolve


def check_references(ref_root: Path, failures: list[str], counts: dict[str, int]) -> None:
    checked = 0
    for path in files(ref_root / "valid"):
        fixture = load(path)
        # validate_instance IS the schema layer plus the cross-field rules. Calling
        # check_cross_field_rules again after it reported every cross-field failure twice.
        errors = validate_instance(fixture["instance"], fixture["schema_ref"])
        if errors:
            failures.append(f"{path.name}: expected valid, got {errors}")
        checked += 1
    counts["references/valid"] = checked

    checked = 0
    for path in files(ref_root / "invalid"):
        fixture = load(path)
        errors = validate_instance(fixture["instance"], fixture["schema_ref"])
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
        checked += 1
    counts["references/invalid"] = checked

    checked = 0
    for path in files(ref_root / "verification"):
        fixture = load(path)
        try:
            receipt = verify_reference(
                fixture["pinned_version_ref"],
                resolver=pinned_resolver(fixture, failures, path.name),
                consumer_context=fixture["consumer_context"],
                subject_local_ref=fixture["subject_local_ref"],
                verification_profile_ref=fixture["verification_profile_ref"],
                verified_at="2026-07-30T10:00:05Z",
                receipt_id="bbbbbbbb-0000-4000-8000-000000000001",
            )
        except CanonicalError as exc:
            failures.append(f"{path.name}: verification raised {exc}")
            checked += 1
            continue
        if receipt["result"] != fixture["expected_result"]:
            failures.append(
                f"{path.name}: expected result {fixture['expected_result']}, "
                f"got {receipt['result']}"
            )
        if receipt.get("failure_code") != fixture["expected_failure_code"]:
            failures.append(
                f"{path.name}: expected failure_code {fixture['expected_failure_code']}, "
                f"got {receipt.get('failure_code')}"
            )
        checked += 1
    counts["references/verification"] = checked


def check_rfc8785(hash_root: Path, failures: list[str], counts: dict[str, int]) -> None:
    checked = 0
    numbers = load(hash_root / "rfc8785" / RFC8785_NUMBERS)
    for entry in numbers["vectors"]:
        value = struct.unpack(">d", bytes.fromhex(entry["ieee754_hex"]))[0]
        rendered = es_number_to_string(value)
        if rendered != entry["expected"]:
            failures.append(
                f"rfc8785 number {entry['ieee754_hex']}: expected {entry['expected']}, "
                f"got {rendered}"
            )
        checked += 1

    for name in RFC8785_STRUCTURAL:
        fixture = load(hash_root / "rfc8785" / name)
        canonical = canonical_json_bytes(
            json.loads(fixture["source"]),
            allow_binary_float=fixture["contains_binary_floats"],
        )
        if canonical.decode("utf-8") != fixture["expected_canonical_json"]:
            failures.append(f"rfc8785 {name}: canonical JSON differs")
        digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
        if digest != fixture["expected_sha256"]:
            failures.append(f"rfc8785 {name}: expected {fixture['expected_sha256']}, got {digest}")
        checked += 1
    counts["hash/rfc8785"] = checked


def check_hash_fixtures(hash_root: Path, failures: list[str], counts: dict[str, int]) -> None:
    checked = 0
    for path in files(hash_root / "vectors"):
        fixture = load(path)
        try:
            profile = profile_for(fixture)
            view = build_hash_view(fixture["instance"], profile)
            canonical = canonical_json_bytes(view)
        except CanonicalError as exc:
            failures.append(f"{path.name}: {exc}")
            checked += 1
            continue
        if canonical.decode("utf-8") != fixture["expected_hash_view_canonical_json"]:
            failures.append(f"{path.name}: hash-view canonical JSON differs")
        digest = canonical_sha256(view)
        if digest != fixture["expected_content_hash"]:
            failures.append(
                f"{path.name}: expected {fixture['expected_content_hash']}, got {digest}"
            )
        checked += 1
    counts["hash/vectors"] = checked

    checked = 0
    for path in files(hash_root / "mutations"):
        case = load(path)
        base = load(hash_root / "vectors" / f"{case['base_fixture']}.json")
        mutated = json.loads(json.dumps(base["instance"]))
        for mutation in case["mutations"]:
            set_pointer(mutated, mutation["pointer"], mutation["value"])
        digest = compute_content_hash(mutated, base["schema_ref"], profile=profile_for(base))
        same = digest == base["expected_content_hash"]
        if (case["expect"] == "unchanged") != same:
            failures.append(f"{path.name}: expected the hash to be {case['expect']}, it was not")
        checked += 1
    counts["hash/mutations"] = checked

    checked = 0
    for path in files(hash_root / "rejected"):
        fixture = load(path)
        try:
            compute_content_hash(
                fixture["instance"], fixture["schema_ref"], profile=profile_for(fixture)
            )
        except CanonicalError as exc:
            if type(exc).__name__ != fixture["expected_error"]:
                failures.append(
                    f"{path.name}: expected {fixture['expected_error']}, got {type(exc).__name__}"
                )
            elif fixture["expected_message_contains"] not in str(exc):
                failures.append(f"{path.name}: message does not name the cause: {exc}")
        else:
            failures.append(f"{path.name}: expected {fixture['expected_error']}, nothing raised")
        checked += 1
    counts["hash/rejected"] = checked

    checked = 0
    for path in files(hash_root / "manifests"):
        manifest = load(path)
        try:
            validate_hash_profile(manifest)
        except CanonicalError as exc:
            failures.append(f"{path.name}: {exc}")
            checked += 1
            continue
        if manifest != derive_hash_profile(manifest["schema_ref"]):
            failures.append(
                f"{path.name}: the committed manifest drifted from its schema annotations"
            )
        checked += 1
    counts["hash/manifests"] = checked


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
    for name in (*RFC8785_STRUCTURAL, RFC8785_NUMBERS):
        path = fixtures_root / HASH_RELATIVE / "rfc8785" / name
        if not path.is_file():
            errors.append(f"{path}: pinned RFC 8785 fixture is missing")

    total = sum(counts.values())
    if not errors and total != EXPECTED_CHECKS:
        errors.append(
            f"the harness ran {total} checks but {EXPECTED_CHECKS} are pinned in "
            "EXPECTED_CHECKS: adding or removing a canonical fixture has to be an explicit, "
            "reviewable edit to the pinned coverage"
        )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay every committed canonical fixture.")
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
    hash_root = fixtures_root / HASH_RELATIVE
    ref_root = fixtures_root / REF_RELATIVE

    failures: list[str] = []
    counts: dict[str, int] = {}
    load_error: ContractError | None = None
    try:
        check_references(ref_root, failures, counts)
        check_rfc8785(hash_root, failures, counts)
        check_hash_fixtures(hash_root, failures, counts)
    except ContractError as exc:
        load_error = exc

    coverage = coverage_errors(fixtures_root, counts)
    total = sum(counts.values())

    # Both classes are always reported. A wrong fixture and a missing suite are
    # different defects, and one must never mask the other; the exit code names
    # the more specific of the two.
    if load_error is not None:
        print(load_error, file=sys.stderr)
    for failure in failures:
        print(failure, file=sys.stderr)
    for error in coverage:
        print(error, file=sys.stderr)

    if load_error is not None or failures:
        print(f"{len(failures)} canonical fixture failures out of {total}", file=sys.stderr)
        return FAILURES_EXIT
    if coverage:
        print(f"canonical fixture coverage is not intact: {total} checks ran", file=sys.stderr)
        return COVERAGE_EXIT

    print(f"canonical fixtures passed: {total} checks")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

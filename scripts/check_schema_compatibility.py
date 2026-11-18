#!/usr/bin/env python3
"""Compare every candidate schema against the RELEASED baseline and fail on MAJOR.

WHY THIS FILE EXISTS
====================

Measured 2026-09-06 on ``main`` at ``e82395a``: ``tooling/compatibility.py`` had
**no callers**. ``compare_files`` and ``breaking_changes`` were called from
nowhere at all; ``compare`` was called only from
``tests/test_the_twenty_one_events.py``, which compares a schema against a
*mutant of itself*. A mutation suite proves the comparator classifies correctly.
It cannot answer the question compatibility is about, because it never once
looks at the version that was released. Nothing in this repository — not a test,
not a script, not a CI step — compared a candidate schema against its N-1.

That matters wherever a released contract is a dependency. A consumer gates on
four merged artifacts, one of which is a "compatibility test". That column was
being satisfied by a self-mutation suite. This script is the N/N+1 check the
column actually names.

WHERE THE BASELINE COMES FROM, AND WHY
======================================

**The committed tree under ``compatibility/released/``.** It is a snapshot of
``schemas/`` as of the last release, and CI compares every pull request against
it. Refreshing that snapshot is part of the release commit, so the baseline can
never be a merge target masquerading as a release:

* **``origin/main`` — rejected, it answers a different question.** main is the
  MERGE TARGET, not the RELEASE. A breaking change that reaches main and is never
  released makes main itself the corrupt reference: the next pull request
  compares against the already-broken shape, sees no difference, and passes.
* **The published wheel — supported for release-time use.** Omit
  ``--baseline-dir`` and the latest released distribution is fetched from
  ``--index-url``. That path is fail-closed: an unreachable index is exit 2,
  never a pass.
* **``--baseline-dir`` — what CI runs.** It must point at a real tree with
  schemas in it; an empty baseline is refused.

WHAT IS COMPARED WITH WHAT
==========================

Documents are paired by ``$id``, never by path. ``schema_version_policy`` in
``OWNERS.yaml`` is a rule about the ``$id``:

    semver on the schema $id: adding a name or an optional member is minor and
    keeps the $id; any change to what a released rule means mints a new $id major
    and bumps DERIVATION_PROFILE_VERSION in the same commit as every manifest it
    invalidates.

So moving ``foo.v1.schema.json`` to another directory is not a contract event and
must not be reported as one, while changing what ``urn:datacompany:foo:1`` means is
the only thing that matters. Pairing by path would get both backwards.

Four outcomes, and which of them is red:

===================================  ======  ==============================
situation                            red?    why
===================================  ======  ==============================
paired, verdict MAJOR                YES     the released rule changed
                                             meaning while keeping its
                                             ``$id`` — the exact violation
paired, verdict MINOR or IDENTICAL   no      the policy permits this and
                                             says the ``$id`` is kept
``$id`` only in the candidate        no      a NEW schema; see the blind
                                             spots below
``$id`` only in the baseline         YES     a released ``$id`` was
                                             WITHDRAWN. Every consumer
                                             resolving it through
                                             ``canonical/registry.py``
                                             breaks, and no pairwise
                                             comparison can see a document
                                             that is not there
===================================  ======  ==============================

A MAJOR verdict on a schema whose ``$id`` *was* bumped never reaches the red row:
the bumped ``$id`` has no baseline, so it lands in the "new schema" row. That is
the correct reading of the policy — minting a new major ``$id`` is precisely how
a breaking change is supposed to ship — and it is why pairing by ``$id`` rather
than by filename is what makes the gate expressible at all.

⚠️ WHAT THIS GATE CANNOT SEE
============================

Written down because a gate whose blind spots are undocumented gets read as
total coverage:

* **A brand-new schema has no baseline.** Its first published shape is ungated
  here; only its second release is. This is unavoidable and is the reason the
  "new" row prints loudly rather than silently.
* **A withdrawn-then-reinstated ``$id`` between two releases** is invisible: only
  the latest release is fetched, so an ``$id`` that vanished and came back with a
  different meaning inside one release cycle compares clean.
* **Meaning that is not in the JSON Schema document.** ``description`` prose,
  ``x-datacompany-*`` extension semantics, cross-schema invariants, the OpenAPI
  documents under ``openapi/``, the TypeScript mirror under
  ``packages/typescript`` and the bindings under ``generated/`` are all outside
  the comparison. A contract can break in any of them with this gate green.
* **Consumer-specific breakage that the comparator calls MINOR** — adding an enum
  member is minor by the policy and breaks a consumer that matches exhaustively.
  The comparator fails toward MAJOR for everything it does not positively
  recognise, so this is bounded, not zero.
* **The rest of the policy sentence.** The policy also requires
  ``DERIVATION_PROFILE_VERSION`` to be bumped in the same commit as every
  invalidated manifest. This gate checks the ``$id`` half only.
* **It is not a substitute for the mutation suite.** That suite proves the
  comparator's classifications are right; this script proves the classifications
  are applied to the released bytes. Neither implies the other, and deleting
  either re-opens a different hole.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

# Repo-anchored, not cwd-anchored: the gate inspects the repository that
# contains it, and finds its own implementation without needing an install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_contracts.tooling.compatibility import (
    CompatibilityReport,
    Verdict,
    breaking_changes,
    compare_files,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The distribution whose released schemas are the baseline.
DISTRIBUTION = "research-contracts"

#: Where the wheel puts the schemas. Set by
#: ``[tool.hatch.build.targets.wheel.force-include]`` in ``pyproject.toml``; if that
#: mapping is ever changed, the fetch below reports an empty baseline and exits 2
#: rather than comparing against nothing.
WHEEL_SCHEMA_ROOT = "research_contracts/schemas"

#: Default index. Overridable so a test never needs the network.
DEFAULT_INDEX_URL = "https://pypi.org/simple/"

SCHEMA_GLOB = "*.schema.json"


class GateError(Exception):
    """The gate could not be run. Distinct from the gate running and failing."""


@dataclass(frozen=True)
class Finding:
    """One red row. ``kind`` is the table in the module docstring."""

    kind: str
    schema_id: str
    detail: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.schema_id}: {self.detail}"


def load_schema_index(root: Path) -> dict[str, Path]:
    """Map every ``$id`` under ``root`` to the file that declares it.

    A document with no ``$id``, or two documents sharing one, is a
    :class:`GateError` rather than a silently dropped row: both make the
    comparison below quietly incomplete, and "quietly incomplete" is the failure
    mode this whole file exists to close.
    """
    if not root.is_dir():
        raise GateError(f"{root}: schema root is not a directory")
    index: dict[str, Path] = {}
    for path in sorted(root.rglob(SCHEMA_GLOB)):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise GateError(f"{path}: unreadable schema ({exc})") from exc
        if not isinstance(document, dict):
            raise GateError(f"{path}: schema document must be a JSON object")
        schema_id = document.get("$id")
        if not isinstance(schema_id, str) or not schema_id.strip():
            raise GateError(
                f"{path}: has no '$id'. This gate pairs documents by $id, so a document "
                "without one is invisible to it — which is indistinguishable from being "
                "compatible"
            )
        if schema_id in index:
            raise GateError(
                f"{schema_id}: declared by both {index[schema_id]} and {path}; a duplicated "
                "$id makes 'the released shape of this $id' ambiguous"
            )
        index[schema_id] = path
    if not index:
        raise GateError(
            f"{root}: no {SCHEMA_GLOB} documents found. An empty side compares clean against "
            "anything, so an empty enumeration is refused rather than reported as green"
        )
    return index


def fetch_released_baseline(destination: Path, index_url: str) -> tuple[Path, str]:
    """Install the latest released wheel into ``destination``; return its schema root.

    Fail-closed by construction: every failure path raises. There is no branch on
    which an unreachable index, a missing distribution or a wheel without schemas
    produces a usable-looking empty baseline.
    """
    uv = shutil.which("uv")
    if uv is None:
        raise GateError(
            "uv is not on PATH; the released baseline is fetched with `uv pip install` and "
            "there is no fallback that would not be a silent pass"
        )
    # An index may be served with a private CA. `--no-config` above already says
    # the gate does not trust the caller's configuration, so the allowed host is
    # derived from `index_url` rather than read from ambient environment; pointing
    # the gate at a different index does not silently keep trusting the old one.
    index_host = urllib.parse.urlsplit(index_url).hostname
    command = [
        uv,
        "pip",
        "install",
        "--no-config",
        "--no-deps",
        "--target",
        str(destination),
        "--index-url",
        index_url,
    ]
    if index_host:
        command += ["--allow-insecure-host", index_host]
    command.append(DISTRIBUTION)
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise GateError(
            f"could not fetch the released baseline from {index_url}: "
            f"uv exited {result.returncode}\n{result.stderr.strip()}"
        )
    installed = sorted(destination.glob(f"{DISTRIBUTION.replace('-', '_')}-*.dist-info"))
    if len(installed) != 1:
        raise GateError(
            f"{destination}: expected exactly one installed {DISTRIBUTION} distribution, "
            f"found {[p.name for p in installed]}"
        )
    version = installed[0].name.removesuffix(".dist-info").split("-")[1]
    schema_root = destination / WHEEL_SCHEMA_ROOT
    if not schema_root.is_dir():
        raise GateError(
            f"{DISTRIBUTION}=={version} ships no {WHEEL_SCHEMA_ROOT}/ — the wheel's "
            "force-include mapping in pyproject.toml has moved, and the baseline this gate "
            "would compare against is empty"
        )
    return schema_root, version


def evaluate(baseline_root: Path, candidate_root: Path) -> tuple[list[Finding], list[str], int]:
    """Return ``(findings, new_ids, compared)`` for two schema trees."""
    baseline = load_schema_index(baseline_root)
    candidate = load_schema_index(candidate_root)

    findings: list[Finding] = []
    reports: dict[str, CompatibilityReport] = {}

    for schema_id in sorted(set(baseline) & set(candidate)):
        report = compare_files(baseline[schema_id], candidate[schema_id])
        reports[schema_id] = report
        if report.verdict is Verdict.MAJOR:
            detail = "; ".join(str(change) for change in report.breaking())
            findings.append(
                Finding(
                    "BREAKING-WITHOUT-A-NEW-ID",
                    schema_id,
                    f"{candidate[schema_id].relative_to(candidate_root)} changes what a "
                    f"released rule means while keeping its $id: {detail}",
                )
            )

    for schema_id in sorted(set(baseline) - set(candidate)):
        findings.append(
            Finding(
                "WITHDRAWN-RELEASED-ID",
                schema_id,
                f"was released as {baseline[schema_id].name} and no candidate document "
                "declares it; every consumer resolving this $id breaks",
            )
        )

    new_ids = sorted(set(candidate) - set(baseline))

    # `breaking_changes` is the module's own multi-report helper. Calling it here
    # is not decoration: it is asserted below to agree with the per-schema counts,
    # so the aggregate the CI message is built from cannot drift from the rows.
    aggregate = breaking_changes(reports.values())
    per_schema = sum(len(report.breaking()) for report in reports.values())
    if len(aggregate) != per_schema:
        raise GateError(
            f"breaking_changes() reported {len(aggregate)} changes across {len(reports)} "
            f"reports while the reports themselves hold {per_schema}"
        )

    return findings, new_ids, len(reports)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare candidate schemas against the released baseline and fail on a MAJOR "
            "verdict for a schema whose $id was not bumped."
        )
    )
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        default=REPO_ROOT / "schemas",
        help="tree of candidate schemas; defaults to this repository's schemas/",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help=(
            "tree of released schemas. Omit to fetch the latest released "
            f"{DISTRIBUTION} wheel from --index-url, which is what CI does."
        ),
    )
    parser.add_argument(
        "--index-url",
        default=DEFAULT_INDEX_URL,
        help=f"index the released baseline is fetched from (default: {DEFAULT_INDEX_URL})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace: tempfile.TemporaryDirectory[str] | None = None
    try:
        if args.baseline_dir is not None:
            baseline_root = args.baseline_dir.expanduser().resolve()
            source = f"{baseline_root} (--baseline-dir)"
        else:
            workspace = tempfile.TemporaryDirectory(prefix="released-baseline-")
            baseline_root, version = fetch_released_baseline(Path(workspace.name), args.index_url)
            source = f"{DISTRIBUTION}=={version} from {args.index_url}"
        findings, new_ids, compared = evaluate(
            baseline_root, args.candidate_dir.expanduser().resolve()
        )
    except GateError as exc:
        print(f"schema compatibility gate could not run: {exc}", file=sys.stderr)
        return 2
    finally:
        if workspace is not None:
            workspace.cleanup()

    print(f"released baseline: {source}")
    print(f"schemas compared against their released shape: {compared}")
    if new_ids:
        print(
            "new $ids with NO released baseline — ungated by this check, review by hand: "
            + ", ".join(new_ids)
        )
    else:
        print("new $ids with no released baseline: none")

    if findings:
        for finding in findings:
            print(str(finding), file=sys.stderr)
        print(
            f"::error::{len(findings)} schema(s) break their released contract. "
            "Per schema_version_policy a change to what a released rule means mints a NEW "
            "major $id; it does not keep the old one.",
            file=sys.stderr,
        )
        return 1

    print("no released $id changed meaning while keeping its $id")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The N/N+1 compatibility gate: it must exist, and it must be able to be red.

WHAT WAS WRONG
==============

Measured on ``main`` at ``e82395a``: ``tooling/compatibility.py`` had **no
callers**. ``compare_files`` and ``breaking_changes`` were called from nowhere in
the package, in ``scripts/`` or in CI. ``compare`` was called only from
``tests/test_the_twenty_one_events.py``, which compares a schema against a
**mutant of itself**.

That distinction is the whole defect. A self-mutation suite proves the comparator
classifies a difference correctly. It cannot prove anything about *this
repository's* schemas, because it never reads the version that was released. So
the module was a correct comparator with nothing to compare, and DataCompany
``13-…§8.3`` — which gates event emission on a merged "compatibility test" column
— was being satisfied by it.

WHAT IS ASSERTED HERE
=====================

Two different things, and both are needed:

* **The gate is wired.** ``scripts/check_schema_compatibility.py`` exists, CI runs
  it, and CI additionally runs a step that asserts it comes back RED on a breaking
  change. ``tests/test_script_entry_points.py`` already forbids a script that no
  ``run:`` invokes; what it cannot say is that the invocation is *believed*, which
  is what the second CI step is for.
* **The gate binds.** Every row of the script's decision table is exercised
  against real schema bytes: a breaking change is red, an additive change is
  green, a withdrawn released ``$id`` is red, and a breaking change that DID mint
  a new major ``$id`` is green. Green rows matter as much as red ones — a gate
  that failed on everything would pass a red-only suite and block every PR.

⚠️ NON-VACUITY. ``test_the_untouched_tree_is_green`` is the control: if the fixture
copy were empty, or the baseline unreadable, every "additive change is accepted"
assertion below would pass for the wrong reason. The gate refuses an empty side
outright (exit 2) precisely so that failure cannot present as a pass, and
``test_an_empty_baseline_is_refused_not_accepted`` pins that.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest
import yaml
from conftest import ROOT, WORKFLOW, run_script

SCRIPT = "check_schema_compatibility.py"
SCHEMAS = ROOT / "schemas"

#: The document mutated by the probes below. Chosen because it is a released
#: foundation schema with both a ``required`` list and a ``properties`` map, so
#: the same file can carry a breaking and an additive change.
TARGET = "common/page.v1.schema.json"


def run_gate(baseline: Path, candidate: Path) -> subprocess.CompletedProcess[str]:
    """Run the gate offline, against two real schema trees."""
    return run_script(SCRIPT, "--baseline-dir", baseline, "--candidate-dir", candidate)


@pytest.fixture
def trees(tmp_path: Path) -> tuple[Path, Path]:
    """A frozen baseline copy of ``schemas/`` and a candidate copy to mutate.

    The real ``schemas/`` tree is never written to. Published schemas are a
    separate decision from a gate that watches them, and a test that edits the
    thing it is testing has no control group.
    """
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    shutil.copytree(SCHEMAS, baseline)
    shutil.copytree(SCHEMAS, candidate)
    return baseline, candidate


def edit(path: Path, mutate: Callable[[dict], None]) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# The control. Everything below is meaningless without it.
# --------------------------------------------------------------------------


def test_the_untouched_tree_is_green(trees: tuple[Path, Path]) -> None:
    baseline, candidate = trees
    result = run_gate(baseline, candidate)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "new $ids with no released baseline: none" in result.stdout


def test_the_control_actually_compared_every_document(trees: tuple[Path, Path]) -> None:
    """A run that compared nothing would satisfy the control above.

    The count is asserted against the tree on disk rather than a pinned integer, so
    adding a schema does not require editing this file — but a gate that silently
    stopped enumerating still fails.
    """
    baseline, candidate = trees
    result = run_gate(baseline, candidate)
    expected = len(list(SCHEMAS.rglob("*.schema.json")))
    assert expected > 0, "schemas/ holds no documents; the whole suite would be vacuous"
    assert f"schemas compared against their released shape: {expected}" in result.stdout


# --------------------------------------------------------------------------
# Row 1 — breaking change, $id unchanged. The violation the gate exists for.
# --------------------------------------------------------------------------


def test_a_newly_required_member_on_a_released_id_is_red(trees: tuple[Path, Path]) -> None:
    baseline, candidate = trees

    def add_required(document: dict) -> None:
        document["$defs"]["page_request_fields"]["required"].append("page_size")

    edit(candidate / TARGET, add_required)
    result = run_gate(baseline, candidate)
    assert result.returncode == 1, result.stdout
    assert "BREAKING-WITHOUT-A-NEW-ID" in result.stderr
    assert "urn:datacompany:page:1" in result.stderr
    assert "page_size" in result.stderr


def test_a_narrowed_enum_on_a_released_id_is_red(trees: tuple[Path, Path]) -> None:
    """A second, structurally different breaking change.

    One probe would only prove the gate is red for one keyword. The comparator
    handles enums, bounds, closedness and ``$defs`` by different code paths, and a
    gate wired to a comparator that only ever saw ``required`` would be a gate for
    ``required``.
    """
    baseline, candidate = trees

    def narrow_enum(document: dict) -> None:
        document["$defs"]["sort_direction"]["enum"] = ["ascending"]

    edit(candidate / TARGET, narrow_enum)
    result = run_gate(baseline, candidate)
    assert result.returncode == 1, result.stdout
    assert "urn:datacompany:page:1" in result.stderr


# --------------------------------------------------------------------------
# Row 2 — additive change, $id unchanged. Must be GREEN, or the gate blocks
# every legitimate release.
# --------------------------------------------------------------------------


def test_an_optional_member_added_to_a_released_id_is_green(trees: tuple[Path, Path]) -> None:
    baseline, candidate = trees

    def add_optional(document: dict) -> None:
        document["$defs"]["page_response"]["properties"]["served_at"] = {
            "type": "string",
            "format": "date-time",
        }

    edit(candidate / TARGET, add_optional)
    result = run_gate(baseline, candidate)
    assert result.returncode == 0, result.stdout + result.stderr


def test_moving_a_file_without_changing_its_id_is_green(trees: tuple[Path, Path]) -> None:
    """Documents are paired by ``$id``, never by path.

    ``schema_version_policy`` is a rule about the ``$id``. A gate that paired by
    filename would call a directory move a contract event and would miss an ``$id``
    edited in place — both errors, in opposite directions.
    """
    baseline, candidate = trees
    source = candidate / TARGET
    destination = candidate / "common/relocated-page.schema.json"
    source.rename(destination)
    result = run_gate(baseline, candidate)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "new $ids with no released baseline: none" in result.stdout


# --------------------------------------------------------------------------
# Row 3 — a new $id has no baseline. Green, and loudly reported: this is the
# gate's documented blind spot, not a silent pass.
# --------------------------------------------------------------------------


def test_a_breaking_change_that_mints_a_new_major_id_is_green(trees: tuple[Path, Path]) -> None:
    baseline, candidate = trees
    document = json.loads((candidate / TARGET).read_text(encoding="utf-8"))
    document["$id"] = "urn:datacompany:page:2"
    document["$defs"]["page_request_fields"]["required"].append("page_size")
    (candidate / "common/page.v2.schema.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    result = run_gate(baseline, candidate)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "urn:datacompany:page:2" in result.stdout


def test_a_new_id_is_reported_as_ungated_rather_than_silently_passed(
    trees: tuple[Path, Path],
) -> None:
    """The blind spot must be visible in the output, or it reads as coverage."""
    baseline, candidate = trees
    (candidate / "common/brand-new.v1.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "urn:datacompany:brand-new:1",
                "type": "object",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_gate(baseline, candidate)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ungated by this check" in result.stdout
    assert "urn:datacompany:brand-new:1" in result.stdout


# --------------------------------------------------------------------------
# Row 4 — a released $id that vanished. No pairwise comparison can see a
# document that is not there.
# --------------------------------------------------------------------------


def test_withdrawing_a_released_id_is_red(trees: tuple[Path, Path]) -> None:
    baseline, candidate = trees
    (candidate / TARGET).unlink()
    result = run_gate(baseline, candidate)
    assert result.returncode == 1, result.stdout
    assert "WITHDRAWN-RELEASED-ID" in result.stderr
    assert "urn:datacompany:page:1" in result.stderr


# --------------------------------------------------------------------------
# Fail-closed. Every way the gate can fail to RUN must be exit 2, never 0.
# --------------------------------------------------------------------------


def test_an_empty_baseline_is_refused_not_accepted(tmp_path: Path) -> None:
    """The failure that makes every other assertion here vacuous.

    An empty baseline compares clean against anything. This is the shape the
    rejected git-tag baseline would have taken: no tags exist, so the tree would
    have been empty and the gate green forever.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run_script(SCRIPT, "--baseline-dir", empty, "--candidate-dir", SCHEMAS)
    assert result.returncode == 2, result.stdout
    assert "no *.schema.json documents found" in result.stderr


def test_a_missing_baseline_directory_is_refused(tmp_path: Path) -> None:
    result = run_script(SCRIPT, "--baseline-dir", tmp_path / "nope", "--candidate-dir", SCHEMAS)
    assert result.returncode == 2, result.stdout
    assert "is not a directory" in result.stderr


def test_an_unreachable_index_is_exit_two_not_a_pass(tmp_path: Path) -> None:
    """Fail-closed on the network path, which is the path CI uses."""
    result = run_script(
        SCRIPT,
        "--index-url",
        "https://index.invalid.example/simple/",
        "--candidate-dir",
        SCHEMAS,
    )
    assert result.returncode == 2, result.stdout
    assert "could not fetch the released baseline" in result.stderr


def test_a_schema_without_an_id_is_refused(trees: tuple[Path, Path]) -> None:
    """A document the gate cannot pair is invisible to it, which reads as compatible."""
    baseline, candidate = trees

    def drop_id(document: dict) -> None:
        del document["$id"]

    edit(candidate / TARGET, drop_id)
    result = run_gate(baseline, candidate)
    assert result.returncode == 2, result.stdout
    assert "has no '$id'" in result.stderr


def test_a_duplicated_id_is_refused(trees: tuple[Path, Path]) -> None:
    baseline, candidate = trees
    shutil.copyfile(candidate / TARGET, candidate / "common/page-copy.v1.schema.json")
    result = run_gate(baseline, candidate)
    assert result.returncode == 2, result.stdout
    assert "declared by both" in result.stderr


# --------------------------------------------------------------------------
# The released baseline itself. Everything above runs offline against a copy;
# this is the only assertion that touches what consumers actually installed.
# --------------------------------------------------------------------------


def test_the_working_tree_is_compatible_with_the_committed_baseline() -> None:
    """The check itself, against ``compatibility/released/``.

    Deliberately NOT skipped when the baseline is missing. ``conftest.require_tool``
    makes the same argument for the lint tools: a gate that skips when its
    dependency is missing is a gate that reports green in exactly the situation it
    was built for.
    """
    result = run_script(SCRIPT, "--baseline-dir", str(ROOT / "compatibility/released"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "released baseline:" in result.stdout


# --------------------------------------------------------------------------
# The wiring. A gate nothing runs is the defect this file was opened for.
# --------------------------------------------------------------------------


def workflow_run_commands() -> str:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    commands = []
    for job in document["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run")
            if isinstance(run, str):
                commands.append(run)
    return "\n".join(commands)


def test_ci_runs_the_gate_against_the_committed_baseline() -> None:
    """CI compares the tree with the released snapshot, not with itself."""
    commands = workflow_run_commands()
    assert "--baseline-dir compatibility/released" in commands, (
        "CI must invoke the gate against compatibility/released/ — the shipped baseline "
        "is refreshed in the release commit"
    )


def test_ci_proves_the_gate_can_be_red_on_every_run() -> None:
    """The step that makes the green one mean something.

    Without it, "the compatibility gate passed" is a statement about a gate nobody
    has ever seen fail — which is what ``compare_files`` having zero callers looked
    like from the outside for the whole life of the module.
    """
    commands = workflow_run_commands()
    assert "__ci_mutant__" in commands, (
        "no CI step mutates a released schema and asserts the gate goes red"
    )
    assert '--candidate-dir "$mutant"' in commands
    assert 'if [ "$status" -ne 1 ]; then' in commands, (
        "the self-proof step must assert exit 1 specifically: exit 2 means the gate "
        "could not run, and treating that as 'red' would pass on a broken index"
    )


def test_the_gate_is_the_only_caller_claim_that_matters() -> None:
    """``compare_files`` and ``breaking_changes`` now have a non-test caller.

    Asserted by reading the script, not by trusting this file's docstring: if the
    script is ever rewritten to re-implement the comparison inline, the module goes
    back to having zero production callers and the mutation suite becomes the only
    thing standing behind the §8.3 compatibility column again.
    """
    source = (ROOT / "scripts" / SCRIPT).read_text(encoding="utf-8")
    assert "from research_contracts.tooling.compatibility import" in source
    assert "compare_files(" in source
    assert "breaking_changes(" in source


# --------------------------------------------------------------------------
# The gate cannot be quietly DISARMED.
#
# Everything above proves the gate is invoked and that its invocation is
# believed. Nothing above pins it in the state where a red exit code stops the
# merge, and the difference is one line in a diff nobody would read twice:
#
#     - name: scripts/check_schema_compatibility.py — candidates vs the RELEASED baseline
#       run: uv run python scripts/check_schema_compatibility.py
#   +   continue-on-error: true
#
# Under that diff every assertion in this file still passes. The step still
# exists, still carries no ``--baseline-dir``, still runs on every pull request,
# and the self-proof step still asserts exit 1. The gate simply stops gating, and
# the workflow renders a green check either way.
#
# ⚠️ THIS REPOSITORY HAS NO OTHER ENFORCEMENT. It is private on a plan without
# branch protection — ``/branches/main/protection`` and ``/rulesets`` both answer
# 403 "Upgrade to GitHub Pro" — so the compatibility gate cannot be a REQUIRED
# status check. A red run is visible and blocks nothing. The workflow's own
# un-neutered state is the entire enforcement mechanism, which is why it is
# asserted here rather than assumed.
#
# ⚠️ ASSERTED ON THE PARSED YAML, NEVER ON THE FILE TEXT. A ``grep`` for
# ``continue-on-error`` is the same bug wearing a different hat: it passes
# against ``continue-on-error: ${{ inputs.soft }}``, it fires on the word inside
# the comment at the head of the ``model-binding`` job, and it cannot tell a step
# key from a job key. The mapping is read where GitHub reads it.
#
# ⚠️ SCOPED TO THE GATE, not to the file. Another step in this workflow may one
# day have a legitimate reason to be advisory — a lint whose findings are not yet
# a floor. A file-wide ban would forbid that and would be wrong.
# --------------------------------------------------------------------------

#: The bare invocation: no ``--baseline-dir``, so it compares against the
#: released wheel. Identifying the step by its command rather than by its
#: ``name:`` means a renamed step is still found; a step title is prose.
BARE_GATE_INVOCATION = (
    "uv run python scripts/check_schema_compatibility.py --baseline-dir compatibility/released"
)


def workflow_document() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def workflow_triggers() -> dict | list:
    """The ``on:`` block, looked up under both spellings it can parse to.

    ⚠️ PyYAML implements YAML 1.1, in which the bare key ``on`` is the BOOLEAN
    ``True`` — not the string ``"on"``. So ``document["on"]`` raises ``KeyError``
    and, far worse, ``document.get("on", {})`` returns an empty mapping under
    which every assertion about ``paths:`` below would pass because there was
    nothing left to look at. That is precisely the vacuous-guard shape these
    tests exist to forbid, so the key is resolved under both spellings and its
    presence is asserted rather than defaulted.
    """
    document = workflow_document()
    for key in (True, "on"):
        if key in document:
            triggers = document[key]
            assert triggers is not None, "the workflow declares an empty `on:` block"
            return triggers
    raise AssertionError(
        "no `on:` trigger block found in the workflow under either the string key "
        "'on' or the YAML 1.1 boolean True — the parse shape changed and every "
        "trigger assertion below would otherwise be vacuous"
    )


def pull_request_trigger() -> dict | None:
    """The ``pull_request:`` entry, or ``None`` when the trigger is absent."""
    triggers = workflow_triggers()
    if isinstance(triggers, list):
        # `on: [pull_request, push]` — the list form carries no filters at all.
        return {} if "pull_request" in triggers else None
    if isinstance(triggers, str):
        # `on: pull_request` — the scalar form, likewise unfilterable.
        return {} if triggers == "pull_request" else None
    if "pull_request" not in triggers:
        return None
    return triggers["pull_request"] or {}


def gate_steps() -> list[tuple[str, dict, dict]]:
    """Every ``(job name, job, step)`` whose ``run:`` invokes the gate script.

    Two today: the gate itself, and the step that proves the gate can be red.
    Both are load-bearing — an advisory self-proof means the gate's own redness
    is once again something nobody has observed.
    """
    document = workflow_document()
    found = []
    for job_name, job in document["jobs"].items():
        for step in job.get("steps", []):
            run = step.get("run")
            if isinstance(run, str) and SCRIPT in run:
                found.append((job_name, job, step))
    return found


def primary_gate_step() -> tuple[str, dict, dict]:
    """The bare invocation specifically, not merely some step that mentions it."""
    for job_name, job, step in gate_steps():
        if step["run"].strip() == BARE_GATE_INVOCATION:
            return job_name, job, step
    raise AssertionError(
        f"no step runs `{BARE_GATE_INVOCATION}` on its own; the gate is either gone "
        "or has been pinned to a local baseline"
    )


def assert_not_disarmed(subject: str, node: dict) -> None:
    """``continue-on-error`` must be absent, or explicitly and literally false.

    ``is False`` and not a truthiness test on purpose. It rejects ``true``, and it
    also rejects every *string* — ``"true"``, and the one that matters,
    ``continue-on-error: ${{ github.event_name == 'pull_request' }}``, which a
    text search reads as a mention and a truthiness test reads as ``True`` only by
    accident of the string being non-empty. An expression here is unreviewable
    from this file, so it is refused rather than evaluated.

    ⚠️ ``continue-on-error: no`` AND ``off`` ARE NOT HOLES. The reason is not
    obvious, so it is recorded rather than left to be re-derived.

    PyYAML implements YAML 1.1, in which ``no``/``off`` resolve to the boolean
    ``False`` — so this assertion passes them. That is a gap only under the
    hypothesis that GitHub reads them as *truthy strings*, silently arming
    ``continue-on-error`` while this file reports the gate armed. That hypothesis
    was checked against primary sources and is **false**:

    * ``actions/runner``'s ``YamlObjectReader.MatchBoolean`` resolves plain
      scalars with the YAML 1.2 core schema — the switch accepts exactly
      ``true|True|TRUE|false|False|FALSE`` and nothing else falls through to a
      ``BooleanToken``.
    * ``continue-on-error`` is declared in ``workflow-v1.0.json`` as
      ``"boolean": {}`` (``boolean-steps-context`` for steps,
      ``boolean-strategy-context`` for jobs) with **no string arm**, and
      ``BooleanDefinition.IsMatch`` is exactly ``literal is BooleanToken``.
    * ``TemplateReader``'s "not a string, convert and retry" branch is guarded by
      ``literal.Type != TokenType.String``, so a value that already resolved to a
      ``StringToken`` gets no second chance — it goes straight to
      ``m_context.Error(UnexpectedValue)``.

    So GitHub sees ``no`` as the string ``"no"``, fails the schema match, and
    emits ``Invalid workflow file … Unexpected value 'no'``. The run never
    starts. Confirmed by executing GitHub's own published parser
    (``@actions/workflow-parser``, the engine behind the github.com workflow
    editor): ``no``/``off``/``yes``/``on``/``No`` — and the explicitly quoted
    ``'no'`` — are all rejected; only ``true``/``false`` parse. That the *quoted*
    string is rejected too proves the failure is the schema match, not scalar
    resolution.

    ``yes``/``on`` need no argument at all: PyYAML resolves them to ``True``,
    which ``is False`` already rejects here.

    The value is therefore unusable as a *quiet* disarm in either parser — false
    here, fatal there — so no raw-scalar check is added for a mutant that cannot
    ship. ⚠️ Residual, stated rather than papered over: this was established from
    runner/languageservices source, from GitHub's published parser, and from a
    server-generated "Invalid workflow file" annotation quoting the identical
    ``Unexpected value`` format string (actions/runner#1492) — NOT by pushing
    such a workflow to github.com and watching it fail. That last mile is
    unproven.

    The divergence that *does* survive is the opposite of the dangerous one, and
    is worth knowing when reading anything else this file asserts: PyYAML accepts
    workflow files that GitHub rejects outright, so a green parse here is never
    by itself evidence that the workflow is valid to GitHub.
    """
    value = node.get("continue-on-error", False)
    assert value is False, (
        f"{subject} sets `continue-on-error: {value!r}`. GitHub honours that key at "
        "BOTH step and job level, and it converts this gate from blocking to "
        "advisory while every other test in this file still passes. This repository "
        "has no required status check to fall back on — the workflow's own state is "
        "the enforcement."
    )


def test_the_gate_steps_are_found_at_all() -> None:
    """The control. Without it the four tests below iterate an empty list.

    A ``gate_steps()`` that matched nothing — a renamed script, a restructured
    workflow, a parse that returned a different shape — would satisfy every
    ``for``-loop assertion here by never entering the loop, which is the exact
    defect class this section was opened for.
    """
    steps = gate_steps()
    assert len(steps) >= 2, (
        f"expected at least the gate and its red-proof step to invoke {SCRIPT}, "
        f"found {len(steps)}: {[name for name, _, step in steps]}"
    )
    primary_gate_step()  # raises if the bare invocation is not among them


def test_the_gate_step_is_not_advisory() -> None:
    for job_name, _job, step in gate_steps():
        assert_not_disarmed(f"step {step.get('name', step['run'])!r} in job {job_name!r}", step)


def test_the_gate_job_is_not_advisory() -> None:
    """The level that is easy to miss.

    ``continue-on-error`` on the JOB applies to every step in it. A reviewer
    scanning the diff around the gate would not see it: it sits ~270 lines above,
    beside ``runs-on:``.

    ⚠️ KNOWN LIMITATION — THE OBSERVER IS COLOCATED WITH ITS SUBJECT, DELIBERATELY.
    This test executes inside the ``gates`` job it inspects, so the one mutant it
    names is also the mutant that swallows its verdict: under a job-level
    ``continue-on-error: true`` this assertion still *fails* and still prints its
    message into the job log — but the run's rollup conclusion goes green, and
    the rollup is what a reviewer, a merge queue and every downstream automation
    actually read. The failure stays loud in a log nobody opens and mute in every
    place a decision is made. (Precisely how GitHub renders the *job's own* badge
    under job-level ``continue-on-error`` is deliberately not asserted here — it
    is a UI detail this file cannot verify, and the rollup is both the part that
    matters and the part that is documented.)

    It is left that way on purpose. Moving the check to a second job does not
    close the hole, it moves it: the observing job can be given the same
    ``continue-on-error``, an ``if: false``, or simply be deleted, and nothing
    inside a workflow can observe its own deletion. The regress only terminates
    OUTSIDE the workflow, at a required status check — which this repository
    cannot have (``/branches/main/protection`` answers 403 "Upgrade to GitHub
    Pro"). What a separate job would genuinely buy is arithmetic, not closure: it
    raises the disarm from one line to two, in two files a reviewer sees
    separately. That is a real improvement and a real ``contracts.yml`` change,
    so it is recorded here as an open gap rather than smuggled into a test-only
    change.
    """
    for job_name, job, _step in gate_steps():
        assert_not_disarmed(f"job {job_name!r}", job)


def test_the_gate_step_and_job_are_unconditional() -> None:
    """An ``if:`` is the other way to render a gate decorative.

    ``if: false`` skips the step; a skipped step is not a failed step, so the
    check renders green. Absence is asserted rather than any particular
    expression, because an expression's value is a property of the event that
    triggered the run and cannot be decided from this file.

    ``strategy:`` is refused on the gate's own job for the same reason it is
    refused across its ``needs`` closure below: a matrix that expands to zero
    entries generates no job, and a job that was never generated reports success
    exactly like a skipped one. Guarding the dependencies against a construct
    while permitting it on the gate itself would leave this file reading complete
    and one key short of it — the defect the whole module exists to forbid.
    """
    for job_name, job, step in gate_steps():
        name = step.get("name", step["run"])
        assert "if" not in step, (
            f"step {name!r} in job {job_name!r} is conditional (`if: {step['if']!r}`). "
            "A skipped gate reports success."
        )
        assert "if" not in job, (
            f"job {job_name!r}, which holds the compatibility gate, is conditional "
            f"(`if: {job['if']!r}`). A skipped job reports success."
        )
        assert "strategy" not in job, (
            f"job {job_name!r}, which holds the compatibility gate, declares a "
            "`strategy:`. A matrix that expands to zero entries generates no job at "
            "all, and an ungenerated job reports success just as a skipped one does; "
            "whether this matrix can expand to zero is not decidable from this file. "
            "Run the gate in an unmatrixed job, or extend this assertion deliberately."
        )


# --------------------------------------------------------------------------
# A disarm that is FEATURE-FLAGGED, not absent.
#
# ⚠️ THIS IS THE ONE ASSERTION HERE THAT GUARDS A PREMISE RATHER THAN A DEFECT,
# AND IT IS NOT DEAD WEIGHT. Do not delete it after checking that the mutant it
# names is rejected by GitHub today — that rejection IS its subject.
#
#     - name: scripts/check_schema_compatibility.py — candidates vs the RELEASED baseline
#       run: uv run python scripts/check_schema_compatibility.py
#   +   background: true
#
# ``step-background`` is a declared property of ``run-step`` in GitHub's own
# ``workflow-v1.0.json``: "runs this step in the background. The workflow
# continues to the next step immediately without waiting for the background step
# to finish." A gate nobody waits for cannot fail the job — and the same one
# line would take the red-proof step with it, so the gate would stop gating and
# stop being observably red in the same diff.
#
# It cannot ship TODAY, and the reason is a vendor feature flag rather than a
# design decision. Measured in ``@actions/workflow-parser`` 0.3.61 — GitHub's
# own published parser, the engine behind the github.com workflow editor::
#
#     dist/templates/template-reader.js:10
#       const backgroundStepProperties =
#         new Set(["background", "wait", "wait-all", "cancel"]);
#
#     dist/templates/template-reader.js:147
#       if (!this.backgroundStepsEnabled() && backgroundStepProperties.has(nextKey.value)) {
#         this._context.error(nextKey, `Unexpected value '${nextKey.value}'`);
#
#     dist/templates/template-reader.js:604
#       backgroundStepsEnabled() {
#         return this._context.state.featureFlags?.isEnabled("allowBackgroundSteps") ?? false;
#       }
#
# So the key is rejected while the flag is off, and the day GitHub turns
# ``allowBackgroundSteps`` on it becomes a one-word disarm. Nothing in this
# repository would announce that flip: the workflow would simply start parsing,
# the gate would start returning immediately, and every other assertion in this
# file would still pass. A guard whose correctness rests on a vendor flag
# staying off should say so and assert against it, which is what this does.
# --------------------------------------------------------------------------

#: The step keys behind ``allowBackgroundSteps``, read off the parser rather
#: than from documentation — see the block comment above for the three lines.
#: ``background`` is the live hazard: it is a property of ``run-step``, so it
#: attaches to the gate step as it stands. ``wait`` / ``wait-all`` / ``cancel``
#: are the required keys of the sibling step types ``wait-step`` /
#: ``wait-all-step`` / ``cancel-step``; they are refused with it because they
#: are gated by the same flag and would arrive on the same day, and because a
#: step carrying one of them alongside ``run:`` is a step whose shape this file
#: has not reasoned about.
#:
#: ⚠️ Re-measure this tuple against the parser before trusting it; a set that has
#: grown a fifth member is a hole, and this file cannot detect that on its own.
BACKGROUND_STEP_KEYS = ("background", "wait", "wait-all", "cancel")


def background_keys_on(step: dict) -> list[str]:
    """Which flag-gated background keys the step declares.

    PRESENCE, not value — deliberately, and this is the one place in this file
    where presence is the right test rather than the overreach it usually is.
    GitHub's check at ``template-reader.js:147`` fires on ``nextKey.value``, the
    key NAME, before the value is ever read: ``background: false`` is rejected
    exactly as ``background: true`` is. Matching the parser's own rule keeps
    this assertion honest about what it is guarding, and refuses the
    unreviewable ``background: ${{ … }}`` for free.

    ⚠️ NOT a ban on keys this file does not recognise. Four named keys, measured
    from the parser. A blanket "the gate step may carry nothing unexpected"
    would fire on ``shell:``, ``id:``, ``timeout-minutes:`` — every ordinary
    thing a step may legitimately grow — and would be the same class of error as
    grepping the file text for ``continue-on-error``: a guard that fires on
    surface rather than on effect.
    """
    return [key for key in BACKGROUND_STEP_KEYS if key in step]


def test_the_background_key_check_is_neither_vacuous_nor_a_blanket_ban() -> None:
    """The control, in both directions.

    Without the negative half, a ``background_keys_on`` that had degenerated into
    ``return []`` would satisfy the assertion below forever. Without the positive
    half, an implementation that flagged every key would pass it too — while
    forbidding an ordinary step from ever gaining a ``shell:`` or an ``id:``.
    """
    ordinary = {
        "name": "scripts/check_schema_compatibility.py — candidates vs the RELEASED baseline",
        "run": BARE_GATE_INVOCATION,
        "env": {"UV_EXTRA_INDEX_URL": "https://index.example/simple/"},
        "working-directory": ".",
        "shell": "bash",
        "id": "compat",
        "timeout-minutes": 10,
    }
    assert background_keys_on(ordinary) == [], (
        "an ordinary step must stay green; this check bans four measured keys, "
        "not every key it does not recognise"
    )
    for key in BACKGROUND_STEP_KEYS:
        assert background_keys_on({"run": BARE_GATE_INVOCATION, key: True}) == [key]
    assert background_keys_on({"run": BARE_GATE_INVOCATION, "background": False}) == [
        "background"
    ], "GitHub rejects the KEY, not the value; `background: false` must not read as absent"


def test_the_gate_step_does_not_run_in_the_background() -> None:
    """The gate must be waited for, whatever GitHub's feature flags say tomorrow.

    See the block comment above for the parser lines this rests on. In short:
    ``background: true`` makes the workflow continue to the next step without
    waiting for this one, so the gate's exit code stops reaching the job's
    conclusion. Today GitHub's parser rejects the key outright because
    ``allowBackgroundSteps`` is off, and the run would never start — a loud
    failure, not a quiet one.

    ⚠️ THAT IS THE POINT, AND IT IS WHY THIS TEST IS NOT REDUNDANT. The guard is
    not wrong today; it acquires a hole on the day the flag is enabled, and that
    day arrives with no announcement, no diff in this repository and no change to
    any other assertion in this file. This is a premise that expires rather than
    fails, so it is pinned rather than left to be rediscovered.
    """
    for job_name, _job, step in gate_steps():
        found = background_keys_on(step)
        assert not found, (
            f"step {step.get('name', step['run'])!r} in job {job_name!r} declares "
            f"{found} — key(s) GitHub gates behind the `allowBackgroundSteps` feature "
            "flag (@actions/workflow-parser, template-reader.js:10/147/604). "
            "`background: true` continues to the next step without waiting, so the "
            "gate's exit code never reaches the job conclusion, and the same line "
            "disarms the red-proof step beside it. This repository has no required "
            "status check to fall back on — the workflow's own state is the "
            "enforcement."
        )


def test_the_pull_request_trigger_has_no_path_filter() -> None:
    """A ``paths:`` filter would let the very change the gate exists for skip it.

    ``paths-ignore: ['**.json']`` or ``paths: ['src/**']`` would mean a PR that
    edits only ``schemas/`` — a contract change, the single input this gate was
    built to classify — starts no run at all. GitHub reports a workflow that never
    ran as a *successful* (neutral) check, so the disarm is invisible in exactly
    the case that matters.
    """
    trigger = pull_request_trigger()
    assert trigger is not None, "the workflow no longer runs on `pull_request`"
    for key in ("paths", "paths-ignore"):
        assert key not in trigger, (
            f"the `pull_request` trigger declares `{key}: {trigger[key]!r}`. Any path "
            "filter can exclude a schema change from the one gate that classifies "
            "schema changes, and a workflow that does not run is not a workflow that "
            "failed."
        )


def test_the_workflow_still_runs_on_pull_request() -> None:
    """The gate must fire BEFORE the merge, not only after it.

    ``push: [main]`` alone would still produce a red run — after the breaking
    change is already on the merge target, and therefore already the shape the
    next PR is cleared against.
    """
    assert pull_request_trigger() is not None, (
        "`pull_request` is no longer a trigger of the contract-gates workflow; the "
        "compatibility gate would only ever run post-merge"
    )


# --------------------------------------------------------------------------
# The three disarms a path filter is not.
#
# ``paths:`` is the trigger filter everyone thinks of, and the three below are
# strictly stronger than it — each one stops the run for EVERY pull request in
# this repository rather than for the subset that touches a directory:
#
#     on:
#       pull_request:
#   +     types: [labeled]          # no run on opened / synchronize / reopened
#   +     branches: ['release/**']  # no run for any PR into main
#
#     jobs:
#       gates:
#   +     needs: [some-job-with-an-if]   # a skipped `needs` skips this job too
#
# ⚠️ THE ASSERTIONS BELOW ARE PROPERTIES, NOT KEY BANS. ``types:`` and
# ``branches:`` both have legitimate uses that disarm nothing —
# ``types: [opened, synchronize, reopened]`` restates the default, and
# ``branches: [main]`` is a normal thing to write. Banning the keys would forbid
# those, which is the same error as grepping for ``continue-on-error``: a guard
# that fires on a mention rather than on an effect. So the property asserted is
# the one that matters — *a pull request targeting ``main``, on the default
# activity types, still starts this workflow* — evaluated by applying GitHub's
# own filter semantics to the parsed trigger.
# --------------------------------------------------------------------------

#: The activity types GitHub uses when ``types:`` is omitted. Quoted from the
#: description of ``pull-request`` in ``actions/runner``'s ``workflow-v1.0.json``:
#: "If no activity types are specified, the workflow runs when a pull request is
#: opened, reopened, or when the head branch of the pull request is updated."
DEFAULT_PULL_REQUEST_TYPES = frozenset({"opened", "reopened", "synchronize"})

#: The base branch every pull request in this repository targets, and the one
#: the gate has to fire for. ``push: [main]`` alone is post-merge (see above).
BASE_BRANCH = "main"

#: Metacharacters of GitHub's filter-pattern syntax that this file refuses to
#: evaluate. They are NOT the glob operators they resemble: ``?`` matches zero or
#: one of the *preceding character*, ``+`` one or more of it, and ``[]`` is a
#: character class. Approximating them would make the matcher below quietly
#: wrong in the permissive direction, so an unrecognised pattern is a failure.
UNSUPPORTED_FILTER_METACHARACTERS = "?+[]"


def as_patterns(value: object) -> list[str] | None:
    """Normalise a filter that GitHub accepts as either a scalar or a sequence."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise AssertionError(f"unrecognised filter shape {value!r}; the parse shape changed")


def branch_pattern_matches(pattern: str, branch: str) -> bool:
    """Whether one GitHub branch filter pattern matches ``branch``.

    Implements the two metacharacters a branch filter realistically uses — ``*``
    (any run of characters except ``/``) and ``**`` (any run of characters) — and
    refuses the rest rather than approximating them. A guard that guesses at its
    own subject is the defect this file exists to forbid, and guessing here would
    fail open: a pattern misread as matching ``main`` reports the gate armed.
    """
    for character in UNSUPPORTED_FILTER_METACHARACTERS:
        assert character not in pattern, (
            f"branch filter pattern {pattern!r} uses {character!r}, a GitHub "
            "filter-pattern metacharacter this test does not implement. Extend "
            "branch_pattern_matches() rather than deleting the assertion — an "
            "undecided pattern must not read as 'the gate still fires'."
        )
    expression = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            expression += ".*"
            index += 2
        elif pattern[index] == "*":
            expression += "[^/]*"
            index += 1
        else:
            expression += re.escape(pattern[index])
            index += 1
    return re.fullmatch(expression, branch) is not None


def last_match_wins(patterns: Iterable[str], branch: str, *, default: bool) -> bool:
    """GitHub's ``!``-negation rule: later matching patterns override earlier ones."""
    verdict = default
    for pattern in patterns:
        negated = pattern.startswith("!")
        if branch_pattern_matches(pattern.removeprefix("!"), branch):
            verdict = not negated
    return verdict


def trigger_fires_for_base_branch(trigger: dict, branch: str) -> bool:
    """Whether ``branches`` / ``branches-ignore`` admit a PR whose BASE is ``branch``.

    Both filters are evaluated against the base — the branch being merged INTO —
    which is why ``branches: ['release/**']`` silences every PR into ``main``
    while looking like it only narrows a release lane.
    """
    include = as_patterns(trigger.get("branches"))
    exclude = as_patterns(trigger.get("branches-ignore"))
    assert include is None or exclude is None, (
        "the `pull_request` trigger declares both `branches` and `branches-ignore`; "
        "GitHub rejects that combination, so the workflow would not run at all"
    )
    if include is not None:
        return last_match_wins(include, branch, default=False)
    if exclude is not None:
        return not last_match_wins(exclude, branch, default=False)
    return True


def test_the_branch_pattern_matcher_is_not_vacuous() -> None:
    """The control for the branch assertion below.

    ``trigger_fires_for_base_branch`` reports "the gate still fires" both when the
    filter genuinely admits ``main`` and when the matcher has degenerated into
    something that returns ``True`` for everything. Only this table can tell the
    two apart, so it is pinned here rather than trusted.
    """
    assert branch_pattern_matches("main", "main")
    assert not branch_pattern_matches("release/**", "main")
    assert not branch_pattern_matches("main", "mainline")
    assert branch_pattern_matches("*", "main")
    assert not branch_pattern_matches("*", "release/1.0"), "`*` must not cross a `/`"
    assert branch_pattern_matches("**", "release/1.0")
    assert branch_pattern_matches("releases/**", "releases/1.0/rc")
    assert trigger_fires_for_base_branch({}, BASE_BRANCH), "an unfiltered trigger fires"
    assert not trigger_fires_for_base_branch({"branches": ["release/**"]}, BASE_BRANCH)
    assert not trigger_fires_for_base_branch({"branches-ignore": ["main"]}, BASE_BRANCH)
    assert trigger_fires_for_base_branch({"branches": ["**", "!release/**"]}, BASE_BRANCH)
    assert not trigger_fires_for_base_branch({"branches": ["**", "!main"]}, BASE_BRANCH)


def test_a_pull_request_on_the_default_activity_types_still_triggers_the_gate() -> None:
    """``types:`` is a stronger disarm than any ``paths:`` filter.

    A path filter still runs the workflow for PRs that touch the filtered paths.
    ``types: [labeled]`` runs it for none of them: opening a PR, pushing to it, or
    reopening it starts **no run at all**, and a workflow that never ran is not a
    workflow that failed — the check simply is not there to be red.

    Absence of the key is NOT the property asserted, because
    ``types: [opened, synchronize, reopened]`` is a legitimate spelling of the
    default and disarms nothing. What is asserted is that the declared set still
    covers all three default activity types, so a PR's normal lifecycle keeps
    reaching the gate.
    """
    trigger = pull_request_trigger()
    assert trigger is not None, "the workflow no longer runs on `pull_request`"
    declared = as_patterns(trigger.get("types"))
    if declared is None:
        return  # the default applies verbatim; nothing was narrowed
    missing = sorted(DEFAULT_PULL_REQUEST_TYPES - set(declared))
    assert not missing, (
        f"the `pull_request` trigger declares `types: {declared!r}`, which drops "
        f"{missing}. GitHub's default is opened/reopened/synchronize; dropping any "
        "of them means an ordinary pull request starts no run of this workflow, so "
        "the compatibility gate never reports at all. Widening `types` is fine — "
        "this assertion only forbids narrowing below the default."
    )


def test_a_pull_request_targeting_main_still_triggers_the_gate() -> None:
    """The same disarm one key down, and the one that reads most like housekeeping.

    ``branches: ['release/**']`` looks like it adds a release lane. It replaces
    the trigger: pull_request branch filters match the BASE branch, so every PR
    into ``main`` — which is every PR in this repository — stops starting a run.
    ``branches-ignore: [main]`` is the same disarm spelled positively.

    Again the property, not the key: ``branches: [main]`` is legitimate and stays
    green. What must hold is that a PR whose base is ``main`` still fires.
    """
    trigger = pull_request_trigger()
    assert trigger is not None, "the workflow no longer runs on `pull_request`"
    assert trigger_fires_for_base_branch(trigger, BASE_BRANCH), (
        f"the `pull_request` trigger's branch filters "
        f"(branches={trigger.get('branches')!r}, "
        f"branches-ignore={trigger.get('branches-ignore')!r}) exclude a pull request "
        f"whose base is {BASE_BRANCH!r}. Every pull request in this repository targets "
        f"{BASE_BRANCH!r}, so the contract gates would start no run — and an absent "
        "check cannot be red."
    )


def jobs_the_gate_depends_on(job_name: str, document: dict) -> list[str]:
    """The transitive ``needs`` closure of ``job_name``, excluding itself."""
    jobs = document["jobs"]
    closure: list[str] = []
    pending = list(as_patterns(jobs[job_name].get("needs")) or [])
    while pending:
        needed = pending.pop()
        if needed in closure:
            continue
        assert needed in jobs, (
            f"job {job_name!r} declares `needs: [{needed!r}]`, which names no job in "
            "this workflow; GitHub rejects the file and nothing runs"
        )
        closure.append(needed)
        pending.extend(as_patterns(jobs[needed].get("needs")) or [])
    return closure


def test_the_gate_job_cannot_be_skipped_through_a_dependency() -> None:
    """``needs:`` is the third disarm, and it leaves no mark on the gate itself.

    ``test_the_gate_step_and_job_are_unconditional`` asserts the gate job carries
    no ``if:``. It says nothing about ``needs:``, and a job whose dependency is
    skipped is skipped in turn — while a skipped job reports success. So::

        jobs:
          decoy:
            if: false
            runs-on: arc-amd64
            steps: [...]
          gates:
            needs: [decoy]

    leaves every other assertion in this file passing, runs the gate never, and
    renders the workflow green.

    ⚠️ THE CHOICE MADE HERE, and why it is not "``gates`` must have no ``needs``".
    A dependency is a legitimate thing to add — a shared build or setup job. The
    hazard is not depending, it is depending on something that can be SKIPPED, and
    skippability is decidable from this file for exactly two constructs: an ``if:``
    on the needed job, and a ``strategy:`` whose matrix can expand to zero jobs.
    Both are refused across the whole transitive closure, since a dependency's
    dependency skips just as effectively. Everything else that could skip a job
    (a cancelled run, a failed dependency) is already loudly red, not quiet.

    A needed job's ``continue-on-error`` is deliberately NOT refused: it makes the
    dependency's failure report as success, which lets the gate run rather than
    stopping it. Wrong direction to be a disarm of this gate.
    """
    document = workflow_document()
    for job_name, _job, _step in gate_steps():
        for needed in jobs_the_gate_depends_on(job_name, document):
            dependency = document["jobs"][needed]
            assert "if" not in dependency, (
                f"job {job_name!r} holds the compatibility gate and depends on job "
                f"{needed!r}, which is conditional (`if: {dependency['if']!r}`). A "
                "skipped dependency skips its dependents, and a skipped job reports "
                "success — the gate would never run and the workflow would be green."
            )
            assert "strategy" not in dependency, (
                f"job {job_name!r} holds the compatibility gate and depends on job "
                f"{needed!r}, which declares a `strategy:`. A matrix that expands to "
                "zero jobs skips the dependency and therefore the gate, and whether "
                "it can is not decidable from this file. Depend on an unconditional, "
                "unmatrixed job, or extend this assertion deliberately."
            )

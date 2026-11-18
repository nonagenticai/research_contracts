"""Repository anchoring.

Every gate resolves its inputs from the repository root derived from this
module's own location. Nothing is resolved from the process working directory:
a cwd-anchored gate silently passes when run from a directory where the inputs
it is supposed to inspect do not exist.
"""

from __future__ import annotations

from pathlib import Path

#: Repository root, derived from this file, not from ``os.getcwd()``.
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

#: The placeholder vocabulary the draft-governance gate validates identifiers against.
ASSIGNED_IDENTIFIER_SCHEMA = REPOSITORY_ROOT / "schemas/meta/assigned-identifier.v1.schema.json"

DENYLIST = REPOSITORY_ROOT / "config/pre-adr-regulatory-denylist.json"
OWNERS_FILE = REPOSITORY_ROOT / "OWNERS.yaml"

# ``RECORDS_DIR`` and ``require_path`` were removed 2026-08-02 as dead code that
# also mis-stated its own guarantee. ``require_path`` promised "a missing
# directory must never glob to []" but tested ``Path.exists()``, which follows
# symlinks and does not distinguish a directory from a file: a symlink to an
# empty directory and a regular file both passed it and both glob to ``[]`` —
# the exact vacuity the docstring forbade. It had zero call sites, so wiring it
# in would have WEAKENED every hand-rolled check it replaced. The real, stronger
# check survives in ``governance.py``, which rejects a symlinked records
# directory explicitly and accumulates the failure instead of raising.
# ``RECORDS_DIR`` had zero readers and is structurally wrong for that gate:
# ``governance_errors`` takes ``repo_root`` as a parameter so it can be exercised
# against a temporary tree, which a ``REPOSITORY_ROOT``-anchored constant defeats.

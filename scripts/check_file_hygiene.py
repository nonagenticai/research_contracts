#!/usr/bin/env python3
"""Entry point: trailing-whitespace, final-newline and byte-frozen fixture gate.

Replaces the upstream ``trailing-whitespace`` and ``end-of-file-fixer`` hooks,
which rewrote tracked files during a commit and existed in no CI step. This one
reports and exits non-zero; it never writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo-anchored, not cwd-anchored: the gate inspects the repository that
# contains it, and finds its own implementation without needing an install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_contracts.tooling.file_hygiene import main

if __name__ == "__main__":
    raise SystemExit(main())

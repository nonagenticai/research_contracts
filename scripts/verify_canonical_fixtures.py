#!/usr/bin/env python3
"""Entry point: FND-002/FND-005 canonical fixture harness."""

from __future__ import annotations

import sys
from pathlib import Path

# Repo-anchored, not cwd-anchored: the gate inspects the repository that
# contains it, and finds its own implementation without needing an install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_contracts.tooling.canonical_fixtures import main

if __name__ == "__main__":
    raise SystemExit(main())

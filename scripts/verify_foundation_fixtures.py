#!/usr/bin/env python3
"""Replay every committed FND-002 foundation fixture (tasks 2, 3 and 6)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_contracts.tooling.foundation_fixtures import main

if __name__ == "__main__":
    raise SystemExit(main())

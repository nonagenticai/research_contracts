#!/usr/bin/env python3
"""Entry point: generate the FND-002 foundation type bindings for Python and TypeScript."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_contracts.tooling.generate_types import main

if __name__ == "__main__":
    raise SystemExit(main())

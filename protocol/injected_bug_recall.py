#!/usr/bin/env python3
"""Compatibility shim for the relocated deterministic-floor benchmark.

Deprecated in v0.3. Use ``python benchmarks/injected/run.py``. This path remains
available through the v0.3 release line and is scheduled for removal in v0.4.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
run = importlib.import_module("benchmarks.injected.run").run


if __name__ == "__main__":
    run()

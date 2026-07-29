"""Compatibility launcher for the promoted self-contained golden case.

Deprecated in v0.3. Use:

    python golden_cases/self_contained/doc-bundle-01/run_case.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "golden_cases" / "self_contained" / "doc-bundle-01" / "run_case.py"


def main() -> int:
    return subprocess.run([sys.executable, str(RUNNER)], cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

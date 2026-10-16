"""Cheap guard: every planted mutant in protocol/matrix_mutants.py still applies.

The full mutation run (CI step "Matrix mutation regression") takes minutes; this
check keeps a policy edit from silently turning a mutant into a no-op.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_matrix_mutant_applies_to_current_policy() -> None:
    spec = importlib.util.spec_from_file_location(
        "matrix_mutants", ROOT / "protocol" / "matrix_mutants.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = (ROOT / "validity_audit" / "policy.py").read_text(encoding="utf-8")
    assert module.inapplicable(source) == []
    assert set(module.MUTANTS) == {
        "M1_revert_h1",
        "M2_unbound_softens_failclass",
        "M3_ignore_downgraded_claims",
        "M4_absence_softens_bound_refutation",
        "M5_revert_r1",
        "M6_withhold_failclass_waiver",
        "M7_swap_unapplied_reasons",
    }

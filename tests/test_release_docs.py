from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from validity_audit.policy import ERROR_CLASS_EFFECTS
from validity_audit.schemas import validate_document

ROOT = Path(__file__).resolve().parents[1]


def test_documented_attestation_is_schema_valid_and_reproduced() -> None:
    documented_path = ROOT / "docs" / "attestation-example.json"
    golden_path = (
        ROOT
        / "golden_cases"
        / "self_contained"
        / "doc-bundle-01"
        / "expected_attestation.json"
    )
    documented = json.loads(documented_path.read_text(encoding="utf-8"))
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    validate_document(documented, "attestation")
    assert documented == golden
    assert documented["attestation_type"] == "unsigned_validity_attestation"
    assert documented["signature"] is None


def test_readme_quickstart_commands_are_ci_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for command in (
        "python -m pip install -e .",
        "python golden_cases/self_contained/doc-bundle-01/run_case.py",
    ):
        assert command in readme
        assert command in workflow


def test_architecture_svg_is_parseable_and_names_all_layers_and_modes() -> None:
    root = ET.parse(ROOT / "docs" / "architecture.svg").getroot()
    text = " ".join(part.strip() for part in root.itertext() if part.strip())
    for required in (
        "Contract boundary",
        "Evidence capture and probes",
        "Independent cold / primed review",
        "Reproduction and error-class policy",
        "Unsigned attestation and receipt",
        "Repository / CLI",
        "Plugin / agent skill",
        "Embedded API / model",
    ):
        assert required in text


def test_fitness_policy_and_readme_table_agree() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    schemas_readme = (ROOT / "schemas" / "README.md").read_text(encoding="utf-8")
    assert ERROR_CLASS_EFFECTS["fitness"] == "advisory"
    assert "| `fitness` | `advisory` |" in readme
    assert "`fitness`, `maintainability`" in schemas_readme


def test_legacy_shim_window_is_documented() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for legacy in (
        "protocol/injected_bug_recall.py",
        "examples/self_contained/run_demo.py",
        "protocol/ledger.py",
    ):
        assert legacy in readme
    assert "earliest removal v0.4.0" in readme

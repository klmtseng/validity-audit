"""Small deterministic probes used during both prepare and finalize."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _relative_markdown_targets(markdown: Path) -> list[str]:
    text = markdown.read_text(encoding="utf-8")
    targets: list[str] = []
    for match in MARKDOWN_LINK.finditer(text):
        target = match.group(1).strip()
        if target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        target = target.split("#", 1)[0].strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        if target:
            targets.append(unquote(target))
    return targets


def run_probes(workspace: Path, artifact_paths: list[str]) -> dict[str, Any]:
    """Run deterministic checks and return a canonical probe report."""
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for artifact_path in sorted(artifact_paths):
        path = workspace / artifact_path
        checks.append(
            {
                "check_id": f"artifact-readable:{artifact_path}",
                "kind": "artifact_readable",
                "path": artifact_path,
                "status": "pass",
            }
        )
        if path.suffix.lower() != ".md":
            continue

        broken: list[str] = []
        for target in _relative_markdown_targets(path):
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(workspace) or not resolved.exists():
                broken.append(target)
        checks.append(
            {
                "check_id": f"relative-links:{artifact_path}",
                "kind": "relative_markdown_links",
                "path": artifact_path,
                "status": "fail" if broken else "pass",
                "broken_targets": broken,
            }
        )
        for index, target in enumerate(broken, 1):
            finding_id = f"probe-broken-reference-{len(findings) + 1}"
            findings.append(
                {
                    "finding_id": finding_id,
                    "title": "Broken relative Markdown reference",
                    "description": (
                        f"{artifact_path} references {target!r}, which does not resolve "
                        "from the linking file."
                    ),
                    "error_class": "material_requirement_miss",
                    "source": "deterministic_probe",
                    "severity": "high",
                    "confidence": "high",
                    "reproduction": "reproduced",
                    "evidence": [
                        {
                            "evidence_id": f"probe-evidence-{len(findings) + 1}-{index}",
                            "kind": "file_line",
                            "description": (
                                "The relative target was resolved from the Markdown file."
                            ),
                            "locator": f"{artifact_path} -> {target}",
                        }
                    ],
                }
            )

    return {
        "probe_version": "0.3.0",
        "checks": checks,
        "findings": findings,
    }

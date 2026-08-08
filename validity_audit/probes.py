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


def _probe_failure(
    *,
    finding_id: str,
    title: str,
    description: str,
    artifact_path: str,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "title": title,
        "description": description,
        "error_class": "material_requirement_miss",
        "source": "deterministic_probe",
        "severity": "high",
        "confidence": "high",
        "reproduction": "reproduced",
        "evidence": [
            {
                "evidence_id": f"evidence-{finding_id}",
                "kind": "file_line",
                "description": "The deterministic probe could not validate the artifact.",
                "locator": artifact_path,
            }
        ],
    }


def run_probes(workspace: Path, artifact_paths: list[str]) -> dict[str, Any]:
    """Run deterministic checks and return a canonical probe report."""
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for artifact_path in sorted(artifact_paths):
        path = workspace / artifact_path
        try:
            path.read_bytes()
        except OSError:
            checks.append(
                {
                    "check_id": f"artifact-readable:{artifact_path}",
                    "kind": "artifact_readable",
                    "path": artifact_path,
                    "status": "fail",
                }
            )
            finding_id = f"probe-unreadable-artifact-{len(findings) + 1}"
            findings.append(
                _probe_failure(
                    finding_id=finding_id,
                    title="Artifact is not readable",
                    description=(
                        f"{artifact_path} could not be read by the deterministic probe."
                    ),
                    artifact_path=artifact_path,
                )
            )
            continue

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

        try:
            targets = _relative_markdown_targets(path)
        except (OSError, UnicodeError):
            checks.append(
                {
                    "check_id": f"relative-links:{artifact_path}",
                    "kind": "relative_markdown_links",
                    "path": artifact_path,
                    "status": "fail",
                    "broken_targets": [],
                }
            )
            finding_id = f"probe-unparseable-markdown-{len(findings) + 1}"
            findings.append(
                _probe_failure(
                    finding_id=finding_id,
                    title="Markdown artifact could not be checked",
                    description=(
                        f"{artifact_path} could not be parsed as UTF-8 Markdown by the "
                        "relative-link verifier."
                    ),
                    artifact_path=artifact_path,
                )
            )
            continue

        broken: list[str] = []
        for target in targets:
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

from __future__ import annotations

from pathlib import Path

from validity_audit.probes import run_probes


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["check_id"] == check_id)


def test_probe_positive_control_clean_artifact_passes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "note.txt").write_text("clean\n", encoding="utf-8")

    report = run_probes(workspace, ["note.txt"])

    assert check(report, "artifact-readable:note.txt")["status"] == "pass"
    assert report["findings"] == []


def test_probe_negative_control_broken_markdown_link_fails(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("[missing](missing.md)\n", encoding="utf-8")

    report = run_probes(workspace, ["README.md"])

    assert check(report, "artifact-readable:README.md")["status"] == "pass"
    links = check(report, "relative-links:README.md")
    assert links["status"] == "fail"
    assert links["broken_targets"] == ["missing.md"]
    assert len(report["findings"]) == 1


def test_probe_fault_control_missing_non_markdown_artifact_fails_closed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    report = run_probes(workspace, ["missing.txt"])

    readable = check(report, "artifact-readable:missing.txt")
    assert readable["status"] == "fail"
    assert len(report["findings"]) == 1
    assert report["findings"][0]["finding_id"].startswith("probe-unreadable-artifact-")


def test_probe_fault_control_non_utf8_markdown_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "bad.md").write_bytes(b"\xff\xfe\xfd")

    report = run_probes(workspace, ["bad.md"])

    assert check(report, "artifact-readable:bad.md")["status"] == "pass"
    assert check(report, "relative-links:bad.md")["status"] == "fail"
    assert len(report["findings"]) == 1
    assert report["findings"][0]["finding_id"].startswith("probe-unparseable-markdown-")

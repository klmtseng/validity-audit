"""Regression tests for markdown injection via reviewer-controlled finding.title.

Issue: a title like '# SIGNATURE VERIFIED' or a title containing newlines could be
inserted raw into attestation.md, causing markdown structure characters to take effect.

After the patch:
- Schema rejects titles containing \\n or \\r (single-line constraint).
- _sanitize_md_title escapes any remaining leading markdown structural character
  so it cannot take effect as a block-level element.
- attestation.json signature remains null (cannot be forged via title injection).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from validity_audit.runtime import AuditRuntimeError, finalize_run, prepare_run
from validity_audit.schemas import SchemaValidationError, validate_document

STARTED = "2026-07-29T00:00:00Z"
COMPLETED = "2026-07-29T00:05:00Z"
ISSUED = "2026-07-29T00:06:00Z"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "README.md").write_text(
        "# Demo\n\n[Details](details.md)\n", encoding="utf-8"
    )
    (workspace / "docs" / "details.md").write_text("# Details\n", encoding="utf-8")
    _write_json(
        workspace / "task.json",
        {
            "$schema": "schemas/task_contract.schema.json",
            "schema_version": "0.3.0",
            "task_id": "injection-test",
            "claims": [
                {
                    "claim_id": "claim-1",
                    "statement": "All links resolve.",
                }
            ],
            "artifact_paths": ["docs/README.md", "docs/details.md"],
            "packs": ["docs"],
        },
    )
    return workspace


def _reviewer_output_with_title(title: str) -> dict:
    return {
        "$schema": "schemas/reviewer_output.schema.json",
        "schema_version": "0.3.0",
        "review_context": "cold",
        "reviewer": {"kind": "model", "label": "test-reviewer"},
        "operator_id": "test-operator",
        "claim_results": [
            {
                "claim_id": "claim-1",
                "outcome": "refuted",
                "evidence": [
                    {
                        "evidence_id": "e1",
                        "kind": "note",
                        "description": "Injection test evidence.",
                    }
                ],
                "finding_ids": ["inject-finding"],
            }
        ],
        "findings": [
            {
                "finding_id": "inject-finding",
                "title": title,
                "description": "A finding with a potentially dangerous title.",
                "error_class": "correctness",
                "severity": "high",
                "confidence": "high",
                "reproduction": "reproduced",
                "evidence": [
                    {
                        "evidence_id": "e2",
                        "kind": "note",
                        "description": "Reproduction evidence.",
                    }
                ],
            }
        ],
        "summary": "Injection test.",
    }


def _do_run(tmp_path: Path, title: str) -> tuple[str, dict]:
    """Run a full prepare+finalize cycle with the given finding title.

    Returns (attestation_md_text, attestation_json_dict).
    """
    workspace = _make_workspace(tmp_path)
    prepare_run(
        workspace=workspace,
        contract_path="task.json",
        run_dir=".validity-audit/runs/inject-run",
        review_context="cold",
        reviewer_kind="model",
        reviewer_label="test-reviewer",
        operator_id="test-operator",
        run_id="run-inject-001",
        started_at=STARTED,
    )
    _write_json(workspace / "reviewer-output.json", _reviewer_output_with_title(title))
    (workspace / "transcript.txt").write_bytes(b"Injection test transcript.\n")
    finalize_run(
        workspace=workspace,
        run_dir=".validity-audit/runs/inject-run",
        reviewer_output_path="reviewer-output.json",
        transcript_path="transcript.txt",
        completed_at=COMPLETED,
        issued_at=ISSUED,
        attestation_id="attestation-inject-001",
        append_ledger=False,
    )
    run_dir = workspace / ".validity-audit/runs/inject-run"
    md = (run_dir / "attestation.md").read_text(encoding="utf-8")
    attest = json.loads((run_dir / "attestation.json").read_text(encoding="utf-8"))
    return md, attest


# Headings that the template itself produces — these are acceptable
_TEMPLATE_HEADINGS = frozenset({
    "# Unsigned Validity Attestation",
    "## Result",
    "## Findings",
})


@pytest.mark.parametrize(
    "title",
    [
        "# SIGNATURE VERIFIED",
        "## fake heading",
        "> injected blockquote",
        "| col1 | col2 |",
        "- injected bullet",
        "`code span injection`",
    ],
)
def test_single_line_md_title_does_not_produce_heading_outside_template(
    tmp_path: Path, title: str
) -> None:
    """Single-line titles with leading markdown structural characters must be escaped
    so they cannot produce block-level markdown elements in attestation.md.

    attestation.json signature must remain null.
    """
    md, attest = _do_run(tmp_path, title)
    lines = md.splitlines()

    unexpected_headings = [
        ln for ln in lines if ln.startswith("#") and ln not in _TEMPLATE_HEADINGS
    ]
    assert not unexpected_headings, (
        f"Finding title {title!r} produced heading line(s) in attestation.md: "
        f"{unexpected_headings}\nFull MD:\n{md}"
    )

    # signature must remain null — injection must not forge a signed record
    assert attest["signature"] is None, (
        f"attestation.json signature was modified: {attest['signature']!r}"
    )


@pytest.mark.parametrize(
    "title_with_newline",
    [
        "Normal start\n# SIGNATURE VERIFIED",
        "line one\r\nline two",
        "embedded\nnewline",
    ],
)
def test_title_with_newline_is_rejected_by_schema(title_with_newline: str) -> None:
    """The reviewer_output schema must reject any title that contains \\n or \\r.

    This prevents multi-line injection from even reaching the rendering stage.
    """
    output = _reviewer_output_with_title(title_with_newline)
    with pytest.raises((SchemaValidationError, AuditRuntimeError)):
        validate_document(output, "reviewer_output")


# ---------------------------------------------------------------------------
# Inline injection tests (residual holes closed in the follow-up commit)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title",
    [
        "[click](http://evil.com)",
        "<script>alert(1)</script>",
        "![x](http://evil.com/a.png)",
        "<!-- hidden -->",
    ],
)
def test_inline_injection_vectors_rendered_as_literal_text(
    tmp_path: Path, title: str
) -> None:
    """Inline CommonMark structures in finding.title must be escaped to literal text.

    After sanitisation the attestation.md must not contain:
    - unescaped link syntax  ``](http``  (backslash-escaped ``\\](`` is fine)
    - unescaped image syntax ``![``      (backslash-escaped ``\\![`` is fine)
    - unescaped HTML comment opener ``<!--``
    - unescaped ``<script``              (backslash-escaped ``\\<script`` is fine)

    We verify the *escaped* forms are present and the *unescaped* forms absent,
    confirming CommonMark will render them as literal punctuation, not active structures.

    attestation.json signature must remain null.
    """
    md, attest = _do_run(tmp_path, title)

    # ---- link vector: "[click](http://evil.com)" ----
    # Unescaped "](http" must be absent; backslash-escaped form allowed.
    assert "](http" not in md, (
        f"Title {title!r}: unescaped link syntax ](http found in attestation.md:\n{md}"
    )
    # ---- image vector: "![x](http://evil.com/a.png)" ----
    # Unescaped "![" must be absent; backslash-escaped "\\![" is fine.
    assert "![" not in md, (
        f"Title {title!r}: unescaped image opener ![ found in attestation.md:\n{md}"
    )
    # ---- HTML comment: "<!-- hidden -->" ----
    # The "<" is backslash-escaped, so "<!--" must be absent (it becomes "\\<\\!--").
    assert "<!--" not in md, (
        f"Title {title!r}: HTML comment opener <!-- found in attestation.md:\n{md}"
    )
    # ---- script tag: "<script>alert(1)</script>" ----
    # The "<" is backslash-escaped → "\\<script" in MD; the substring "<script" still
    # appears right after the backslash.  We verify the *preceding* char is a backslash
    # (i.e. it is escaped) by checking the raw sequence "\\<script" is present.
    if "<script" in md:
        idx = md.index("<script")
        assert idx > 0 and md[idx - 1] == "\\", (
            f"Title {title!r}: unescaped <script found at index {idx} in attestation.md:\n{md}"
        )

    assert attest["signature"] is None, (
        f"attestation.json signature was modified: {attest['signature']!r}"
    )


@pytest.mark.parametrize(
    "title_with_unicode_sep",
    [
        "safe\x0b# after",   # VT  U+000B
        "safe\x0c# after",   # FF  U+000C
        "safe\x85# after",   # NEL U+0085
        "safe # after", # LS  U+2028
        "safe # after", # PS  U+2029
    ],
)
def test_unicode_line_separators_rejected_by_schema(
    title_with_unicode_sep: str,
) -> None:
    """The reviewer_output schema must reject titles containing Unicode line/paragraph
    separators (U+000B, U+000C, U+0085, U+2028, U+2029).

    These characters are inert in CommonMark but could cause block-promotion in
    non-standard renderers. The schema pattern provides defence-in-depth.
    """
    output = _reviewer_output_with_title(title_with_unicode_sep)
    with pytest.raises((SchemaValidationError, AuditRuntimeError)):
        validate_document(output, "reviewer_output")

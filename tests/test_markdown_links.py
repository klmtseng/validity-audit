from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def relative_targets(markdown: Path) -> list[str]:
    text = markdown.read_text(encoding="utf-8")
    targets = []
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


def test_relative_markdown_links_resolve_from_the_linking_file() -> None:
    broken = []
    for markdown in sorted(ROOT.rglob("*.md")):
        for target in relative_targets(markdown):
            resolved = (markdown.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{markdown.relative_to(ROOT)} -> {target}")
    assert not broken, "broken relative Markdown links:\n" + "\n".join(broken)

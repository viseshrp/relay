from __future__ import annotations

import json
import re
from pathlib import Path


REVIEW_COMMENTS_PATTERN = re.compile(
    r"```relay-review-comments\s*(?P<body>.*?)```",
    re.IGNORECASE | re.DOTALL,
)
VERDICT_PATTERN = re.compile(
    r"^\s*## Verdict\s*(?:\r?\n)+\s*(?P<verdict>PASS|FAIL|PASS_WITH_WARNINGS)\s*$",
    re.MULTILINE,
)


def _is_valid_review_comment(comment: object) -> bool:
    if not isinstance(comment, dict):
        return False
    required_keys = {"file", "line", "severity", "comment"}
    return required_keys.issubset(comment)


def extract_review_comments(raw_output: str) -> tuple[list[dict[str, object]], bool]:
    match = REVIEW_COMMENTS_PATTERN.search(raw_output)
    if match is None:
        return [], False
    try:
        comments = json.loads(match.group("body").strip())
    except json.JSONDecodeError:
        return [], False
    if not isinstance(comments, list):
        return [], False
    if not all(_is_valid_review_comment(comment) for comment in comments):
        return [], False
    return comments, True


def extract_review_summary(raw_output: str) -> str:
    marker = "## Summary"
    index = raw_output.find(marker)
    return raw_output[index:].strip() if index >= 0 else raw_output.strip()


def extract_verdict(summary_markdown: str) -> str | None:
    match = VERDICT_PATTERN.search(summary_markdown)
    if match is None:
        return None
    return match.group("verdict")


def persist_review_outputs(
    review_dir: Path,
    raw_output: str,
    comments: list[dict[str, object]],
    summary_markdown: str,
) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "REVIEW_COMMENTS.json").write_text(json.dumps(comments, indent=2), encoding="utf-8")
    (review_dir / "REVIEW_SUMMARY.md").write_text(summary_markdown, encoding="utf-8")
    (review_dir / "REVIEW_RAW.md").write_text(raw_output, encoding="utf-8")

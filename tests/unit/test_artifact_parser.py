from relay.artifacts.parsers import extract_review_comments, extract_review_summary, extract_verdict


def test_parser_returns_false_for_malformed_json() -> None:
    comments, parsed = extract_review_comments("```relay-review-comments\n[{]\n```")
    assert parsed is False
    assert comments == []


def test_parser_returns_false_when_sentinel_is_missing() -> None:
    comments, parsed = extract_review_comments("No structured comments here.")
    assert parsed is False
    assert comments == []


def test_parser_rejects_wrong_comment_structure() -> None:
    comments, parsed = extract_review_comments('```relay-review-comments\n[{"severity": "warning"}]\n```')
    assert parsed is False
    assert comments == []


def test_parser_uses_first_sentinel_block() -> None:
    raw = """```relay-review-comments
[{"file": "app.py", "line": 3, "severity": "warning", "comment": "First"}]
```

```relay-review-comments
[{"file": "app.py", "line": 4, "severity": "warning", "comment": "Second"}]
```"""
    comments, parsed = extract_review_comments(raw)
    assert parsed is True
    assert comments == [{"file": "app.py", "line": 3, "severity": "warning", "comment": "First"}]


def test_review_summary_and_verdict_parsing() -> None:
    pass_summary = """## Summary
Looks good.

## Verdict
PASS
"""
    fail_summary = """## Summary
Needs more work.

## Verdict
FAIL
"""
    warning_summary = """## Summary
Minor issues remain.

## Verdict
PASS_WITH_WARNINGS
"""

    assert extract_verdict(extract_review_summary(pass_summary)) == "PASS"
    assert extract_verdict(extract_review_summary(fail_summary)) == "FAIL"
    assert extract_verdict(extract_review_summary(warning_summary)) == "PASS_WITH_WARNINGS"
    assert extract_verdict(extract_review_summary("## Summary\nMissing verdict section")) is None
    assert extract_verdict(extract_review_summary("## Summary\n## Verdict\nPASSISH")) is None

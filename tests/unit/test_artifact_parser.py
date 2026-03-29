from relay.artifacts.parsers import extract_review_comments, extract_review_summary, extract_verdict


def test_review_parser_extracts_comments_and_verdict() -> None:
    raw = """```relay-review-comments
    [{"file": "app.py", "line": 12, "severity": "warning", "comment": "Issue"}]
    ```

    ## Summary
    Fine.

    ## Verdict
    PASS_WITH_WARNINGS
    """
    comments, parsed = extract_review_comments(raw)
    assert parsed is True
    assert comments[0]["file"] == "app.py"
    assert extract_verdict(extract_review_summary(raw)) == "PASS_WITH_WARNINGS"

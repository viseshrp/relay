from relay.copilot.prompts import (
    build_correction_prompt,
    build_critique_prompt,
    build_execution_prompt,
    build_exploration_finalization_prompt,
    build_fix_prompt,
    build_planning_prompt,
    build_review_prompt,
)


def test_prompt_templates_include_context_paths() -> None:
    context_paths = ["/src", "/tests"]
    prompts = [
        build_exploration_finalization_prompt("transcript", context_paths, "/tmp/out.md"),
        build_planning_prompt("plan", context_paths, "/tmp"),
        build_critique_prompt("spec", "plan", "brief", context_paths, "/tmp/critique.md"),
        build_correction_prompt("critique", "brief", "spec", context_paths, "/tmp/plan.md"),
        build_execution_prompt("spec", "plan", context_paths),
        build_review_prompt("spec", "plan", context_paths, "/tmp"),
        build_fix_prompt([], "summary", "spec", "plan", context_paths),
    ]

    for prompt in prompts:
        assert "/src" in prompt
        assert "/tests" in prompt


def test_review_prompt_contains_required_outputs() -> None:
    prompt = build_review_prompt("spec", "plan", ["/src"], "/tmp/review")
    assert "REVIEW_COMMENTS.json" in prompt
    assert "REVIEW_SUMMARY.md" in prompt
    assert "PASS_WITH_WARNINGS" in prompt

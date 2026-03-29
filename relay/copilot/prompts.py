from __future__ import annotations

import json
from pathlib import Path


REVIEW_SUMMARY_TEMPLATE = """## Summary
Summarize the current implementation outcome in 3-5 concise bullets.

## Deviations from Spec
List concrete deviations from SPEC.md and IMPLEMENTATION_PLAN.md. Use "None." if there are none.

## Risks
List technical or product risks that remain after review. Use "None." if there are none.

## Suggestions
List targeted next actions to address any remaining issues. Use "None." if there are none.

## Verdict
PASS
"""


def _format_context_paths(context_paths: list[str]) -> str:
    if not context_paths:
        return "- None selected."
    return "\n".join(f"- {path}" for path in context_paths)


def build_exploration_finalization_prompt(
    transcript_markdown: str,
    context_paths: list[str],
    output_path: str,
) -> str:
    return f"""You are finalizing Relay's Exploration phase.

Summarize the conversation below into a structured Markdown planning brief and write it to:
{output_path}

Required section headings, in this exact order:
1. Problem
2. Goals
3. Constraints
4. Preferred Stack
5. Files to Read
6. Desired Output

Requirements:
- Use the conversation as the primary source of truth.
- Include the selected context paths verbatim in the "Files to Read" section.
- Be specific about constraints, success criteria, and requested output.
- Output clean Markdown only.
- Do not wrap the answer in code fences.

Selected context paths:
{_format_context_paths(context_paths)}

Conversation transcript:

{transcript_markdown}
"""


def build_planning_prompt(
    planning_prompt_markdown: str,
    context_paths: list[str],
    output_dir: str,
) -> str:
    spec_path = Path(output_dir) / "SPEC.md"
    plan_path = Path(output_dir) / "IMPLEMENTATION_PLAN.md"
    return f"""You are Relay's Planning phase.

Read the planning brief below, then create these two files in the exact output directory shown:
- {spec_path.as_posix()}
- {plan_path.as_posix()}

Requirements:
- SPEC.md must capture the full problem, goals, constraints, architecture, workflows, APIs, and acceptance criteria needed to implement the request.
- IMPLEMENTATION_PLAN.md must describe the concrete implementation plan, file/module responsibilities, rollout order, and testing strategy.
- Use the selected context paths as primary reading targets when relevant.
- Be explicit enough that a separate implementation phase can execute without needing missing clarification.
- Write both files directly to disk in the specified directory.
- Do not commit changes.

Selected context paths:
{_format_context_paths(context_paths)}

Planning brief:

{planning_prompt_markdown}
"""


def build_critique_prompt(
    spec_markdown: str,
    implementation_plan_markdown: str,
    planning_prompt_markdown: str,
    context_paths: list[str],
    output_path: str,
) -> str:
    return f"""You are Relay's Plan Critique phase.

Critically review IMPLEMENTATION_PLAN.md against the planning brief and SPEC.md, then produce:
- {output_path}

Output requirements:
- Preserve the full plan content inline.
- Add human-readable critique callouts using blockquotes in the form:
  > **Critique:** comment text
- Add machine-readable critique markers using HTML comments in the form:
  <!-- CRITIQUE: comment text -->
- Every critique point should appear in both forms close to the relevant plan section.
- Focus on missing scope, unclear sequencing, risky assumptions, testing gaps, and conflicts with the spec.
- Do not output anything except the fully critiqued Markdown file content.

Selected context paths:
{_format_context_paths(context_paths)}

Planning brief:

{planning_prompt_markdown}

SPEC.md:

{spec_markdown}

IMPLEMENTATION_PLAN.md:

{implementation_plan_markdown}
"""


def build_correction_prompt(
    critiqued_plan_markdown: str,
    planning_prompt_markdown: str,
    spec_markdown: str,
    context_paths: list[str],
    output_path: str,
) -> str:
    return f"""You are Relay's Plan Correction phase.

Address every critique point in the critiqued implementation plan and write a clean corrected plan to:
- {output_path}

Requirements:
- Resolve all critique comments.
- Remove every critique marker and blockquote from the final output.
- Keep the corrected plan internally consistent with SPEC.md and the planning brief.
- Preserve concrete file/module responsibilities and rollout order.
- Output Markdown only and write it directly to disk.

Selected context paths:
{_format_context_paths(context_paths)}

Planning brief:

{planning_prompt_markdown}

SPEC.md:

{spec_markdown}

Critiqued plan:

{critiqued_plan_markdown}
"""


def build_execution_prompt(
    spec_markdown: str,
    implementation_plan_markdown: str,
    context_paths: list[str],
) -> str:
    return f"""You are Relay's Execution phase.

Implement the plan in the current working tree using SPEC.md and the corrected IMPLEMENTATION_PLAN.md as the source of truth.

Requirements:
- Apply changes directly to the working tree.
- Do not create commits.
- Follow the implementation plan exactly.
- After implementing, run the necessary build, test, and lint or validation commands locally.
- Fix issues found by validation before finishing when feasible.
- Summarize important validation results in stdout.

Selected context paths:
{_format_context_paths(context_paths)}

SPEC.md:

{spec_markdown}

Corrected IMPLEMENTATION_PLAN.md:

{implementation_plan_markdown}
"""


def build_review_prompt(
    spec_markdown: str,
    implementation_plan_markdown: str,
    context_paths: list[str],
    output_dir: str,
) -> str:
    comments_path = Path(output_dir) / "REVIEW_COMMENTS.json"
    summary_path = Path(output_dir) / "REVIEW_SUMMARY.md"
    return f"""You are Relay's Review phase.

Review the current working tree against SPEC.md and the corrected IMPLEMENTATION_PLAN.md.

You must produce two outputs:
1. A JSON array of review comments, emitted inside a fenced code block tagged exactly as:
```relay-review-comments
[{{"file": "src/example.py", "line": 1, "severity": "warning", "comment": "Example"}}]
```
2. A Markdown summary that follows the exact template below and is written to {summary_path.as_posix()}.

Also write the parsed JSON comments to {comments_path.as_posix()}.

Rules for review comments:
- Each item must have keys: file, line, severity, comment.
- severity must be exactly one of: error, warning, suggestion.
- Use null for file or line when a finding is not file-specific.
- Keep comments concrete and actionable.

Rules for the summary:
- Use the exact section headings shown below.
- The Verdict line must be exactly one of: PASS, FAIL, PASS_WITH_WARNINGS.

Summary template:

{REVIEW_SUMMARY_TEMPLATE}

Selected context paths:
{_format_context_paths(context_paths)}

SPEC.md:

{spec_markdown}

Corrected IMPLEMENTATION_PLAN.md:

{implementation_plan_markdown}
"""


def build_fix_prompt(
    review_comments: list[dict[str, object]],
    review_summary_markdown: str,
    spec_markdown: str,
    implementation_plan_markdown: str,
    context_paths: list[str],
) -> str:
    comments_json = json.dumps(review_comments, indent=2, sort_keys=True)
    return f"""You are Relay's Fix phase.

Resolve the review findings in the working tree, then re-run the relevant validation commands.

Requirements:
- Prioritize all error severity findings, then warnings, then suggestions.
- Keep changes aligned with SPEC.md and the corrected IMPLEMENTATION_PLAN.md.
- Do not commit changes.
- Summarize the fixes and validation results in stdout.

Selected context paths:
{_format_context_paths(context_paths)}

REVIEW_COMMENTS.json:

{comments_json}

REVIEW_SUMMARY.md:

{review_summary_markdown}

SPEC.md:

{spec_markdown}

Corrected IMPLEMENTATION_PLAN.md:

{implementation_plan_markdown}
"""

"""Validation warnings name references that will be empty at run time."""

from __future__ import annotations

import pytest

from relay.workflows.actions.language import (
    MAX_WARNINGS,
    load,
    referenced_secrets,
    workflow_warnings,
)

AGENT = "This agent step has no prompt or prompt-files, so the agent receives no instructions."


def warnings(text: str) -> list[tuple[str, str]]:
    found = workflow_warnings(load(text))
    assert all(item.context["severity"] == "warning" for item in found)
    return [(str(item.context["field"]), item.message) for item in found]


@pytest.mark.parametrize(
    "text, fixed, field, message",
    [
        (
            "jobs:\n  check:\n    steps:\n      - run: echo ${{ inputs.task }}\n",
            "on:\n  workflow_dispatch:\n    inputs:\n      task: {type: string}\n"
            "jobs:\n  check:\n    steps:\n      - run: echo ${{ inputs.task }}\n",
            "jobs.check.steps[0].run",
            "inputs.task is not a declared input. It will be empty at run time.",
        ),
        (
            "jobs:\n  check:\n    steps:\n      - run: echo ${{ steps.nope.outputs.x }}\n",
            "jobs:\n  check:\n    steps:\n      - id: nope\n        run: echo\n"
            "      - run: echo ${{ steps.nope.outputs.x }}\n",
            "jobs.check.steps[0].run",
            "steps.nope does not name an earlier step in this job. It will be empty at run time.",
        ),
        (
            "jobs:\n  b:\n    steps: [{run: echo}]\n"
            "  a:\n    steps:\n      - run: echo ${{ needs.b.outputs.x }}\n",
            "jobs:\n  b:\n    steps: [{run: echo}]\n"
            "  a:\n    needs: b\n    steps:\n      - run: echo ${{ needs.b.outputs.x }}\n",
            "jobs.a.steps[0].run",
            "needs.b is not listed in this job's needs. It will be empty at run time.",
        ),
        (
            "jobs:\n  ask:\n    steps:\n      - uses: relay/agent@v1\n"
            "        with: {agent: codex}\n",
            "jobs:\n  ask:\n    steps:\n      - uses: relay/agent@v1\n"
            "        with: {agent: codex, prompt: Review the change.}\n",
            "jobs.ask.steps[0]",
            AGENT,
        ),
    ],
)
def test_each_reference_without_a_value_is_a_warning_until_it_is_declared(
    text: str, fixed: str, field: str, message: str
) -> None:
    [warning] = workflow_warnings(load(text))
    assert warning.message == f"{field}: {message}"
    assert warning.context == {"field": field, "severity": "warning"}
    assert warnings(fixed) == []


def test_a_clean_source_has_no_warnings() -> None:
    text = (
        "on:\n"
        "  workflow_dispatch:\n    inputs:\n      task: {type: string}\n"
        "  workflow_call:\n    inputs:\n      depth: {type: number}\n"
        "jobs:\n"
        "  build:\n"
        "    outputs:\n      sha: ${{ steps.make.outputs.sha }}\n"
        "    steps:\n"
        "      - id: make\n        run: echo ${{ inputs.task }} ${{ inputs.DEPTH }}\n"
        "      - if: steps.make.outcome == 'success'\n"
        "        run: echo ${{ steps.MAKE.outputs.sha }} ${{ vars.X }} ${{ env.Y }}"
        " ${{ secrets.Z }} ${{ matrix.axis }}\n"
        "      - uses: relay/agent@v1\n"
        "        with:\n          agent: codex\n          prompt-files: prompts/review.md\n"
        "  publish:\n"
        "    needs: [build]\n"
        "    if: needs.build.result == 'success'\n"
        "    steps:\n"
        "      - run: echo ${{ needs.Build.outputs.sha }} ${{ toJSON(needs.*.result) }}"
        " ${{ inputs[matrix.key] }}\n"
    )
    assert warnings(text) == []


def test_bare_conditions_job_fields_and_later_steps_are_checked_in_source_order() -> None:
    text = (
        "jobs:\n"
        "  check:\n"
        "    if: needs.setup.result == 'success'\n"
        "    outputs:\n"
        "      first: ${{ steps.first.outputs.x }}\n"
        "      other: ${{ steps.other.outputs.x }}\n"
        "    steps:\n"
        "      - id: first\n"
        "        run: echo ${{ steps.first.outputs.x }} ${{ steps.first.outputs.y }}\n"
        "      - if: steps.later.outcome == 'success'\n"
        "        run: echo\n"
        "      - id: later\n"
        "        uses: relay/agent@v1\n"
        "        with: {agent: codex, prompt: ' '}\n"
    )
    assert warnings(text) == [
        (
            "jobs.check.if",
            "jobs.check.if: needs.setup is not listed in this job's needs. "
            "It will be empty at run time.",
        ),
        (
            "jobs.check.outputs.other",
            "jobs.check.outputs.other: steps.other does not name an earlier step in this job. "
            "It will be empty at run time.",
        ),
        # A step cannot read its own outputs, and one warning covers a repeated name.
        (
            "jobs.check.steps[0].run",
            "jobs.check.steps[0].run: steps.first does not name an earlier step in this job. "
            "It will be empty at run time.",
        ),
        (
            "jobs.check.steps[1].if",
            "jobs.check.steps[1].if: steps.later does not name an earlier step in this job. "
            "It will be empty at run time.",
        ),
        ("jobs.check.steps[2]", f"jobs.check.steps[2]: {AGENT}"),
    ]


def test_warnings_are_bounded_and_survive_deep_operator_chains() -> None:
    names = " ".join(f"${{{{ inputs.name{index} }}}}" for index in range(MAX_WARNINGS + 5))
    assert len(warnings(f"jobs:\n  check:\n    steps:\n      - run: echo {names}\n")) == (
        MAX_WARNINGS
    )
    # Left-nested chains pass the parser's depth limit, so the walk must not recurse.
    chain = " && ".join(["inputs.flag"] * 1_300)
    assert warnings(f"jobs:\n  check:\n    if: {chain}\n    steps: [{{run: echo}}]\n") == [
        (
            "jobs.check.if",
            "jobs.check.if: inputs.flag is not a declared input. It will be empty at run time.",
        )
    ]


def test_referenced_secrets_are_literal_names_per_job() -> None:
    document = load(
        "env:\n  SHARED: ${{ secrets.shared_token }}\n"
        "jobs:\n"
        "  build:\n"
        "    steps:\n      - run: echo ${{ secrets.GITHUB_TOKEN }} ${{ secrets[matrix.key] }}\n"
        "  deploy:\n"
        "    env:\n      KEY: ${{ secrets['Deploy_Key'] }}\n"
        "    steps: [{run: echo}]\n"
    )
    assert referenced_secrets(document) == {"SHARED_TOKEN", "GITHUB_TOKEN", "DEPLOY_KEY"}
    assert referenced_secrets(document, job="build") == {"SHARED_TOKEN", "GITHUB_TOKEN"}
    assert referenced_secrets(document, job="deploy") == {"SHARED_TOKEN", "DEPLOY_KEY"}


def test_unparsed_matrix_values_and_reusable_jobs_never_raise() -> None:
    # Include values are interpolated at launch but not expression-checked by load.
    text = (
        "jobs:\n"
        "  matrix:\n"
        "    timeout-minutes: 5\n"
        "    strategy:\n"
        "      matrix:\n"
        "        v: [1]\n"
        "        include:\n"
        "          - extra:\n"
        "              open: '${{ inputs.unclosed '\n"
        "              broken: '${{ inputs.a == }}'\n"
        "              note: '${{ inputs.note }}'\n"
        "    steps: [{run: echo}]\n"
        "  reuse:\n"
        "    uses: ./.relay/workflows/child.yaml\n"
        "    with:\n"
        "      value: ${{ needs.matrix.outputs.x }}\n"
    )
    assert warnings(text) == [
        (
            "jobs.matrix.strategy.matrix.include[0].extra.note",
            "jobs.matrix.strategy.matrix.include[0].extra.note: inputs.note is not a declared "
            "input. It will be empty at run time.",
        ),
        (
            "jobs.reuse.with.value",
            "jobs.reuse.with.value: needs.matrix is not listed in this job's needs. "
            "It will be empty at run time.",
        ),
    ]

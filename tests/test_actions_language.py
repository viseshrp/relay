"""Language contracts independent of provider accounts or owner state."""

from datetime import datetime, timezone

import pytest

from relay.errors import WorkflowValidationError
from relay.execution.triggers import occurrences, validate_schedule
from relay.workflows.actions.language import expand_matrix, load, resolve_inputs


def test_boolean_expression_cannot_silently_clear_an_explicit_agent_effort() -> None:
    from relay.workflows.actions.compiler import bind_agent

    step = load(
        "jobs: {work: {runs-on: self-hosted, steps: [{uses: relay/agent@v1, "
        "with: {agent: codex, model: m1, effort: '${{ true }}'}}]}}"
    ).value["jobs"]["work"]["steps"][0]
    with pytest.raises(WorkflowValidationError, match="exact provider value or null"):
        bind_agent(step, {})


@pytest.mark.parametrize("addition", ["permissions: read-all", "container: alpine", "services: {}"])
def test_platform_only_job_features_are_rejected(addition):
    with pytest.raises(WorkflowValidationError):
        load(
            f"jobs:\n  test:\n    runs-on: self-hosted\n    {addition}\n"
            "    steps: [{run: echo ready}]\n"
        )


@pytest.mark.parametrize(
    "source",
    [
        "jobs: {}\njobs: {}",
        "jobs: !custom {}",
        "jobs: &a {test: *a}",
        "jobs: {test: {<<: {runs-on: self-hosted}}}",
    ],
)
def test_duplicate_keys_tags_cycles_and_merges_are_rejected(source):
    with pytest.raises(WorkflowValidationError):
        load(source)


def test_field_contexts_are_checked_without_evaluating_or_fetching_secrets():
    with pytest.raises(WorkflowValidationError):
        load("jobs: {test: {runs-on: self-hosted, if: '${{ secrets.KEY }}', steps: [{run: echo}]}}")
    value = load(
        "jobs: {test: {runs-on: self-hosted, env: {permissions: yes}, "
        "steps: [{run: 'echo ${{ secrets.KEY }}'}]}}"
    )
    assert value.value["jobs"]["test"]["env"]["permissions"] == "yes"


def test_matrix_include_augments_original_combinations_then_appends_new_rows():
    assert expand_matrix(
        {
            "os": ["a", "b"],
            "include": [{"color": "green"}, {"os": "a", "color": "pink"}, {"os": "c"}],
            "exclude": [{"os": "b"}],
        }
    ) == [{"os": "a", "color": "pink"}, {"os": "c"}]


def test_typed_inputs_and_missing_defaults():
    source = {
        "on": {
            "workflow_call": {"inputs": {"flag": {"type": "boolean"}, "count": {"type": "number"}}}
        }
    }
    assert resolve_inputs(source, {}, event="workflow_call") == {"flag": False, "count": 0}
    with pytest.raises(WorkflowValidationError):
        resolve_inputs(source, {"flag": "false"}, event="workflow_call")


def test_dst_gap_advances_and_repeated_wall_time_fires_once():
    schedule = {"cron": "30 2 * * *", "timezone": "America/New_York"}
    result = occurrences(
        schedule,
        datetime(2026, 3, 8, tzinfo=timezone.utc),
        datetime(2026, 3, 9, tzinfo=timezone.utc),
    )
    assert [instant.hour for _, instant in result] == [7]
    repeated = occurrences(
        {"cron": "30 1 * * *", "timezone": "America/New_York"},
        datetime(2026, 11, 1, tzinfo=timezone.utc),
        datetime(2026, 11, 2, tzinfo=timezone.utc),
    )
    assert len(repeated) == 1
    with pytest.raises(WorkflowValidationError):
        validate_schedule({"cron": "* * * * *"})


def test_source_hashes_capture_executable_mode_as_well_as_bytes() -> None:
    import base64

    from relay.workflows.actions.compiler import sources_hashes

    content = base64.b64encode(b"echo ready\n").decode()
    ordinary = sources_hashes({".relay/actions/task/run.sh": "echo ready\n"})
    executable = sources_hashes({".relay/actions/task/run.sh": "\0asset:755:" + content})
    assert (
        ordinary["source:.relay/actions/task/run.sh"]
        == executable["source:.relay/actions/task/run.sh"]
    )
    assert (
        ordinary["mode:.relay/actions/task/run.sh"] != executable["mode:.relay/actions/task/run.sh"]
    )


@pytest.mark.parametrize(
    "field", ["name: 5", "description: false", "author: []", "branding: {color: black}"]
)
def test_action_metadata_rejects_invalid_field_types(field: str) -> None:
    from relay.workflows.actions.metadata import load_action

    source = "name: Local\ndescription: A local action\nruns: {using: node20, main: main.js}\n"
    key = field.split(":", 1)[0]
    source = "\n".join(line for line in source.splitlines() if not line.startswith(key + ":"))
    with pytest.raises(WorkflowValidationError):
        load_action(source + "\n" + field)


def test_local_action_missing_required_input_is_rejected_before_launch(project) -> None:
    from relay.workflows.actions.language import capture_sources

    project.write(
        ".relay/actions/required/action.yml",
        "name: Required\ndescription: Local\n"
        "inputs: {value: {description: Value, required: true}}\n"
        "runs: {using: node20, main: main.js}\n",
    )
    project.write(".relay/actions/required/main.js", "throw Error('never execute');")
    with pytest.raises(WorkflowValidationError, match="missing required"):
        capture_sources(
            load(
                "jobs: {main: {runs-on: self-hosted, steps: [{uses: ./.relay/actions/required}]}}"
            ),
            project.repository,
        )

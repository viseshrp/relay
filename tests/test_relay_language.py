"""Only syntax with a local Relay contract belongs in the public language."""

from io import StringIO
from typing import Any

import pytest
from ruamel.yaml import YAML

from relay.errors import WorkflowValidationError
from relay.workflows.actions.language import load, support_manifest
from relay.workflows.actions.metadata import load_action


def source(value: dict[str, Any]) -> str:
    stream = StringIO()
    YAML().dump(value, stream)
    return stream.getvalue()


def test_local_jobs_require_steps_and_have_no_runner_selector() -> None:
    assert load("jobs: {check: {steps: [{run: echo Ready}]}}").value["jobs"]["check"] == {
        "steps": [{"run": "echo Ready"}]
    }


def test_local_start_points_and_recovery_compile_without_changing_job_sources() -> None:
    from relay.workflows.actions.compiler import definition

    document = load(
        "recovery: {enabled: true, max_retries: 2}\n"
        "entrypoints: [{scope_path: root.check}]\n"
        "jobs: {check: {steps: [{run: echo Ready}]}}\n"
    )
    compiled = definition(document)
    assert compiled.recovery.enabled and compiled.recovery.max_retries == 2
    assert compiled.entrypoints[0].scope_path == "root.check"
    assert compiled.actions["jobs"] == document.value["jobs"]


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "n" * 257),
        ("run-name", "r" * 1001),
        ("recovery", {"enabled": True, "max_retries": 1000}),
        ("entrypoints", [{"scope_path": "root.missing"}]),
    ],
)
def test_editor_contract_bounds_are_validated(field: str, value: object) -> None:
    with pytest.raises(WorkflowValidationError):
        load(source({field: value, "jobs": {"check": {"steps": [{"run": "echo Ready"}]}}}))


@pytest.mark.parametrize(
    "selector",
    ["self-hosted", "ubuntu-latest", ["self-hosted"], {"labels": "local"}, "${{ host.os }}"],
)
def test_all_runner_selector_forms_are_removed(selector: object) -> None:
    with pytest.raises(WorkflowValidationError, match="runs-on: Unknown workflow field"):
        load(source({"jobs": {"check": {"runs-on": selector, "steps": [{"run": "echo"}]}}}))


@pytest.mark.parametrize(
    "field", ["permissions", "container", "services", "snapshot", "cancel-timeout-minutes"]
)
def test_hosted_job_fields_are_absent(field: str) -> None:
    with pytest.raises(WorkflowValidationError, match=f"{field}: Unknown workflow field"):
        load(source({"jobs": {"check": {field: {}, "steps": [{"run": "echo"}]}}}))


@pytest.mark.parametrize("value", [1, 2, "${{ inputs.count }}"])
def test_parallelism_field_is_removed_even_when_one(value: object) -> None:
    with pytest.raises(WorkflowValidationError, match="max-parallel: Unknown workflow field"):
        load(
            source(
                {
                    "jobs": {
                        "check": {
                            "strategy": {"matrix": {"target": ["docs"]}, "max-parallel": value},
                            "steps": [{"run": "echo"}],
                        }
                    }
                }
            )
        )


@pytest.mark.parametrize(
    "step",
    [
        {"run": "echo", "background": False},
        {"uses": "relay/agent@v1", "background": True},
        {"wait": "task"},
        {"wait-all": True},
        {"cancel": "task"},
        {"parallel": [{"run": "echo"}]},
    ],
)
def test_unimplemented_step_variants_fail_in_jobs_and_composites(step: dict[str, Any]) -> None:
    with pytest.raises(WorkflowValidationError):
        load(source({"jobs": {"check": {"steps": [step]}}}))
    with pytest.raises(WorkflowValidationError):
        load_action(
            source(
                {
                    "name": "Local",
                    "description": "Local",
                    "runs": {"using": "composite", "steps": [step]},
                }
            )
        )


@pytest.mark.parametrize(
    "trigger",
    [
        {"push": {"unknown": True}},
        {"workflow_run": {"types": ["completed"]}},
        {"workflow_dispatch": {"permissions": "write-all"}},
        {"schedule": [{"cron": "*/5 * * * *", "branches": ["main"]}]},
        {"repository_dispatch": {"paths": ["**"]}},
    ],
)
def test_trigger_configuration_is_strict(trigger: dict[str, Any]) -> None:
    with pytest.raises(WorkflowValidationError, match="Unknown workflow field"):
        load(source({"on": trigger, "jobs": {"check": {"steps": [{"run": "echo"}]}}}))


@pytest.mark.parametrize("value", [True, False])
def test_environment_deployment_flag_is_removed(value: bool) -> None:
    with pytest.raises(WorkflowValidationError, match="deployment: Unknown workflow field"):
        load(
            source(
                {
                    "jobs": {
                        "check": {
                            "environment": {"name": "local", "deployment": value},
                            "steps": [{"run": "echo"}],
                        }
                    }
                }
            )
        )


@pytest.mark.parametrize(
    "expression",
    [
        "github.sha",
        "runner.os",
        "relay.token",
        "relay.server_url",
        "relay.repository_owner",
        "host.environment",
        "host.tool_cache",
        "host['debug']",
        "strategy['max-parallel']",
    ],
)
def test_platform_expression_roots_and_placeholders_are_removed(expression: str) -> None:
    with pytest.raises(WorkflowValidationError, match="Unrecognized"):
        load(source({"jobs": {"check": {"steps": [{"run": f"echo ${{{{ {expression} }}}}"}]}}}))


@pytest.mark.parametrize(
    "metadata",
    [
        {"branding": {"icon": "activity", "color": "blue"}},
        {"author": "Owner"},
        {"outputs": {"result": {"description": "Result", "value": "ignored"}}},
        {"runs": {"using": "node20", "main": "main.js", "post-if": "always()"}},
    ],
)
def test_ignored_action_metadata_is_removed(metadata: dict[str, Any]) -> None:
    with pytest.raises(WorkflowValidationError):
        load_action(
            source(
                {
                    "name": "Local",
                    "description": "Local",
                    "runs": {"using": "node20", "main": "main.js"},
                    **metadata,
                }
            )
        )


def test_manifest_contains_only_local_reachable_definitions_and_facts() -> None:
    manifest = support_manifest()
    assert manifest["dialect"] == "relay-local-1"
    assert "relay" in manifest["contexts"] and "host" in manifest["contexts"]
    assert "github" not in manifest["contexts"] and "runner" not in manifest["contexts"]
    assert set(manifest["definitions"]["on-mapping"]["mapping"]["properties"]) == set(
        manifest["events"]
    )
    assert (
        not {
            "runs-on",
            "container",
            "services",
            "permissions",
            "workflow-root-strict",
            "wait-step",
            "pull-request",
        }
        & manifest["definitions"].keys()
    )
    assert manifest["context_properties"]["host"] == ["arch", "name", "os", "temp"]


@pytest.mark.parametrize(
    "header",
    [
        "on: schedule",
        "on: {schedule: []}",
        "on: {workflow_dispatch: {inputs: {task: {type: string, options: [unused]}}}}",
        "on: {workflow_call: {inputs: {task: {type: string, default: '${{ inputs.task }}'}}}}",
    ],
)
def test_configuration_with_no_resolvable_local_effect_is_rejected(header: str) -> None:
    with pytest.raises(WorkflowValidationError):
        load(header + "\njobs: {check: {steps: [{run: echo}]}}")


def test_matrix_policy_requires_a_matrix() -> None:
    with pytest.raises(WorkflowValidationError, match="matrix: Required field"):
        load("jobs: {check: {strategy: {fail-fast: false}, steps: [{run: echo}]}}")


@pytest.mark.parametrize(
    "expression", ["relay.run_id", "format('{0}', relay.attempt_number)", "toJSON(relay.workspace)"]
)
def test_run_name_cannot_use_unallocated_runtime_facts(expression: str) -> None:
    with pytest.raises(WorkflowValidationError, match="not available before launch"):
        load(
            source(
                {
                    "run-name": f"${{{{ {expression} }}}}",
                    "jobs": {"check": {"steps": [{"run": "echo"}]}},
                }
            )
        )


def test_local_filters_and_queue_enums_have_exact_semantics() -> None:
    document = load(
        "on: {workflow_run: {workflows: Check}, repository_dispatch: {types: [rebuild]}}\n"
        "jobs: {check: {steps: [{run: echo}]}}"
    )
    assert document.value["on"]["workflow_run"]["workflows"] == ["Check"]
    assert document.value["on"]["repository_dispatch"]["types"] == ["rebuild"]
    for header in (
        "concurrency: {group: work, queue: ignored}",
        "on: {workflow_run: {conclusions: [unknown]}}",
    ):
        with pytest.raises(WorkflowValidationError, match="Expected one of"):
            load(header + "\njobs: {check: {steps: [{run: echo}]}}")


@pytest.mark.parametrize(
    "options",
    ['["Approve","Reject"]', '["", "Approve"]', '["Same","Same"]', "[1]", '{"Approve":true}'],
)
def test_human_wait_answer_buttons_are_bounded(options: str) -> None:
    value = {
        "jobs": {
            "main": {
                "steps": [
                    {
                        "uses": "relay/human-wait@v1",
                        "with": {"prompt": "Continue?", "options": options},
                    }
                ]
            }
        }
    }
    if options == '["Approve","Reject"]':
        assert load(source(value)).value["jobs"]
    else:
        with pytest.raises(WorkflowValidationError, match="answer strings"):
            load(source(value))

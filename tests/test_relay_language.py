"""Only syntax with a local Relay contract belongs in the public language."""

from io import StringIO
import re
from typing import Any

import pytest
from ruamel.yaml import YAML

from relay.errors import WorkflowValidationError
from relay.workflows.actions.language import load, support_manifest, workflow_diagnostics
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


def test_manifest_describes_builtin_versions() -> None:
    manifest = support_manifest()
    versions = manifest["builtin_versions"]
    assert len(versions) == 11
    assert all(version["status"] == "current" for version in versions.values())
    assert all(
        reference == f"relay/{version['name']}@v{version['major']}"
        for reference, version in versions.items()
    )
    assert manifest["builtins"] == sorted(versions)
    assert set(manifest["builtin_inputs"]) == set(versions)


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
    "options, error",
    [
        ('["Approve","Reject"]', None),
        ("Approve\nReject\n", None),
        ('["", "Approve"]', "answer strings"),
        ('["Same","Same"]', "answer strings"),
        ("Same\nSame", "answer strings"),
        ("\n".join(f"Answer {index}" for index in range(11)), "answer strings"),
        ("[1]", "options: Write a JSON array of strings or one value per line."),
    ],
)
def test_human_wait_answer_buttons_are_bounded(options: str, error: str | None) -> None:
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
    if error is None:
        assert load(source(value)).value["jobs"]
    else:
        with pytest.raises(WorkflowValidationError, match=re.escape(error)):
            load(source(value))


def _properties(definition: str) -> list[str]:
    return list(support_manifest()["definitions"][definition]["mapping"]["properties"])


def test_closest_suggests_one_nearby_name() -> None:
    from relay.workflows.actions.suggest import closest

    agent_inputs = support_manifest()["builtin_inputs"]["relay/agent@v1"]["allowed"]
    assert closest("stpes", _properties("job-factory")) == "steps"
    assert closest("rnu", _properties("run-step")) == "run"
    assert closest("need", _properties("job-factory")) == "needs"
    assert closest("Jobs", ["jobs"]) == "jobs"
    assert closest("prmpt", agent_inputs) == "prompt"
    assert closest("xyz", _properties("job-factory")) is None
    assert closest("agent", _properties("regular-step")) is None


@pytest.mark.parametrize(
    "text, expected, suggested",
    [
        (
            "Jobs: {a: {steps: [{run: echo}]}}\n",
            "workflow.Jobs: Unknown workflow field. Did you mean jobs?",
            "workflow.jobs",
        ),
        (
            "jobs:\n  a:\n    need: b\n    steps: [{run: echo}]\n  b:\n    steps: [{run: echo}]\n",
            "workflow.jobs.a.need: Unknown workflow field. Did you mean needs?",
            "workflow.jobs.a.needs",
        ),
        (
            "jobs:\n  a:\n    steps:\n      - rnu: echo\n",
            "workflow.jobs.a.steps[0].rnu: Unknown workflow field. Did you mean run?",
            "workflow.jobs.a.steps[0].run",
        ),
        (
            "jobs:\n  a:\n    stpes:\n      - run: echo\n",
            "workflow.jobs.a.stpes: Unknown workflow field. Did you mean steps?",
            "workflow.jobs.a.steps",
        ),
    ],
)
def test_unknown_keys_suggest_the_nearest_field(text: str, expected: str, suggested: str) -> None:
    messages = [issue.message for issue in workflow_diagnostics(text)]
    assert [message for message in messages if expected in message] == [expected]
    assert f"{suggested}: Required field is missing." not in messages
    with pytest.raises(WorkflowValidationError, match=re.escape(expected.partition(": ")[2])):
        load(text)


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "on: {workflow_dispatch: {inputs: {x: {type: text}}}}\n"
            "jobs: {a: {steps: [{run: echo}]}}\n",
            "Expected one of string, boolean, number, environment, choice.",
        ),
        ("jobs: {a: {steps: [{uses: relay/agent}]}}\n", "Did you mean relay/agent@v1?"),
        ("jobs: {a: {steps: [{uses: relay/agent@v9}]}}\n", "Did you mean relay/agent@v1?"),
        (
            "jobs: {a: {steps: [{uses: someone/thing@v1}]}}\n",
            "Use one of relay/agent@v1, relay/cache@v1,",
        ),
        (
            "jobs: {a: {steps: [{run: echo, if: 'inputs.x == \"y\"'}]}}\n",
            "Strings use single quotes, for example 'main'.",
        ),
        (
            "jobs: {a: {steps: [{run: echo, uses: relay/agent@v1}]}}\n",
            "workflow.jobs.a.steps[0]: A step needs either run or uses, not both.",
        ),
        (
            "jobs: {a: {steps: [{name: Nothing}]}}\n",
            "workflow.jobs.a.steps[0]: A step needs run (a script) or uses (an action).",
        ),
    ],
)
def test_errors_list_the_valid_choices(text: str, expected: str) -> None:
    issues = workflow_diagnostics(text)
    assert any(expected in issue.message for issue in issues), [i.message for i in issues]
    if "A step needs" in expected:
        assert [issue.message for issue in issues] == [expected]
    with pytest.raises(WorkflowValidationError, match=re.escape(expected)):
        load(text)


def test_someone_elses_action_lists_every_current_builtin() -> None:
    with pytest.raises(WorkflowValidationError) as caught:
        load("jobs: {a: {steps: [{uses: someone/thing@v1}]}}\n")
    builtins = ", ".join(support_manifest()["builtins"])
    assert caught.value.message == (
        "jobs.a.steps[0].uses: Only frozen local and versioned relay actions are supported. "
        f"Use one of {builtins}, or a local action under ./.relay/actions/."
    )


@pytest.mark.parametrize(
    "text, line",
    [
        ("jobs:\n  a:\n    steps: [{run: echo}]\n  a:\n    steps: [{run: echo}]\n", "4"),
        ("on:\n  push: {}\n  pull_request:\njobs: {a: {steps: [{run: echo}]}}\n", "3"),
        (
            "jobs:\n  a:\n    steps:\n      - run: echo\n      - uses: relay/loop@v1\n"
            "        with:\n          max-iterations: 2\n",
            "5",
        ),
        (
            "jobs:\n  a:\n    strategy:\n      matrix:\n        v: '${{ inputs.v }}'\n"
            "    steps: [{run: echo}]\n",
            "5",
        ),
    ],
)
def test_every_diagnostic_has_a_line(text: str, line: str) -> None:
    issues = workflow_diagnostics(text)
    assert issues
    assert [issue.context["line"] for issue in issues] == [line] * len(issues)


@pytest.mark.parametrize(
    "written, hint",
    [
        ("github.sha", "Use relay.sha."),
        ("github.ref", "Use relay.ref."),
        ("github.ref_name", "Use relay.ref_name."),
        ("github.ref_type", "Use relay.ref_type."),
        ("github.event", "Use relay.event."),
        ("github.event.pull_request.title", "Use relay.event."),
        ("github.event_name", "Use relay.event_name."),
        ("github.event.inputs.task", "Use inputs.task."),
        ("github.workspace", "Use relay.workspace."),
        ("github.repository", "Use relay.repository."),
        ("github.actor", "Use relay.actor."),
        ("github.triggering_actor", "Use relay.actor."),
        ("github.workflow", "Use relay.workflow."),
        ("github.workflow_ref", "Use relay.workflow_ref."),
        ("github.run_id", "Use relay.run_id."),
        ("github.run_number", "Use relay.run_number."),
        ("github.run_attempt", "Use relay.attempt_number."),
        ("github.job", "Use relay.job."),
        ("github.action", "Use relay.action."),
        ("github.action_path", "Use relay.action_path."),
        ("runner.os", "Use host.os."),
        ("runner.arch", "Use host.arch."),
        ("runner.name", "Use host.name."),
        ("runner.temp", "Use host.temp."),
        ("github.token", "Relay does not issue a token; bind a secret instead."),
        (
            "github.server_url",
            "Use relay, which provides action, action_path, actor, attempt_number, chain, "
            "delivery_id, event, event_name, job, ref, ref_name, ref_type, repository, run_id, "
            "run_number, scheduled_at, sha, workflow, workflow_ref, workspace.",
        ),
        ("runner.tool_cache", "Use host, which provides arch, name, os, temp."),
    ],
)
def test_platform_names_point_to_relay_names(written: str, hint: str) -> None:
    root = written.partition(".")[0]
    with pytest.raises(WorkflowValidationError) as caught:
        load(source({"jobs": {"a": {"steps": [{"run": f"echo ${{{{ {written} }}}}"}]}}}))
    assert caught.value.message == (
        f"workflow.jobs.a.steps[0].run: Unrecognized named-value: {root}. {hint}"
    )


FILE_VARIABLE_MESSAGES = {
    "GITHUB_OUTPUT": "Write step outputs to $RELAY_OUTPUT.",
    "GITHUB_ENV": "Set variables for later steps in $RELAY_ENV.",
    "GITHUB_PATH": "Add search paths in $RELAY_PATH.",
    "GITHUB_STATE": "Save action state in $RELAY_STATE.",
    "GITHUB_STEP_SUMMARY": "Write the step summary to $RELAY_STEP_SUMMARY.",
}


@pytest.mark.parametrize("name", list(FILE_VARIABLE_MESSAGES))
@pytest.mark.parametrize(
    "script",
    [
        'echo "value=1" >> "${name}"',
        '"value=1" | Out-File -Append $env:{name}',
        "python -c \"import os; open(os.environ['{name}'], 'a')\"",
    ],
    ids=["bash", "pwsh", "python"],
)
def test_unknown_file_variables_are_rejected(name: str, script: str) -> None:
    run = script.replace("{name}", name)
    with pytest.raises(WorkflowValidationError) as caught:
        load(source({"jobs": {"a": {"steps": [{"run": "echo"}, {"run": run}]}}}))
    assert caught.value.message == (
        f"jobs.a.steps[1].run: {name} is not a Relay variable. {FILE_VARIABLE_MESSAGES[name]}"
    )
    assert any(
        issue.message == caught.value.message
        for issue in workflow_diagnostics(
            source({"jobs": {"a": {"steps": [{"run": "echo"}, {"run": run}]}}})
        )
    )


def test_relay_file_variables_and_other_github_names_validate() -> None:
    assert load(
        source(
            {
                "jobs": {
                    "a": {
                        "steps": [
                            {"run": 'echo "value=1" >> "$RELAY_OUTPUT"'},
                            {"run": "echo $GITHUB_TOKEN $GITHUB_OUTPUTS"},
                        ]
                    }
                }
            }
        )
    )
    with pytest.raises(WorkflowValidationError, match="GITHUB_ENV is not a Relay variable"):
        load_action(
            source(
                {
                    "name": "Local",
                    "description": "Local",
                    "runs": {
                        "using": "composite",
                        "steps": [{"run": 'echo "A=1" >> "$GITHUB_ENV"', "shell": "bash"}],
                    },
                }
            )
        )


@pytest.mark.parametrize(
    "reference, guidance",
    [
        (
            "actions/checkout@v4",
            "Remove this step: jobs already run in a working copy of this repository.",
        ),
        (
            "actions/setup-python@v5",
            "Remove this step and use the tool installed on this computer.",
        ),
        (
            "actions/upload-artifact@v4",
            "Use relay/upload-artifact@v1 with the same name, path, and retention-days inputs.",
        ),
        (
            "actions/download-artifact@v4",
            "Use relay/download-artifact@v1 with the same name and path inputs.",
        ),
        (
            "actions/cache@v4",
            "Use relay/cache@v1 with the same key, path, and restore-keys inputs.",
        ),
        (
            "actions/cache/restore@v4",
            "Use relay/restore-cache@v1 with the same key, path, and restore-keys inputs.",
        ),
        ("actions/cache/save@v4", "Use relay/save-cache@v1 with the same key and path inputs."),
        (
            "docker://alpine:3.20",
            "Run the program with a run step or relay/command@v1 instead of a container image.",
        ),
        (
            "./.github/actions/setup",
            "Move the action to ./.relay/actions/setup and use that path.",
        ),
    ],
)
def test_common_actions_get_specific_guidance(reference: str, guidance: str) -> None:
    with pytest.raises(WorkflowValidationError) as caught:
        load(source({"jobs": {"a": {"steps": [{"uses": reference}]}}}))
    assert caught.value.message == (
        "jobs.a.steps[0].uses: Only frozen local and versioned relay actions are supported. "
        + guidance
    )


def test_each_rejected_step_reports_its_own_index() -> None:
    text = (
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
    )
    issues = workflow_diagnostics(text)
    assert [(issue.message.partition(":")[0], issue.context["line"]) for issue in issues] == [
        ("jobs.a.steps[0].uses", "4"),
        ("jobs.a.steps[1].uses", "5"),
    ]


def test_a_step_written_as_text_asks_for_a_mapping() -> None:
    text = "jobs:\n  a:\n    steps:\n      - echo Ready\n"
    issues = workflow_diagnostics(text)
    assert [(issue.message, issue.context["line"]) for issue in issues] == [
        ("workflow.jobs.a.steps[0]: Expected a mapping.", "4")
    ]
    with pytest.raises(WorkflowValidationError, match="Expected a mapping"):
        load(text)


EVENTS_SENTENCE = (
    "Relay supports workflow_dispatch, workflow_call, schedule, push, repository_dispatch, "
    "and workflow_run. Pull request and other hosted events have no local equivalent."
)


@pytest.mark.parametrize(
    "header, line",
    [
        ("on: pull_request\n", "1"),
        ("on:\n  - push\n  - pull_request\n", "3"),
        ("on:\n  push: {}\n  pull_request:\n", "3"),
        ("on:\n  push: {}\n  pull_request: {branches: [main]}\n", "3"),
    ],
    ids=["scalar", "list", "mapping", "configured-mapping"],
)
def test_unsupported_events_share_one_message(header: str, line: str) -> None:
    text = header + "jobs: {a: {steps: [{run: echo}]}}\n"
    issues = workflow_diagnostics(text)
    assert len(issues) == 1
    assert issues[0].message.endswith(EVENTS_SENTENCE)
    assert issues[0].context["line"] == line
    with pytest.raises(WorkflowValidationError, match=re.escape(EVENTS_SENTENCE)):
        load(text)


def test_contract_check_rejects_an_event_without_an_adapter() -> None:
    """The contract check guards events even if the schema ever admits a new one."""
    from relay.workflows.actions.language import _validate_contracts

    workflow = {"on": {"pull_request": {}}, "jobs": {"a": {"steps": [{"run": "echo"}]}}}
    with pytest.raises(WorkflowValidationError) as caught:
        _validate_contracts(workflow)
    assert caught.value.message == (
        f"on.pull_request: This event has no local Relay adapter. {EVENTS_SENTENCE}"
    )
    assert caught.value.context == {"field": "on.pull_request", "feature": "unsupported"}


def test_expression_axis_explains_the_whole_matrix_form() -> None:
    text = (
        "jobs:\n  a:\n    strategy:\n      matrix:\n"
        '        v: ${{ fromJSON(\'["a","b"]\') }}\n    steps: [{run: echo}]\n'
    )
    with pytest.raises(WorkflowValidationError) as caught:
        load(text)
    assert caught.value.message == (
        "jobs.a.strategy.matrix.v: A matrix axis must be a nonempty sequence. To build the "
        "matrix from an expression, set the whole matrix: matrix: ${{ fromJSON(...) }}."
    )
    with pytest.raises(WorkflowValidationError) as plain:
        load("jobs: {a: {strategy: {matrix: {v: []}}, steps: [{run: echo}]}}")
    assert plain.value.message == (
        "jobs.a.strategy.matrix.v: A matrix axis must be a nonempty sequence."
    )


@pytest.mark.parametrize(
    "uses, field, line",
    [
        ("relay/agent@v1", "agents: [codex, claude]", "6"),
        ("relay/command@v1", "argv: [git, status]", "6"),
        ("relay/human-wait@v1", "options: [yes, no]", "6"),
    ],
)
def test_with_lists_explain_the_accepted_forms(uses: str, field: str, line: str) -> None:
    extra = "\n          prompt: Go?" if uses == "relay/human-wait@v1" else ""
    text = (
        f"jobs:\n  ask:\n    steps:\n      - uses: {uses}\n        with:\n"
        f"          {field}{extra}\n"
    )
    name = field.partition(":")[0]
    expected = (
        f"workflow.jobs.ask.steps[0].with.{name}: Expected a scalar string. "
        'Write a list as one value per line under "|", or as a JSON array string.'
    )
    issues = workflow_diagnostics(text)
    assert [(issue.message, issue.context["line"]) for issue in issues] == [(expected, line)]
    with pytest.raises(WorkflowValidationError, match=re.escape(expected.partition(": ")[2])):
        load(text)


def test_lists_outside_with_keep_the_plain_message() -> None:
    issues = workflow_diagnostics("jobs: {main: {steps: [{run: [echo]}]}}\n")
    assert [issue.message for issue in issues] == [
        "workflow.jobs.main.steps[0].run: Expected a scalar string."
    ]

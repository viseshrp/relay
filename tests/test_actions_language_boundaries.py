"""Public YAML and input boundaries fail before any execution or credentials."""

from pathlib import Path

import pytest

from relay.errors import WorkflowValidationError
from relay.workflows.actions.language import (
    capture_sources,
    expand_matrix,
    load,
    resolve_inputs,
    source_bytes,
)
from tests.support import RelayProject

BASE = "jobs: {main: {steps: [{run: echo ready}]}}\n"


@pytest.mark.parametrize(
    "source,reason",
    [
        ("jobs: {}", "at least one"),
        ("jobs: {bad.id: {steps: [{run: echo}]}}", "identifier"),
        (
            "jobs: {main: {needs: missing, steps: [{run: echo}]}}",
            "dependency",
        ),
        (
            "jobs: {main: {needs: [main, main], steps: [{run: echo}]}}",
            "dependency",
        ),
        ("jobs: {main: {needs: main, steps: [{run: echo}]}}", "cycle"),
        ("jobs: {main: {runs-on: ubuntu-latest, steps: [{run: echo}]}}", "Unknown workflow field"),
        ("jobs: {main: {runs-on: [self-hosted], steps: [{run: echo}]}}", "Unknown workflow field"),
        ("jobs: {main: {steps: []}}", "ordered steps"),
        ("jobs: {main: {steps: [{id: bad.id, run: echo}]}}", "step id"),
        (
            "jobs: {main: {steps: [{id: a, run: echo}, {id: a, run: echo}]}}",
            "step id",
        ),
        (
            "jobs: {main: {steps: [{uses: actions/checkout@v4}]}}",
            "frozen local",
        ),
        ("jobs: {main: {uses: owner/repo/workflow.yml@main}}", "static local"),
        (
            "jobs: {main: {timeout-minutes: 0, steps: [{run: echo}]}}",
            "positive",
        ),
        (
            "jobs: {main: {steps: [{run: echo, timeout-minutes: -1}]}}",
            "positive",
        ),
        (
            "jobs: {main: {strategy: {max-parallel: 2}, steps: [{run: echo}]}}",
            "Unknown workflow field",
        ),
        (
            "concurrency: {group: same, queue: max, cancel-in-progress: true}\n" + BASE,
            "cannot cancel",
        ),
        ("on: pull_request\n" + BASE, "Expected one of"),
        (
            "on: {workflow_run: {workflows: [Upstream], types: [requested]}}\n" + BASE,
            "Unknown workflow field",
        ),
        ("on: {push: {branches: [main], branches-ignore: [other]}}\n" + BASE, "mutually exclusive"),
        ("on: {push: {paths: ['!private/**']}}\n" + BASE, "positive pattern"),
        ("on: {workflow_dispatch: {inputs: {mode: {type: choice}}}}\n" + BASE, "require options"),
        ("on: {workflow_dispatch: {inputs: {bad.id: {type: string}}}}\n" + BASE, "identifier"),
        (
            "on: {workflow_dispatch: {inputs: {enabled: {type: boolean, default: yes}}}}\n" + BASE,
            "boolean",
        ),
        ("defaults: {run: {shell: '${{ secrets.SHELL }}'}}\n" + BASE, "Expressions"),
        (
            "jobs: {main: {steps: [{run: echo, unknown: true}]}}",
            "Unknown workflow field",
        ),
        (
            "jobs: {main: {steps: [{run: echo, continue-on-error: yes}]}}",
            "boolean",
        ),
        (
            "jobs: {main: {steps: [{run: echo, timeout-minutes: .inf}]}}",
            "finite number",
        ),
        ("jobs: {main: {steps: [{run: [echo]}]}}", "scalar string"),
    ],
)
def test_invalid_public_workflows_report_the_field_and_reason(source: str, reason: str) -> None:
    with pytest.raises(WorkflowValidationError, match=reason) as caught:
        load(source)
    assert caught.value.context.get("field")
    assert int(caught.value.context["line"]) >= 1


@pytest.mark.parametrize(
    "matrix",
    [
        {"axis": []},
        {"axis": "value"},
        {"axis": list(range(257))},
        {"include": {}},
        {"exclude": {}},
        {"include": [1]},
        {"exclude": [1]},
        {"axis": [1], "exclude": [{"axis": 1}]},
        {"include": [{}] * 257},
    ],
)
def test_invalid_matrix_shapes_and_expansion_bounds_are_rejected(matrix: dict[str, object]) -> None:
    with pytest.raises(WorkflowValidationError):
        expand_matrix(matrix)


@pytest.mark.parametrize(
    "kind,value,extra,reason",
    [
        ("boolean", "true", {}, "boolean"),
        ("number", True, {}, "finite number"),
        ("number", float("inf"), {}, "finite number"),
        ("number", "2", {}, "finite number"),
        ("string", 2, {}, "string"),
        ("choice", "wrong", {"options": ["right"]}, "declared option"),
        ("environment", "missing", {}, "configured environment"),
        ("string", "x" * 65536, {}, "65535 bytes"),
    ],
    ids=[
        "boolean-string",
        "number-boolean",
        "number-infinity",
        "number-string",
        "string-number",
        "choice-unknown",
        "environment-unknown",
        "string-oversized",
    ],
)
def test_launch_input_types_and_payload_bounds(
    kind: str, value: object, extra: dict[str, object], reason: str
) -> None:
    workflow = {"on": {"workflow_dispatch": {"inputs": {"value": {"type": kind, **extra}}}}}
    with pytest.raises(WorkflowValidationError, match=reason):
        resolve_inputs(workflow, {"value": value}, environments=["prod"])


def test_required_unknown_and_defaulted_launch_inputs() -> None:
    workflow = {
        "on": {"workflow_dispatch": {"inputs": {"value": {"type": "string", "required": True}}}}
    }
    with pytest.raises(WorkflowValidationError, match="Unknown input"):
        resolve_inputs(workflow, {"other": "x"})
    with pytest.raises(WorkflowValidationError, match="Required input"):
        resolve_inputs(workflow, {})
    assert resolve_inputs(workflow, {"value": ""}) == {"value": ""}
    workflow["on"]["workflow_dispatch"]["inputs"]["value"]["default"] = "fallback"
    assert resolve_inputs(workflow, {}) == {"value": "fallback"}


def test_yaml_resource_bounds_and_syntax_diagnostics() -> None:
    for source, reason in [
        ("#" * 1048577, "1 MiB"),
        ("jobs: [", "Invalid YAML"),
        ("{1: value}", "keys must be strings"),
        ("version: 1\nnodes: {}", "jobs mapping"),
        ("a: " + "[" * 52 + "value" + "]" * 52, "depth limit"),
        ("a: &a [value]\nb: [" + ", ".join(["*a"] * 101) + "]", "alias limit"),
        ("a: [" + ", ".join(["value"] * 10001) + "]", "node or depth"),
        (
            "on: {workflow_dispatch: {inputs: {"
            + ", ".join(f"v{i}: {{type: string}}" for i in range(26))
            + "}}}\n"
            + BASE,
            "At most 25",
        ),
    ]:
        with pytest.raises(WorkflowValidationError, match=reason):
            load(source)


def test_frozen_local_references_require_callable_utf8_sources(project: RelayProject) -> None:
    caller = load("jobs: {call: {uses: ./.relay/workflows/child.yaml}}")
    path = project.relay_root / "workflows/child.yaml"
    for data, reason in [(None, "missing"), (b"\xff", "UTF-8"), (BASE.encode(), "workflow_call")]:
        if data is not None:
            path.write_bytes(data)
        with pytest.raises(WorkflowValidationError, match=reason):
            capture_sources(caller, project.repository)
    project.write_workflow(
        "child", "on: workflow_call\njobs: {call: {uses: ./.relay/workflows/child.yaml}}"
    )
    with pytest.raises(WorkflowValidationError, match="cycle"):
        capture_sources(caller, project.repository)
    for reference, reason in (
        ("./missing", "frozen local"),
        ("./.relay/actions/missing", "directory is missing"),
    ):
        with pytest.raises(WorkflowValidationError, match=reason):
            capture_sources(
                load(f"jobs: {{a: {{steps: [{{uses: {reference}}}]}}}}"),
                project.repository,
            )


def test_frozen_asset_decoding_preserves_bytes_and_modes() -> None:
    assert source_bytes("\0binary:/w==") == (b"\xff", 0o600)
    assert source_bytes("\0asset:755:/w==") == (b"\xff", 0o755)
    assert source_bytes("é\r\n") == ("é\r\n".encode(), 0o600)


def test_reusable_depth_and_unique_source_limits(project: RelayProject) -> None:
    for index in range(12):
        project.write(
            f".relay/workflows/level{index}.yaml",
            f"on: workflow_call\njobs: {{call: "
            f"{{uses: ./.relay/workflows/level{index + 1}.yaml}}}}\n"
            if index < 11
            else "on: workflow_call\n" + BASE,
        )
    with pytest.raises(WorkflowValidationError, match="10 levels"):
        capture_sources(
            load("jobs: {call: {uses: ./.relay/workflows/level0.yaml}}"), project.repository
        )
    for index in range(51):
        project.write(f".relay/workflows/child{index}.yaml", "on: workflow_call\n" + BASE)
    jobs = ", ".join(f"call{i}: {{uses: ./.relay/workflows/child{i}.yaml}}" for i in range(51))
    with pytest.raises(WorkflowValidationError, match="50 unique"):
        capture_sources(load("jobs: {" + jobs + "}"), project.repository)


def test_captured_source_byte_bounds_and_shared_references(project: RelayProject) -> None:
    project.write(".relay/workflows/child.yaml", "on: workflow_call\n" + BASE)
    shared = load(
        "jobs: {a: {uses: ./.relay/workflows/child.yaml}, b: {uses: ./.relay/workflows/child.yaml}}"
    )
    assert list(capture_sources(shared, project.repository)) == [".relay/workflows/child.yaml"]
    project.write(".relay/workflows/child.yaml", "#" * 1048577)
    with pytest.raises(WorkflowValidationError, match="1 MiB"):
        capture_sources(shared, project.repository)
    for index in range(11):
        project.write(
            f".relay/workflows/large{index}.yaml", "on: workflow_call\n" + BASE + "#" * 1000000
        )
    jobs = ", ".join(f"call{i}: {{uses: ./.relay/workflows/large{i}.yaml}}" for i in range(11))
    with pytest.raises(WorkflowValidationError, match="10 MiB"):
        capture_sources(load("jobs: {" + jobs + "}"), project.repository)


def test_local_action_scripts_and_binary_assets_are_frozen_before_launch(
    project: RelayProject,
) -> None:
    project.write(
        ".relay/actions/task/action.yaml",
        "name: Task\ndescription: Assets\nruns: {using: node20, main: main.js, post: post.js}\n",
    )
    project.write(".relay/actions/task/main.js", "main bytes\n")
    project.write(".relay/actions/task/post.js", "post bytes\n")
    binary = project.relay_root / "actions/task/asset.bin"
    binary.write_bytes(b"\x00\xff\r\n")
    caller = load("jobs: {main: {steps: [{uses: ./.relay/actions/task}]}}")
    sources = capture_sources(caller, project.repository)
    assert source_bytes(sources[".relay/actions/task/asset.bin"])[0] == b"\x00\xff\r\n"
    assert sources[".relay/actions/task/main.js"] == "main bytes\n"
    assert sources[".relay/actions/task/post.js"] == "post bytes\n"
    (project.relay_root / "actions/task/post.js").unlink()
    with pytest.raises(WorkflowValidationError, match="script is missing"):
        capture_sources(caller, project.repository)


def test_unreadable_action_asset_fails_capture(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    from relay.workflows.actions.language import capture_script

    path = project.write("asset", "bytes")
    original = Path.read_bytes

    def unreadable(self: Path) -> bytes:
        if self == path:
            message = "Disposable unreadable file"
            raise OSError(message)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    with pytest.raises(WorkflowValidationError, match="could not be read"):
        capture_script(path, project.repository, {})

"""Serial local jobs and ordered steps, using Relay's existing attempt machinery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
from typing import Any, cast
import uuid

from relay.errors import NodeExecutionError, RelayError
from relay.execution.action_commands import ActionRuntime, CommandLog
from relay.execution.action_files import (
    MAX_FILE,
    atomic_state,
    consume,
    file_text,
    key_values,
    read_state,
    shell_script,
    step_files,
)
from relay.execution.dispatch import dispatch_node
from relay.execution.masking import redactor
from relay.execution.runner import (
    AttemptContext,
    ExecutionOutcome,
    OutcomeKind,
    RunnerStore,
    run_claim_token,
)
from relay.execution.state import AttemptStopReason, EventSource
from relay.paths import safe_resolve
from relay.workflows.actions import expressions
from relay.workflows.actions.compiler import _timeout
from relay.workflows.actions.compiler import definition as compile_definition
from relay.workflows.actions.language import (
    events,
    expand_matrix,
    load,
    resolve_inputs,
    source_bytes,
)
from relay.workflows.actions.metadata import load_action
from relay.workflows.outputs import extract_outputs
from relay.workflows.schema import ActionsJobNode, ActionsStepNode, CommandNode
from relay.workflows.scope import node_scope

from .agent import AgentNodeDriver
from .base import parse_node
from .command import CommandExecutor


def _repository() -> Any:
    # Runtime adapters load lazily; language validation needs neither Django nor storage.
    from relay.web import actions_repository

    return actions_repository


def _stop(context: AttemptContext) -> ExecutionOutcome | None:
    values = _repository().execution_context(context.attempt.attempt_id)
    if values["_cancelled"]:
        return ExecutionOutcome(
            OutcomeKind.FAILED,
            stop_reason=AttemptStopReason.CANCELED,
            error_code="canceled",
            raw_outcome="cancelled",
            conclusion="cancelled",
        )
    if context.timed_out():
        return ExecutionOutcome(
            OutcomeKind.FAILED,
            stop_reason=AttemptStopReason.TIMEOUT,
            error_code="node_timeout",
            raw_outcome="failure",
            conclusion="failure",
        )
    return None


def _state_path(context: AttemptContext, scope: str) -> Path:
    node = _repository().scope_node_id(context.attempt.run_id, scope)
    return _repository().job_state_path(node)


def _materialize_action(node: ActionsStepNode, reference: str, directory: Path) -> None:
    from relay.execution.action_products import checked_path

    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for source_path, content in node.sources.items():
        if not source_path.startswith(reference + "/"):
            continue
        target = checked_path(directory, source_path[len(reference) + 1 :])
        raw, mode = source_bytes(content)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or target.read_bytes() != raw:
                message = "Frozen action assets changed during execution."
                raise NodeExecutionError(message)
        else:
            target.write_bytes(raw)
            target.chmod(mode)


def _export_outputs(context: AttemptContext, outputs: Mapping[str, str]) -> dict[str, str]:
    masks = redactor(context.attempt.run_id)
    accepted = {}
    for key, value in outputs.items():
        if masks.contains(value):
            context.runtime.append_attempt_event(
                context.attempt.attempt_id,
                "actions.warning",
                EventSource.SYSTEM,
                {"message": f"Skipped secret-bearing job output {key!r}."},
            )
        else:
            accepted[key] = value
    _repository().output_budget(context.attempt.attempt_id, accepted)
    return accepted


def _step_values(
    context: AttemptContext, node: ActionsStepNode, state: Mapping[str, Any]
) -> dict[str, Any]:
    base = _repository().execution_context(context.attempt.attempt_id)
    from relay.web.actions_bindings import job_secrets

    values = {name: base[name] for name in ("github", "inputs", "vars", "needs")}
    values["inputs"] = node.caller_inputs or values["inputs"]
    values.update(
        {
            "env": dict(state.get("env", {})),
            "matrix": node.matrix,
            "strategy": {
                "fail-fast": node.job.get("strategy", {}).get("fail-fast", True),
                "max-parallel": 1,
                "job-index": state.get("matrix_index", 0),
                "job-total": state.get("matrix_total", 1),
            },
            "steps": {
                key.rsplit(".", 1)[-1]: value
                for key, value in state.get("steps", {}).items()
                if key.rsplit(".", 1)[0] == context.attempt.scope_path.rsplit(".", 1)[0]
            },
            "job": {
                "status": "failure"
                if any(
                    item.get("conclusion") == "failure" for item in state.get("steps", {}).values()
                )
                or "failure" in state.get("anonymous_statuses", {}).values()
                else "success"
            },
            "runner": {
                "os": {"Darwin": "macOS", "Windows": "Windows"}.get(platform.system(), "Linux"),
                "arch": "ARM64" if platform.machine().lower() in {"arm64", "aarch64"} else "X64",
                "name": platform.node(),
                "environment": "self-hosted",
                "temp": str(context.resources.directory / "temp") if context.resources else "",
                "tool_cache": "",
                "debug": "",
            },
            "secrets": job_secrets(
                context.attempt.run_id, node.state_scope, state.get("environment_name")
            ),
            "_cancelled": base["_cancelled"],
        }
    )
    values["vars"] = state.get("vars", values["vars"])
    values["github"] = {
        **values["github"],
        "job": node.job_id,
        "action": node.step_id,
        "action_path": node.action_path,
    }
    values["_statuses"] = ["failure"] if values["job"]["status"] == "failure" else []
    return values


def _children(
    context: AttemptContext,
    nodes: Mapping[str, ActionsJobNode | ActionsStepNode],
    driver: AgentNodeDriver,
    *,
    inputs: Mapping[str, Any],
) -> tuple[OutcomeKind, dict[str, dict[str, Any]]]:
    """Execute one finite ordered scope; every attempt is committed before running."""
    runtime = context.runtime
    scope = context.attempt.scope_path
    frozen = {key: item.model_dump(mode="json", by_alias=True) for key, item in nodes.items()}
    runtime.ensure_scope_nodes(context.attempt.run_id, scope, frozen, inputs, None)
    executors = {
        "actions_job": ActionsJobExecutor(driver),
        "actions_step": ActionsStepExecutor(driver),
    }
    records = dict(runtime.scope_node_records(context.attempt.run_id, scope, tuple(nodes)))
    failures = False
    for key, node in nodes.items():
        stopped = _stop(context)
        if stopped:
            from relay.web.actions_repository import settle_stopped_children

            settle_stopped_children(context.attempt.run_id, scope, stopped)
            return OutcomeKind.FAILED, {}
        record = records[key]
        if record.status == "pending":
            if isinstance(node, ActionsJobNode):
                dependencies = [records[needed] for needed in node.needs]
                values = _repository().execution_context(context.attempt.attempt_id)
                values["inputs"] = dict(inputs)
                values["needs"] = {
                    item.node_id: {
                        "outputs": dict(item.outputs),
                        "result": {
                            "succeeded": "success",
                            "failed": "failure",
                            "skipped": "skipped",
                            "canceled": "cancelled",
                        }.get(item.status, ""),
                    }
                    for item in dependencies
                }
                values["_statuses"] = [item["result"] for item in values["needs"].values()]
                enabled = expressions.condition(node.job.get("if"), values)
            else:
                path = _state_path(context, node.state_scope)
                guard = replace(
                    context, attempt=replace(context.attempt, scope_path=node_scope(scope, key))
                )
                values = _step_values(guard, node, read_state(path))
                enabled = expressions.condition(
                    node.step.get("if"), values, workspace=context.worktree
                )
            status = runtime.transition_scope_node(
                record.node_run_id,
                "dependencies_satisfied" if enabled else "guard_false",
                expected_status="pending",
            )
            if status == "skipped":
                _repository().record_skipped(record.node_run_id)
            record = runtime.scope_node_record(context.attempt.run_id, record.node_run_id)
        retries = 0
        while record.status in {"ready", "dispatched", "waiting"} or (
            isinstance(node, ActionsStepNode) and record.status == "failed"
        ):
            if record.status == "failed":
                decision = _repository().retry_step(record.node_run_id)
                if decision == "waiting":
                    return OutcomeKind.WAITING, {}
                if decision != "ready" or retries >= 3:
                    break
                retries += 1
                record = runtime.scope_node_record(context.attempt.run_id, record.node_run_id)
            token = (
                dispatch_node(runtime, record.node_run_id, lambda _token: None)
                if record.status != "dispatched"
                else runtime.create_dispatch(record.node_run_id)
            )
            if token:
                run_claim_token(
                    runtime,
                    token,
                    context.attempt.worker_id,
                    executors,
                    heartbeat_owners=(
                        (context.attempt.attempt_id, context.attempt.worker_id),
                        *context.heartbeat_owners,
                    ),
                    inherited_deadline=context.deadline_at,
                )
            record = runtime.scope_node_record(context.attempt.run_id, record.node_run_id)
            if record.status not in {"succeeded", "failed", "skipped", "canceled"}:
                break
        records[key] = record
        if record.status not in {"succeeded", "failed", "skipped", "canceled"}:
            return OutcomeKind.WAITING, {}
        if isinstance(node, ActionsStepNode):
            _repository().settled_step_result(record.node_run_id)
        if record.status in {"failed", "canceled"}:
            failures = True
            if (
                isinstance(node, ActionsJobNode)
                and node.matrix_index is not None
                and node.job.get("strategy", {}).get("fail-fast", True)
            ):
                for other_key, other in records.items():
                    if other_key != key and other.status == "pending":
                        runtime.transition_scope_node(
                            other.node_run_id, "dependencies_unreachable", expected_status="pending"
                        )
                        _repository().record_skipped(other.node_run_id)
                break
    outputs = {key: dict(record.outputs) for key, record in records.items()}
    return OutcomeKind.FAILED if failures else OutcomeKind.SUCCEEDED, outputs


class ActionsJobExecutor:
    driver: AgentNodeDriver

    def __init__(self, driver: AgentNodeDriver) -> None:
        self.driver = driver

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, ActionsJobNode)
        stopped = _stop(context)
        if stopped:
            _repository().settle_stopped_children(
                context.attempt.run_id,
                context.attempt.scope_path,
                stopped,
            )
            if not node.coordinator:
                path = _repository().job_state_path(context.attempt.node_run_id)
                if path.is_file():
                    posts = self.run_posts(context, path)
                    return replace(stopped, declared_artifacts=posts.declared_artifacts)
            return stopped
        values = _repository().execution_context(context.attempt.attempt_id)
        inputs = node.caller_inputs or values["inputs"]
        values["inputs"] = inputs
        raw_matrix = node.job.get("strategy", {}).get("matrix")
        if raw_matrix is not None and node.matrix_index is None:
            variants = _repository().frozen_matrix(
                context.attempt.run_id, context.attempt.scope_path
            )
            if variants is None:
                resolved = expressions.interpolate(raw_matrix, values, workspace=context.worktree)
                if not isinstance(resolved, Mapping):
                    message = "The matrix expression must produce a mapping."
                    raise NodeExecutionError(message)
                variants = expand_matrix(resolved)
            maximum = expressions.interpolate(
                node.job.get("strategy", {}).get("max-parallel", 1), values
            )
            if maximum != 1:
                message = "Relay executes one matrix variant at a time."
                raise NodeExecutionError(message)
            _repository().set_matrix_manifest(context.attempt.node_run_id, variants)
            children = {
                f"variant_{index + 1}": node.model_copy(
                    update={
                        "matrix": matrix,
                        "matrix_index": index,
                        "needs": [],
                        "coordinator": "uses" in node.job,
                        "bound_agents": {
                            key.removeprefix(f"variant_{index + 1}."): agent
                            for key, agent in node.bound_agents.items()
                            if key.startswith(f"variant_{index + 1}.")
                        }
                        or {
                            key.removeprefix("dynamic."): agent
                            for key, agent in node.bound_agents.items()
                            if key.startswith("dynamic.")
                        },
                    }
                )
                for index, matrix in enumerate(variants)
            }
            kind, results = _children(context, children, self.driver, inputs=inputs)
            records = _repository().node_results(context.attempt.run_id, context.attempt.scope_path)
            outputs = {
                key: value
                for variant, result in results.items()
                if records[variant]["conclusion"] == "success"
                for key, value in result.items()
                if value != ""
            }
            return self._outcome(kind, outputs, node, values)
        values["matrix"] = node.matrix
        _repository().display_name(
            context.attempt.attempt_id,
            expressions.string(expressions.interpolate(node.job.get("name", node.job_id), values)),
        )
        if node.job.get("timeout-minutes") is not None:
            timeout = expressions.interpolate(node.job["timeout-minutes"], values)
            deadline = _repository().step_deadline(context.attempt.attempt_id, float(str(timeout)))
            resolved = time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds()
            context = replace(
                context,
                deadline_at=min(resolved, context.deadline_at) if context.deadline_at else resolved,
            )
        if "uses" in node.job:
            return self.call_workflow(context, node, values)
        declared_environment = node.job.get("environment")
        environment_name = expressions.interpolate(
            declared_environment.get("name")
            if isinstance(declared_environment, Mapping)
            else declared_environment,
            values,
        )
        if environment_name and not _repository().environment_gate(
            context.attempt.attempt_id, str(environment_name), values
        ):
            return ExecutionOutcome(OutcomeKind.WAITING)
        from relay.web.actions_bindings import job_secrets

        secrets = job_secrets(
            context.attempt.run_id,
            context.attempt.scope_path,
            str(environment_name) if environment_name else None,
        )
        values["secrets"] = secrets
        values["vars"] = {
            **values["vars"],
            **values["_context"]
            .get("environment_bindings", {})
            .get(environment_name, {})
            .get("vars", {}),
        }
        _repository().prepare_job_workspace(context.attempt.run_id)
        resource = _repository().job_resources(
            context.attempt.node_run_id, context.attempt.run_id, context.attempt.attempt_id
        )
        path = resource.directory / "job-state.json"
        state = read_state(path)
        if not state.get("initialized"):
            environment = {
                **values["_launch"].get("workflow_defaults", {}).get("env", {}),
                **node.workflow.get("env", {}),
                **node.job.get("env", {}),
            }
            state.update(
                {
                    "env": expressions.interpolate(environment, values),
                    "initialized": True,
                    "matrix_index": node.matrix_index or 0,
                    "environment_name": environment_name,
                    "vars": values["vars"],
                    "matrix_total": len(
                        _repository().matrix_manifest(
                            context.attempt.run_id, context.attempt.scope_path
                        )
                    )
                    or 1,
                }
            )
            atomic_state(path, state)
        steps = {}
        for index, raw_step in enumerate(node.job["steps"]):
            step_id = raw_step.get("id") or f"step_{index + 1}"
            step_timeout = raw_step.get("timeout-minutes")
            steps[step_id] = ActionsStepNode(
                step=raw_step,
                workflow=node.workflow,
                job=node.job,
                job_id=node.job_id,
                step_id=step_id,
                index=index,
                matrix=node.matrix,
                sources=node.sources,
                bound_agent=node.bound_agents.get(step_id),
                caller_inputs=dict(inputs),
                bound_agents={
                    key.removeprefix(step_id + "."): agent
                    for key, agent in node.bound_agents.items()
                    if key.startswith(step_id + ".")
                },
                state_scope=context.attempt.scope_path,
                timeout=_timeout(step_timeout)
                or (node.bound_agents[step_id].timeout if step_id in node.bound_agents else None),
            )
        kind, results = _children(context, steps, self.driver, inputs=inputs)
        if kind is OutcomeKind.WAITING:
            return ExecutionOutcome(kind)
        stopped = _stop(context)
        posts = self.run_posts(context, path)
        if stopped:
            return replace(stopped, declared_artifacts=posts.declared_artifacts)
        if posts.kind is OutcomeKind.FAILED:
            kind = OutcomeKind.FAILED
        state = read_state(path)
        job_values = {
            **values,
            "steps": {
                key.rsplit(".", 1)[-1]: item
                for key, item in state["steps"].items()
                if key.rsplit(".", 1)[0] == context.attempt.scope_path
            },
            "env": state["env"],
            "runner": {},
            "job": {"status": "failure" if kind is OutcomeKind.FAILED else "success"},
            "strategy": {"max-parallel": 1},
            "secrets": secrets,
        }
        outputs = {
            key: expressions.string(
                expressions.interpolate(value, job_values, workspace=context.worktree)
            )
            for key, value in node.job.get("outputs", {}).items()
        }
        outputs = _export_outputs(context, outputs)
        if environment_name:
            configured = values["_context"].get("environments", {}).get(environment_name, {})
            declared = node.job.get("environment")
            raw_url = (
                declared.get("url", configured.get("url", ""))
                if isinstance(declared, Mapping)
                else configured.get("url", "")
            )
            url = expressions.string(expressions.interpolate(raw_url, job_values))
            _repository().publish_environment(
                context.attempt.attempt_id, str(environment_name), url
            )
        return replace(
            self._outcome(kind, outputs, node, values),
            declared_artifacts=posts.declared_artifacts,
            error_message=posts.error_message,
        )

    def _outcome(
        self,
        kind: OutcomeKind,
        outputs: Mapping[str, Any],
        node: ActionsJobNode,
        values: Mapping[str, Any],
    ) -> ExecutionOutcome:
        raw = "failure" if kind is OutcomeKind.FAILED else "success"
        continued = expressions.truthy(
            expressions.interpolate(node.job.get("continue-on-error", False), values)
        )
        return ExecutionOutcome(
            kind,
            outputs=outputs,
            error_code="job_failed" if kind is OutcomeKind.FAILED else None,
            raw_outcome=raw,
            conclusion="success" if continued and raw == "failure" else raw,
        )

    def call_workflow(
        self, context: AttemptContext, node: ActionsJobNode, values: Mapping[str, Any]
    ) -> ExecutionOutcome:
        reference = str(node.job["uses"]).removeprefix("./")
        try:
            source = node.sources[reference]
        except KeyError:
            message = "The reusable workflow was not frozen at launch."
            raise NodeExecutionError(message) from None
        document = load(source, source=Path(reference))
        supplied = cast(dict[str, Any], expressions.interpolate(node.job.get("with", {}), values))
        inputs = resolve_inputs(document.value, supplied, event="workflow_call")
        from relay.execution.action_products import cache_mode

        inherited_cache = cache_mode(node.workflow, node.job, node.caller_cache_mode)
        compiled = compile_definition(document, node.sources)
        children = {
            key: child.model_copy(
                update={
                    "caller_inputs": inputs,
                    "workflow_scope": context.attempt.scope_path,
                    "caller_secret_scope": context.attempt.scope_path,
                    "caller_secret_mapping": node.job.get("secrets", {}),
                    "caller_cache_mode": inherited_cache,
                    "job": {
                        **child.job,
                        "_caller_cache_mode": inherited_cache,
                    },
                    "bound_agents": {
                        name.removeprefix(f"{key}."): agent
                        for name, agent in node.bound_agents.items()
                        if name.startswith(f"{key}.")
                    },
                }
            )
            for key, child in compiled.nodes.items()
            if isinstance(child, ActionsJobNode)
        }
        kind, results = _children(context, children, self.driver, inputs=inputs)
        if kind is OutcomeKind.WAITING:
            return ExecutionOutcome(kind)
        call = events(document.value)["workflow_call"]
        records = _repository().node_results(context.attempt.run_id, context.attempt.scope_path)
        jobs = {
            key: {"outputs": result, "result": records[key]["conclusion"]}
            for key, result in results.items()
        }
        outputs = {
            key: expressions.string(
                expressions.interpolate(item["value"], {**values, "jobs": jobs})
            )
            for key, item in call.get("outputs", {}).items()
        }
        outputs = _export_outputs(context, outputs)
        return self._outcome(kind, outputs, node, values)

    def run_posts(self, context: AttemptContext, path: Path) -> ExecutionOutcome:
        """Only already registered JavaScript post scripts may run after owner stop."""
        state = read_state(path)
        from relay.execution.action_products import execute_product

        failed = bool(state.get("post_failed"))
        artifacts: dict[str, str] = dict(state.get("post_artifacts", {}))
        for post in state.get("cache_posts", []):
            if post.get("completed"):
                continue
            if (
                all(item.get("conclusion") != "failure" for item in state["steps"].values())
                and "failure" not in state.get("anonymous_statuses", {}).values()
            ):
                try:
                    execute_product(
                        context,
                        "relay/save-cache@v1",
                        post["inputs"],
                        {},
                        ActionsStepNode.model_validate(post["node"]),
                    )
                except OSError:
                    context.runtime.append_attempt_event(
                        context.attempt.attempt_id,
                        "actions.warning",
                        EventSource.SYSTEM,
                        {"message": "Cache save failed; job evidence is retained separately."},
                    )
            post["completed"] = True
            atomic_state(path, state)
        for post in reversed(state.get("posts", [])):
            if post.get("completed"):
                continue
            stopped = _stop(context)
            statuses = (
                ["failure"]
                if failed
                or any(item.get("conclusion") == "failure" for item in state["steps"].values())
                or "failure" in state.get("anonymous_statuses", {}).values()
                else []
            )
            if not expressions.condition(
                post.get("condition", "always()"),
                {
                    **post.get("values", {}),
                    "env": state["env"],
                    "job": {"status": "failure" if statuses else "success"},
                    "_statuses": statuses,
                    "_cancelled": bool(
                        stopped and stopped.stop_reason is AttemptStopReason.CANCELED
                    ),
                },
            ):
                post["completed"] = True
                atomic_state(path, state)
                continue
            deadline = time.monotonic() + 10
            cleanup = replace(context, deadline_at=deadline, registered_cleanup=True)
            cleanup_dir = path.parent / f"cleanup-{uuid.uuid4()}"
            cleanup_dir.mkdir(mode=0o700)
            paths = step_files(cleanup_dir)
            environment = {
                **state["env"],
                **post["env"],
                **{f"STATE_{key}": value for key, value in post.get("state", {}).items()},
                **{key: str(value) for key, value in paths.items()},
            }
            command = CommandNode(type="command", run=post["argv"], env=environment)
            attempt = replace(
                cleanup.attempt, frozen_def=command.model_dump(mode="json", by_alias=True)
            )
            masks = redactor(context.attempt.run_id)
            log = CommandLog(context.runtime, context.attempt.attempt_id, masks)
            try:
                outcome = CommandExecutor().execute(
                    replace(
                        cleanup,
                        attempt=attempt,
                        runtime=cast(RunnerStore, ActionRuntime(context.runtime, log, masks)),
                    )
                )
            finally:
                log.flush()
            _, retained, summary = consume(state, cleanup_dir.name, paths, context.worktree)
            artifacts.update(retained)
            if summary:
                context.runtime.append_attempt_event(
                    context.attempt.attempt_id,
                    "actions.summary",
                    EventSource.COMMAND,
                    {"markdown": masks.text(summary)},
                )
            if outcome.kind is not OutcomeKind.SUCCEEDED:
                failed = True
                state["post_failed"] = True
                context.runtime.append_attempt_event(
                    context.attempt.attempt_id,
                    "actions.post_failed",
                    EventSource.COMMAND,
                    {"message": "A registered JavaScript cleanup hook failed."},
                )
            post["completed"] = True
            state["post_artifacts"] = artifacts
            atomic_state(path, state)
        return ExecutionOutcome(
            OutcomeKind.FAILED if failed else OutcomeKind.SUCCEEDED,
            declared_artifacts=artifacts,
            error_message="A registered JavaScript cleanup hook failed." if failed else None,
        )


class ActionsStepExecutor:
    driver: AgentNodeDriver

    def __init__(self, driver: AgentNodeDriver) -> None:
        self.driver = driver

    def execute(self, context: AttemptContext) -> ExecutionOutcome:
        node = parse_node(context, ActionsStepNode)
        stopped = _stop(context)
        if context.resources is None:
            message = "The step has no owned private resources."
            raise NodeExecutionError(message)
        state_path = _state_path(context, node.state_scope)
        state = read_state(state_path)
        values = _step_values(context, node, state)
        _repository().display_name(
            context.attempt.attempt_id,
            expressions.string(
                expressions.interpolate(
                    node.step.get("name", node.step_id), values, workspace=context.worktree
                )
            ),
        )
        if node.step.get("timeout-minutes") is not None:
            timeout = expressions.interpolate(
                node.step["timeout-minutes"], values, workspace=context.worktree
            )
            deadline = _repository().step_deadline(context.attempt.attempt_id, float(str(timeout)))
            resolved = time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds()
            context = replace(
                context,
                deadline_at=min(resolved, context.deadline_at) if context.deadline_at else resolved,
            )
        masks = redactor(context.attempt.run_id)
        resources = context.resources
        if resources is None:
            message = "The step has no owned private resources."
            raise NodeExecutionError(message)
        paths = step_files(resources.directory)
        artifact_list = resources.directory / "github-artifacts-list.json"
        artifact_list.write_text(
            json.dumps({"version": 1, "subjects": state["subjects"]}), encoding="utf-8"
        )
        environment = {
            **{key: expressions.string(value) for key, value in state["env"].items()},
            **cast(dict[str, Any], expressions.interpolate(node.step.get("env", {}), values)),
            **{key: str(value) for key, value in paths.items()},
            "GITHUB_ARTIFACTS_LIST": str(artifact_list),
            "GITHUB_WORKSPACE": str(context.worktree),
            "GITHUB_SHA": values["github"]["sha"],
            "GITHUB_REF": values["github"]["ref"],
            "GITHUB_RUN_ID": context.attempt.run_id,
            "GITHUB_RUN_NUMBER": str(values["github"]["run_number"]),
            "GITHUB_ACTION": node.step_id,
            "GITHUB_ACTION_PATH": node.action_path,
            "GITHUB_JOB": node.job_id,
            "RUNNER_TEMP": str(resources.directory / "temp"),
            "RUNNER_OS": values["runner"]["os"],
            "RUNNER_ARCH": values["runner"]["arch"],
        }
        if state["path"]:
            environment["PATH"] = os.pathsep.join(
                [*state["path"], environment.get("PATH", os.environ.get("PATH", ""))]
            )
        values["env"] = {
            **values["env"],
            **cast(dict[str, Any], expressions.interpolate(node.step.get("env", {}), values)),
        }
        log = CommandLog(context.runtime, context.attempt.attempt_id, masks)
        proxy = cast(RunnerStore, ActionRuntime(context.runtime, log, masks))
        command_context = replace(context, runtime=proxy)
        try:
            try:
                outcome = stopped or self.perform(
                    command_context, node, values, environment, paths, state_path
                )
            except RelayError as error:
                context.runtime.append_attempt_event(
                    context.attempt.attempt_id, "error", EventSource.SYSTEM, error.to_envelope()
                )
                outcome = ExecutionOutcome(
                    OutcomeKind.FAILED, error_code=error.error_code, error_message=error.message
                )
        finally:
            log.flush()
        if outcome.kind is OutcomeKind.WAITING:
            return outcome
        state = read_state(state_path)
        outputs, artifacts, summary = consume(
            state, context.attempt.attempt_id, paths, context.worktree
        )
        outputs.update({key: expressions.string(value) for key, value in outcome.outputs.items()})
        if (
            sum(
                len(key.encode("utf-16-le")) + len(value.encode("utf-16-le"))
                for key, value in outputs.items()
            )
            > MAX_FILE
        ):
            message = "Step outputs exceed 1 MiB in UTF-16."
            raise NodeExecutionError(message)
        if outcome.outputs:
            state.setdefault("reports", {})[context.attempt.scope_path] = dict(outcome.outputs)
        if outcome.kind is OutcomeKind.SUCCEEDED:
            outcome = _stop(context) or outcome
        raw = (
            "success"
            if outcome.kind is OutcomeKind.SUCCEEDED
            else "cancelled"
            if outcome.stop_reason is AttemptStopReason.CANCELED
            else "failure"
        )
        continued = raw == "failure" and expressions.truthy(
            expressions.interpolate(node.step.get("continue-on-error", False), values)
        )
        conclusion = "success" if continued else raw
        if "id" in node.step:
            state["steps"][context.attempt.scope_path] = {
                "outputs": outputs,
                "outcome": raw,
                "conclusion": conclusion,
            }
        else:
            state.setdefault("anonymous_statuses", {})[context.attempt.scope_path] = conclusion
        if summary:
            context.runtime.append_attempt_event(
                context.attempt.attempt_id,
                "actions.summary",
                EventSource.COMMAND,
                {"markdown": masks.text(summary)},
            )
        atomic_state(state_path, state)
        return replace(
            outcome,
            kind=OutcomeKind.SUCCEEDED if continued else outcome.kind,
            outputs=cast(dict, masks.payload(outputs)),
            declared_artifacts={**outcome.declared_artifacts, **artifacts},
            raw_outcome=raw,
            conclusion=conclusion,
        )

    def perform(
        self,
        context: AttemptContext,
        node: ActionsStepNode,
        values: Mapping[str, Any],
        environment: dict[str, str],
        paths: Mapping[str, Path],
        state_path: Path,
    ) -> ExecutionOutcome:
        if "run" in node.step:
            defaults = {
                **node.workflow.get("defaults", {}).get("run", {}),
                **node.job.get("defaults", {}).get("run", {}),
            }
            directory = expressions.interpolate(
                node.step.get("working-directory", defaults.get("working-directory", ".")), values
            )
            workspace = safe_resolve(context.worktree, str(directory))
            if not workspace.is_dir():
                message = "The working-directory does not exist."
                raise NodeExecutionError(message)
            source = expressions.string(
                expressions.interpolate(node.step["run"], values, workspace=context.worktree)
            )
            shell = expressions.interpolate(node.step.get("shell", defaults.get("shell")), values)
            if context.resources is None:
                message = "Missing step resources."
                raise NodeExecutionError(message)
            argv = shell_script(context.resources.directory, source, cast(str | None, shell))
            command = CommandNode(type="command", run=argv, env=environment)
            attempt = replace(
                context.attempt, frozen_def=command.model_dump(mode="json", by_alias=True)
            )
            return CommandExecutor().execute(replace(context, attempt=attempt, worktree=workspace))
        reference = str(node.step["uses"])
        inputs = cast(
            dict[str, Any],
            expressions.interpolate(node.step.get("with", {}), values, workspace=context.worktree),
        )
        if reference == "relay/command@v1":
            if "argv" in inputs:
                try:
                    argv = json.loads(str(inputs["argv"]))
                except ValueError:
                    message = "Command argv must be a JSON argument vector."
                    raise NodeExecutionError(message) from None
            else:
                launch = _repository().execution_context(context.attempt.attempt_id)["_launch"]
                argv = (
                    launch.get("workflow_defaults", {})
                    .get("commands", {})
                    .get(inputs.get("command"))
                )
            if (
                not isinstance(argv, list)
                or not argv
                or any(not isinstance(item, str) for item in argv)
            ):
                message = "Use argv or a configured named command."
                raise NodeExecutionError(message)
            command = CommandNode(type="command", run=argv, env=environment)
            attempt = replace(
                context.attempt, frozen_def=command.model_dump(mode="json", by_alias=True)
            )
            return CommandExecutor().execute(replace(context, attempt=attempt))
        if reference == "relay/human-wait@v1":
            deadline = (
                float(inputs["timeout-minutes"]) * 60 if "timeout-minutes" in inputs else None
            )
            if deadline is not None and not 0 < deadline <= 21600:
                message = "Human wait timeout must be between zero and 360 minutes."
                raise NodeExecutionError(message)
            _repository().request_human_wait(
                context.attempt.attempt_id,
                expressions.string(inputs.get("prompt", "Owner input required.")),
                deadline,
            )
            return ExecutionOutcome(OutcomeKind.WAITING, wait_timeout_seconds=deadline)
        if reference == "relay/agent@v1":
            if node.bound_agent is None:
                message = "The agent route was not frozen at launch."
                raise NodeExecutionError(message)
            prompt = str(inputs.get("prompt", ""))
            attempt = replace(
                context.attempt,
                prompt_contents=(*context.attempt.prompt_contents, prompt)
                if prompt
                else context.attempt.prompt_contents,
            )
            resources = (
                replace(context.resources, overrides=environment) if context.resources else None
            )
            outcome = self.driver.execute(
                replace(context, attempt=attempt, resources=resources), node.bound_agent
            )
            if outcome.kind is not OutcomeKind.SUCCEEDED:
                return outcome
            if "report" in inputs:
                try:
                    output, artifacts = self.report(context, inputs)
                except RelayError as error:
                    report = safe_resolve(context.worktree, str(inputs["report"]))
                    return replace(
                        outcome,
                        kind=OutcomeKind.FAILED,
                        error_code=error.error_code,
                        error_message=error.message,
                        stop_reason=AttemptStopReason.OUTPUT_INVALID,
                        declared_artifacts={"report": str(inputs["report"])}
                        if report.is_file()
                        else {},
                    )
                return replace(
                    outcome, outputs={**outcome.outputs, **output}, declared_artifacts=artifacts
                )
            return outcome
        if reference == "relay/validate-report@v1":
            outputs, artifacts = self.report(context, inputs)
            return ExecutionOutcome(
                OutcomeKind.SUCCEEDED, outputs=outputs, declared_artifacts=artifacts
            )
        if reference == "relay/validate-input@v1":
            from pydantic import TypeAdapter, ValidationError

            from relay.workflows.schema import InputDefinition, WorkflowDefinition
            from relay.workflows.validation import resolve_inputs as validate_typed_inputs

            raw = expressions.string(inputs.get("value", ""))
            kind = inputs.get("type", "string")
            value: object = raw
            if kind in {"number", "boolean", "integer", "enum"}:
                value = expressions.evaluate(f"fromJSON('{raw.replace(chr(39), chr(39) * 2)}')", {})
            try:
                definition = TypeAdapter(InputDefinition).validate_python(
                    {
                        "type": kind,
                        "required": True,
                        "constraints": json.loads(str(inputs.get("constraints", "{}"))),
                    }
                )
            except (ValueError, ValidationError):
                message = "The input type or constraint declaration is invalid."
                raise NodeExecutionError(message) from None
            validate_typed_inputs(
                WorkflowDefinition(
                    version=1, name="Input validation", inputs={"value": definition}, nodes={}
                ),
                {"value": value},
            )
            return ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs={"value": raw, "valid": "true"})
        if reference == "relay/loop@v1":
            return self.loop(context, node, inputs, values)
        if reference.startswith("./"):
            return self.local_action(context, node, inputs, values, environment, paths, state_path)
        from relay.execution.action_products import execute_product

        return execute_product(context, reference, inputs, values, node)

    def report(
        self, context: AttemptContext, inputs: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, str]]:
        from pydantic import TypeAdapter, ValidationError

        from relay.workflows.schema import OutputSelector

        artifact = str(inputs.get("report", inputs.get("path", "")))
        if "selector" in inputs:
            try:
                raw = json.loads(str(inputs["selector"]))
            except ValueError:
                message = "The report selector must be valid JSON."
                raise NodeExecutionError(message) from None
        else:
            format_name = inputs.get("format", "label")
            if format_name == "exists":
                return {
                    "value": (
                        "true" if safe_resolve(context.worktree, artifact).is_file() else "false"
                    )
                }, {}
            raw = (
                {"label": {"artifact": artifact, "label": str(inputs.get("label", "Ready"))}}
                if format_name == "label"
                else {
                    f"{format_name}_path": {
                        "artifact": artifact,
                        "path": str(inputs.get("field", "value")),
                    }
                }
            )
        try:
            selector = TypeAdapter(OutputSelector).validate_python(raw)
        except ValidationError:
            message = "The report selector is invalid."
            raise NodeExecutionError(message) from None
        return extract_outputs(context.worktree, {"value": selector}), {"report": artifact}

    def loop(
        self,
        context: AttemptContext,
        node: ActionsStepNode,
        inputs: Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> ExecutionOutcome:
        from relay.execution.action_products import cache_mode

        maximum = int(str(inputs.get("max-iterations", 1)))
        if not 1 <= maximum <= 100:
            message = "Loop max-iterations must be between 1 and 100."
            raise NodeExecutionError(message)
        for index in range(maximum):
            child = ActionsJobNode(
                job_id="iteration",
                job={
                    "uses": inputs["workflow"],
                    "with": json.loads(str(inputs.get("inputs", "{}"))),
                    "secrets": "inherit",
                },
                workflow=node.workflow,
                sources=node.sources,
                coordinator=True,
                bound_agents={
                    key.removeprefix(f"iteration_{index + 1}."): agent
                    for key, agent in node.bound_agents.items()
                    if key.startswith(f"iteration_{index + 1}.")
                },
                caller_inputs=node.caller_inputs,
                caller_secret_scope=node.state_scope,
                caller_secret_mapping="inherit",  # noqa: S106 - forwarding policy, not a value
                caller_cache_mode=cache_mode(node.workflow, node.job),
            )
            kind, results = _children(
                context, {f"iteration_{index + 1}": child}, self.driver, inputs=node.caller_inputs
            )
            if kind is not OutcomeKind.SUCCEEDED:
                return ExecutionOutcome(
                    kind, error_code="loop_iteration_failed" if kind is OutcomeKind.FAILED else None
                )
            output = results[f"iteration_{index + 1}"]
            until = inputs.get("until-output")
            if not until or expressions.equal(output.get(str(until)), inputs.get("equals", "true")):
                return ExecutionOutcome(OutcomeKind.SUCCEEDED, outputs=output)
        return ExecutionOutcome(OutcomeKind.FAILED, error_code="loop_exhausted")

    def local_action(
        self,
        context: AttemptContext,
        node: ActionsStepNode,
        inputs: Mapping[str, Any],
        values: Mapping[str, Any],
        environment: dict[str, str],
        paths: Mapping[str, Path],
        state_path: Path,
    ) -> ExecutionOutcome:
        reference = str(node.step["uses"]).removeprefix("./").rstrip("/")
        text = node.sources.get(
            f"{reference}/action.yml", node.sources.get(f"{reference}/action.yaml")
        )
        if text is None:
            message = "Local action metadata was not frozen."
            raise NodeExecutionError(message)
        metadata = load_action(text)
        declarations = metadata.get("inputs", {})
        if inputs.keys() - declarations.keys() or any(
            item.get("required") and name not in inputs and "default" not in item
            for name, item in declarations.items()
        ):
            message = "Local action has missing required or unknown inputs."
            raise NodeExecutionError(message)
        for name, item in declarations.items():
            if name in inputs and item.get("deprecationMessage"):
                context.runtime.append_attempt_event(
                    context.attempt.attempt_id,
                    "actions.warning",
                    EventSource.SYSTEM,
                    {"message": item["deprecationMessage"]},
                )
        inputs = {
            **{name: item.get("default", "") for name, item in metadata.get("inputs", {}).items()},
            **inputs,
        }
        runs = metadata["runs"]
        if runs["using"] == "composite":
            from hashlib import sha256

            directory = state_path.parent / (
                "composite-" + sha256(context.attempt.scope_path.encode()).hexdigest()
            )
            _materialize_action(node, reference, directory)
            steps = {
                step.get("id") or f"step_{index + 1}": node.model_copy(
                    update={
                        "step": step,
                        "step_id": step.get("id") or f"step_{index + 1}",
                        "index": index,
                        "caller_inputs": dict(inputs),
                        "action_path": str(directory),
                        "bound_agent": node.bound_agents.get(step.get("id") or f"step_{index + 1}"),
                        "bound_agents": {
                            key.removeprefix((step.get("id") or f"step_{index + 1}") + "."): agent
                            for key, agent in node.bound_agents.items()
                            if key.startswith((step.get("id") or f"step_{index + 1}") + ".")
                        },
                    }
                )
                for index, step in enumerate(runs["steps"])
            }
            kind, _ = _children(context, steps, self.driver, inputs=inputs)
            if kind is OutcomeKind.WAITING:
                return ExecutionOutcome(kind)
            state = read_state(state_path)
            local_steps = {
                key.rsplit(".", 1)[-1]: item
                for key, item in state["steps"].items()
                if key.rsplit(".", 1)[0] == context.attempt.scope_path
            }
            outputs = {
                name: expressions.string(
                    expressions.interpolate(
                        item["value"], {**values, "inputs": inputs, "steps": local_steps}
                    )
                )
                for name, item in metadata.get("outputs", {}).items()
            }
            return ExecutionOutcome(kind, outputs=outputs)
        major = int(str(runs["using"])[4:])
        executable = None
        for candidate in (f"node{major}", f"node-{major}", "node"):
            resolved = shutil.which(candidate)
            if resolved:
                try:
                    version = subprocess.run(  # noqa: S603 - installed Node version probe
                        [resolved, "--version"],
                        shell=False,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    ).stdout.strip()
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if version.startswith(f"v{major}."):
                    executable = resolved
                    break
        if executable is None:
            message = f"This local action requires installed Node.js {major}."
            raise NodeExecutionError(message)
        if context.resources is None:
            message = "Missing step resources."
            raise NodeExecutionError(message)
        directory = context.resources.directory / "action"
        _materialize_action(node, reference, directory)
        environment.update(
            {
                f"INPUT_{name.upper().replace(' ', '_')}": expressions.string(value)
                for name, value in inputs.items()
            }
        )
        environment["GITHUB_ACTION_PATH"] = str(directory)
        if "post" in runs:
            state = read_state(state_path)
            state["posts"].append(
                {
                    "argv": [executable, str(safe_resolve(directory, runs["post"]))],
                    "env": environment,
                    "state": {},
                    "completed": False,
                    "condition": runs.get("post-if", "always()"),
                    "values": {
                        "github": values["github"],
                        "runner": values["runner"],
                        "inputs": dict(inputs),
                    },
                }
            )
            # Copy registered cleanup scripts into the durable job resource allocation.
            post_dir = state_path.parent / f"post-{context.attempt.attempt_id}"
            shutil.copytree(directory, post_dir)
            state["posts"][-1]["argv"][1] = str(safe_resolve(post_dir, runs["post"]))
            state["posts"][-1]["env"] = {**environment, "GITHUB_ACTION_PATH": str(post_dir)}
            atomic_state(state_path, state)
        command = CommandNode(
            type="command",
            run=[executable, str(safe_resolve(directory, runs["main"]))],
            env=environment,
        )
        attempt = replace(
            context.attempt, frozen_def=command.model_dump(mode="json", by_alias=True)
        )
        outcome = CommandExecutor().execute(replace(context, attempt=attempt))
        if "post" in runs:
            state = read_state(state_path)
            state["posts"][-1]["state"] = key_values(file_text(paths["GITHUB_STATE"]))
            atomic_state(state_path, state)
        return outcome

"""Shared parsing, context, output, and event helpers for node executors."""

from __future__ import annotations

import codecs
from collections import deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
import time
from typing import TYPE_CHECKING, BinaryIO, Protocol, TypeVar

from pydantic import TypeAdapter, ValidationError

from relay.constants import ATTEMPT_HEARTBEAT_INTERVAL_SECONDS, CONTROL_POLL_INTERVAL_SECONDS
from relay.errors import NodeExecutionError, PersistenceError
from relay.execution.dispatch import dispatch_node
from relay.execution.runner import AttemptContext, OutcomeKind, run_claim_token
from relay.execution.scheduler import (
    activation_sources,
    entry_node_for_scope,
    evaluate_eligibility,
    reachable_node_ids,
)
from relay.execution.state import EventSource, NodeStatus
from relay.workflows.graph import compile_graph
from relay.workflows.outputs import extract_outputs
from relay.workflows.schema import (
    JsonPathSelector,
    LabelSelector,
    NodeDefinition,
    OutputSelector,
    YamlPathSelector,
)

if TYPE_CHECKING:
    from .agent import AgentNodeDriver

NodeT = TypeVar("NodeT", bound=NodeDefinition)
_NODE_ADAPTER: TypeAdapter[NodeDefinition] = TypeAdapter(NodeDefinition)
_OUTPUT_READ_BYTES = 8_192
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3_600.0}


@dataclass(frozen=True, slots=True)
class NestedScopeResult:
    """Terminal state and validated outputs from one scoped child graph."""

    kind: OutcomeKind
    node_outputs: Mapping[str, Mapping[str, object]]
    error_code: str | None = None


class NestedScopeRunner(Protocol):
    def execute_scope(
        self,
        context: AttemptContext,
        nodes: Mapping[str, NodeDefinition],
        *,
        parent_scope: str,
        inputs: Mapping[str, object],
        loop_index: int | None = None,
    ) -> NestedScopeResult: ...


class MissingNestedScopeRunner:
    def execute_scope(
        self,
        context: AttemptContext,
        nodes: Mapping[str, NodeDefinition],
        *,
        parent_scope: str,
        inputs: Mapping[str, object],
        loop_index: int | None = None,
    ) -> NestedScopeResult:
        del nodes, parent_scope, inputs, loop_index
        message = "No durable nested-scope runner is available."
        raise NodeExecutionError(message, context={"node": context.attempt.scope_path})


def _expression_values(
    context: AttemptContext,
    inputs: Mapping[str, object],
    dependencies: Mapping[str, Mapping[str, object]],
    loop_index: int | None,
) -> dict[str, object]:
    return {
        "inputs": dict(inputs),
        "needs": {node_id: {"outputs": dict(outputs)} for node_id, outputs in dependencies.items()},
        "run": dict(context.attempt.run_metadata),
        "loop": {"index": loop_index} if loop_index is not None else {},
    }


class SynchronousScopeRunner:
    """Run a finite child DAG inline so a one-worker consumer cannot deadlock."""

    def __init__(self, agent_driver: AgentNodeDriver) -> None:
        self.agent_driver: AgentNodeDriver = agent_driver

    def execute_scope(
        self,
        context: AttemptContext,
        nodes: Mapping[str, NodeDefinition],
        *,
        parent_scope: str,
        inputs: Mapping[str, object],
        loop_index: int | None = None,
    ) -> NestedScopeResult:
        graph = compile_graph(nodes, location=parent_scope)
        frozen = {
            node_id: node.model_dump(mode="json", by_alias=True) for node_id, node in nodes.items()
        }
        context.runtime.ensure_scope_nodes(
            context.attempt.run_id,
            parent_scope,
            frozen,
            inputs,
            loop_index,
        )
        incoming, control_downstream = activation_sources(nodes)
        entry_value = context.attempt.run_metadata.get("entry_point")
        entry_point = entry_value if isinstance(entry_value, str) else None
        entry_node = entry_node_for_scope(entry_point, parent_scope)
        reachable = (
            reachable_node_ids(entry_node, graph, control_downstream)
            if entry_node is not None
            else frozenset(nodes)
        )
        node_ids = tuple(nodes)
        queue = deque(graph.topological_order)
        propagated: set[str] = set()

        from . import node_executors

        executors = node_executors(agent_driver=self.agent_driver, scope_runner=self)
        while queue:
            node_id = queue.popleft()
            records = context.runtime.scope_node_records(
                context.attempt.run_id, parent_scope, node_ids
            )
            record = records[node_id]
            node = nodes[node_id]
            if record.status == NodeStatus.PENDING.value:
                if node_id not in reachable:
                    context.runtime.transition_scope_node(
                        record.node_run_id, "dependencies_unreachable"
                    )
                    queue.extend(graph.downstream[node_id])
                    queue.extend(control_downstream[node_id])
                    continue
                if node_id == entry_node:
                    # Launch preflight proved this entry point's declared inputs and artifacts.
                    context.runtime.transition_scope_node(
                        record.node_run_id, "dependencies_satisfied"
                    )
                activators = incoming[node_id]
                if activators and node_id != entry_node:
                    source_records = [records[source] for source in activators]
                    selected = any(item.selected_branch == node_id for item in source_records)
                    complete = all(
                        item.status
                        in {
                            NodeStatus.SUCCEEDED.value,
                            NodeStatus.SKIPPED.value,
                            NodeStatus.FAILED.value,
                            NodeStatus.CANCELED.value,
                        }
                        for item in source_records
                    )
                    if complete and not selected:
                        context.runtime.transition_scope_node(
                            record.node_run_id, "dependencies_unreachable"
                        )
                    elif not selected:
                        continue
                records = context.runtime.scope_node_records(
                    context.attempt.run_id, parent_scope, node_ids
                )
                record = records[node_id]
                if record.status == NodeStatus.PENDING.value:
                    dependencies = {
                        needed: records[needed].outputs for needed in graph.dependencies[node_id]
                    }
                    eligibility = evaluate_eligibility(
                        node,
                        {needed: records[needed].status for needed in graph.dependencies[node_id]},
                        _expression_values(context, inputs, dependencies, loop_index),
                    )
                    if eligibility.action is None:
                        continue
                    context.runtime.transition_scope_node(record.node_run_id, eligibility.action)
                    records = context.runtime.scope_node_records(
                        context.attempt.run_id, parent_scope, node_ids
                    )
                    record = records[node_id]

            if record.status == NodeStatus.READY.value:
                token = dispatch_node(
                    context.runtime,
                    record.node_run_id,
                    lambda _claim_token: None,
                )
                heartbeat_due = time.monotonic() + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
                while True:
                    outcome = run_claim_token(
                        context.runtime,
                        token,
                        context.attempt.worker_id,
                        executors,
                    )
                    records = context.runtime.scope_node_records(
                        context.attempt.run_id, parent_scope, node_ids
                    )
                    record = records[node_id]
                    if outcome is not None and outcome.kind is not OutcomeKind.WAITING:
                        break
                    if record.status in {
                        NodeStatus.SUCCEEDED.value,
                        NodeStatus.SKIPPED.value,
                        NodeStatus.FAILED.value,
                        NodeStatus.CANCELED.value,
                    }:
                        break
                    context.runtime.resolve_human_wait_controls()
                    context.runtime.expire_human_waits()
                    now = time.monotonic()
                    if now >= heartbeat_due:
                        if not context.runtime.heartbeat_attempt(
                            context.attempt.attempt_id,
                            context.attempt.worker_id,
                        ):
                            message = "The enclosing scope lost its durable worker ownership."
                            raise PersistenceError(
                                message,
                                context={"node": context.attempt.scope_path},
                            )
                        heartbeat_due = now + ATTEMPT_HEARTBEAT_INTERVAL_SECONDS
                    time.sleep(CONTROL_POLL_INTERVAL_SECONDS)
                records = context.runtime.scope_node_records(
                    context.attempt.run_id, parent_scope, node_ids
                )
                record = records[node_id]

            if record.status in {NodeStatus.FAILED.value, NodeStatus.CANCELED.value}:
                return NestedScopeResult(OutcomeKind.FAILED, {}, "nested_node_failed")
            if (
                record.status
                in {
                    NodeStatus.SUCCEEDED.value,
                    NodeStatus.SKIPPED.value,
                }
                and node_id not in propagated
            ):
                queue.extend(graph.downstream[node_id])
                queue.extend(control_downstream[node_id])
                propagated.add(node_id)

        records = context.runtime.scope_node_records(context.attempt.run_id, parent_scope, node_ids)
        if any(
            record.status not in {NodeStatus.SUCCEEDED.value, NodeStatus.SKIPPED.value}
            for record in records.values()
        ):
            return NestedScopeResult(OutcomeKind.WAITING, {})
        return NestedScopeResult(
            OutcomeKind.SUCCEEDED,
            {node_id: dict(record.outputs) for node_id, record in records.items()},
        )


def parse_node(context: AttemptContext, expected: type[NodeT]) -> NodeT:
    """Revalidate the immutable node snapshot before executing it."""
    try:
        node = _NODE_ADAPTER.validate_python(dict(context.attempt.frozen_def))
    except ValidationError:
        message = "The frozen node definition is invalid."
        raise NodeExecutionError(message, context={"node": context.attempt.scope_path}) from None
    if not isinstance(node, expected):
        message = f"The executor cannot run node type {node.type!r}."
        raise NodeExecutionError(message, context={"node": context.attempt.scope_path})
    return node


def duration_seconds(value: str | None) -> float | None:
    """Convert schema-validated `250ms`, `4s`, `3m`, or `2h` to seconds."""
    if value is None:
        return None
    suffix = "ms" if value.endswith("ms") else value[-1]
    number = value[: -len(suffix)]
    try:
        return int(number) * _DURATION_UNITS[suffix]
    except (KeyError, ValueError):
        message = f"Duration {value!r} is not valid."
        raise NodeExecutionError(message) from None


def expression_context(context: AttemptContext) -> dict[str, object]:
    """Build the only names visible to a workflow expression."""
    needs = {
        node_id: {"outputs": dict(outputs)}
        for node_id, outputs in context.attempt.upstream_outputs.items()
    }
    loop_index = context.attempt.run_metadata.get("loop_index")
    loop = {"index": loop_index} if isinstance(loop_index, int) else {}
    return {
        "inputs": dict(context.attempt.inputs),
        "needs": needs,
        "run": dict(context.attempt.run_metadata),
        "loop": loop,
    }


def _selector_artifact(selector: OutputSelector) -> str | None:
    if isinstance(selector, LabelSelector):
        return selector.label.artifact
    if isinstance(selector, JsonPathSelector):
        return selector.json_path.artifact
    if isinstance(selector, YamlPathSelector):
        return selector.yaml_path.artifact
    return None


def declared_output_artifacts(selectors: Mapping[str, OutputSelector]) -> dict[str, str]:
    """Treat selector-backed files as the node's required retained artifacts."""
    return {
        name: reference
        for name, selector in selectors.items()
        if (reference := _selector_artifact(selector)) is not None
    }


def validated_outputs(
    worktree: Path, selectors: Mapping[str, OutputSelector]
) -> tuple[dict[str, object], dict[str, str]]:
    """Extract declared values and identify their required source files."""
    return extract_outputs(worktree, selectors), declared_output_artifacts(selectors)


def decoded_chunks(stream: BinaryIO) -> Iterator[str]:
    """Decode every output byte in bounded chunks, escaping malformed UTF-8."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="backslashreplace")
    while data := stream.read(_OUTPUT_READ_BYTES):
        text = decoder.decode(data)
        if text:
            yield text
    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail


def emit_output_stream(context: AttemptContext, stream: BinaryIO, event_type: str) -> None:
    """Persist a complete command stream as bounded ordered event chunks."""
    stream.seek(0)
    for chunk in decoded_chunks(stream):
        context.runtime.append_attempt_event(
            context.attempt.attempt_id,
            event_type,
            EventSource.COMMAND,
            {"chunk": chunk},
        )


__all__ = [
    "MissingNestedScopeRunner",
    "NestedScopeResult",
    "NestedScopeRunner",
    "SynchronousScopeRunner",
    "declared_output_artifacts",
    "decoded_chunks",
    "duration_seconds",
    "emit_output_stream",
    "expression_context",
    "parse_node",
    "validated_outputs",
]

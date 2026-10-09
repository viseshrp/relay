"""Compile stage repair policies without changing portable source documents."""

from __future__ import annotations

from collections.abc import Mapping

from relay.constants import REPAIR_NODE_PREFIX

from .schema import LoopNode, NodeDefinition, RepairAcceptance, Scalar, WorkflowDefinition


def accepted_verdict(outputs: Mapping[str, object], output: str, expected: Scalar) -> bool:
    """Compare JSON kinds and values; `True` never accepts the number `1`."""
    actual = outputs.get(output)
    # JSON has one number kind: 1.0 equals 1, while true remains a boolean.
    same_kind = type(actual) is type(expected) or (
        type(actual) in (int, float) and type(expected) in (int, float)
    )
    return output in outputs and same_kind and actual == expected


def compile_repairs(definition: WorkflowDefinition) -> WorkflowDefinition:
    """Add durable coordinators in O(V+E), retaining the original node identities."""
    enabled = {source: rule for source, rule in definition.repairs.items() if rule.enabled}
    if not enabled:
        return definition
    nodes = {}
    for node_id, node in definition.nodes.items():
        # review -> ship also waits for relay_repair_review -> ship. The source
        # report remains recorded even when a verifier later accepts its repairs.
        needs = [*node.needs, *(f"{REPAIR_NODE_PREFIX}{n}" for n in node.needs if n in enabled)]
        nodes[node_id] = node.model_copy(update={"needs": needs})
    for source, rule in enabled.items():
        nodes[f"{REPAIR_NODE_PREFIX}{source}"] = LoopNode(
            type="loop",
            needs=[source],
            max_iterations=rule.max_rounds,
            exhausted="",
            body={"fix": rule.fix, "verify": rule.verify.model_copy(update={"needs": ["fix"]})},
            repair_rule=RepairAcceptance(
                source=source,
                accepted_output=rule.accepted_output,
                accepted_value=rule.accepted_value,
                fix_instruction=rule.fix_instruction,
                verify_instruction=rule.verify_instruction,
            ),
        )
    return definition.model_copy(update={"nodes": nodes})


def effective_dependency_outputs(
    definitions: Mapping[str, NodeDefinition], outputs: Mapping[str, Mapping[str, object]]
) -> dict[str, Mapping[str, object]]:
    """Expose the accepted verifier's outputs under its original stage name."""
    result = dict(outputs)
    for node_id, values in outputs.items():
        node = definitions[node_id]
        if isinstance(node, LoopNode) and node.repair_rule is not None:
            result[node.repair_rule.source] = values
    return result

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { WorkflowNodeData } from "../workflow";
import { ActionIcon, StatusIcon, type ActionGlyph } from "./ActionIcon";

export function RunGraphNode({ data }: NodeProps<Node<WorkflowNodeData>>) {
  const kind: ActionGlyph =
    data.kind === "agent"
      ? "agent"
      : data.kind === "command"
        ? "command"
        : data.kind === "loop"
          ? "loop"
          : data.kind === "human_wait"
            ? "human"
            : "workflow";
  return (
    <div className="run-graph-node">
      <Handle type="target" position={Position.Left} />
      <StatusIcon
        status={typeof data.status === "string" ? data.status : "pending"}
      />
      <strong>
        <ActionIcon name={kind} size={14} /> {data.label.split("\n")[0]}
        {Array.isArray(data.members) && <small>Show all jobs</small>}
        {typeof data.agent === "string" && data.agent && (
          <small title={data.agent} className="graph-agent">
            {data.agent}
          </small>
        )}
      </strong>
      <span className="graph-duration">
        {typeof data.duration === "string" ? data.duration : ""}
      </span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

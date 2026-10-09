import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { WorkflowNodeData } from "../workflow";
import { StatusIcon } from "./ActionIcon";

export function RunGraphNode({ data }: NodeProps<Node<WorkflowNodeData>>) {
  return (
    <div className="run-graph-node">
      <Handle type="target" position={Position.Left} />
      <StatusIcon
        status={typeof data.status === "string" ? data.status : "pending"}
      />
      <strong>
        {data.label.split("\n")[0]}
        {Array.isArray(data.members) && <small>Show all jobs</small>}
      </strong>
      <span className="graph-duration">
        {typeof data.duration === "string" ? data.duration : ""}
      </span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

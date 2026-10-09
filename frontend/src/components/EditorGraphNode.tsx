import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { WorkflowNodeData } from "../workflow";
import { ActionIcon } from "./ActionIcon";

export function EditorGraphNode({ data }: NodeProps<Node<WorkflowNodeData>>) {
  return (
    <div
      className="editor-graph-node"
      title={`${data.label}\n${String(data.detail ?? "")}`}
    >
      <Handle type="target" position={Position.Left} />
      <ActionIcon name="workflow" />
      <strong>{data.label}</strong>
      <span>{String(data.detail ?? "")}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

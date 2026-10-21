import { Button } from "@mui/material";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { cardHeight } from "../actions-workflow";
import type { WorkflowNodeData } from "../workflow";
import { ActionIcon } from "./ActionIcon";

export function EditorGraphNode({ data }: NodeProps<Node<WorkflowNodeData>>) {
  const steps = Array.isArray(data.steps) ? data.steps.map(String) : [];
  const detail = typeof data.detail === "string" ? data.detail : "";
  const expandable =
    typeof data.childWorkflow === "string" &&
    typeof data.onExpand === "function";
  return (
    <div
      className="editor-graph-node"
      // The layout leaves this much room for the card.
      style={{
        height: cardHeight(
          steps.length,
          typeof data.childWorkflow === "string",
        ),
      }}
      title={[data.label, ...steps, detail].filter(Boolean).join("\n")}
    >
      <Handle type="target" position={Position.Left} />
      <ActionIcon name="workflow" />
      <strong>{data.label}</strong>
      {steps.length > 0 ? (
        <ol
          className="editor-graph-steps"
          aria-label={`Steps in ${data.label}`}
        >
          {steps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      ) : (
        <span>{detail}</span>
      )}
      {expandable && (
        <Button
          className="nodrag nopan"
          size="small"
          onClick={(event) => {
            event.stopPropagation();
            (data.onExpand as () => void)();
          }}
        >
          {data.loopBody ? "Expand loop body" : "Open child workflow"}
        </Button>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

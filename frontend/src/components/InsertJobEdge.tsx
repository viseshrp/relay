import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";
export function InsertJobEdge(props: EdgeProps) {
  const [path, x, y] = getBezierPath(props);
  return (
    <>
      <BaseEdge path={path} {...props} />
      <EdgeLabelRenderer>
        <button
          type="button"
          className="nodrag nopan insert-job"
          style={{
            transform: `translate(-50%, -50%) translate(${x}px,${y}px)`,
          }}
          aria-label={`Insert job between ${props.source} and ${props.target}`}
          onClick={() => {
            if (typeof props.data?.onInsert === "function")
              props.data.onInsert(props.source, props.target);
          }}
        >
          +
        </button>
      </EdgeLabelRenderer>
    </>
  );
}

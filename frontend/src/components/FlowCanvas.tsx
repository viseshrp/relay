import {
  Background,
  Controls,
  type Edge,
  MiniMap,
  type Node,
  type NodeMouseHandler,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import { useEffect } from "react";

import type { WorkflowNodeData } from "../workflow";

interface FlowCanvasProps {
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
}

export function FlowCanvas({ nodes, edges, selectedId, onSelect }: FlowCanvasProps) {
  const [visibleNodes, setNodes, onNodesChange] = useNodesState(nodes);
  const [visibleEdges, setEdges, onEdgesChange] = useEdgesState(edges);

  useEffect(() => {
    setNodes((current) =>
      nodes.map((node) => ({
        ...node,
        position: current.find((item) => item.id === node.id)?.position ?? node.position,
        selected: node.id === selectedId,
      })),
    );
  }, [nodes, selectedId, setNodes]);

  useEffect(() => setEdges(edges), [edges, setEdges]);

  const selectNode: NodeMouseHandler = (_event, node) => onSelect?.(node.id);

  return (
    <div className="flow-canvas">
      <ReactFlow
        nodes={visibleNodes}
        edges={visibleEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={selectNode}
        fitView
        minZoom={0.25}
        maxZoom={1.75}
      >
        <MiniMap pannable zoomable />
        <Controls />
        <Background gap={20} size={1} />
      </ReactFlow>
    </div>
  );
}

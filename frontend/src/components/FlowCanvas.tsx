import {
  Background,
  Controls,
  getNodesBounds,
  type Edge,
  MiniMap,
  type Node,
  type NodeMouseHandler,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useNodesInitialized,
  useReactFlow,
} from "@xyflow/react";
import { useEffect, useRef } from "react";
import type { RefObject } from "react";

import { RunGraphNode } from "./RunGraphNode";

import type { WorkflowNodeData } from "../workflow";

const RUN_NODE_TYPES = { runJob: RunGraphNode };

interface FlowCanvasProps {
  runMode?: boolean;
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  followSelection?: boolean;
  focusRequest?: number;
  initialFocusId?: string | null;
}

function FocusStep({ selectedId, focusRequest }: { selectedId?: string | null; focusRequest: number }) {
  const initialized = useNodesInitialized();
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (initialized && selectedId) void fitView({ nodes: [{ id: selectedId }], padding: 0.6, minZoom: 0.8, maxZoom: 1 });
  }, [initialized, selectedId, focusRequest, fitView]);
  return null;
}

function InitialRunViewport({ container }: { container: RefObject<HTMLDivElement | null> }) {
  const initialized = useNodesInitialized();
  const positioned = useRef(false);
  const { getNodes, fitView, setViewport } = useReactFlow();
  useEffect(() => {
    if (!initialized || positioned.current || !container.current) return;
    const nodes = getNodes();
    const first = nodes[0];
    if (!first) return;
    positioned.current = true;
    const bounds = getNodesBounds(nodes);
    const available = container.current;
    const zoom = Math.min(available.clientWidth / (bounds.width * 1.4), available.clientHeight / (bounds.height * 1.4));
    if (zoom < 0.65) {
      void setViewport({ x: 24 - first.position.x * 0.8, y: 24 - first.position.y * 0.8, zoom: 0.8 });
    } else {
      void fitView({ padding: 0.2, minZoom: 0.65, maxZoom: 1 });
    }
  }, [initialized, container, getNodes, fitView, setViewport]);
  return null;
}

export function FlowCanvas({ runMode = false, nodes, edges, selectedId, onSelect, followSelection = false, focusRequest = 0, initialFocusId }: FlowCanvasProps) {
  const container = useRef<HTMLDivElement>(null);
  const [visibleNodes, setNodes, onNodesChange] = useNodesState(nodes);
  const [visibleEdges, setEdges, onEdgesChange] = useEdgesState(edges);

  useEffect(() => {
    setNodes((current) => {
      const previous = new Map(current.map((node) => [node.id, node]));
      return nodes.map((node) => ({
        ...node,
        // A status refresh keeps the same renderer and its measured handles.
        // ResizeObserver reports actual size changes; clearing measurements
        // can hide edges when the node's size has not changed.
        measured: node.measured ?? (previous.get(node.id)?.type === node.type ? previous.get(node.id)?.measured : undefined),
        position: followSelection || runMode ? node.position : previous.get(node.id)?.position ?? node.position,
        selected: node.id === selectedId,
      }));
    });
  }, [nodes, selectedId, setNodes, followSelection, runMode]);

  useEffect(() => setEdges(edges), [edges, setEdges]);

  const selectNode: NodeMouseHandler = (_event, node) => onSelect?.(node.id);

  return (
    <div ref={container} className="flow-canvas" onKeyDown={runMode ? (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const target = event.target;
      if (!(target instanceof HTMLElement) || !target.classList.contains("react-flow__node")) return;
      const id = target.dataset.id;
      if (id) { event.preventDefault(); onSelect?.(id); }
    } : undefined}>
      <ReactFlow
        nodes={visibleNodes}
        edges={visibleEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={selectNode}
        nodeTypes={runMode ? RUN_NODE_TYPES : undefined}
        nodesDraggable={!runMode}
        zoomOnScroll={!runMode}
        preventScrolling={!runMode}
        panOnScroll={false}
        zoomOnDoubleClick={!runMode}
        fitViewOptions={runMode ? { padding: 0.2, minZoom: 0.65, maxZoom: 1 } : undefined}
        fitView={!runMode}
        minZoom={0.25}
        maxZoom={1.75}
      >
        {runMode && <InitialRunViewport container={container} />}
        {/* Authoring can focus a stage while retaining manually dragged positions. */}
        {(followSelection || initialFocusId) && <FocusStep selectedId={selectedId ?? initialFocusId} focusRequest={focusRequest} />}
        {!runMode && <MiniMap pannable zoomable />}
        <Controls position={runMode ? "bottom-right" : "bottom-left"} showInteractive={!runMode} />
        {!runMode && <Background gap={20} size={1} />}
      </ReactFlow>
    </div>
  );
}

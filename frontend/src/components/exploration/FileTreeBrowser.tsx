import type { FileTreeNode } from "@/types/api";

export function FileTreeBrowser({
  nodes,
  selected,
  onToggle,
}: {
  nodes: FileTreeNode[];
  selected: string[];
  onToggle: (path: string) => void;
}) {
  return (
    <div className="space-y-2 text-sm">
      {nodes.map((node) => (
        <div key={node.path} className="space-y-2">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={selected.includes(node.path)} onChange={() => onToggle(node.path)} />
            <span>{node.name}</span>
          </label>
          {node.children.length ? <div className="ml-4 border-l border-border pl-4"><FileTreeBrowser nodes={node.children} selected={selected} onToggle={onToggle} /></div> : null}
        </div>
      ))}
    </div>
  );
}

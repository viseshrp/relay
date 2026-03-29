import { useQuery } from "@tanstack/react-query";

import { getProjectFiles } from "@/api/projects";
import { FileTreeBrowser } from "@/components/exploration/FileTreeBrowser";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet } from "@/components/ui/sheet";

export function ContextPanel({
  open,
  onOpenChange,
  projectId,
  selected,
  onToggle,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  selected: string[];
  onToggle: (path: string) => void;
}) {
  const { data } = useQuery({ queryKey: ["files", projectId], queryFn: () => getProjectFiles(projectId), enabled: open });
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <div className="space-y-4">
        <div>
          <h3 className="text-lg font-semibold">Context Paths</h3>
          <p className="text-sm text-muted-foreground">Select files and folders to carry into later phases.</p>
        </div>
        <ScrollArea className="h-[80vh] pr-2">
          <FileTreeBrowser nodes={data ?? []} selected={selected} onToggle={onToggle} />
        </ScrollArea>
      </div>
    </Sheet>
  );
}

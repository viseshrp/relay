import { useQuery } from "@tanstack/react-query";

import { getProjectFiles } from "@/api/projects";
import { FileTreeBrowser } from "@/components/exploration/FileTreeBrowser";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";

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
      <SheetContent>
        <div className="space-y-4">
          <SheetHeader>
            <SheetTitle>Context Paths</SheetTitle>
            <SheetDescription>Select files and folders to carry into later phases.</SheetDescription>
          </SheetHeader>
          <ScrollArea className="h-[80vh] pr-2">
            <FileTreeBrowser nodes={data ?? []} selected={selected} onToggle={onToggle} />
          </ScrollArea>
        </div>
      </SheetContent>
    </Sheet>
  );
}

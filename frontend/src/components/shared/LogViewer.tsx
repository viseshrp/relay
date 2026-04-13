import { ScrollArea } from "@/components/ui/scroll-area";

export function LogViewer({ lines }: { lines: string[] }) {
  return (
    <ScrollArea className="max-h-[26rem] rounded-[1.5rem] border border-border bg-slate-950 p-4 font-mono text-xs text-slate-100">
      <pre className="whitespace-pre-wrap">{lines.join("")}</pre>
    </ScrollArea>
  );
}

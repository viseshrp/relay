import type { ExplorationMessage } from "@/types/api";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

export function ChatThread({ messages }: { messages: ExplorationMessage[] }) {
  return (
    <ScrollArea className="h-[32rem] space-y-4 rounded-[2rem] border border-border bg-card p-4">
      <div className="space-y-4">
        {messages.map((message) => (
          <div key={`${message.id}-${message.sequence_number}`} className={cn("max-w-[85%] rounded-[1.75rem] p-4 text-sm", message.role === "user" ? "ml-auto bg-primary text-primary-foreground" : "bg-secondary text-secondary-foreground")}>
            {message.content || "Streaming..."}
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}

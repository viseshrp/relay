import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import { Card } from "@/components/ui/card";

export function PhasePromptTab({ prompt }: { prompt: string }) {
  return (
    <Card>
      <MarkdownRenderer content={prompt || "No prompt recorded yet."} />
    </Card>
  );
}

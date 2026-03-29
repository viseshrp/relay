import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import { Card } from "@/components/ui/card";

export function PlanningPromptView({ content }: { content: string }) {
  return (
    <Card>
      <MarkdownRenderer content={content} />
    </Card>
  );
}

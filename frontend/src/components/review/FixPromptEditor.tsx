import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";

export function FixPromptEditor({
  open,
  initialValue,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  initialValue: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (value: string) => Promise<unknown>;
}) {
  const [value, setValue] = useState(initialValue);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <div className="space-y-4">
        <h3 className="text-lg font-semibold">Fix Prompt</h3>
        <Textarea value={value} onChange={(event) => setValue(event.target.value)} />
        <Button onClick={() => void onSubmit(value)}>Send to Fix</Button>
      </div>
    </Sheet>
  );
}

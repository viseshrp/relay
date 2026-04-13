import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function ChatInput({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (content: string) => Promise<unknown>;
}) {
  const [value, setValue] = useState("");
  return (
    <div className="space-y-3">
      <Textarea value={value} onChange={(event) => setValue(event.target.value)} disabled={disabled} placeholder="Describe the problem, constraints, and desired outcome." />
      <div className="flex justify-end">
        <Button
          onClick={async () => {
            if (!value.trim()) {
              return;
            }
            await onSend(value);
            setValue("");
          }}
          disabled={disabled}
        >
          Send
        </Button>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
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

  useEffect(() => {
    setValue(initialValue);
  }, [initialValue]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <div className="space-y-4">
          <SheetHeader>
            <SheetTitle>Fix Prompt</SheetTitle>
          </SheetHeader>
          <Textarea className="min-h-[24rem]" value={value} onChange={(event) => setValue(event.target.value)} />
          <SheetFooter>
            <Button onClick={() => void onSubmit(value)}>Send to Fix</Button>
          </SheetFooter>
        </div>
      </SheetContent>
    </Sheet>
  );
}

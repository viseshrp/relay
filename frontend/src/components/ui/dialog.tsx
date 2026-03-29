import * as React from "react";

import { cn } from "@/lib/utils";

export function Dialog({
  open,
  onOpenChange,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}) {
  if (!open) {
    return null;
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4" onClick={() => onOpenChange(false)}>
      <div className={cn("w-full max-w-lg rounded-[2rem] border border-border bg-card p-6 shadow-panel")} onClick={(event) => event.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

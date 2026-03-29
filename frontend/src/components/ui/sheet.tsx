import * as React from "react";

import { cn } from "@/lib/utils";

export function Sheet({
  open,
  onOpenChange,
  side = "right",
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  side?: "left" | "right";
  children: React.ReactNode;
}) {
  if (!open) {
    return null;
  }
  return (
    <div className="fixed inset-0 z-50 bg-slate-950/40" onClick={() => onOpenChange(false)}>
      <div
        className={cn(
          "absolute top-0 h-full w-full max-w-xl border-l border-border bg-card p-6 shadow-panel",
          side === "right" ? "right-0" : "left-0 border-r border-l-0",
        )}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

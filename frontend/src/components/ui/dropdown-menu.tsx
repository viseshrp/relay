import * as React from "react";

import { cn } from "@/lib/utils";

export function DropdownMenu({
  open,
  anchor,
  children,
}: {
  open: boolean;
  anchor: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="relative inline-flex">
      {anchor}
      {open ? <div className={cn("absolute right-0 top-full z-50 mt-2 min-w-[12rem] rounded-2xl border border-border bg-card p-2 shadow-panel")}>{children}</div> : null}
    </div>
  );
}

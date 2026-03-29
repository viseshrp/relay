import * as React from "react";

import { cn } from "@/lib/utils";

export function Card({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-[2rem] border border-border bg-card p-6 shadow-panel", className)}>{children}</div>;
}

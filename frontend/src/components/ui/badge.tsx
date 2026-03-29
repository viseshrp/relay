import * as React from "react";

import { cn } from "@/lib/utils";

export function Badge({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("inline-flex rounded-full bg-secondary px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em]", className)}>{children}</div>;
}

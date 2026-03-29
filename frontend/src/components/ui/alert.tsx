import * as React from "react";

import { cn } from "@/lib/utils";

export function Alert({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-[1.5rem] border border-destructive/20 bg-destructive/10 p-4 text-sm text-foreground", className)}>{children}</div>;
}

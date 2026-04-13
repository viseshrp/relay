import * as React from "react";

import { cn } from "@/lib/utils";

export function Alert({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-[1.5rem] border border-destructive/20 bg-destructive/10 p-4 text-sm text-foreground", className)}>{children}</div>;
}

export function AlertTitle({ className, children }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h5 className={cn("font-semibold", className)}>{children}</h5>;
}

export function AlertDescription({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mt-1 text-sm text-muted-foreground", className)}>{children}</div>;
}

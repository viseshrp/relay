import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = {
  default: "bg-primary text-primary-foreground",
  secondary: "bg-secondary text-secondary-foreground",
} as const;

export function Badge({
  className,
  variant = "secondary",
  children,
}: React.HTMLAttributes<HTMLDivElement> & { variant?: keyof typeof badgeVariants }) {
  return <div className={cn("inline-flex rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em]", badgeVariants[variant], className)}>{children}</div>;
}

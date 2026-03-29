import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "flex h-10 w-full rounded-2xl border border-border bg-card px-4 py-2 text-sm shadow-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-ring/30",
      className,
    )}
    {...props}
  />
));

Input.displayName = "Input";

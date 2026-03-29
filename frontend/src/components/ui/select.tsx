import * as React from "react";

import { cn } from "@/lib/utils";

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  options?: Array<{ label: string; value: string }>;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(({ className, children, options, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(
      "flex h-10 w-full rounded-2xl border border-border bg-card px-4 py-2 text-sm shadow-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-ring/30",
      className,
    )}
    {...props}
  >
    {options?.map((option) => (
      <option key={option.value} value={option.value}>
        {option.label}
      </option>
    ))}
    {children}
  </select>
));

Select.displayName = "Select";

import * as React from "react";

import { cn } from "@/lib/utils";

export function Table({ className, children }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto rounded-[1.75rem] border border-border bg-card">
      <table className={cn("min-w-full text-sm", className)}>{children}</table>
    </div>
  );
}

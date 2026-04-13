import * as React from "react";

import { cn } from "@/lib/utils";

export function Table({ className, children }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto rounded-[1.75rem] border border-border bg-card">
      <table className={cn("min-w-full text-sm", className)}>{children}</table>
    </div>
  );
}

export function TableHeader({ className, children }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("bg-secondary/60", className)}>{children}</thead>;
}

export function TableBody({ className, children }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={className}>{children}</tbody>;
}

export function TableRow({ className, children }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("border-t border-border", className)}>{children}</tr>;
}

export function TableHead({ className, children }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("px-4 py-3 text-left font-medium", className)}>{children}</th>;
}

export function TableCell({ className, children }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-4 py-3 align-top", className)}>{children}</td>;
}

import * as React from "react";

import { cn } from "@/lib/utils";

type SheetContextValue = {
  side: "left" | "right";
  onOpenChange: (open: boolean) => void;
};

const SheetContext = React.createContext<SheetContextValue | null>(null);

export function Sheet({
  open,
  onOpenChange,
  side = "right",
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  side?: "left" | "right";
  children: React.ReactNode;
}) {
  if (!open) {
    return null;
  }
  return (
    <SheetContext.Provider value={{ side, onOpenChange }}>
      <div className="fixed inset-0 z-50 bg-slate-950/40" onClick={() => onOpenChange(false)}>
        {children}
      </div>
    </SheetContext.Provider>
  );
}

export function SheetContent({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  const context = React.useContext(SheetContext);
  if (context === null) {
    throw new Error("SheetContent must be used within Sheet.");
  }
  return (
    <div
      className={cn(
        "absolute top-0 h-full w-full max-w-xl border-l border-border bg-card p-6 shadow-panel",
        context.side === "right" ? "right-0" : "left-0 border-r border-l-0",
        className,
      )}
      onClick={(event) => event.stopPropagation()}
    >
      {children}
    </div>
  );
}

export function SheetHeader({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("space-y-2", className)}>{children}</div>;
}

export function SheetTitle({ className, children }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-lg font-semibold", className)}>{children}</h2>;
}

export function SheetDescription({ className, children }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)}>{children}</p>;
}

export function SheetFooter({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex justify-end gap-3", className)}>{children}</div>;
}

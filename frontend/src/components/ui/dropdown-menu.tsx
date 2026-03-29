import * as React from "react";

import { cn } from "@/lib/utils";

type DropdownMenuContextValue = {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
};

const DropdownMenuContext = React.createContext<DropdownMenuContextValue | null>(null);

export function DropdownMenu({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = React.useState(false);
  return (
    <DropdownMenuContext.Provider value={{ isOpen, setIsOpen }}>
      <div className="relative inline-flex">{children}</div>
    </DropdownMenuContext.Provider>
  );
}

export function DropdownMenuTrigger({
  asChild = false,
  children,
}: {
  asChild?: boolean;
  children: React.ReactNode;
}) {
  const context = React.useContext(DropdownMenuContext);
  if (context === null) {
    throw new Error("DropdownMenuTrigger must be used within DropdownMenu.");
  }

  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(children, {
      onClick: () => context.setIsOpen(!context.isOpen),
    });
  }

  return (
    <button type="button" onClick={() => context.setIsOpen(!context.isOpen)}>
      {children}
    </button>
  );
}

export function DropdownMenuContent({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  const context = React.useContext(DropdownMenuContext);
  if (context === null) {
    throw new Error("DropdownMenuContent must be used within DropdownMenu.");
  }
  if (!context.isOpen) {
    return null;
  }
  return <div className={cn("absolute right-0 top-full z-50 mt-2 min-w-[12rem] rounded-2xl border border-border bg-card p-2 shadow-panel", className)}>{children}</div>;
}

export function DropdownMenuCheckboxItem({
  checked,
  onCheckedChange,
  className,
  children,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={cn("flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm transition hover:bg-secondary/60", className)}
      onClick={() => onCheckedChange(!checked)}
    >
      <span className={cn("flex h-4 w-4 items-center justify-center rounded border border-border text-[10px]", checked && "bg-primary text-primary-foreground")}>
        {checked ? "✓" : ""}
      </span>
      <span>{children}</span>
    </button>
  );
}

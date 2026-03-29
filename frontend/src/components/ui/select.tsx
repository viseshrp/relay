import * as React from "react";

import { cn } from "@/lib/utils";

type SelectContextValue = {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  value: string;
  onValueChange: (value: string) => void;
  selectedLabel: string | null;
  registerItem: (value: string, label: string) => void;
  disabled: boolean;
};

const SelectContext = React.createContext<SelectContextValue | null>(null);

export function Select({
  value,
  onValueChange,
  disabled = false,
  children,
}: {
  value: string;
  onValueChange: (value: string) => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = React.useState(false);
  const [labels, setLabels] = React.useState<Record<string, string>>({});

  const registerItem = React.useCallback((itemValue: string, label: string) => {
    setLabels((current) => (current[itemValue] === label ? current : { ...current, [itemValue]: label }));
  }, []);

  return (
    <SelectContext.Provider
      value={{
        isOpen,
        setIsOpen,
        value,
        onValueChange,
        selectedLabel: labels[value] ?? null,
        registerItem,
        disabled,
      }}
    >
      <div className="relative">{children}</div>
    </SelectContext.Provider>
  );
}

export function SelectTrigger({ className, children }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const context = React.useContext(SelectContext);
  if (context === null) {
    throw new Error("SelectTrigger must be used within Select.");
  }
  return (
    <button
      type="button"
      className={cn(
        "flex h-10 w-full items-center justify-between rounded-2xl border border-border bg-card px-4 py-2 text-sm shadow-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      disabled={context.disabled}
      onClick={() => {
        if (!context.disabled) {
          context.setIsOpen(!context.isOpen);
        }
      }}
    >
      {children}
    </button>
  );
}

export function SelectValue({ placeholder }: { placeholder?: string }) {
  const context = React.useContext(SelectContext);
  if (context === null) {
    throw new Error("SelectValue must be used within Select.");
  }
  return <span className={cn(!context.selectedLabel && "text-muted-foreground")}>{context.selectedLabel ?? placeholder ?? ""}</span>;
}

export function SelectContent({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  const context = React.useContext(SelectContext);
  if (context === null) {
    throw new Error("SelectContent must be used within Select.");
  }
  if (!context.isOpen || context.disabled) {
    return null;
  }
  return <div className={cn("absolute z-50 mt-2 w-full rounded-2xl border border-border bg-card p-2 shadow-panel", className)}>{children}</div>;
}

export function SelectItem({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children: React.ReactNode;
}) {
  const context = React.useContext(SelectContext);
  if (context === null) {
    throw new Error("SelectItem must be used within Select.");
  }

  const label = typeof children === "string" ? children : String(children);
  React.useEffect(() => {
    context.registerItem(value, label);
  }, [context, label, value]);

  const isSelected = context.value === value;
  return (
    <button
      type="button"
      className={cn(
        "flex w-full rounded-xl px-3 py-2 text-left text-sm transition hover:bg-secondary/60",
        isSelected && "bg-secondary text-secondary-foreground",
        className,
      )}
      onClick={() => {
        if (!context.disabled) {
          context.onValueChange(value);
          context.setIsOpen(false);
        }
      }}
    >
      {children}
    </button>
  );
}

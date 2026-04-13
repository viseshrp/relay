import * as React from "react";

import { cn } from "@/lib/utils";

type SelectContextValue = {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  value: string;
  onValueChange: (value: string) => void;
  selectedLabel: string | null;
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
  const rootRef = React.useRef<HTMLDivElement>(null);
  // Collect labels from the full child tree so saved values render correctly
  // even before a menu has ever been opened.
  const labels = React.useMemo(() => extractSelectLabels(children), [children]);

  React.useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current?.contains(event.target as Node)) {
        return;
      }
      setIsOpen(false);
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [isOpen]);

  return (
    <SelectContext.Provider
      value={{
        isOpen,
        setIsOpen,
        value,
        onValueChange,
        selectedLabel: labels[value] ?? null,
        disabled,
      }}
    >
      <div ref={rootRef} className="relative">
        {children}
      </div>
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
      aria-expanded={context.isOpen}
      aria-haspopup="listbox"
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
  return (
    <div
      className={cn(
        "absolute left-0 top-full z-50 mt-2 max-h-72 w-full overflow-y-auto overscroll-contain rounded-2xl border border-border bg-card p-2 shadow-panel",
        className,
      )}
      role="listbox"
    >
      {children}
    </div>
  );
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

  const isSelected = context.value === value;
  return (
    <button
      type="button"
      role="option"
      aria-selected={isSelected}
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

function extractSelectLabels(children: React.ReactNode): Record<string, string> {
  const labels: Record<string, string> = {};

  React.Children.forEach(children, (child) => {
    if (!React.isValidElement(child)) {
      return;
    }

    if (child.type === SelectItem) {
      const props = child.props as { value: string; children: React.ReactNode };
      labels[props.value] = extractTextContent(props.children);
      return;
    }

    const nestedChildren = (child.props as { children?: React.ReactNode }).children;
    if (nestedChildren !== undefined) {
      Object.assign(labels, extractSelectLabels(nestedChildren));
    }
  });

  return labels;
}

function extractTextContent(children: React.ReactNode): string {
  if (typeof children === "string" || typeof children === "number") {
    return String(children);
  }
  if (Array.isArray(children)) {
    return children.map((child) => extractTextContent(child)).join("").trim();
  }
  if (!React.isValidElement(children)) {
    return "";
  }
  const nestedChildren = (children.props as { children?: React.ReactNode }).children;
  return extractTextContent(nestedChildren);
}

import * as React from "react";

import { cn } from "@/lib/utils";

type TabsContextValue = {
  activeValue: string;
  setActiveValue: (value: string) => void;
};

const TabsContext = React.createContext<TabsContextValue | null>(null);

export function Tabs({
  value,
  defaultValue,
  onValueChange,
  className,
  children,
}: {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const [internalValue, setInternalValue] = React.useState(defaultValue ?? value ?? "");
  const activeValue = value ?? internalValue;

  const setActiveValue = React.useCallback(
    (nextValue: string) => {
      if (value === undefined) {
        setInternalValue(nextValue);
      }
      onValueChange?.(nextValue);
    },
    [onValueChange, value],
  );

  return (
    <TabsContext.Provider value={{ activeValue, setActiveValue }}>
      <div className={cn("space-y-4", className)}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-wrap gap-2 rounded-full bg-secondary/60 p-1", className)}>{children}</div>;
}

export function TabsTrigger({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children: React.ReactNode;
}) {
  const context = React.useContext(TabsContext);
  if (context === null) {
    throw new Error("TabsTrigger must be used within Tabs.");
  }
  const isActive = context.activeValue === value;
  return (
    <button
      type="button"
      className={cn(
        "rounded-full px-3 py-2 text-sm transition",
        isActive ? "bg-card text-foreground shadow-sm" : "text-muted-foreground",
        className,
      )}
      onClick={() => context.setActiveValue(value)}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children: React.ReactNode;
}) {
  const context = React.useContext(TabsContext);
  if (context === null) {
    throw new Error("TabsContent must be used within Tabs.");
  }
  if (context.activeValue !== value) {
    return null;
  }
  return <div className={className}>{children}</div>;
}

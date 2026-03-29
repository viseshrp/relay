import * as React from "react";

import { cn } from "@/lib/utils";

export function Tabs({
  value,
  onValueChange,
  tabs,
}: {
  value: string;
  onValueChange: (value: string) => void;
  tabs: Array<{ value: string; label: string; content: React.ReactNode }>;
}) {
  const active = tabs.find((tab) => tab.value === value) ?? tabs[0];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 rounded-full bg-secondary/60 p-1">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            type="button"
            className={cn(
              "rounded-full px-3 py-2 text-sm transition",
              tab.value === active.value ? "bg-card text-foreground shadow-sm" : "text-muted-foreground",
            )}
            onClick={() => onValueChange(tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div>{active.content}</div>
    </div>
  );
}

import * as React from "react";

import { cn } from "@/lib/utils";

export function Toggle({
  pressed,
  onPressedChange,
  children,
  className,
}: {
  pressed: boolean;
  onPressedChange: (value: boolean) => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-9 items-center rounded-full border border-border px-4 text-sm transition",
        pressed ? "bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
        className,
      )}
      onClick={() => onPressedChange(!pressed)}
    >
      {children}
    </button>
  );
}

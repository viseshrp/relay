import * as React from "react";

import { cn } from "@/lib/utils";

type DialogContextValue = {
  onOpenChange: (open: boolean) => void;
};

const DialogContext = React.createContext<DialogContextValue | null>(null);

export function Dialog({
  open,
  onOpenChange,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}) {
  if (!open) {
    return null;
  }
  return (
    <DialogContext.Provider value={{ onOpenChange }}>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4" onClick={() => onOpenChange(false)}>
        {children}
      </div>
    </DialogContext.Provider>
  );
}

export function DialogContent({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("w-full max-w-lg rounded-[2rem] border border-border bg-card p-6 shadow-panel", className)} onClick={(event) => event.stopPropagation()}>
      {children}
    </div>
  );
}

export function DialogHeader({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("space-y-2", className)}>{children}</div>;
}

export function DialogTitle({ className, children }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-xl font-semibold", className)}>{children}</h2>;
}

export function DialogDescription({ className, children }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)}>{children}</p>;
}

export function DialogFooter({ className, children }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex justify-end gap-3", className)}>{children}</div>;
}

export function DialogClose({ className, children }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const context = React.useContext(DialogContext);
  if (context === null) {
    throw new Error("DialogClose must be used within Dialog.");
  }
  return (
    <button type="button" className={className} onClick={() => context.onOpenChange(false)}>
      {children}
    </button>
  );
}

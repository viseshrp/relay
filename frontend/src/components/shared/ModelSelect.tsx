import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { ModelOption } from "@/types/api";

type ModelSelectProps = {
  value: string;
  options: ModelOption[];
  disabled?: boolean;
  placeholder: string;
  onValueChange: (value: string) => void;
};

export function ModelSelect({
  value,
  options,
  disabled = false,
  placeholder,
  onValueChange,
}: ModelSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number; width: number } | null>(null);

  const selectedOption = useMemo(
    () => options.find((option) => option.id === value) ?? null,
    [options, value],
  );

  const filteredOptions = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (normalizedQuery === "") {
      return options;
    }

    // Model catalogs are small, so a single linear scan keeps the code simple
    // while still matching both human-readable labels and exact model ids.
    return options.filter((option) => {
      const searchableText = `${option.name} ${option.id}`.toLowerCase();
      return searchableText.includes(normalizedQuery);
    });
  }, [options, query]);

  useEffect(() => {
    if (disabled) {
      setIsOpen(false);
      setQuery("");
      setMenuPosition(null);
    }
  }, [disabled]);

  useEffect(() => {
    if (!isOpen) {
      setMenuPosition(null);
      return;
    }

    updateMenuPosition(triggerRef, setMenuPosition);
    const focusTimer = window.requestAnimationFrame(() => searchInputRef.current?.focus());

    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current?.contains(event.target as Node) || menuRef.current?.contains(event.target as Node)) {
        return;
      }
      setIsOpen(false);
      setQuery("");
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      setIsOpen(false);
      setQuery("");
    };

    const handleViewportChange = () => {
      updateMenuPosition(triggerRef, setMenuPosition);
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    window.addEventListener("resize", handleViewportChange);
    window.addEventListener("scroll", handleViewportChange, true);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
      window.removeEventListener("resize", handleViewportChange);
      window.removeEventListener("scroll", handleViewportChange, true);
      window.cancelAnimationFrame(focusTimer);
    };
  }, [isOpen]);

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        className={cn(
          "flex h-10 w-full items-center justify-between rounded-2xl border border-border bg-card px-4 py-2 text-sm shadow-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60",
        )}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        disabled={disabled}
        onClick={() => {
          if (disabled) {
            return;
          }
          const nextIsOpen = !isOpen;
          setIsOpen(nextIsOpen);
          if (nextIsOpen) {
            setQuery("");
          }
        }}
      >
        <span className={cn(selectedOption === null && "text-muted-foreground")}>
          {selectedOption?.name ?? placeholder}
        </span>
      </button>

      {isOpen && menuPosition !== null
        ? createPortal(
            <div
              ref={menuRef}
              className="fixed z-[100] rounded-2xl border border-border bg-card p-2 shadow-panel"
              style={{
                top: menuPosition.top,
                left: menuPosition.left,
                width: menuPosition.width,
              }}
            >
              <div className="space-y-2">
                <Input
                  ref={searchInputRef}
                  value={query}
                  placeholder="Search models"
                  className="h-9"
                  onChange={(event) => setQuery(event.target.value)}
                />
                <div className="max-h-72 overflow-y-auto overscroll-contain" role="listbox">
                  {filteredOptions.length > 0 ? (
                    filteredOptions.map((option) => {
                      const isSelected = option.id === value;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          role="option"
                          aria-selected={isSelected}
                          className={cn(
                            "flex w-full rounded-xl px-3 py-2 text-left text-sm transition hover:bg-secondary/60",
                            isSelected && "bg-secondary text-secondary-foreground",
                          )}
                          onClick={() => {
                            onValueChange(option.id);
                            setIsOpen(false);
                            setQuery("");
                          }}
                        >
                          {option.name}
                        </button>
                      );
                    })
                  ) : (
                    <div className="px-3 py-2 text-sm text-muted-foreground">
                      No matching models.
                    </div>
                  )}
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}

function updateMenuPosition(
  triggerRef: { current: HTMLButtonElement | null },
  setMenuPosition: (position: { top: number; left: number; width: number } | null) => void,
) {
  const trigger = triggerRef.current;
  if (trigger === null) {
    setMenuPosition(null);
    return;
  }

  // The menu is rendered in a fixed portal so it never changes the layout of
  // the surrounding table or card. Its position is recomputed from the trigger.
  const rect = trigger.getBoundingClientRect();
  setMenuPosition({
    top: rect.bottom + 8,
    left: rect.left,
    width: rect.width,
  });
}

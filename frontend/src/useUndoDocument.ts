import { useCallback, useRef, useState } from "react";

export function useUndoDocument() {
  const [text, setRaw] = useState(""); const past = useRef<string[]>([]); const future = useRef<string[]>([]);
  const value = useRef("");
  const setText = useCallback((next: string) => {
    if (next === value.current) return;
    past.current = [...past.current.slice(-99), value.current]; future.current = [];
    value.current = next; setRaw(next);
  }, []);
  const reset = useCallback(() => { past.current = []; future.current = []; }, []);
  const undo = useCallback(() => { const next = past.current.pop(); if (next === undefined) return; future.current.push(value.current); value.current = next; setRaw(next); }, []);
  const redo = useCallback(() => { const next = future.current.pop(); if (next === undefined) return; past.current.push(value.current); value.current = next; setRaw(next); }, []);
  return { text, setText, reset, undo, redo, canUndo: past.current.length > 0, canRedo: future.current.length > 0 };
}

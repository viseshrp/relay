import { useState } from "react";

function storedPanels(key: string): Record<string, boolean> {
  try {
    const value: unknown = JSON.parse(
      sessionStorage.getItem(`relay.panels.${key}`) ?? "{}",
    );
    return value && typeof value === "object" && !Array.isArray(value)
      ? Object.fromEntries(
          Object.entries(value).filter(
            ([, expanded]) => typeof expanded === "boolean",
          ),
        )
      : {};
  } catch {
    return {};
  }
}

export function useDisclosureState(
  key: string,
): [Record<string, boolean>, (name: string, expanded: boolean) => void] {
  const [states, setStates] = useState<Record<string, Record<string, boolean>>>(
    {},
  );
  return [
    states[key] ?? storedPanels(key),
    (name, expanded) => {
      const next = { ...(states[key] ?? storedPanels(key)), [name]: expanded };
      try {
        sessionStorage.setItem(`relay.panels.${key}`, JSON.stringify(next));
      } catch {
        /* Session storage is optional. */
      }
      setStates((current) => ({ ...current, [key]: next }));
    },
  ];
}

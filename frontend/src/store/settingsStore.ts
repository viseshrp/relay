import { create } from "zustand";

const THEME_STORAGE_KEY = "relay-theme";

function initialTheme(): string {
  if (typeof window === "undefined") {
    return "system";
  }
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  return savedTheme === "light" || savedTheme === "dark" || savedTheme === "system" ? savedTheme : "system";
}

interface SettingsState {
  autopilot: boolean;
  theme: string;
  setAutopilot: (value: boolean) => void;
  setTheme: (value: string) => void;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  autopilot: true,
  theme: initialTheme(),
  setAutopilot: (autopilot) => set({ autopilot }),
  setTheme: (theme) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    }
    set({ theme });
  },
}));

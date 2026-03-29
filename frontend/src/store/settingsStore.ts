import { create } from "zustand";

interface SettingsState {
  autopilot: boolean;
  theme: string;
  setAutopilot: (value: boolean) => void;
  setTheme: (value: string) => void;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  autopilot: true,
  theme: "system",
  setAutopilot: (autopilot) => set({ autopilot }),
  setTheme: (theme) => set({ theme }),
}));

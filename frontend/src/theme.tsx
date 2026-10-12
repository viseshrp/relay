import { CssBaseline, ThemeProvider } from "@mui/material";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  applyThemeToDocument,
  getStoredThemePreference,
  getSystemTheme,
  setStoredThemePreference,
} from "./document-theme";
import { createRelayTheme } from "./theme-factory";
import type { ResolvedTheme, ThemePreference } from "./tokens";

export * from "./tokens";
export * from "./document-theme";
export * from "./theme-factory";

interface ThemeContextValue {
  preference: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setPreference: (pref: ThemePreference) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  preference: "system",
  resolvedTheme: "light",
  setPreference: () => {},
  toggleTheme: () => {},
});

export function useThemeMode(): ThemeContextValue {
  return useContext(ThemeContext);
}

export function RelayThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPrefState] = useState<ThemePreference>(() =>
    getStoredThemePreference(),
  );
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(() =>
    getSystemTheme(),
  );

  const resolvedTheme: ResolvedTheme =
    preference === "system" ? systemTheme : preference;

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = (event: MediaQueryListEvent) => {
      setSystemTheme(event.matches ? "dark" : "light");
    };
    media.addEventListener("change", handleChange);
    return () => media.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    applyThemeToDocument(resolvedTheme, preference);
  }, [resolvedTheme, preference]);

  const setPreference = useCallback((newPref: ThemePreference) => {
    setPrefState(newPref);
    setStoredThemePreference(newPref);
  }, []);

  const toggleTheme = useCallback(() => {
    setPreference(resolvedTheme === "dark" ? "light" : "dark");
  }, [resolvedTheme, setPreference]);

  const theme = useMemo(() => createRelayTheme(resolvedTheme), [resolvedTheme]);

  const contextValue = useMemo<ThemeContextValue>(
    () => ({
      preference,
      resolvedTheme,
      setPreference,
      toggleTheme,
    }),
    [preference, resolvedTheme, setPreference, toggleTheme],
  );

  return (
    <ThemeContext.Provider value={contextValue}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ThemeContext.Provider>
  );
}

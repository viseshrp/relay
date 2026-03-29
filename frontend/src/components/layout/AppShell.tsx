import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Outlet } from "react-router-dom";
import { AlertTriangle } from "lucide-react";

import { getSystemStatus } from "@/api/settings";
import { Navbar } from "@/components/layout/Navbar";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useSettingsStore } from "@/store/settingsStore";

export function AppShell() {
  const theme = useSettingsStore((state) => state.theme);
  const { data: systemStatus } = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus, refetchInterval: 5000 });

  useEffect(() => {
    const root = document.documentElement;
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const applyTheme = () => {
      const resolvedTheme = theme === "system" ? (mediaQuery.matches ? "dark" : "light") : theme;
      root.classList.toggle("dark", resolvedTheme === "dark");
    };

    applyTheme();
    mediaQuery.addEventListener("change", applyTheme);
    return () => mediaQuery.removeEventListener("change", applyTheme);
  }, [theme]);

  const copilotAvailable = systemStatus?.copilot.copilot_available ?? false;
  const copilotAuthenticated = systemStatus?.copilot.authenticated ?? false;
  const copilotOk = copilotAvailable && copilotAuthenticated;

  return (
    <div className="min-h-screen">
      <Navbar />
      {systemStatus && !copilotOk ? (
        <Alert className="mx-4 mt-2">
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <AlertTitle>Copilot CLI Not Available</AlertTitle>
              <AlertDescription>
                {!copilotAvailable
                  ? "GitHub Copilot CLI is not installed. Install it with: npm install -g @github/copilot"
                  : "GitHub Copilot CLI is not authenticated. Run: copilot login"}
              </AlertDescription>
            </div>
          </div>
        </Alert>
      ) : null}
      <main className="mx-auto max-w-7xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}

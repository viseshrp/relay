import { Moon, Sun } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, useLocation } from "react-router-dom";

import { getSystemStatus } from "@/api/settings";
import { AutopilotToggle } from "@/components/layout/AutopilotToggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useSettingsStore } from "@/store/settingsStore";

const navItems = [
  { to: "/projects", label: "Projects" },
  { to: "/runs", label: "Runs" },
  { to: "/settings", label: "Settings" },
];

function NavbarLink({ to, label }: { to: string; label: string }) {
  const location = useLocation();
  const isActive = location.pathname === to || location.pathname.startsWith(`${to}/`);

  return (
    <Button asChild variant="ghost" className={isActive ? "bg-accent" : ""}>
      <NavLink to={to}>{label}</NavLink>
    </Button>
  );
}

export function Navbar() {
  const { data } = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus, refetchInterval: 5000 });
  const theme = useSettingsStore((state) => state.theme);
  const setTheme = useSettingsStore((state) => state.setTheme);
  const isHealthy = data?.copilot?.copilot_available === true && data?.copilot?.authenticated === true;

  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-background/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-4">
        <div className="flex items-center gap-6">
          <Link to="/projects" className="text-xl font-semibold tracking-[0.18em] uppercase text-primary">
            Relay
          </Link>
          <nav className="flex items-center gap-2">
            {navItems.map((item) => <NavbarLink key={item.to} to={item.to} label={item.label} />)}
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <AutopilotToggle />
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label="Toggle theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className={cn("h-3 w-3 rounded-full", isHealthy ? "bg-emerald-500" : "bg-rose-500")} />
            Copilot
          </div>
        </div>
      </div>
    </header>
  );
}

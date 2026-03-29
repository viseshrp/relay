import { useQuery } from "@tanstack/react-query";
import { Link, NavLink } from "react-router-dom";

import { getSystemStatus } from "@/api/settings";
import { AutopilotToggle } from "@/components/layout/AutopilotToggle";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/projects", label: "Projects" },
  { to: "/runs", label: "Runs" },
  { to: "/settings", label: "Settings" },
];

export function Navbar() {
  const { data } = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus, refetchInterval: 5000 });
  const isHealthy = data?.copilot?.copilot_available === true && data?.copilot?.authenticated === true;

  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-background/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-4">
        <div className="flex items-center gap-6">
          <Link to="/projects" className="text-xl font-semibold tracking-[0.18em] uppercase text-primary">
            Relay
          </Link>
          <nav className="flex items-center gap-2">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "inline-flex rounded-full px-3 py-2 text-sm transition",
                    isActive ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/40",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <AutopilotToggle />
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className={cn("h-3 w-3 rounded-full", isHealthy ? "bg-emerald-500" : "bg-rose-500")} />
            Copilot
          </div>
        </div>
      </div>
    </header>
  );
}

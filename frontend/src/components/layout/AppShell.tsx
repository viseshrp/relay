import { Outlet } from "react-router-dom";

import { Navbar } from "@/components/layout/Navbar";

export function AppShell() {
  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="mx-auto max-w-7xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}

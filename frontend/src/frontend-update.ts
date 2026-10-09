import { useEffect, useState } from "react";

export function useFrontendUpdate(): boolean {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    const entry = document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.src;
    if (!entry) return;
    let request: AbortController | null = null;
    let active = true;
    async function check() {
      if (!active || request || document.visibilityState === "hidden") return;
      const controller = new AbortController(); request = controller;
      try {
        const response = await fetch("/", { cache: "no-store", signal: controller.signal });
        if (!response.ok || !response.headers.get("content-type")?.includes("text/html")) return;
        const page = new DOMParser().parseFromString(await response.text(), "text/html");
        const next = page.querySelector('script[type="module"][src]')?.getAttribute("src");
        if (active && next) setAvailable(new URL(next, window.location.origin).href !== entry);
      } catch { /* Update discovery never blocks the workspace or hides API failures. */ }
      finally { if (request === controller) request = null; }
    }
    const checkVisible = () => { void check(); };
    void check();
    const timer = window.setInterval(checkVisible, 60000);
    window.addEventListener("focus", checkVisible);
    document.addEventListener("visibilitychange", checkVisible);
    return () => { active = false; request?.abort(); window.clearInterval(timer); window.removeEventListener("focus", checkVisible); document.removeEventListener("visibilitychange", checkVisible); };
  }, []);
  return available;
}

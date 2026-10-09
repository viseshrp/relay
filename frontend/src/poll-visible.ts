import { RelayApiError } from "./api";

/** One non-overlapping poller; hidden tabs are quiet and unchanged reads back off. */
export function pollVisible(
  read: () => Promise<unknown>,
  interval = 5000,
  quietAfter = 60000,
): { stop: () => void; refresh: () => void } {
  let stopped = false,
    busy = false,
    pending = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let fingerprint: string | undefined,
    changedAt = Date.now();
  async function update() {
    clearTimeout(timer);
    if (stopped || document.hidden) return;
    if (busy) {
      pending = true;
      return;
    }
    busy = true;
    try {
      const result = JSON.stringify(await read());
      if (result !== fingerprint) {
        fingerprint = result;
        changedAt = Date.now();
      }
    } catch (error) {
      if (error instanceof RelayApiError && error.status === 401)
        stopped = true;
    } finally {
      busy = false;
      if (!stopped && !document.hidden) {
        const delay =
          Date.now() - changedAt >= quietAfter
            ? Math.max(30000, interval)
            : interval;
        timer = setTimeout(() => void update(), pending ? 0 : delay);
        pending = false;
      }
    }
  }
  function refresh() {
    changedAt = Date.now();
    void update();
  }
  function visibility() {
    if (document.hidden) clearTimeout(timer);
    else refresh();
  }
  window.addEventListener("focus", refresh);
  document.addEventListener("visibilitychange", visibility);
  void update();
  return {
    refresh,
    stop: () => {
      stopped = true;
      clearTimeout(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visibility);
    },
  };
}

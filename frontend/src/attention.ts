import { useEffect, useRef, useState } from "react";
import { pollVisible } from "./poll-visible";
import { api, errorMessage } from "./api";

export interface Attention {
  waiting_count: number;
  waiting_runs: string[];
  waiting_runs_truncated: boolean;
  finished: Array<{
    id: number;
    run_id: string;
    project_id: string;
    workflow_key: string;
    status: string;
  }>;
  event_cursor: number;
  more: boolean;
}
const EMPTY: Attention = {
  waiting_count: 0,
  waiting_runs: [],
  waiting_runs_truncated: false,
  finished: [],
  event_cursor: 0,
  more: false,
};
const NOTIFICATIONS = "relay.notifications";
export function attentionChanged(): void {
  window.dispatchEvent(new Event("relay-attention-change"));
}

export function useAttention(
  authenticated: boolean,
  openRun: (run: string, project?: string) => void,
) {
  const [attention, setAttention] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [notificationError, setNotificationError] = useState<string | null>(
    null,
  );
  const [notifications, setNotifications] = useState(
    () =>
      localStorage.getItem(NOTIFICATIONS) === "true" &&
      "Notification" in window &&
      Notification.permission === "granted",
  );
  const notify = useRef(notifications);
  notify.current = notifications;
  const open = useRef(openRun);
  open.current = openRun;
  useEffect(() => {
    if (!authenticated) {
      setAttention(EMPTY);
      return;
    }
    const controller = new AbortController();
    let cursor: number | null = null;
    let waiting = new Set<string>();
    let busy = false;
    let changedWhileBusy = false;
    function notification(
      title: string,
      run: string,
      tag: string,
      project?: string,
    ) {
      if (
        !notify.current ||
        !("Notification" in window) ||
        Notification.permission !== "granted"
      )
        return;
      try {
        const message = new Notification(title, {
          tag,
          body: "Open Relay to see the run.",
        });
        message.onclick = () => {
          window.focus();
          open.current(run, project);
          message.close();
        };
      } catch {
        setNotificationError(
          "Your browser could not show a desktop notification. Check its site settings.",
        );
      }
    }
    async function refresh() {
      if (controller.signal.aborted) return;
      if (busy) {
        changedWhileBusy = true;
        return;
      }
      busy = true;
      try {
        let more = false;
        do {
          const value = await api<Attention>(
            `/api/attention${cursor === null ? "" : `?since=${cursor}`}`,
            { signal: controller.signal },
          );
          if (controller.signal.aborted) return;
          if (cursor !== null) {
            for (const run of value.waiting_runs)
              if (!waiting.has(run))
                notification("Relay is waiting for you", run, `waiting-${run}`);
            for (const run of value.finished)
              notification(
                `Relay run ${run.status === "succeeded" ? "complete" : run.status}`,
                run.run_id,
                `finished-${run.id}`,
                run.project_id,
              );
          }
          waiting = new Set(value.waiting_runs);
          cursor = value.event_cursor;
          more = value.more;
          setAttention(value);
          setError(null);
        } while (more && !controller.signal.aborted);
        return [cursor, ...waiting];
      } catch (caught) {
        if (!controller.signal.aborted) setError(errorMessage(caught));
        throw caught;
      } finally {
        busy = false;
        if (changedWhileBusy) {
          changedWhileBusy = false;
          void refresh().catch(() => undefined);
        }
      }
    }
    const polling = pollVisible(refresh);
    const changed = polling.refresh;
    window.addEventListener("relay-attention-change", changed);

    return () => {
      controller.abort();
      polling.stop();
      window.removeEventListener("relay-attention-change", changed);
    };
  }, [authenticated]);
  useEffect(() => {
    document.title = attention.waiting_count
      ? `(${attention.waiting_count}) Relay`
      : "Relay";
  }, [attention.waiting_count]);
  async function toggleNotifications(): Promise<void> {
    if (notifications) {
      localStorage.removeItem(NOTIFICATIONS);
      setNotifications(false);
      setNotificationError(null);
      return;
    }
    if (!("Notification" in window)) {
      setNotificationError(
        "This browser does not support desktop notifications.",
      );
      return;
    }
    try {
      if ((await Notification.requestPermission()) === "granted") {
        localStorage.setItem(NOTIFICATIONS, "true");
        setNotifications(true);
        setNotificationError(null);
      } else
        setNotificationError(
          "Desktop notifications are blocked. Allow them in your browser's site settings to enable them.",
        );
    } catch (caught) {
      setNotificationError(errorMessage(caught));
    }
  }
  return {
    attention,
    error: error ?? notificationError,
    notifications,
    toggleNotifications,
  };
}

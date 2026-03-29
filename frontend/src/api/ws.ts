import type { RelayWsEvent } from "@/types/ws";

type Handler = (event: RelayWsEvent) => void;

class RelayWsClient {
  private socket: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private subscriptions = new Set<string>();
  private subscribeAll = false;
  private reconnectTimer: number | null = null;

  connect() {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
      return;
    }
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    this.socket = new WebSocket(`${protocol}://${window.location.host}/api/v1/ws`);
    this.socket.onopen = () => {
      this.subscriptions.forEach((runId) => this.send({ type: "subscribe", run_id: runId }));
      if (this.subscribeAll) {
        this.send({ type: "subscribe_all" });
      }
    };
    this.socket.onmessage = (event) => {
      const data = JSON.parse(event.data) as RelayWsEvent;
      this.handlers.forEach((handler) => handler(data));
    };
    this.socket.onclose = () => {
      if (this.reconnectTimer !== null) {
        window.clearTimeout(this.reconnectTimer);
      }
      this.reconnectTimer = window.setTimeout(() => this.connect(), 1000);
    };
  }

  subscribe(handler: Handler) {
    this.handlers.add(handler);
    this.connect();
    return () => {
      this.handlers.delete(handler);
    };
  }

  subscribeRun(runId: string) {
    this.subscriptions.add(runId);
    this.send({ type: "subscribe", run_id: runId });
  }

  unsubscribeRun(runId: string) {
    this.subscriptions.delete(runId);
    this.send({ type: "unsubscribe", run_id: runId });
  }

  subscribeAllRuns() {
    this.subscribeAll = true;
    this.send({ type: "subscribe_all" });
  }

  unsubscribeAllRuns() {
    this.subscribeAll = false;
    this.send({ type: "unsubscribe_all" });
  }

  private send(payload: Record<string, unknown>) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    }
  }
}

export const wsClient = new RelayWsClient();

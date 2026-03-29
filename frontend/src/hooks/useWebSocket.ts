import { useEffect } from "react";

import { wsClient } from "@/api/ws";
import type { RelayWsEvent } from "@/types/ws";

export function useWebSocket(handler: (event: RelayWsEvent) => void) {
  useEffect(() => wsClient.subscribe(handler), [handler]);
}

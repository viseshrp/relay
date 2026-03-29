import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { finalizeExploration, listExplorationMessages, sendExplorationMessage } from "@/api/exploration";
import { wsClient } from "@/api/ws";
import type { ExplorationMessage } from "@/types/api";

export function useExplorationChat(runId: string | undefined) {
  const queryClient = useQueryClient();
  const [streaming, setStreaming] = useState<Record<string, string>>({});

  const messagesQuery = useQuery({
    queryKey: ["exploration", runId],
    queryFn: () => listExplorationMessages(runId as string),
    enabled: Boolean(runId),
  });

  useEffect(() => {
    if (!runId) {
      return undefined;
    }
    return wsClient.subscribe((event) => {
      if (event.type !== "exploration_chunk" || event.run_id !== runId) {
        return;
      }
      setStreaming((current) => ({
        ...current,
        [event.message_id]: `${current[event.message_id] ?? ""}${event.content}`,
      }));
      if (event.done) {
        queryClient.invalidateQueries({ queryKey: ["exploration", runId] });
        setStreaming((current) => {
          const next = { ...current };
          delete next[event.message_id];
          return next;
        });
      }
    });
  }, [queryClient, runId]);

  const sendMutation = useMutation({
    mutationFn: (content: string) => sendExplorationMessage(runId as string, content),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["exploration", runId] }),
  });

  const finalizeMutation = useMutation({
    mutationFn: () => finalizeExploration(runId as string),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", runId] }),
  });

  const liveMessages = Object.entries(streaming).map(([id, content]) => ({
    id,
    workflow_run_id: runId ?? "",
    role: "assistant" as const,
    content,
    sequence_number: Number.MAX_SAFE_INTEGER,
    created_at: "",
  }));

  return {
    messages: [...(messagesQuery.data ?? []), ...liveMessages] as ExplorationMessage[],
    isLoading: messagesQuery.isLoading,
    isStreaming: sendMutation.isPending || finalizeMutation.isPending || liveMessages.length > 0,
    sendMessage: sendMutation.mutateAsync,
    finalize: finalizeMutation.mutateAsync,
  };
}

import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type {
  AgentConfiguration,
  AgentsResponse,
  ModelObservation,
  RetryConfiguration,
} from "../types";

export interface SettingsChoices {
  agents: AgentsResponse;
  models: Pick<ModelObservation, "value" | "name">[];
  configuration: AgentConfiguration;
}

export type PendingChoice =
  { ready: SettingsChoices; error: null } | { ready: null; error: string };
export function choiceKey(
  settings: Pick<RetryConfiguration, "agent_id" | "model_value">,
): string {
  return JSON.stringify([settings.agent_id, settings.model_value]);
}

export function usePendingChoices(
  runId: string | null,
  projectId: string,
  paused: boolean,
  settings: RetryConfiguration[],
) {
  const unique = [
    ...new Map(settings.map((item) => [choiceKey(item), item])).values(),
  ];
  const signature = JSON.stringify(unique.map(choiceKey).sort());
  const targets = useMemo(
    () =>
      (JSON.parse(signature) as string[]).map((raw) => {
        const [agent_id, model_value] = JSON.parse(raw) as [string, string];
        return { agent_id, model_value };
      }),
    [signature],
  );
  const [revision, setRevision] = useState(0);
  const key = JSON.stringify([runId, projectId, paused, signature, revision]);
  const [state, setState] = useState<{
    key: string;
    choices: Record<string, PendingChoice>;
  }>({ key: "", choices: {} });

  useEffect(() => {
    setState({ key, choices: {} });
    if (!runId || !paused || targets.length === 0) return;
    const controller = new AbortController();
    const agents = api<AgentsResponse>("/api/agents", {
      signal: controller.signal,
    });
    const models = new Map<string, Promise<SettingsChoices["models"]>>();
    function modelChoices(agentId: string): Promise<SettingsChoices["models"]> {
      const previous = models.get(agentId);
      if (previous) return previous;
      const request = api<{ models: SettingsChoices["models"] }>(
        projectPath(
          `/api/agents/${encodeURIComponent(agentId)}/models`,
          projectId,
        ),
        { method: "POST", body: "{}", signal: controller.signal },
      ).then((result) => result.models);
      models.set(agentId, request);
      return request;
    }
    let next = 0;
    async function load(): Promise<void> {
      while (!controller.signal.aborted) {
        const target = targets[next++];
        if (!target) return;
        let result: PendingChoice;
        try {
          const inventory = await agents;
          const [advertised, configuration] = await Promise.all([
            modelChoices(target.agent_id),
            api<AgentConfiguration>(
              projectPath(
                `/api/agents/${encodeURIComponent(target.agent_id)}/configuration`,
                projectId,
              ),
              {
                method: "POST",
                body: JSON.stringify({ model: target.model_value }),
                signal: controller.signal,
              },
            ),
          ]);
          result = {
            ready: { agents: inventory, models: advertised, configuration },
            error: null,
          };
        } catch (caught) {
          result = { ready: null, error: errorMessage(caught) };
        }
        if (!controller.signal.aborted)
          setState((current) =>
            current.key === key
              ? {
                  key,
                  choices: { ...current.choices, [choiceKey(target)]: result },
                }
              : current,
          );
      }
    }
    // Bound provider initialization and share probes for jobs with the same route.
    void Promise.all([load(), load()]);
    return () => controller.abort();
  }, [key, runId, paused, targets, projectId]);
  return {
    choices: state.key === key ? state.choices : {},
    retry: () => setRevision((value) => value + 1),
  };
}

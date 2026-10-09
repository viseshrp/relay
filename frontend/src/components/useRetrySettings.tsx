import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type {
  AgentConfiguration,
  AgentsResponse,
  RetryConfiguration,
  RetryOptions,
} from "../types";
import type { SettingsChoices } from "./usePendingChoices";
import { RetryModel } from "./RetrySettingsShared";
type ReadResponse1 = { models: RetryModel[] };

export function useRetrySettings({
  problem,
  projectId,
  onClose,
  onRetry,
  purpose = "retry",
  initialChoices,
}: {
  problem: RetryConfiguration;
  projectId: string;
  onClose: () => void;
  onRetry: (scope: string, options?: RetryOptions) => Promise<void>;
  purpose?: "retry" | "pending";
  initialChoices?: SettingsChoices;
}) {
  const [agents, setAgents] = useState<AgentsResponse | null>(
    initialChoices?.agents ?? null,
  );
  const [agentId, setAgentId] = useState(problem.agent_id);
  const [model, setModel] = useState(problem.model_value);
  const [models, setModels] = useState<{
    agentId: string;
    choices: RetryModel[];
  } | null>(
    initialChoices
      ? { agentId: problem.agent_id, choices: initialChoices.models }
      : null,
  );
  const [state, setState] = useState<{
    key: string;
    configuration: AgentConfiguration | null;
  }>(
    initialChoices
      ? {
          key: JSON.stringify([
            problem.agent_id,
            problem.model_value,
            projectId,
          ]),
          configuration: initialChoices.configuration,
        }
      : { key: "", configuration: null },
  );
  const [selection, setSelection] = useState(0);
  const [permissionSelection, setPermissionSelection] = useState(0);
  const [handoff, setHandoff] = useState(problem.default_handoff_prompt ?? "");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const changed =
    model !== "" &&
    (agentId !== problem.agent_id || model !== problem.model_value);
  const key = JSON.stringify([agentId, model, projectId]);
  const configuration = state.key === key ? state.configuration : null;
  const handoffTooLong =
    problem.handoff_prompt_max_bytes !== undefined &&
    new TextEncoder().encode(handoff).length > problem.handoff_prompt_max_bytes;

  useEffect(() => {
    if (initialChoices) return;
    const controller = new AbortController();
    void api<AgentsResponse>("/api/agents", { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setAgents(value);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [initialChoices]);

  useEffect(() => {
    if (initialChoices && agentId === problem.agent_id) {
      setModels({ agentId, choices: initialChoices.models });
      return;
    }
    const controller = new AbortController();
    void api<ReadResponse1>(
      projectPath(
        `/api/agents/${encodeURIComponent(agentId)}/models`,
        projectId,
      ),
      { method: "POST", body: "{}", signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted)
          setModels({ agentId, choices: value.models });
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [agentId, projectId, initialChoices, problem.agent_id]);

  useEffect(() => {
    if (
      initialChoices &&
      agentId === problem.agent_id &&
      model === problem.model_value
    ) {
      setState({ key, configuration: initialChoices.configuration });
      return;
    }
    const controller = new AbortController();
    if (!model) return () => controller.abort();
    void api<AgentConfiguration>(
      projectPath(
        `/api/agents/${encodeURIComponent(agentId)}/configuration`,
        projectId,
      ),
      {
        method: "POST",
        body: JSON.stringify({ model }),
        signal: controller.signal,
      },
    )
      .then((value) => {
        if (!controller.signal.aborted) setState({ key, configuration: value });
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [
    agentId,
    model,
    key,
    projectId,
    initialChoices,
    problem.agent_id,
    problem.model_value,
  ]);
  const selector = configuration?.effort;
  const editable =
    selector !== null &&
    selector !== undefined &&
    selector.transport !== "native";
  const choices = models?.agentId === agentId ? models.choices : [];
  const currentEffort =
    selector?.choices.find((choice) => choice.value === problem.effort)?.name ??
    problem.effort ??
    "Agent’s default";
  const currentPermission =
    configuration?.permission_mode?.choices.find(
      (choice) => choice.value === problem.permission_mode,
    )?.name ??
    problem.permission_mode ??
    "Agent’s default";

  function changeAgent(value: string) {
    setAgentId(value);
    setModel("");
    setSelection(1);
    setPermissionSelection(1);
    setState({ key: "", configuration: null });
    setError(null);
  }

  function changeModel(value: string) {
    setModel(value);
    setSelection(
      value === problem.model_value && agentId === problem.agent_id ? 0 : 1,
    );
    setPermissionSelection(
      value === problem.model_value && agentId === problem.agent_id ? 0 : 1,
    );
    setState({ key: "", configuration: null });
    setError(null);
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const effort =
        selection === 0
          ? undefined
          : selection === 1
            ? null
            : selector?.choices[selection - 2]?.value;
      const permission =
        permissionSelection === 0
          ? undefined
          : permissionSelection === 1
            ? null
            : configuration?.permission_mode?.choices[permissionSelection - 2]
                ?.value;
      await onRetry(
        problem.scope_path,
        changed
          ? {
              agent_id: agentId,
              model,
              effort: editable ? (effort ?? null) : null,
              permission_mode: permission ?? null,
              handoff_prompt: handoff,
            }
          : { effort, permission_mode: permission },
      );
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return {
    fallback: null as null,
    onClose,
    submitting,
    purpose,
    problem,
    agents,
    agentId,
    changeAgent,
    key,
    models,
    model,
    changeModel,
    choices,
    configuration,
    error,
    editable,
    selection,
    setSelection,
    changed,
    currentEffort,
    selector,
    permissionSelection,
    setPermissionSelection,
    currentPermission,
    handoff,
    handoffTooLong,
    setHandoff,
    submit,
  };
}
export type RetrySettingsState = Extract<
  ReturnType<typeof useRetrySettings>,
  { fallback: null }
>;

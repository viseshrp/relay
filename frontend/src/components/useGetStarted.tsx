import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { editorHolder } from "../editor-session";
import { projectPath } from "../navigation";
import type {
  AgentReadiness,
  AgentsResponse,
  JsonScalar,
  WorkflowTemplate,
} from "../types";

import { GetStartedProps } from "./GetStartedShared";
type ReadResponse1 = { runs: Array<{ id: string }> };
type ReadResponse2 = { agents: AgentReadiness[] };
type ReadResponse3 = { run_id: string };

export function useGetStarted({
  project,
  requestProject,
  runSucceeded,
  onWorkflowCreated,
  onRunLaunched,
  onOpenProject,
  onClose,
}: GetStartedProps) {
  const [inventory, setInventory] = useState<AgentsResponse | null>(null);
  const [readiness, setReadiness] = useState<AgentReadiness[]>([]);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState(0);
  const [complete, setComplete] = useState<boolean | null>(null);
  const [newWorkflow, setNewWorkflow] = useState<"starter" | "blank" | null>(
    null,
  );
  const [workflow, setWorkflow] = useState<string | null>(null);
  const [template, setTemplate] = useState<WorkflowTemplate | null>(null);
  const [inputs, setInputs] = useState<Record<string, JsonScalar>>({});
  const [model, setModel] = useState("");
  const [launching, setLaunching] = useState(false);
  const holder = useRef(editorHolder());
  const models = Array.from(
    new Set(readiness.filter((row) => row.ready).flatMap((row) => row.models)),
  );
  const fullWorkflow = template?.id === "ai-coding-workflow";
  const codingModels =
    readiness.find((row) => row.id === inputs.agent && row.ready)?.models ?? [];
  const claudeModels =
    readiness.find((row) => row.id === "claude" && row.ready)?.models ?? [];
  const readyToRun = fullWorkflow
    ? typeof inputs.model === "string" &&
      codingModels.includes(inputs.model) &&
      typeof inputs.opus_model === "string" &&
      claudeModels.includes(inputs.opus_model) &&
      typeof inputs.task === "string" &&
      Boolean(inputs.task.trim())
    : Boolean(model) && models.includes(model);

  useEffect(() => {
    let active = true;
    void api<ReadResponse1>(
      `/api/runs?project=${encodeURIComponent(project.id)}&status=succeeded&limit=1`,
    )
      .then((value) => {
        if (active) setComplete(runSucceeded || value.runs.length > 0);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(errorMessage(caught));
          setComplete(false);
        }
      });
    return () => {
      active = false;
    };
  }, [project.id, runSucceeded]);
  useEffect(() => {
    if (runSucceeded) setComplete(true);
  }, [runSucceeded]);

  useEffect(() => {
    let active = true;
    setChecking(true);
    setReadiness([]);
    setError(null);
    void api<AgentsResponse>("/api/agents")
      .then(async (inventory) => {
        if (!active) return;
        setInventory(inventory);
        const value = await api<ReadResponse2>(
          projectPath("/api/agents/check", requestProject),
          { method: "POST", body: "{}" },
        );
        if (!active) return;
        setReadiness(value.agents);
        setModel((current) =>
          value.agents.some((row) => row.ready && row.models.includes(current))
            ? current
            : (value.agents.find((row) => row.ready)?.models[0] ?? ""),
        );
      })
      .catch((caught: unknown) => {
        if (active) setError(errorMessage(caught));
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, [check, requestProject]);

  async function launch() {
    if (!workflow) return;
    setLaunching(true);
    setError(null);
    try {
      const response = await api<ReadResponse3>(
        projectPath("/api/runs", requestProject),
        {
          method: "POST",
          body: JSON.stringify({
            workflow_key: workflow,
            project_id: project.id,
            ...(!fullWorkflow ? { model } : {}),
            inputs,
          }),
        },
      );
      onRunLaunched(response.run_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLaunching(false);
    }
  }

  return {
    fallback: null as null,
    onClose,
    complete,
    project,
    onOpenProject,
    inventory,
    readiness,
    checking,
    setError,
    setCheck,
    workflow,
    setNewWorkflow,
    template,
    inputs,
    setInputs,
    model,
    setModel,
    models,
    fullWorkflow,
    codingModels,
    claudeModels,
    readyToRun,
    launch,
    launching,
    error,
    newWorkflow,
    requestProject,
    holder,
    onWorkflowCreated,
    setWorkflow,
    setTemplate,
  };
}
export type GetStartedState = Extract<
  ReturnType<typeof useGetStarted>,
  { fallback: null }
>;

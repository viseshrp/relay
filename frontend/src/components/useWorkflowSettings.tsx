import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import { Binding, Environment, Template } from "./WorkflowSettingsShared";
type ReadResponse1 = { bindings: Binding[] };
type ReadResponse2 = { environments: Environment[] };
type ReadResponse3 = { templates: Template[] };

export function useWorkflowSettings({
  open,
  projectId,
  yaml,
  onClose,
  onEnvironments,
}: {
  open: boolean;
  projectId: string | null;
  yaml: string;
  onClose: () => void;
  onEnvironments: (names: string[]) => void;
}) {
  const [tab, setTab] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [scope, setScope] = useState("project");
  const [environment, setEnvironment] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState("variable");
  const [source, setSource] = useState("environment");
  const [reference, setReference] = useState("");
  const [value, setValue] = useState("");
  const [config, setConfig] = useState<Environment>({
    name: "",
    approval_required: false,
    wait_minutes: 0,
    branches: [],
    url: "",
  });
  const [bundle, setBundle] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [description, setDescription] = useState("");
  const endpoint = useCallback(
    (path: string) => projectPath(path, projectId),
    [projectId],
  );
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const [saved, configured, library] = await Promise.all([
        api<ReadResponse1>(endpoint("/api/workflow-bindings"), {
          signal,
        }),
        api<ReadResponse2>(endpoint("/api/workflow-environments"), { signal }),
        api<ReadResponse3>("/api/workflow-library", { signal }),
      ]);
      if (signal?.aborted) return;
      setBindings(saved.bindings);
      setEnvironments(configured.environments);
      setTemplates(library.templates);
      onEnvironments(configured.environments.map((item) => item.name));
    },
    [endpoint, onEnvironments],
  );
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    setValue("");
    setError("");
    setBindings([]);
    setEnvironments([]);
    setTemplates([]);
    void refresh(abort.signal).catch((e) => {
      if (!abort.signal.aborted) setError(errorMessage(e));
    });
    return () => abort.abort();
  }, [open, refresh]);
  async function mutate(path: string, body: unknown) {
    setBusy(true);
    setError("");
    try {
      await api(endpoint(path), { method: "POST", body: JSON.stringify(body) });
      setValue("");
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function exportTemplate(id: string) {
    try {
      const result = await api(
        `/api/workflow-library?id=${encodeURIComponent(id)}`,
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(result, null, 2)], {
          type: "application/json",
        }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `${id.replace("owner:", "")}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const selectedScope =
    scope === "installation"
      ? "installation"
      : scope === "environment"
        ? `environment:${projectId}:${environment}`
        : `project:${projectId}`;

  return {
    fallback: null as null,
    open,
    onClose,
    busy,
    setValue,
    value,
    tab,
    setTab,
    error,
    scope,
    setScope,
    environment,
    setEnvironment,
    environments,
    bindings,
    selectedScope,
    mutate,
    name,
    setName,
    kind,
    setKind,
    source,
    setSource,
    reference,
    setReference,
    setConfig,
    config,
    templates,
    exportTemplate,
    templateName,
    setTemplateName,
    description,
    setDescription,
    yaml,
    bundle,
    setBundle,
    setError,
  };
}
export type WorkflowSettingsState = Extract<
  ReturnType<typeof useWorkflowSettings>,
  { fallback: null }
>;

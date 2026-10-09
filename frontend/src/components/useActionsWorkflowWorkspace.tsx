import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api, csrfToken, errorMessage } from "../api";
import { projectPath } from "../navigation";
import { editorHolder } from "../editor-session";
import {
  actionsGraph,
  editorYaml,
  editActions,
  parseActions,
  type ActionWorkflow,
} from "../actions-workflow";
import type {
  AgentRecord,
  AgentsResponse,
  ProjectSettingsResponse,
  ProviderDefaults,
  WorkflowDocumentResponse,
  WorkflowDraft,
} from "../types";
import type { WorkflowWorkspaceProps } from "./WorkflowWorkspace";

import type { LanguageManifest } from "../workflow-language";
import type { PromptEdits } from "./PromptFilesEditor";
import { useUndoDocument } from "../useUndoDocument";

import { type WorkflowEntry } from "./WorkflowSidebar";
import { Diagnostic, Trigger, encoded } from "./ActionsWorkflowWorkspaceShared";
type ReadResponse1 = { workflows: WorkflowEntry[] };
type ReadResponse2 = {
  lease: unknown;
  conflict?: { message: string };
};
type ReadResponse3 = { draft: WorkflowDraft };
type ReadResponse4 = { valid: boolean; diagnostics: Diagnostic[] };
type ReadResponse5 = { triggers: Trigger[] };
type ReadResponse6 = { environments: Array<{ name: string }> };
type ReadResponse7 = { triggers: Trigger[] };

export function useActionsWorkflowWorkspace(props: WorkflowWorkspaceProps) {
  const { requestProject, onWorkflowLoaded, onNavigationReady } = props;
  const [loadRevision, setLoadRevision] = useState(0);
  const [inventory, setInventory] = useState<WorkflowEntry[]>([]);
  const [key, setKey] = useState(props.initialWorkflow || "");
  const {
    text,
    setText,
    reset: resetUndo,
    undo,
    redo,
    canUndo,
    canRedo,
  } = useUndoDocument();
  const [saved, setSaved] = useState("");
  const [base, setBase] = useState("");
  const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [notice, setNotice] = useState("");
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [defaultModel, setDefaultModel] = useState("");
  const [providerDefaults, setProviderDefaults] = useState<
    Record<string, ProviderDefaults>
  >({});
  const [loadedDocument, setLoadedDocument] = useState("");
  const [leaseError, setLeaseError] = useState("");
  const [lease, setLease] = useState(false);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState("");
  const [search, setSearch] = useState("");
  const [focusRequest, setFocusRequest] = useState(0);
  const [index, setIndex] = useState(0);
  const [create, setCreate] = useState(Boolean(props.initialCreate));
  const [launch, setLaunch] = useState(props.initialLaunch);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const [valid, setValid] = useState(false);
  const [triggerRows, setTriggerRows] = useState<Trigger[]>([]);
  const [activation, setActivation] = useState<string | null>(null);
  const [authorize, setAuthorize] = useState(false);
  const [manifest, setManifest] = useState<LanguageManifest | null>(null);
  const [sourceSettings, setSourceSettings] = useState(false);
  const [promptEdits, setPromptEdits] = useState<PromptEdits>({});
  const [mode, setMode] = useState("Split");
  const [drawer, setDrawer] = useState(false);
  const [formatted, setFormatted] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    id: string;
    x: number;
    y: number;
  } | null>(null);
  const [startJob, setStartJob] = useState("");
  const [newKind, setNewKind] = useState("script");
  const [settings, setSettings] = useState(false);
  const [environments, setEnvironments] = useState<string[]>([]);
  const holder = useRef(editorHolder());
  const writes = useRef(Promise.resolve());
  const currentDocument = useRef("");
  const [lastValid, setLastValid] = useState<ActionWorkflow | null>(null);
  const parsed = useMemo(() => parseActions(text), [text]);
  const savedParsed = useMemo(() => parseActions(saved), [saved]);
  const graph = useMemo(
    () => actionsGraph(valid ? parsed.value : (lastValid ?? parsed.value)),
    [parsed.value, lastValid, valid],
  );
  useEffect(() => {
    if (valid && parsed.value) setLastValid(parsed.value);
  }, [valid, parsed.value]);
  const job = parsed.value?.jobs[jobId];
  const matchingJobs = Object.entries(parsed.value?.jobs || {}).filter(
    ([id, item]) =>
      `${id} ${item.name || ""}`.toLowerCase().includes(search.toLowerCase()),
  );
  useEffect(() => {
    const abort = new AbortController();
    void Promise.all([
      api<AgentsResponse>("/api/agents", { signal: abort.signal }),
      api<ProjectSettingsResponse>(
        projectPath("/api/projects/defaults", requestProject),
        { signal: abort.signal },
      ),
    ])
      .then(([inventory, defaults]) => {
        if (!abort.signal.aborted) {
          setAgents(inventory.agents);
          setDefaultModel(defaults.effective.workflow_defaults.model || "");
          setProviderDefaults(defaults.effective.workflow_defaults.providers);
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(errorMessage(e));
      });
    return () => abort.abort();
  }, [requestProject]);
  useEffect(() => {
    const abort = new AbortController();
    void api<LanguageManifest>("/api/workflow-language", {
      signal: abort.signal,
    })
      .then(setManifest)
      .catch((e) => {
        if (!abort.signal.aborted) setError(errorMessage(e));
      });
    return () => abort.abort();
  }, []);
  const path = useCallback(
    (suffix: string) =>
      projectPath(`/api/workflows/${encoded(key)}${suffix}`, requestProject),
    [key, requestProject],
  );
  currentDocument.current = path("");
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const result = await api<ReadResponse1>(
        projectPath("/api/workflows", requestProject),
        { signal },
      );
      if (signal?.aborted) return;
      setInventory(result.workflows);
      if (!key && result.workflows.length)
        setKey(
          (
            result.workflows.find((item) => item.key === "workflow.yaml") ||
            result.workflows[0]
          ).key,
        );
    },
    [requestProject, key],
  );
  useEffect(() => {
    const abort = new AbortController();
    void refresh(abort.signal).catch((e) => {
      if (!abort.signal.aborted) setError(errorMessage(e));
    });
    return () => abort.abort();
  }, [refresh]);
  useEffect(() => {
    if (props.initialWorkflow) setKey(props.initialWorkflow);
  }, [props.initialWorkflow]);
  useEffect(() => {
    if (props.initialLaunch) setLaunch(true);
  }, [props.initialLaunch]);
  useEffect(() => {
    if (!key) return;
    const abort = new AbortController();
    let renew: number | undefined;
    setLease(false);
    setLeaseError("");
    setError("");
    setSearch("");
    setNotice("");
    setText("");
    setSaved("");
    setDraft(null);
    setPromptEdits({});
    setLoadedDocument("");
    setLastValid(null);
    const endpoint = projectPath(
      `/api/workflows/${encoded(key)}`,
      requestProject,
    );
    const leaseEndpoint = projectPath(
      `/api/workflows/${encoded(key)}/lease`,
      requestProject,
    );
    async function acquire() {
      try {
        const result = await api<ReadResponse2>(leaseEndpoint, {
          method: "POST",
          signal: abort.signal,
          body: JSON.stringify({ holder: holder.current, soft_conflict: true }),
        });
        if (!abort.signal.aborted) {
          setLease(Boolean(result.lease));
          setLeaseError(result.conflict?.message ?? "");
        }
      } catch (e) {
        if (!abort.signal.aborted) {
          setLease(false);
          setLeaseError(errorMessage(e));
        }
      }
    }
    void api<WorkflowDocumentResponse>(endpoint, { signal: abort.signal })
      .then(async (result) => {
        if (abort.signal.aborted) return;
        setText(editorYaml(result.draft?.yaml ?? result.yaml));
        setSaved(editorYaml(result.yaml));
        setBase(result.base_hash);
        setDraft(result.draft);
        setPromptEdits(result.draft?.prompts ?? {});
        setLoadedDocument(endpoint);
        await acquire();
        if (!abort.signal.aborted) {
          onWorkflowLoaded(key);
          renew = window.setInterval(() => {
            void acquire();
          }, 30000);
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(errorMessage(e));
      });
    const release = () => {
      navigator.sendBeacon(
        leaseEndpoint.replace(/\/lease(?=\?|$)/, "/lease/release"),
        new URLSearchParams({
          holder: holder.current,
          csrfmiddlewaretoken: csrfToken(),
        }),
      );
    };
    window.addEventListener("pagehide", release);
    return () => {
      abort.abort();
      window.clearInterval(renew);
      window.removeEventListener("pagehide", release);
      release();
    };
  }, [key, requestProject, onWorkflowLoaded, setText, loadRevision]);
  const flush = useCallback(async () => {
    if (
      !key ||
      loadedDocument !==
        projectPath(`/api/workflows/${encoded(key)}`, requestProject) ||
      (text === (draft ? editorYaml(draft.yaml) : saved) &&
        JSON.stringify(promptEdits) === JSON.stringify(draft?.prompts ?? {}))
    )
      return;
    if (!lease)
      throw new Error(
        "The editing lease is unavailable. Your draft remains in this editor.",
      );
    writes.current = writes.current
      .catch(() => undefined)
      .then(async () => {
        const result = await api<ReadResponse3>(
          projectPath(`/api/workflows/${encoded(key)}/draft`, requestProject),
          {
            method: "POST",
            body: JSON.stringify({
              yaml: text,
              prompts: promptEdits,
              base_hash: base,
              holder: holder.current,
            }),
          },
        );
        if (currentDocument.current === loadedDocument) setDraft(result.draft);
      });
    await writes.current;
  }, [
    key,
    text,
    saved,
    draft,
    lease,
    base,
    requestProject,
    loadedDocument,
    promptEdits,
  ]);
  useLayoutEffect(() => {
    onNavigationReady(flush);
    return () => onNavigationReady(null);
  }, [flush, onNavigationReady]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void flush().catch((e) => {
        if (currentDocument.current === loadedDocument)
          setError(errorMessage(e));
      });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [flush, loadedDocument]);
  useEffect(() => {
    setValid(false);
    setDiagnostics([]);
    if (!text || loadedDocument !== path("")) return;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      void api<ReadResponse4>(
        projectPath("/api/workflow-language/validate", requestProject),
        {
          method: "POST",
          signal: abort.signal,
          body: JSON.stringify({ yaml: text, source: key }),
        },
      )
        .then((result) => {
          if (!abort.signal.aborted) {
            setValid(result.valid);
            setDiagnostics(result.diagnostics);
          }
        })
        .catch((e) => {
          if (!abort.signal.aborted) setError(errorMessage(e));
        });
    }, 300);
    return () => {
      abort.abort();
      window.clearTimeout(timer);
    };
  }, [text, key, requestProject, loadedDocument, path]);
  useEffect(() => {
    setJobId((current) =>
      parsed.value?.jobs[current]
        ? current
        : Object.keys(parsed.value?.jobs || {})[0] || "",
    );
  }, [parsed.value]);
  useEffect(() => {
    setIndex(0);
  }, [jobId]);
  useEffect(() => {
    const abort = new AbortController();
    setTriggerRows([]);
    void api<ReadResponse5>(
      projectPath("/api/workflow-triggers", requestProject),
      { signal: abort.signal },
    )
      .then((result) => {
        if (!abort.signal.aborted) setTriggerRows(result.triggers);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(errorMessage(e));
      });
    return () => abort.abort();
  }, [requestProject]);
  async function save(next = text): Promise<boolean> {
    const target = path("");
    try {
      await flush();
      await api(path("/save"), {
        method: "POST",
        body: JSON.stringify({
          yaml: next,
          prompts: promptEdits,
          base_hash: base,
          holder: holder.current,
        }),
      });
      const result = await api<WorkflowDocumentResponse>(target);
      if (currentDocument.current !== target) return false;
      setText(editorYaml(result.yaml));
      setSaved(editorYaml(result.yaml));
      setBase(result.base_hash);
      setDraft(null);
      setPromptEdits({});
      setError("");
      setNotice("Workflow and instructions saved and validated.");
      return true;
    } catch (e) {
      if (currentDocument.current === target) setError(errorMessage(e));
      return false;
    }
  }
  async function restoreSaved() {
    const target = path("");
    const previousDraft = draft;
    setText(saved);
    setPromptEdits({});
    try {
      if (previousDraft)
        await api(path("/draft/discard"), {
          method: "POST",
          body: JSON.stringify({ updated_at: previousDraft.updated_at }),
        });
      if (currentDocument.current === target) {
        setDraft(null);
        setError("");
      }
    } catch (e) {
      if (currentDocument.current === target) setError(errorMessage(e));
    }
  }
  async function takeOver() {
    try {
      await api(path("/lease"), {
        method: "POST",
        body: JSON.stringify({ holder: holder.current, takeover: true }),
      });
      setLease(true);
      setLeaseError("");
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "z" &&
        !(
          event.target instanceof HTMLElement &&
          event.target.closest("input, textarea, .cm-content")
        )
      ) {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (lease && valid) void save();
      }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  });
  useEffect(() => {
    const abort = new AbortController();
    setEnvironments([]);
    void api<ReadResponse6>(
      projectPath("/api/workflow-environments", requestProject),
      { signal: abort.signal },
    )
      .then((result) => {
        if (!abort.signal.aborted)
          setEnvironments(result.environments.map((item) => item.name));
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(errorMessage(e));
      });
    return () => abort.abort();
  }, [requestProject]);
  function change(parts: Array<string | number>, value: unknown) {
    try {
      setText(editActions(text, parts, value));
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function toggleTrigger(event: string, enabled: boolean) {
    try {
      const result = await api<ReadResponse7>(
        projectPath("/api/workflow-triggers", requestProject),
        {
          method: "POST",
          body: JSON.stringify({ key, event, enabled, allow_writers: enabled }),
        },
      );
      setTriggerRows(result.triggers);
      setActivation(null);
      setAuthorize(false);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const events =
    parsed.value?.on &&
    typeof parsed.value.on === "object" &&
    !Array.isArray(parsed.value.on)
      ? Object.keys(parsed.value.on)
      : typeof parsed.value?.on === "string"
        ? [parsed.value.on]
        : [];
  useEffect(resetUndo, [base, key, resetUndo]);
  function removeJob(id: string | string[]) {
    const ids = Array.isArray(id) ? id : [id];
    let next = text;
    for (const key of ids) next = editActions(next, ["jobs", key], undefined);
    for (const [other, value] of Object.entries(parsed.value?.jobs ?? {})) {
      const needs =
        typeof value.needs === "string" ? [value.needs] : (value.needs ?? []);
      if (!ids.includes(other) && needs.some((needed) => ids.includes(needed)))
        next = editActions(
          next,
          ["jobs", other, "needs"],
          needs.filter((item) => !ids.includes(item)),
        );
    }
    setText(next);
    setContextMenu(null);
    setDrawer(false);
  }
  function addJob(source?: string, target?: string) {
    let number = 1;
    while (parsed.value?.jobs[`job_${number}`]) number++;
    const id = `job_${number}`;
    const step =
      newKind === "script"
        ? { run: "echo Ready" }
        : {
            uses: newKind,
            with: Object.fromEntries(
              (manifest?.builtin_inputs[newKind]?.required ?? []).map(
                (field) => [field, field === "max-iterations" ? "3" : ""],
              ),
            ),
          };
    let next = editActions(text, ["jobs", id], {
      ...(source ? { needs: [source] } : {}),
      steps: [step],
    });
    if (target) {
      const job = parsed.value?.jobs[target];
      const needs =
        typeof job?.needs === "string" ? [job.needs] : (job?.needs ?? []);
      next = editActions(
        next,
        ["jobs", target, "needs"],
        [...needs.filter((item) => item !== source), id],
      );
    }
    setText(next);
    setJobId(id);
    setDrawer(true);
  }
  async function runFromJob(id: string) {
    const point = `root.${id}`;
    const entries = parsed.value?.entrypoints ?? [];
    const next = entries.some((entry) => entry.scope_path === point)
      ? text
      : editActions(text, ["entrypoints"], [...entries, { scope_path: point }]);
    setContextMenu(null);
    setText(next);
    if (await save(next)) {
      setStartJob(point);
      setLaunch(true);
    }
  }
  function duplicateJob(id: string) {
    let next = `${id}_copy`;
    let number = 2;
    while (parsed.value?.jobs[next]) next = `${id}_copy_${number++}`;
    change(["jobs", next], parsed.value?.jobs[id]);
    setJobId(next);
    setContextMenu(null);
    setDrawer(true);
  }
  const disabled =
    inventory.find((item) => item.key === key)?.disabled === true;

  return {
    fallback: null as null,
    inventory,
    setLoadRevision,
    key,
    props,
    setCreate,
    flush,
    setKey,
    setError,
    parsed,
    save,
    disabled,
    lease,
    valid,
    text,
    saved,
    promptEdits,
    setLaunch,
    savedParsed,
    base,
    holder,
    setInventory,
    setNotice,
    setSourceSettings,
    sourceSettings,
    manifest,
    change,
    mode,
    setMode,
    canUndo,
    undo,
    canRedo,
    redo,
    setFormatted,
    restoreSaved,
    setSettings,
    settings,
    setEnvironments,
    notice,
    leaseError,
    takeOver,
    error,
    draft,
    diagnostics,
    setJobId,
    setDrawer,
    lastValid,
    focusRequest,
    jobId,
    graph,
    addJob,
    setContextMenu,
    setText,
    search,
    setSearch,
    matchingJobs,
    setFocusRequest,
    newKind,
    setNewKind,
    events,
    triggerRows,
    toggleTrigger,
    setActivation,
    drawer,
    job,
    removeJob,
    index,
    setIndex,
    agents,
    providerDefaults,
    defaultModel,
    setPromptEdits,
    contextMenu,
    duplicateJob,
    runFromJob,
    formatted,
    create,
    refresh,
    startJob,
    launch,
    environments,
    activation,
    setAuthorize,
    authorize,
  };
}
export type ActionsWorkflowWorkspaceState = Extract<
  ReturnType<typeof useActionsWorkflowWorkspace>,
  { fallback: null }
>;

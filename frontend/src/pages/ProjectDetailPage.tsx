import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { deleteProject, getProject, getProjectSettings, updateProjectSettings } from "@/api/projects";
import { listRuns } from "@/api/runs";
import { getSystemStatus, getUserSettings } from "@/api/settings";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Toggle } from "@/components/ui/toggle";
import type { WorkflowStatus } from "@/types/api";
import { formatRunDuration } from "@/lib/utils";

const KNOWN_PHASES = [
  "exploration",
  "planning",
  "plan_critique",
  "plan_correction",
  "execution",
  "review",
] as const;

const TERMINAL_STATUSES = new Set<WorkflowStatus>(["completed", "completed_with_unresolved_findings", "failed", "cancelled"]);

function buildUseGlobalModelState(overrides: Record<string, string>): Record<string, boolean> {
  return KNOWN_PHASES.reduce<Record<string, boolean>>((state, phase) => {
    state[phase] = overrides[phase] === undefined;
    return state;
  }, {});
}

function OverrideModeToggle({
  useGlobal,
  onChange,
}: {
  useGlobal: boolean;
  onChange: (useGlobal: boolean) => void;
}) {
  return (
    <div className="flex gap-2">
      <Button variant={useGlobal ? "default" : "outline"} onClick={() => onChange(true)}>
        Use global default
      </Button>
      <Button variant={!useGlobal ? "default" : "outline"} onClick={() => onChange(false)}>
        Override
      </Button>
    </div>
  );
}

export function ProjectDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [tab, setTab] = useState("overview");
  const [modelOverrides, setModelOverrides] = useState<Record<string, string>>({});
  const [useGlobalModel, setUseGlobalModel] = useState<Record<string, boolean>>({});
  const [retryUseGlobal, setRetryUseGlobal] = useState(true);
  const [retryValue, setRetryValue] = useState("5");
  const [reviewUseGlobal, setReviewUseGlobal] = useState(true);
  const [reviewValue, setReviewValue] = useState("5");
  const [autopilotUseGlobal, setAutopilotUseGlobal] = useState(true);
  const [autopilotValue, setAutopilotValue] = useState(true);

  const projectQuery = useQuery({ queryKey: ["project", id], queryFn: () => getProject(id) });
  const runsQuery = useQuery({ queryKey: ["runs", "project", id], queryFn: () => listRuns({ project_id: id, limit: 100 }) });
  const projectSettingsQuery = useQuery({ queryKey: ["project-settings", id], queryFn: () => getProjectSettings(id) });
  const userSettingsQuery = useQuery({ queryKey: ["user-settings"], queryFn: getUserSettings });
  const systemQuery = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus });
  const modelOptions = systemQuery.data?.copilot.available_models ?? [];
  const hasAvailableModels = modelOptions.length > 0;

  useEffect(() => {
    if (!projectSettingsQuery.data || !userSettingsQuery.data) {
      return;
    }

    const overrides = projectSettingsQuery.data.phase_model_mapping;
    setModelOverrides(overrides);
    setUseGlobalModel(buildUseGlobalModelState(overrides));
    setRetryUseGlobal(projectSettingsQuery.data.retry_count === null);
    setRetryValue(String(projectSettingsQuery.data.retry_count ?? userSettingsQuery.data.retry_limit));
    setReviewUseGlobal(projectSettingsQuery.data.review_fix_loop_limit === null);
    setReviewValue(String(projectSettingsQuery.data.review_fix_loop_limit ?? userSettingsQuery.data.review_fix_loop_limit));
    setAutopilotUseGlobal(projectSettingsQuery.data.autopilot_default === null);
    setAutopilotValue(projectSettingsQuery.data.autopilot_default ?? userSettingsQuery.data.autopilot);
  }, [projectSettingsQuery.data, userSettingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      updateProjectSettings(id, {
        phase_model_mapping: Object.fromEntries(
          KNOWN_PHASES.filter((phase) => !useGlobalModel[phase]).map((phase) => [phase, modelOverrides[phase] ?? ""]),
        ),
        retry_count: retryUseGlobal ? null : Number(retryValue),
        review_fix_loop_limit: reviewUseGlobal ? null : Number(reviewValue),
        autopilot_default: autopilotUseGlobal ? null : autopilotValue,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project-settings", id] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteProject(id),
    onSuccess: () => navigate("/projects"),
  });

  const activeRuns = useMemo(
    () => (runsQuery.data?.items ?? []).filter((run) => run.status === "running" || run.status === "waiting_for_user"),
    [runsQuery.data?.items],
  );

  if (
    projectQuery.isLoading ||
    runsQuery.isLoading ||
    projectSettingsQuery.isLoading ||
    userSettingsQuery.isLoading ||
    systemQuery.isLoading ||
    !projectQuery.data ||
    !userSettingsQuery.data
  ) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="configuration">Configuration</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <Card className="space-y-6">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h1 className="text-3xl font-semibold">{projectQuery.data.name}</h1>
                <p className="text-sm text-muted-foreground">{projectQuery.data.path}</p>
              </div>
              <div className="flex gap-3">
                <Button asChild>
                  <Link to={`/projects/${id}/workflows/new`}>New Workflow</Link>
                </Button>
                <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
                  Delete Project
                </Button>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Repository</h2>
                <p className="mt-2 text-sm">Git branch: {projectQuery.data.current_branch ?? "Not a git repository"}</p>
              </div>
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">Active Runs</h2>
                <p className="mt-2 text-sm">{activeRuns.length} active workflow(s)</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {activeRuns.map((run) => (
                    <Link key={run.id} to={`/runs/${run.id}`}>
                      <StatusBadge status={run.status} />
                    </Link>
                  ))}
                </div>
              </div>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="runs">
          <Table>
            <TableHeader>
              <TableRow className="border-t-0">
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Duration</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runsQuery.data?.items.map((run) => (
                <TableRow key={run.id}>
                  <TableCell>
                    <Link to={`/runs/${run.id}`} className="text-primary">
                      {run.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={run.status} />
                  </TableCell>
                  <TableCell>{new Date(run.created_at).toLocaleString()}</TableCell>
                  <TableCell>{formatRunDuration(run.created_at, run.updated_at, TERMINAL_STATUSES.has(run.status))}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TabsContent>

        <TabsContent value="configuration">
          <Card className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold">Configuration Overrides</h2>
              <p className="text-sm text-muted-foreground">Project settings override the global defaults only where you explicitly enable them.</p>
            </div>

            <Table>
              <TableHeader>
                <TableRow className="border-t-0">
                  <TableHead>Phase</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Model</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {KNOWN_PHASES.map((phase) => (
                  <TableRow key={phase}>
                    <TableCell className="font-medium capitalize">{phase.replaceAll("_", " ")}</TableCell>
                    <TableCell>
                      <OverrideModeToggle
                        useGlobal={useGlobalModel[phase] ?? true}
                        onChange={(useGlobal) =>
                          setUseGlobalModel((current) => ({
                            ...current,
                            [phase]: useGlobal,
                          }))
                        }
                      />
                    </TableCell>
                    <TableCell>
                      <Select
                        disabled={!hasAvailableModels || (useGlobalModel[phase] ?? true)}
                        value={useGlobalModel[phase] ? userSettingsQuery.data.phase_model_mapping[phase] ?? "" : modelOverrides[phase] ?? ""}
                        onValueChange={(value) =>
                          setModelOverrides((current) => ({
                            ...current,
                            [phase]: value,
                          }))
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={hasAvailableModels ? "Select model" : "No models available"} />
                        </SelectTrigger>
                        <SelectContent>
                          {modelOptions.map((model) => (
                            <SelectItem key={model.id} value={model.id}>
                              {model.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <div className="grid gap-6 md:grid-cols-3">
              <div className="space-y-3">
                <label className="text-sm font-medium">Retry count override</label>
                <OverrideModeToggle useGlobal={retryUseGlobal} onChange={setRetryUseGlobal} />
                <Input disabled={retryUseGlobal} value={retryValue} onChange={(event) => setRetryValue(event.target.value)} />
              </div>
              <div className="space-y-3">
                <label className="text-sm font-medium">Review-fix loop limit override</label>
                <OverrideModeToggle useGlobal={reviewUseGlobal} onChange={setReviewUseGlobal} />
                <Input disabled={reviewUseGlobal} value={reviewValue} onChange={(event) => setReviewValue(event.target.value)} />
              </div>
              <div className="space-y-3">
                <label className="text-sm font-medium">Autopilot default override</label>
                <OverrideModeToggle useGlobal={autopilotUseGlobal} onChange={setAutopilotUseGlobal} />
                <Toggle pressed={autopilotValue} onPressedChange={setAutopilotValue} className={autopilotUseGlobal ? "pointer-events-none opacity-60" : ""}>
                  {autopilotValue ? "Enabled" : "Disabled"}
                </Toggle>
              </div>
            </div>

            <div className="flex justify-end">
              <Button onClick={() => saveMutation.mutate()}>Save</Button>
            </div>
          </Card>
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={deleteDialogOpen}
        title="Delete Project"
        description="Are you sure you want to remove this project? This does not delete project files."
        onOpenChange={setDeleteDialogOpen}
        onConfirm={() => {
          setDeleteDialogOpen(false);
          deleteMutation.mutate();
        }}
      />
    </>
  );
}

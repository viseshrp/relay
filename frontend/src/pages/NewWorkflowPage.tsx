import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { createRun } from "@/api/runs";
import { getSystemStatus, getUserSettings } from "@/api/settings";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Toggle } from "@/components/ui/toggle";

const KNOWN_PHASES = [
  "exploration",
  "planning",
  "plan_critique",
  "plan_correction",
  "execution",
  "review",
] as const;

export function NewWorkflowPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [advanced, setAdvanced] = useState(false);
  const [name, setName] = useState("");
  const [retryLimit, setRetryLimit] = useState("5");
  const [reviewLimit, setReviewLimit] = useState("5");
  const [autopilot, setAutopilot] = useState(true);
  const [phaseModelMapping, setPhaseModelMapping] = useState<Record<string, string>>({});
  const settingsQuery = useQuery({ queryKey: ["user-settings"], queryFn: getUserSettings });
  const systemQuery = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus });
  const modelOptions = systemQuery.data?.copilot.available_models ?? [];
  const hasAvailableModels = modelOptions.length > 0;

  useEffect(() => {
    if (!settingsQuery.data) {
      return;
    }
    // The form mirrors the resolved defaults so a new workflow starts from the
    // same baseline the backend would otherwise resolve implicitly.
    setRetryLimit(String(settingsQuery.data.retry_limit));
    setReviewLimit(String(settingsQuery.data.review_fix_loop_limit));
    setAutopilot(settingsQuery.data.autopilot);
    setPhaseModelMapping(settingsQuery.data.phase_model_mapping);
  }, [settingsQuery.data]);

  const createMutation = useMutation({
    mutationFn: () =>
      createRun({
        project_id: id,
        name,
        retry_limit: Number(retryLimit),
        review_fix_loop_limit: Number(reviewLimit),
        autopilot,
        phase_model_mapping: phaseModelMapping,
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });

  if (settingsQuery.isLoading || systemQuery.isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <Card className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">New Workflow</h1>
        <p className="mt-1 text-sm text-muted-foreground">Create a new Relay workflow for this project.</p>
      </div>
      <div className="space-y-4">
        <label className="space-y-2 text-sm font-medium">
          <span>Workflow name</span>
          <Input placeholder="Workflow name" value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <Toggle pressed={advanced} onPressedChange={setAdvanced}>
          {advanced ? "Hide advanced settings" : "Show advanced settings"}
        </Toggle>
        {advanced ? (
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-2 text-sm font-medium">
              <span>Max retries per phase</span>
              <Input value={retryLimit} onChange={(event) => setRetryLimit(event.target.value)} />
            </label>
            <label className="space-y-2 text-sm font-medium">
              <span>Max review-fix loop iterations</span>
              <Input value={reviewLimit} onChange={(event) => setReviewLimit(event.target.value)} />
            </label>
            <div className="md:col-span-2">
              <Toggle pressed={autopilot} onPressedChange={setAutopilot}>
                Autopilot {autopilot ? "Enabled" : "Disabled"}
              </Toggle>
            </div>
            {KNOWN_PHASES.map((phase) => (
              <label key={phase} className="space-y-2 text-sm font-medium">
                <span className="capitalize">{phase.replaceAll("_", " ")} model</span>
                <Select
                  disabled={!hasAvailableModels}
                  value={phaseModelMapping[phase] ?? ""}
                  onValueChange={(value) =>
                    setPhaseModelMapping((current) => ({
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
              </label>
            ))}
          </div>
        ) : null}
        <div className="flex justify-end">
          <Button onClick={() => createMutation.mutate()} disabled={!name.trim()}>
            Create & Start
          </Button>
        </div>
      </div>
    </Card>
  );
}

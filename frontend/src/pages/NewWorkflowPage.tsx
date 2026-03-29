import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { getUserSettings } from "@/api/settings";
import { createRun } from "@/api/runs";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Toggle } from "@/components/ui/toggle";

const KNOWN_PHASES = [
  "exploration",
  "planning",
  "plan_critique",
  "plan_correction",
  "execution",
  "review",
];

export function NewWorkflowPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [advanced, setAdvanced] = useState(false);
  const [name, setName] = useState("");
  const [retryLimit, setRetryLimit] = useState("5");
  const [reviewLimit, setReviewLimit] = useState("5");
  const [autopilot, setAutopilot] = useState(true);
  const [phaseModelMapping, setPhaseModelMapping] = useState<Record<string, string>>({});
  const { data: settings } = useQuery({ queryKey: ["user-settings"], queryFn: getUserSettings });

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

  return (
    <Card className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">New Workflow</h1>
        <p className="mt-1 text-sm text-muted-foreground">Create a new Relay workflow for this project.</p>
      </div>
      <div className="space-y-4">
        <Input placeholder="Workflow name" value={name} onChange={(event) => setName(event.target.value)} />
        <Toggle pressed={advanced} onPressedChange={setAdvanced}>
          {advanced ? "Hide advanced settings" : "Show advanced settings"}
        </Toggle>
        {advanced ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Input value={retryLimit} onChange={(event) => setRetryLimit(event.target.value)} placeholder="Retry limit" />
            <Input value={reviewLimit} onChange={(event) => setReviewLimit(event.target.value)} placeholder="Review loop limit" />
            <div className="md:col-span-2">
              <Toggle pressed={autopilot} onPressedChange={setAutopilot}>
                Autopilot {autopilot ? "Enabled" : "Disabled"}
              </Toggle>
            </div>
            {KNOWN_PHASES.map((phase) => (
              <Select
                key={phase}
                value={phaseModelMapping[phase] ?? settings?.phase_model_mapping[phase] ?? ""}
                onChange={(event) => setPhaseModelMapping((current) => ({ ...current, [phase]: event.target.value }))}
                options={[
                  { label: "Copilot default", value: "" },
                  ...Object.entries(settings?.phase_model_mapping ?? {}).map(([key, value]) => ({ label: `${key}: ${value || "default"}`, value })),
                ]}
              />
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

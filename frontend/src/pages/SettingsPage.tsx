import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { getSystemStatus, getUserSettings, updateUserSettings } from "@/api/settings";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Toggle } from "@/components/ui/toggle";

const KNOWN_PHASES = [
  "exploration",
  "planning",
  "plan_critique",
  "plan_correction",
  "execution",
  "review",
];

export function SettingsPage() {
  const { data: settings } = useQuery({ queryKey: ["user-settings"], queryFn: getUserSettings });
  const { data: system } = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus });
  const [draft, setDraft] = useState(settings);

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  const mutation = useMutation({
    mutationFn: () => updateUserSettings(draft ?? {}),
  });

  if (!draft) {
    return null;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">Global defaults used when projects and runs do not override them.</p>
      </div>
      <Card className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">General</h2>
          <p className="text-sm text-muted-foreground">Relay data directory: {draft.relay_data_dir}</p>
          <p className="text-sm text-muted-foreground">Worker status: {system?.worker_status ?? "unknown"}</p>
        </div>
        <Input
          value={draft.copilot_cli_path_override ?? ""}
          onChange={(event) => setDraft({ ...draft, copilot_cli_path_override: event.target.value })}
          placeholder="Copilot CLI path override"
        />
        <Toggle pressed={draft.autopilot} onPressedChange={(value) => setDraft({ ...draft, autopilot: value })}>
          Autopilot {draft.autopilot ? "Enabled" : "Disabled"}
        </Toggle>
        <Input value={String(draft.retry_limit)} onChange={(event) => setDraft({ ...draft, retry_limit: Number(event.target.value) })} />
        <Input
          value={String(draft.review_fix_loop_limit)}
          onChange={(event) => setDraft({ ...draft, review_fix_loop_limit: Number(event.target.value) })}
        />
        {KNOWN_PHASES.map((phase) => (
          <Input
            key={phase}
            value={draft.phase_model_mapping[phase] ?? ""}
            onChange={(event) =>
              setDraft({
                ...draft,
                phase_model_mapping: { ...draft.phase_model_mapping, [phase]: event.target.value },
              })
            }
            placeholder={`${phase} model`}
          />
        ))}
        <div className="flex justify-end">
          <Button onClick={() => mutation.mutate()}>Save Settings</Button>
        </div>
      </Card>
    </div>
  );
}

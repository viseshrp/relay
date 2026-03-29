import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getSystemStatus, getUserSettings, updateUserSettings } from "@/api/settings";
import { ModelSelect } from "@/components/shared/ModelSelect";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Toggle } from "@/components/ui/toggle";
import type { UserSettings } from "@/types/api";

const KNOWN_PHASES = [
  "exploration",
  "planning",
  "plan_critique",
  "plan_correction",
  "execution",
  "review",
] as const;

export function SettingsPage() {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({ queryKey: ["user-settings"], queryFn: getUserSettings });
  const systemQuery = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus });
  const [draft, setDraft] = useState<UserSettings | null>(null);
  const modelOptions = systemQuery.data?.copilot.available_models ?? [];
  const hasAvailableModels = modelOptions.length > 0;

  useEffect(() => {
    if (settingsQuery.data) {
      setDraft(settingsQuery.data);
    }
  }, [settingsQuery.data]);

  const mutation = useMutation({
    mutationFn: () => {
      if (draft === null) {
        throw new Error("Settings draft is not ready.");
      }

      return updateUserSettings({
        copilot_cli_path_override: draft.copilot_cli_path_override,
        phase_model_mapping: draft.phase_model_mapping,
        autopilot: draft.autopilot,
        retry_limit: draft.retry_limit,
        review_fix_loop_limit: draft.review_fix_loop_limit,
        theme: draft.theme,
      });
    },
    onSuccess: (savedSettings) => {
      // Use the server response as the next source of truth so the page always
      // reflects what actually persisted rather than the optimistic draft.
      setDraft(savedSettings);
      queryClient.setQueryData(["user-settings"], savedSettings);
    },
  });

  if (settingsQuery.isLoading || systemQuery.isLoading || !draft) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
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
        </div>
        <label className="space-y-2 text-sm font-medium">
          <span>Relay data directory</span>
          <div className="rounded-2xl border border-border bg-secondary/40 px-4 py-2 text-sm">{draft.relay_data_dir}</div>
        </label>
        <label className="space-y-2 text-sm font-medium">
          <span>Copilot CLI path</span>
          <div className="rounded-2xl border border-border bg-secondary/40 px-4 py-2 text-sm">{systemQuery.data?.copilot.gh_path ?? "Not detected"}</div>
        </label>
      </Card>

      <Separator />

      <Card className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">Models</h2>
        </div>
        {!hasAvailableModels ? (
          <p className="text-sm text-muted-foreground">No models are currently available for the authenticated Copilot account.</p>
        ) : null}
        <Table>
          <TableHeader>
            <TableRow className="border-t-0">
              <TableHead>Phase</TableHead>
              <TableHead>Model</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {KNOWN_PHASES.map((phase) => (
              <TableRow key={phase}>
                <TableCell className="font-medium capitalize">{phase.replaceAll("_", " ")}</TableCell>
                <TableCell>
                  <ModelSelect
                    value={draft.phase_model_mapping[phase] ?? ""}
                    options={modelOptions}
                    disabled={!hasAvailableModels}
                    placeholder={hasAvailableModels ? "Select model" : "No models available"}
                    onValueChange={(value) =>
                      setDraft({
                        ...draft,
                        phase_model_mapping: {
                          ...draft.phase_model_mapping,
                          [phase]: value,
                        },
                      })
                    }
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Separator />

      <Card className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">Autopilot</h2>
        </div>
        <label className="flex items-center justify-between gap-4 text-sm font-medium">
          <span>Default autopilot</span>
          <Toggle pressed={draft.autopilot} onPressedChange={(value) => setDraft({ ...draft, autopilot: value })}>
            {draft.autopilot ? "Enabled" : "Disabled"}
          </Toggle>
        </label>
      </Card>

      <Separator />

      <Card className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">Retry/Loop Limits</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="space-y-2 text-sm font-medium">
            <span>Max retries per phase</span>
            <Input value={String(draft.retry_limit)} onChange={(event) => setDraft({ ...draft, retry_limit: Number(event.target.value) })} />
          </label>
          <label className="space-y-2 text-sm font-medium">
            <span>Max review-fix loop iterations</span>
            <Input
              value={String(draft.review_fix_loop_limit)}
              onChange={(event) => setDraft({ ...draft, review_fix_loop_limit: Number(event.target.value) })}
            />
          </label>
        </div>
      </Card>

      <div className="flex justify-end">
        <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          {mutation.isPending ? "Saving..." : "Save Settings"}
        </Button>
      </div>
    </div>
  );
}

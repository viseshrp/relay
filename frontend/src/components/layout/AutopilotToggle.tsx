import { useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { getUserSettings, updateUserSettings } from "@/api/settings";
import { Toggle } from "@/components/ui/toggle";
import { useSettingsStore } from "@/store/settingsStore";

export function AutopilotToggle() {
  const autopilot = useSettingsStore((state) => state.autopilot);
  const setAutopilot = useSettingsStore((state) => state.setAutopilot);

  const settingsQuery = useQuery({
    queryKey: ["user-settings"],
    queryFn: getUserSettings,
  });

  useEffect(() => {
    if (settingsQuery.data) {
      setAutopilot(settingsQuery.data.autopilot);
    }
  }, [setAutopilot, settingsQuery.data]);

  const mutation = useMutation({
    mutationFn: (next: boolean) => updateUserSettings({ autopilot: next }),
    onSuccess: (data) => setAutopilot(data.autopilot),
  });

  return (
    <Toggle pressed={autopilot} onPressedChange={(next) => mutation.mutate(next)} className="min-w-[8rem] justify-center">
      Autopilot {autopilot ? "On" : "Off"}
    </Toggle>
  );
}

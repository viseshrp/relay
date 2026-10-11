import type { OwnerSettings } from "./types";

export function settingsErrors(
  settings: OwnerSettings,
): Record<string, string> {
  const errors: Record<string, string> = {};
  const defaults = settings.workflow_defaults;
  if (defaults.timeout && !/^[0-9]+(?:ms|s|m|h)$/.test(defaults.timeout))
    errors.timeout = "Use a duration such as 30s, 15m, or 2h.";
  if (
    !Number.isInteger(defaults.recovery.max_retries) ||
    defaults.recovery.max_retries < 1 ||
    defaults.recovery.max_retries > 2
  )
    errors.retries = "Choose one or two additional attempts.";
  if (
    !Number.isInteger(defaults.repairs.max_rounds) ||
    defaults.repairs.max_rounds < 1 ||
    defaults.repairs.max_rounds > 100
  )
    errors.rounds = "Choose 1–100 repair rounds.";
  if (
    !Number.isInteger(settings.port) ||
    settings.port < 1 ||
    settings.port > 65535
  )
    errors.port = "Choose an integer from 1 through 65535.";
  if (!Number.isInteger(settings.workers) || settings.workers < 1)
    errors.workers = "Choose a positive whole number.";
  return errors;
}

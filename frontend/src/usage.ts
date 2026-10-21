import { countLabel } from "./count";
import type { AttemptUsage, RunUsage, UsageCost } from "./types";

function costLabel(cost: UsageCost): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: cost.currency,
      maximumFractionDigits: 4,
    }).format(cost.amount);
  } catch {
    // Providers may report a code that Intl does not know; keep it verbatim.
    return `${cost.amount.toLocaleString()} ${cost.currency}`;
  }
}

function tokenParts(usage: {
  input_tokens: number | null;
  output_tokens: number | null;
  cached_read_tokens: number | null;
}): string[] {
  return [
    usage.input_tokens !== null &&
      `${countLabel(usage.input_tokens, "token")} in`,
    usage.output_tokens !== null &&
      `${countLabel(usage.output_tokens, "token")} out`,
    usage.cached_read_tokens !== null &&
      `${usage.cached_read_tokens.toLocaleString()} cached`,
  ].filter((part): part is string => Boolean(part));
}

/** "1,200 tokens in · 80 tokens out · $0.25", or null when nothing was reported. */
export function attemptUsageLabel(
  usage: AttemptUsage | null | undefined,
): string | null {
  if (!usage) return null;
  const parts = tokenParts(usage);
  if (!parts.length && usage.total_tokens !== null)
    parts.push(countLabel(usage.total_tokens, "token"));
  if (usage.cost) parts.push(costLabel(usage.cost));
  return parts.length ? parts.join(" · ") : null;
}

/** Run totals name how many attempts reported, so unknown usage never reads as zero. */
export function runUsageLabel(
  usage: RunUsage | null | undefined,
): string | null {
  if (!usage?.attempts_reported) return null;
  const parts = [...tokenParts(usage), ...usage.costs.map(costLabel)];
  if (!parts.length) return null;
  const coverage =
    usage.attempts_reported === usage.attempts
      ? ""
      : ` (reported by ${usage.attempts_reported} of ${countLabel(usage.attempts, "attempt")})`;
  return `${parts.join(" · ")}${coverage}`;
}

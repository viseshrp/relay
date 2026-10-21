import { expect, test } from "@playwright/test";

import type { AttemptUsage, RunUsage } from "../src/types";
import { attemptUsageLabel, runUsageLabel } from "../src/usage";

const silent: AttemptUsage = {
  input_tokens: null,
  output_tokens: null,
  thought_tokens: null,
  cached_read_tokens: null,
  cached_write_tokens: null,
  total_tokens: null,
  cost: null,
};

test("unreported attempt usage has no label instead of zero", () => {
  expect(attemptUsageLabel(null)).toBeNull();
  expect(attemptUsageLabel(silent)).toBeNull();
});

test("attempt usage lists reported tokens and cost", () => {
  expect(
    attemptUsageLabel({
      ...silent,
      input_tokens: 1200,
      output_tokens: 1,
      cost: { amount: 0.25, currency: "USD" },
    }),
  ).toMatch(/^1,200 tokens in · 1 token out · .*0\.25/);
  expect(attemptUsageLabel({ ...silent, total_tokens: 9 })).toBe("9 tokens");
  expect(
    attemptUsageLabel({ ...silent, cost: { amount: 2, currency: "credits" } }),
  ).toBe("2 credits");
});

test("run usage names partial reporting and keeps currencies apart", () => {
  const usage: RunUsage = {
    attempts: 3,
    attempts_reported: 2,
    input_tokens: null,
    output_tokens: 10,
    thought_tokens: null,
    cached_read_tokens: null,
    cached_write_tokens: null,
    total_tokens: null,
    costs: [
      { currency: "EUR", amount: 1.5 },
      { currency: "USD", amount: 0.5 },
    ],
  };
  const label = runUsageLabel(usage);
  expect(label).toMatch(/^10 tokens out · .*1\.5.* · .*0\.5/);
  expect(label).toMatch(/\(reported by 2 of 3 attempts\)$/);
  expect(runUsageLabel({ ...usage, attempts_reported: 0 })).toBeNull();
});

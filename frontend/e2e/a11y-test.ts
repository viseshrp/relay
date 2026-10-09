import { test as base, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

export * from "@playwright/test";
export const test = base.extend<{ accessibility: void }>({
  accessibility: [
    async ({ page }, use, info) => {
      await use();
      if (
        page.isClosed() ||
        !page.url().startsWith("http://127.0.0.1:") ||
        info.status !== "passed"
      )
        return;
      // Audit final colors rather than an intermediate enable/disable transition.
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.evaluate(async () => {
        await Promise.all(
          document
            .getAnimations()
            .filter(
              (animation) =>
                animation.effect?.getComputedTiming().iterations !== Infinity,
            )
            .map((animation) => animation.finished.catch(() => undefined)),
        );
        await new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        );
      });
      const scan = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        scan.violations
          .filter(
            (item) => item.impact === "critical" || item.impact === "serious",
          )
          .map((item) => ({
            id: item.id,
            impact: item.impact,
            nodes: item.nodes.map((node) => ({
              target: node.target,
              summary: node.failureSummary,
            })),
          })),
      ).toEqual([]);
    },
    { auto: true },
  ],
});

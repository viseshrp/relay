import { parsePatchFiles, type FileDiffOptions } from "@pierre/diffs";
import { FileDiff } from "@pierre/diffs/react";
import { useMemo, type ReactNode } from "react";

export default function HighlightedDiff({
  patch,
  split,
  wrap,
  fallback,
}: {
  patch: string;
  split: boolean;
  wrap: boolean;
  fallback: ReactNode;
}) {
  const fileDiff = useMemo(() => {
    try {
      return parsePatchFiles(patch, undefined, true)[0]?.files[0];
    } catch {
      // A byte-limited preview can end inside a hunk; preserve its original text.
      return undefined;
    }
  }, [patch]);
  const options = useMemo<FileDiffOptions<undefined, undefined>>(
    () => ({
      diffStyle: split ? "split" : "unified",
      overflow: wrap ? "wrap" : "scroll",
      theme: "github-light-high-contrast",
      unsafeCSS: "[data-no-newline] span { color: #475569; opacity: 1; }",
      onPostRender: (node) => {
        for (const code of node.shadowRoot?.querySelectorAll("code") ?? []) {
          code.tabIndex = 0;
          code.setAttribute(
            "aria-label",
            code.hasAttribute("data-deletions")
              ? "Previous file lines"
              : "Updated file lines",
          );
        }
      },
      themeType: "light",
      preferredHighlighter: "shiki-js",
      disableFileHeader: true,
      hunkSeparators: "metadata",
      lineDiffType: "word-alt",
      // Relay's error boundary shows the patch rather than library error details.
      disableErrorHandling: true,
    }),
    [split, wrap],
  );
  return fileDiff ? (
    <FileDiff className="diff-rendered" fileDiff={fileDiff} options={options} />
  ) : (
    fallback
  );
}

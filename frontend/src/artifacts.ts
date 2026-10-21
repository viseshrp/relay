import type { ArtifactRecord } from "./types";

export function visibleArtifacts(
  artifacts: ArtifactRecord[],
): ArtifactRecord[] {
  return artifacts.filter(
    (artifact) =>
      artifact.preservation_state === "preserved" &&
      !(
        (artifact.name === "worktree_diff" && artifact.bytes === 0) ||
        (["commits", "commits.json"].includes(artifact.name) &&
          artifact.bytes <= 3)
      ),
  );
}

/** The review material shown first when the owner has not chosen one. */
export function defaultReviewSelection(
  documents: { label: string; artifact: ArtifactRecord }[],
  hasChanges: boolean,
  requestText: string | null,
): string | undefined {
  if (requestText) {
    const named = documents.find(
      ({ label }) => label !== "" && requestText.includes(label),
    );
    if (named) return named.artifact.id;
  }
  if (hasChanges) return "changes";
  return documents.reduce<ArtifactRecord | undefined>(
    (newest, { artifact }) =>
      !newest || Number(artifact.id) > Number(newest.id) ? artifact : newest,
    undefined,
  )?.id;
}

/** Name a retained file by its path inside the run's working copy. */
export function artifactPath(runId: string, artifact: ArtifactRecord): string {
  // /worktrees/<run>/r-12/docs/REVIEW.md becomes docs/REVIEW.md.
  // Keep directories so docs/REVIEW.md and audit/REVIEW.md remain distinct.
  const source = artifact.source_path.replace(/\\/g, "/");
  const marker = `/worktrees/${runId}/`;
  const offset = source.indexOf(marker);
  return offset >= 0
    ? source.slice(offset + marker.length).replace(/^r-\d+\//, "")
    : source;
}

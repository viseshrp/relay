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

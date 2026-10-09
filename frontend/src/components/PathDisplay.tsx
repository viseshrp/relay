import { Button, Typography } from "@mui/material";
import { useState } from "react";

function shortenedPath(path: string): string {
  const parts = path.replaceAll("\\", "/").split("/").filter(Boolean);
  const absolute =
    path.startsWith("/") ||
    /^[A-Za-z]:[\\/]/.test(path) ||
    path.startsWith("\\\\");
  return absolute && parts.length ? `…/${parts.slice(-2).join("/")}` : path;
}

export function PathDisplay({
  path,
  label,
  display,
}: {
  path: string;
  label: string;
  display?: string;
}) {
  const [notice, setNotice] = useState<string | null>(null);
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(path);
      setNotice("Path copied.");
    } catch {
      setNotice("Could not copy. Select the full path below to copy it.");
    }
  }
  return (
    <details className="path-display">
      <summary role="button" title={path} aria-label={`Full path for ${label}`}>
        <code>{display ?? shortenedPath(path)}</code>
        <span>Full path</span>
      </summary>
      <div className="path-details">
        <code>{path}</code>
        <Button
          onClick={() => void copy()}
          aria-label={`Copy full path for ${label}`}
        >
          Copy path
        </Button>
      </div>
      {notice && (
        <Typography variant="caption" role="status">
          {notice}
        </Typography>
      )}
    </details>
  );
}

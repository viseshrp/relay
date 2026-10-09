import { Alert, Button, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
type ReadResponse1 = { repositories: Array<{ path: string; name: string }> };

type Candidate = { path: string; repository: boolean; message: string };
export function ProjectFolderValidation({
  path,
  disabled,
  onValidated,
  onSelect,
}: {
  path: string;
  disabled: boolean;
  onValidated: (valid: boolean) => void;
  onSelect: (path: string) => void;
}) {
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState<Array<{ path: string; name: string }>>(
    [],
  );
  useEffect(() => {
    const controller = new AbortController();
    void api<ReadResponse1>("/api/projects/candidates", {
      signal: controller.signal,
    })
      .then((result) => setRecent(result.repositories))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    onValidated(false);
    setCandidate(null);
    setError("");
    if (!path.trim()) return () => controller.abort();
    const timer = window.setTimeout(() => {
      void api<Candidate>(
        `/api/projects/candidates?path=${encodeURIComponent(path)}`,
        { signal: controller.signal },
      )
        .then((result) => {
          if (!controller.signal.aborted) {
            setCandidate(result);
            onValidated(result.repository);
          }
        })
        .catch((caught) => {
          if (!controller.signal.aborted) setError(errorMessage(caught));
        });
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [path, onValidated]);
  async function initialize() {
    setBusy(true);
    setError("");
    try {
      const result = await api<Candidate>("/api/projects/initialize-git", {
        method: "POST",
        body: JSON.stringify({ path, confirmed: true }),
      });
      setCandidate(result);
      onValidated(result.repository);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Stack spacing={1}>
      {candidate && (
        <Alert severity={candidate.repository ? "success" : "info"}>
          {candidate.message}
          {!candidate.repository && (
            <Button
              disabled={busy || disabled}
              onClick={() => void initialize()}
            >
              Initialize Git in this folder
            </Button>
          )}
        </Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {recent.length > 0 && (
        <>
          <Typography variant="subtitle2">
            Repositories in common folders
          </Typography>
          {recent.map((item) => (
            <Button
              key={item.path}
              title={item.path}
              disabled={disabled}
              onClick={() => onSelect(item.path)}
            >
              {item.name}
            </Button>
          ))}
        </>
      )}
    </Stack>
  );
}

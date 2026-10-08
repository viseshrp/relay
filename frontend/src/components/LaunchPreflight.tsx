import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import { useState } from "react";
import { errorMessage } from "../api";
import type { LaunchCleanliness } from "../types";

export function LaunchPreflight({ result, error, onCheck }: {
  result: LaunchCleanliness | null; error: string | null; onCheck: () => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  async function copy(command: string): Promise<void> {
    try { await navigator.clipboard.writeText(command); setCopied(command); setCopyError(null); }
    catch (caught) { setCopyError(errorMessage(caught)); }
  }
  return <Stack component="section" aria-label="Launch file check" spacing={1}>
    <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between" }}>
      <Typography variant="subtitle1">Project files</Typography>
      <Button onClick={onCheck}>Check files again</Button>
    </Stack>
    {error ? <Alert severity="error">{error}</Alert> : !result ? <Typography>Checking project files…</Typography> : <>
      <Typography>{result.clean ? "Project files are ready to run." : `${result.blocking_count} ${result.blocking_count === 1 ? "file blocks" : "files block"} this run.`}</Typography>
      {result.files.filter((file) => !file.allowed).map((file) => <Box key={file.path}>
        <Typography component="code" sx={{ overflowWrap: "anywhere" }}>{file.path}</Typography>
        <Typography variant="body2">{file.reasons.join(", ")}{file.original_path ? ` · from ${file.original_path}` : ""}</Typography>
      </Box>)}
      {result.allowed_count > 0 && <Box component="details"><Box component="summary">{result.allowed_count} allowed {result.allowed_count === 1 ? "file" : "files"}</Box>
        {result.files.filter((file) => file.allowed).map((file) => <Box key={file.path} sx={{ mt: 1 }}>
          <Typography component="code" sx={{ overflowWrap: "anywhere" }}>{file.path}</Typography>
          <Typography variant="body2">{file.reasons.join(", ")}</Typography>
        </Box>)}
      </Box>}
      {result.truncated && <Alert severity="info">Showing {result.files.length} changed files. The counts include every changed file. Run git status in your project folder to see the full list.</Alert>}
      {!result.clean && <Box component="details" className="launch-guidance"><Box component="summary">How to resolve these changes</Box><Stack spacing={1}>
        <Typography variant="body2">Run a command in your project folder after choosing which changes to keep.</Typography>
        <Stack direction="row" sx={{ alignItems: "center", justifyContent: "space-between" }}><Box component="code">git commit</Box><Button aria-label="Copy git commit" onClick={() => void copy("git commit")}>Copy</Button></Stack>
        <Typography variant="body2">Stage the files you want to keep, then commit them.</Typography>
        <Stack direction="row" sx={{ alignItems: "center", justifyContent: "space-between" }}><Box component="code">git stash -u</Box><Button aria-label="Copy git stash -u" onClick={() => void copy("git stash -u")}>Copy</Button></Stack>
        <Typography variant="body2">Stash temporarily removes tracked and untracked changes, including workflow files and reports.</Typography>
      </Stack></Box>}
    </>}
    {copied && <Typography role="status">Copied {copied}.</Typography>}
    {copyError && <Alert severity="error">{copyError}</Alert>}
  </Stack>;
}

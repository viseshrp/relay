import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
type ReadResponse1 = { key: string | null };

export function WorkflowManagement({
  workflowKey,
  name,
  baseHash,
  holder,
  project,
  disabled,
  onChanged,
}: {
  workflowKey: string;
  name: string;
  baseHash: string;
  holder: string;
  project: string | null;
  disabled: boolean;
  onChanged: (key: string | null) => Promise<void>;
}) {
  const [action, setAction] = useState("");
  const [nextKey, setNextKey] = useState("");
  const [nextName, setNextName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  function open(value: string) {
    setAction(value);
    setError("");
    setNextName(value === "duplicate" ? `${name} copy` : name);
    setNextKey(
      value === "duplicate"
        ? workflowKey.replace(/\.(yaml|yml)$/, "-copy.yaml")
        : workflowKey,
    );
  }
  async function submit() {
    setBusy(true);
    setError("");
    try {
      const response = await api<ReadResponse1>(
        projectPath(
          `/api/workflows/${workflowKey.split("/").map(encodeURIComponent).join("/")}/manage`,
          project,
        ),
        {
          method: "POST",
          body: JSON.stringify({
            action,
            holder,
            base_hash: baseHash,
            new_key: nextKey,
            name: nextName,
            confirmed: action === "delete",
          }),
        },
      );
      await onChanged(response.key);
      setAction("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }
  const title = action
    ? `${action.charAt(0).toUpperCase()}${action.slice(1)} workflow`
    : "Manage workflow";
  return (
    <>
      <Button disabled={!workflowKey} onClick={() => open("manage")}>
        Manage workflow
      </Button>
      <Dialog
        open={Boolean(action)}
        onClose={() => {
          if (!busy) setAction("");
        }}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>{title}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {action === "manage" ? (
              <>
                {[
                  "rename",
                  "duplicate",
                  disabled ? "enable" : "disable",
                  "delete",
                ].map((value) => (
                  <Button key={value} onClick={() => open(value)}>
                    {value.charAt(0).toUpperCase() + value.slice(1)}
                  </Button>
                ))}
              </>
            ) : (
              <>
                <Typography sx={{ overflowWrap: "anywhere" }}>
                  {workflowKey}
                </Typography>
                {["rename", "duplicate"].includes(action) && (
                  <>
                    <TextField
                      label="Workflow file name"
                      value={nextKey}
                      onChange={(event) => setNextKey(event.target.value)}
                    />
                    <TextField
                      label="Workflow display name"
                      value={nextName}
                      onChange={(event) => setNextName(event.target.value)}
                    />
                  </>
                )}
                {action === "delete" && (
                  <Alert severity="warning">
                    Delete this workflow file? Run history and shared prompt
                    files stay available.
                  </Alert>
                )}
                {action === "disable" && (
                  <Typography>
                    Running this workflow and automatic triggers will be
                    disabled. Its file and history stay available.
                  </Typography>
                )}
              </>
            )}
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button disabled={busy} onClick={() => setAction("")}>
            Cancel
          </Button>
          {action !== "manage" && (
            <Button
              disabled={
                busy ||
                (["rename", "duplicate"].includes(action) && !nextKey.trim())
              }
              color={action === "delete" ? "error" : "primary"}
              onClick={() => void submit()}
            >
              {busy ? "Working…" : `Confirm ${action}`}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </>
  );
}

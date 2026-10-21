import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { HelpSelectField } from "./HelpTip";

export interface LoopTarget {
  key: string;
  name: string;
}

/** Ask which of the project's other workflows a new loop step repeats. */
export function LoopWorkflowDialog({
  open,
  workflows,
  onClose,
  onChoose,
}: {
  open: boolean;
  workflows: LoopTarget[];
  onClose: () => void;
  onChoose: (key: string) => void;
}) {
  const [key, setKey] = useState("");
  useEffect(() => {
    if (open) setKey(workflows[0]?.key ?? "");
  }, [open, workflows]);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      aria-labelledby="loop-workflow-title"
    >
      <DialogTitle id="loop-workflow-title">
        Choose the workflow to repeat
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography>
            The step runs this workflow again until it reports done, at most
            three times. You can change the limit afterwards.
          </Typography>
          <HelpSelectField
            topic={{
              title: "Workflow to repeat",
              description:
                "A reusable workflow in this project. Relay runs it as the loop body and reads its outputs to decide whether to repeat it.",
              guide: "reusable-workflows-and-local-actions",
            }}
            label="Workflow to repeat"
            value={key}
            onChange={(event) => setKey(String(event.target.value))}
          >
            {workflows.map((item) => (
              <MenuItem key={item.key} value={item.key}>
                {item.name && item.name !== item.key
                  ? `${item.name} (${item.key})`
                  : item.key}
              </MenuItem>
            ))}
          </HelpSelectField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button disabled={!key} onClick={() => onChoose(key)}>
          Repeat this workflow
        </Button>
      </DialogActions>
    </Dialog>
  );
}

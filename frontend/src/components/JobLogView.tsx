import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";

import { rawLog } from "../log";

import { fullscreenShortcut } from "./JobLogShared";
import type { JobLogState } from "./useJobLog";
export function JobLogView({ state }: { state: JobLogState }) {
  const {
    root,
    fullscreen,
    contents,
    setFullscreen,
    raw,
    setRaw,
    menuButton,
    events,
    command,
    download,
  } = state;
  return (
    <Box ref={root} className="job-log" tabIndex={-1}>
      {!fullscreen && contents}
      <Dialog
        open={fullscreen}
        fullScreen
        onClose={() => setFullscreen(false)}
        slotProps={{
          transition: {
            onExited: () => {
              root.current?.focus();
            },
          },
        }}
      >
        <DialogTitle>
          Job logs{" "}
          <Button onClick={() => setFullscreen(false)} sx={{ float: "right" }}>
            Exit full screen
          </Button>
        </DialogTitle>
        <DialogContent
          className="fullscreen-log"
          onKeyDown={(event) => {
            if (fullscreenShortcut(event)) {
              event.preventDefault();
              setFullscreen(false);
            }
          }}
        >
          {fullscreen && contents}
        </DialogContent>
      </Dialog>
      <Dialog
        open={raw}
        onClose={() => setRaw(false)}
        fullWidth
        maxWidth="lg"
        slotProps={{
          transition: { onExited: () => menuButton.current?.focus() },
        }}
      >
        <DialogTitle>Raw logs</DialogTitle>
        <DialogContent>
          <Box component="pre" className="activity-text">
            {rawLog(events, command)}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRaw(false)}>Close</Button>
          <Button onClick={download}>Download logs</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}

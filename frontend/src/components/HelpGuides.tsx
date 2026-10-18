import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import gettingStarted from "../../../docs/getting-started.md?raw";
import firstWorkflow from "../../../docs/build-your-first-workflow.md?raw";
import actions from "../../../docs/coming-from-github-actions.md?raw";
import keyboard from "../../../docs/keyboard-shortcuts.md?raw";
import { SafeMarkdown } from "./SafeMarkdown";

export type HelpGuide =
  | "Getting started"
  | "Build your first workflow"
  | "Coming from GitHub Actions"
  | "Keyboard shortcuts";
const guides: Record<HelpGuide, string> = {
  "Getting started": gettingStarted,
  "Build your first workflow": firstWorkflow,
  "Coming from GitHub Actions": actions,
  "Keyboard shortcuts": keyboard,
};
export function HelpGuides({
  guide,
  onClose,
}: {
  guide: HelpGuide | null;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={guide !== null}
      onClose={onClose}
      fullWidth
      maxWidth="md"
      aria-labelledby="help-guide-title"
    >
      <DialogTitle id="help-guide-title">{guide}</DialogTitle>
      {/* Long guides scroll; keyboard users can focus and scroll them. */}
      <DialogContent tabIndex={0}>
        {guide && (
          <SafeMarkdown
            text={guides[guide]
              .replace(/^# [^\n]+\n+/, "")
              // Example tags are for the documentation checker, not readers.
              .replace(/<!--[\s\S]*?-->\n?/g, "")}
          />
        )}
      </DialogContent>
      <DialogActions>
        <Button
          component="a"
          target="_blank"
          rel="noreferrer"
          href="https://github.com/viseshrp/relay/blob/main/docs/web-ui.md"
        >
          Full documentation
        </Button>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

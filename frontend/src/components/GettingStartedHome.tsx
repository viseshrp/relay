import { Button, Paper, Stack, Typography } from "@mui/material";
import { OnboardingIllustration } from "./OnboardingIllustration";

export function GettingStartedHome({
  onOpenProject,
  onShowWelcome,
  heading = "h1",
}: {
  onOpenProject: () => void;
  onShowWelcome: () => void;
  heading?: "h1" | "h2";
}) {
  return (
    <Paper
      component="section"
      aria-label="Start using Relay"
      variant="outlined"
      className="getting-started-home"
    >
      <Stack spacing={2}>
        <Typography component={heading} variant="h4">
          Your first workflow starts here
        </Typography>
        <Typography>
          Relay runs coding-agent workflows on your computer. Open a Git
          repository to draw a workflow, follow its jobs, and review the
          results.
        </Typography>
        <OnboardingIllustration kind="project" />
        <ol className="getting-started-steps">
          <li>
            <strong>Open a project.</strong> Choose a local Git repository.
            Relay creates a blank .relay folder if needed. Make a first Git
            commit before launching.
          </li>
          <li>
            <strong>Connect an agent.</strong> Install and sign in to Codex,
            Claude Code, GitHub Copilot CLI, Cursor CLI, or Antigravity. One
            working agent is enough; command-only workflows do not need one.
          </li>
          <li>
            <strong>Choose a workflow.</strong> Use a starter such as Ask an
            agent, or create a blank workflow and add stages. Get started in
            Help checks agent connections.
          </li>
          <li>
            <strong>Run and review.</strong> Press Run workflow, fill its
            inputs, then open jobs for live output. Answer review requests when
            Relay waits for you.
          </li>
        </ol>
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
          <Button variant="contained" onClick={onOpenProject}>
            Open your first project
          </Button>
          <Button onClick={onShowWelcome}>Show welcome slides</Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

import { Alert, Button } from "@mui/material";
import { Component, type ReactNode } from "react";

export class WorkspaceBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(_error: unknown): { failed: boolean } {
    return { failed: true };
  }

  render(): ReactNode {
    if (this.state.failed) return <Alert severity="error" action={<Button onClick={() => window.location.reload()}>Reload Relay</Button>}>
      Relay could not open this workspace. If Relay was updated, reload to load the current version. Unsaved workflow recovery drafts remain in this browser.
    </Alert>;
    return this.props.children;
  }
}

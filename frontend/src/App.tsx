import {
  AppBar,
  Box,
  Button,
  CircularProgress,
  Container,
  Tab,
  Tabs,
  Toolbar,
  Typography,
} from "@mui/material";
import { lazy, Suspense, useEffect, useState } from "react";

import { api } from "./api";
import { AuthView } from "./components/AuthView";
import type { AuthState } from "./types";

type Workspace = "author" | "runs";

const WorkflowWorkspace = lazy(() =>
  import("./components/WorkflowWorkspace").then((module) => ({
    default: module.WorkflowWorkspace,
  })),
);
const RunWorkspace = lazy(() =>
  import("./components/RunWorkspace").then((module) => ({
    default: module.RunWorkspace,
  })),
);

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [workspace, setWorkspace] = useState<Workspace>("author");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);

  useEffect(() => {
    void api<AuthState>("/api/auth").then(setAuth);
  }, []);

  if (auth === null) {
    return (
      <Box className="loading-shell">
        <CircularProgress aria-label="Loading Relay" />
      </Box>
    );
  }
  if (!auth.authenticated) return <AuthView state={auth} onAuthenticated={setAuth} />;

  async function logout() {
    await api<{ authenticated: boolean }>("/api/auth/logout", {
      method: "POST",
      body: "{}",
    });
    setAuth(await api<AuthState>("/api/auth"));
  }

  return (
    <Box sx={{ minHeight: "100vh" }}>
      <AppBar position="sticky" color="inherit" elevation={0} className="app-header">
        <Toolbar>
          <Typography variant="h5" color="primary" sx={{ mr: 4 }}>Relay</Typography>
          <Tabs
            value={workspace}
            onChange={(_event, value: Workspace) => setWorkspace(value)}
            sx={{ flex: 1 }}
          >
            <Tab value="author" label="Author" />
            <Tab value="runs" label="Runs" />
          </Tabs>
          <Typography variant="body2" color="text.secondary" sx={{ mr: 2 }}>
            {auth.username}
          </Typography>
          <Button color="inherit" onClick={() => void logout()}>Sign out</Button>
        </Toolbar>
      </AppBar>
      <Container maxWidth={false} className="app-content">
        <Suspense fallback={<Box className="loading-panel"><CircularProgress /></Box>}>
          {workspace === "author" ? (
            <WorkflowWorkspace
              onRunLaunched={(runId) => {
                setSelectedRun(runId);
                setWorkspace("runs");
              }}
            />
          ) : (
            <RunWorkspace selectedRun={selectedRun} onSelectRun={setSelectedRun} />
          )}
        </Suspense>
      </Container>
    </Box>
  );
}

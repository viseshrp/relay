import {
  AppBar,
  Alert,
  Box,
  Button,
  CircularProgress,
  Container,
  Stack,
  Tab,
  Tabs,
  Toolbar,
  Typography,
} from "@mui/material";
import { lazy, Suspense, useEffect, useState } from "react";

import { api, errorMessage } from "./api";
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
  const [authAttempt, setAuthAttempt] = useState(0);
  const [authError, setAuthError] = useState<string | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let active = true;
    setAuthError(null);
    void api<AuthState>("/api/auth")
      .then((value) => { if (active) setAuth(value); })
      .catch((caught: unknown) => { if (active) setAuthError(errorMessage(caught)); });
    return () => { active = false; };
  }, [authAttempt]);

  if (auth === null) {
    return (
      <Box className="loading-shell">
        {authError ? (
          <Stack spacing={2} sx={{ maxWidth: 600, p: 2 }}>
            <Alert severity="error">{authError}</Alert>
            <Button variant="contained" onClick={() => setAuthAttempt((value) => value + 1)}>
              Retry
            </Button>
          </Stack>
        ) : <CircularProgress aria-label="Loading Relay" />}
      </Box>
    );
  }
  if (!auth.authenticated) return <AuthView state={auth} onAuthenticated={setAuth} />;

  async function logout() {
    setLogoutError(null);
    setSigningOut(true);
    try {
      await api<{ authenticated: boolean }>("/api/auth/logout", {
        method: "POST", body: "{}",
      });
      setAuth(null);
      setAuthAttempt((value) => value + 1);
    } catch (caught) {
      setLogoutError(errorMessage(caught));
    } finally {
      setSigningOut(false);
    }
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
          <Button color="inherit" onClick={() => void logout()} disabled={signingOut}>Sign out</Button>
        </Toolbar>
      </AppBar>
      <Container maxWidth={false} className="app-content">
        {logoutError && (
          <Alert severity="error" sx={{ mb: 2 }} action={
            <Button color="inherit" onClick={() => void logout()} disabled={signingOut}>Retry</Button>
          }>{logoutError}</Alert>
        )}
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

import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { type FormEvent, useState } from "react";

import { api, errorMessage } from "../api";
import type { AuthState } from "../types";

interface AuthViewProps {
  state: AuthState;
  onAuthenticated: (state: AuthState) => void;
}

export function AuthView({ state, onAuthenticated }: AuthViewProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const path = state.owner_created ? "/api/auth/login" : "/api/auth/onboard";
      await api<{ authenticated: boolean; username: string }>(path, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      onAuthenticated(await api<AuthState>("/api/auth"));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box className="auth-shell">
      <Paper component="form" onSubmit={submit} className="auth-card" elevation={8}>
        <Stack spacing={3}>
          <Box>
            <Typography variant="h4" sx={{ fontWeight: 760 }}>Relay</Typography>
            <Typography color="text.secondary">
              {state.owner_created
                ? "Sign in to Relay on this computer."
                : "Create a password for this computer's Relay. Only people who can use this computer can reach it."}
            </Typography>
          </Box>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            required
            autoFocus
          />
          <TextField
            label="Password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={state.owner_created ? "current-password" : "new-password"}
            required
          />
          {!state.owner_created && (
            <Box>
              <Typography variant="body2">Choose a password that follows these rules:</Typography>
              <Box component="ul" sx={{ pl: 3, my: 1 }}>
                {(state.password_rules ?? []).map((rule) => (
                  <Typography component="li" variant="body2" key={rule}>{rule}</Typography>
                ))}
              </Box>
              <Typography variant="body2" color="text.secondary">
                Relay keeps this password on your computer.
              </Typography>
            </Box>
          )}
          <Button type="submit" variant="contained" size="large" disabled={busy}>
            {busy ? "Working…" : state.owner_created ? "Sign in" : "Create password"}
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}

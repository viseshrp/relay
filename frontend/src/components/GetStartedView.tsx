import { PathDisplay } from "./PathDisplay";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  Link,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import { errorMessage } from "../api";

import { CreateWorkflowDialog } from "./CreateWorkflowDialog";
import { readinessLabel } from "./GetStartedShared";
import type { GetStartedState } from "./useGetStarted";
export function GetStartedView({ state }: { state: GetStartedState }) {
  const {
    onClose,
    complete,
    project,
    onOpenProject,
    inventory,
    readiness,
    checking,
    setError,
    setCheck,
    workflow,
    setNewWorkflow,
    template,
    inputs,
    setInputs,
    model,
    setModel,
    models,
    launch,
    launching,
    error,
    newWorkflow,
    requestProject,
    holder,
    onWorkflowCreated,
    setWorkflow,
    setTemplate,
  } = state;
  return (
    <Dialog
      open
      onClose={onClose}
      fullWidth
      maxWidth="lg"
      aria-labelledby="get-started-title"
    >
      <Box
        component="section"
        aria-labelledby="get-started-title"
        sx={{ display: "flex", flexDirection: "column", minHeight: 0 }}
      >
        <DialogTitle id="get-started-title">Get started</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <Typography>
              Relay runs coding jobs in order, shows their progress, and asks
              for your approval when a workflow needs it.
            </Typography>
            {complete && (
              <Alert severity="success">
                Your first run completed. You can use this checklist again for
                another workflow.
              </Alert>
            )}
            <Box>
              <Typography variant="h6">1. Project ✓</Typography>
              <Typography>{project.display_name}</Typography>
              <PathDisplay
                path={project.canonical_path}
                label={project.display_name}
              />
              <Button onClick={onOpenProject}>Choose another project</Button>
            </Box>
            <Box>
              <Typography variant="h6">2. Agents</Typography>
              <Typography variant="body2">
                One working agent is enough. A connection check reads available
                models; authentication is verified when a run starts.
              </Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: {
                    xs: "1fr",
                    sm: "1fr 1fr",
                    lg: "repeat(5, 1fr)",
                  },
                  gap: 1,
                  mt: 1,
                }}
              >
                {inventory?.agents.map((agent) => {
                  const row = readiness.find((item) => item.id === agent.id);
                  const label = readinessLabel(row, agent.installed, checking);
                  return (
                    <Paper
                      component="article"
                      aria-label={agent.display_name}
                      key={agent.id}
                      variant="outlined"
                      sx={{ p: 2 }}
                    >
                      <Stack spacing={1}>
                        <Typography variant="subtitle1">
                          {agent.display_name}
                        </Typography>
                        <Typography>
                          {row?.ready ? "✓ " : "○ "}
                          {label}
                        </Typography>
                        {!agent.installed && (
                          <Link
                            href={agent.install_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Install {agent.display_name}
                          </Link>
                        )}
                        {agent.installed && row && !row.ready && (
                          <>
                            <Typography variant="body2">
                              {row.reason ??
                                "The agent returned no models. Check its installation and sign-in."}
                            </Typography>
                            <Typography variant="body2">
                              {row.login_guidance}
                            </Typography>
                            <Box component="code">{row.login_command}</Box>
                            <Button
                              onClick={() =>
                                void navigator.clipboard
                                  .writeText(row.login_command)
                                  .catch((caught: unknown) =>
                                    setError(errorMessage(caught)),
                                  )
                              }
                            >
                              Copy sign-in command
                            </Button>
                          </>
                        )}
                        {row?.cleanup_warning && (
                          <Alert severity="warning">
                            {row.cleanup_warning}
                          </Alert>
                        )}
                      </Stack>
                    </Paper>
                  );
                })}
              </Box>
              <Button
                onClick={() => setCheck((value) => value + 1)}
                disabled={checking}
              >
                {checking ? "Checking agents…" : "Check again"}
              </Button>
              {!checking &&
                readiness.length > 0 &&
                !readiness.some((row) => row.ready) && (
                  <Alert severity="warning">
                    Install and sign in to one agent, then choose Check again.
                  </Alert>
                )}
            </Box>
            <Box>
              <Typography variant="h6">
                3. First workflow {workflow ? "✓" : ""}
              </Typography>
              <Button variant="outlined" onClick={() => setNewWorkflow(true)}>
                Start from a template
              </Button>
              <Button onClick={() => setNewWorkflow(true)}>
                Blank workflow
              </Button>
              {workflow && (
                <Typography variant="body2">
                  {template?.name ?? "Blank workflow"} is saved in your project.
                </Typography>
              )}
            </Box>
            <Box>
              <Typography variant="h6">
                4. First run {complete ? "✓" : ""}
              </Typography>
              {!template ? (
                <Typography variant="body2">
                  Choose a template above, or close this checklist to add jobs
                  in the workflow editor.
                </Typography>
              ) : (
                <Stack spacing={2} sx={{ mt: 1 }}>
                  {Object.entries(template.inputs).map(([key, definition]) =>
                    definition.type === "enum" ? (
                      <FormControl key={key}>
                        <InputLabel id={`setup-input-${key}`}>
                          {definition.description ?? key}
                        </InputLabel>
                        <Select
                          labelId={`setup-input-${key}`}
                          label={definition.description ?? key}
                          value={inputs[key] ?? ""}
                          onChange={(event) =>
                            setInputs((current) => ({
                              ...current,
                              [key]: event.target.value,
                            }))
                          }
                        >
                          {definition.constraints?.values?.map((value) => (
                            <MenuItem key={value} value={value}>
                              {value}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    ) : (
                      <TextField
                        key={key}
                        label={definition.description ?? key}
                        value={inputs[key] ?? ""}
                        onChange={(event) =>
                          setInputs((current) => ({
                            ...current,
                            [key]: event.target.value,
                          }))
                        }
                      />
                    ),
                  )}
                  <FormControl>
                    <InputLabel id="setup-model">Model</InputLabel>
                    <Select
                      labelId="setup-model"
                      label="Model"
                      value={model}
                      onChange={(event) => setModel(event.target.value)}
                    >
                      {models.map((value) => (
                        <MenuItem key={value} value={value}>
                          {value}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <Button
                    variant="contained"
                    onClick={() => void launch()}
                    disabled={
                      launching || checking || !model || !models.includes(model)
                    }
                  >
                    Run workflow
                  </Button>
                </Stack>
              )}
            </Box>
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Close checklist</Button>
        </DialogActions>
        <CreateWorkflowDialog
          open={newWorkflow}
          requestProject={requestProject}
          holder={holder.current}
          onClose={() => setNewWorkflow(false)}
          onCreated={async (key, selected) => {
            await onWorkflowCreated(key);
            setWorkflow(key);
            setTemplate(selected);
            setInputs(
              Object.fromEntries(
                Object.entries(selected?.inputs ?? {}).flatMap(
                  ([name, definition]) =>
                    definition.default === undefined
                      ? []
                      : [[name, definition.default]],
                ),
              ),
            );
          }}
        />
      </Box>
    </Dialog>
  );
}

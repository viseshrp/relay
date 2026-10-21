import { WorkflowLibrarySettings } from "./WorkflowLibrarySettings";
import { HelpControl, HelpSelectField, HelpTextField } from "./HelpTip";
import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";

import type { WorkflowSettingsState } from "./useWorkflowSettings";
export function WorkflowSettingsView({
  state,
}: {
  state: WorkflowSettingsState;
}) {
  const {
    open,
    onClose,
    busy,
    setValue,
    value,
    tab,
    setTab,
    error,
    scope,
    setScope,
    environment,
    setEnvironment,
    environments,
    bindings,
    selectedScope,
    mutate,
    name,
    setName,
    kind,
    setKind,
    source,
    setSource,
    reference,
    setReference,
    setConfig,
    config,
  } = state;
  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!busy) {
          setValue("");
          onClose();
        }
      }}
      fullWidth
      maxWidth="md"
    >
      <DialogTitle>Workflow settings</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Tabs value={tab} onChange={(_, next: number) => setTab(next)}>
            <Tab label="Variables and secrets" />
            <Tab label="Environments" />
            <Tab label="Workflow library" />
          </Tabs>
          {error && <Alert severity="error">{error}</Alert>}
          {tab === 0 && (
            <>
              <HelpSelectField
                topic="bindingScope"
                label="Scope"
                value={scope}
                onChange={(e) => setScope(String(e.target.value))}
              >
                <MenuItem value="installation">All projects</MenuItem>
                <MenuItem value="project">This project</MenuItem>
                <MenuItem value="environment">Environment</MenuItem>
              </HelpSelectField>
              {scope === "environment" && (
                <HelpSelectField
                  topic="bindingEnvironment"
                  label="Binding environment"
                  value={environment}
                  onChange={(e) => setEnvironment(String(e.target.value))}
                >
                  {environments.map((item) => (
                    <MenuItem key={item.name} value={item.name}>
                      {item.name}
                    </MenuItem>
                  ))}
                </HelpSelectField>
              )}
              {bindings
                .filter((item) => item.scope === selectedScope)
                .map((item) => (
                  <Stack
                    direction="row"
                    spacing={1}
                    key={`${item.kind}:${item.name}`}
                    sx={{ alignItems: "center" }}
                  >
                    <Typography sx={{ flex: 1 }}>
                      {item.name} ·{" "}
                      {item.kind === "secret"
                        ? `${item.source}: ${item.source === "environment" ? item.reference : "saved credential"}`
                        : item.value}
                    </Typography>
                    <Button
                      disabled={busy}
                      onClick={() =>
                        void mutate("/api/workflow-bindings", {
                          scope,
                          environment,
                          name: item.name,
                          kind: item.kind,
                          delete: true,
                        })
                      }
                    >
                      Remove {item.name}
                    </Button>
                  </Stack>
                ))}
              <HelpTextField
                topic="bindingName"
                label="Binding name"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <HelpSelectField
                topic="bindingType"
                label="Binding type"
                value={kind}
                onChange={(e) => {
                  setKind(String(e.target.value));
                  setValue("");
                }}
              >
                <MenuItem value="variable">Variable</MenuItem>
                <MenuItem value="secret">Secret</MenuItem>
              </HelpSelectField>
              {kind === "secret" && (
                <HelpSelectField
                  topic="secretSource"
                  label="Secret source"
                  width="wide"
                  value={source}
                  onChange={(e) => {
                    setSource(String(e.target.value));
                    setValue("");
                  }}
                >
                  <MenuItem value="environment">
                    Process environment variable
                  </MenuItem>
                  <MenuItem value="credential-store">
                    Native credential store
                  </MenuItem>
                </HelpSelectField>
              )}
              {kind === "secret" && source === "environment" ? (
                <HelpTextField
                  topic="secretReference"
                  label="Environment variable reference"
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                />
              ) : (
                <HelpTextField
                  topic="bindingValue"
                  label={
                    kind === "secret" ? "New secret value" : "Variable value"
                  }
                  type={kind === "secret" ? "password" : "text"}
                  autoComplete="off"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                />
              )}
              <Typography variant="body2">
                Project values override values for all projects. Approved
                environments can override project values. Saved secret values
                are never returned to this editor.
              </Typography>
              <Button
                disabled={
                  busy || !name || (scope === "environment" && !environment)
                }
                onClick={() =>
                  void mutate("/api/workflow-bindings", {
                    scope,
                    environment,
                    name,
                    kind,
                    source,
                    reference,
                    value,
                  })
                }
              >
                Save binding
              </Button>
            </>
          )}
          {tab === 1 && (
            <>
              {environments.map((item) => (
                <Button key={item.name} onClick={() => setConfig(item)}>
                  Edit {item.name}
                </Button>
              ))}
              <HelpTextField
                topic="environmentName"
                label="Environment name"
                value={config.name}
                onChange={(e) => setConfig({ ...config, name: e.target.value })}
              />
              <HelpControl topic="environmentApproval">
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={config.approval_required}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          approval_required: e.target.checked,
                        })
                      }
                    />
                  }
                  label="Require my approval before this job starts"
                />
              </HelpControl>
              <HelpTextField
                topic="environmentWait"
                label="Wait timer (minutes)"
                type="number"
                value={config.wait_minutes}
                onChange={(e) =>
                  setConfig({ ...config, wait_minutes: Number(e.target.value) })
                }
              />
              <HelpTextField
                topic="environmentBranches"
                label="Allowed branch patterns (one per line)"
                multiline
                value={config.branches.join("\n")}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    branches: e.target.value.split("\n").filter(Boolean),
                  })
                }
              />
              <HelpTextField
                topic="environmentUrl"
                label="Environment URL"
                value={config.url}
                onChange={(e) => setConfig({ ...config, url: e.target.value })}
              />
              <Button
                disabled={busy || !config.name}
                onClick={() =>
                  void mutate("/api/workflow-environments", config)
                }
              >
                Save environment
              </Button>
            </>
          )}
          {tab === 2 && (
            <>
              <WorkflowLibrarySettings state={state} />
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={() => {
            setValue("");
            onClose();
          }}
          disabled={busy}
        >
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}

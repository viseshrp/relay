import {
  Alert,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
} from "@mui/material";
import type { GetStartedState } from "./useGetStarted";

export function GetStartedRunInputs({ state }: { state: GetStartedState }) {
  const {
    template,
    inputs,
    setInputs,
    model,
    setModel,
    models,
    fullWorkflow,
    codingModels,
    claudeModels,
    readyToRun,
    launch,
    launching,
    checking,
  } = state;
  if (!template) return null;
  return (
    <Stack spacing={2} sx={{ mt: 1 }}>
      {Object.entries(template.inputs).map(([key, definition]) =>
        fullWorkflow && (key === "model" || key === "opus_model") ? (
          <FormControl key={key} required>
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
              {(key === "model" ? codingModels : claudeModels).map((value) => (
                <MenuItem key={value} value={value}>
                  {value}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        ) : definition.type === "enum" ? (
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
                  ...(fullWorkflow && key === "agent" ? { model: "" } : {}),
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
      {fullWorkflow && !claudeModels.length && (
        <Alert severity="warning">
          Install and sign in to Claude Code, then choose Check again. This
          workflow uses Claude Opus for planning and review.
        </Alert>
      )}
      {!fullWorkflow && (
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
      )}
      <Button
        variant="contained"
        onClick={() => void launch()}
        disabled={launching || checking || !readyToRun}
      >
        Run workflow
      </Button>
    </Stack>
  );
}

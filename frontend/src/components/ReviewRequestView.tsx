import { ReviewEvidence } from "./RunReviewShared";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import { jobDuration } from "../job";

import { stageLabel } from "../navigation";

import { object } from "./RunReviewShared";
import type { ReviewRequestState } from "./useReviewRequest";
export function ReviewRequestView({ state }: { state: ReviewRequestState }) {
  const {
    card,
    interaction,
    selected,
    isReview,
    link,
    runId,
    artifacts,
    options,
    busy,
    answer,
    labelId,
    value,
    setValue,
    simpleForm,
    fields,
    form,
    setForm,
    required,
    feedback,
    setFeedback,
    error,
    ready,
  } = state;
  return (
    <Paper
      ref={card}
      id={`request-${interaction.id}`}
      variant="outlined"
      className="interaction-card"
      sx={{ borderColor: selected ? "primary.main" : "warning.main" }}
    >
      <Stack spacing={2}>
        <Stack
          direction="row"
          spacing={1}
          sx={{ alignItems: "center", justifyContent: "space-between" }}
        >
          <Typography variant="h6">
            {isReview
              ? "Your review is needed"
              : interaction.kind === "permission"
                ? "A tool needs your permission"
                : "An agent needs an answer"}
          </Typography>
          <Button component="a" href={link()}>
            Link to request
          </Button>
        </Stack>
        <Typography variant="subtitle2">
          {stageLabel(interaction.scope_path)}
        </Typography>
        <Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {String(interaction.request.prompt ?? "Your response is needed.")}
        </Typography>
        {interaction.deadline && (
          <Typography variant="body2">
            Expires in{" "}
            {jobDuration(new Date().toISOString(), interaction.deadline)} (
            {String(interaction.request.deadline_source ?? "workflow timeout")}
            ).
          </Typography>
        )}
        {isReview && (
          <ReviewEvidence runId={runId} artifacts={artifacts} pendingReview />
        )}
        <Box data-owner-response>
          {isReview && options.length > 0 && (
            <Stack
              direction="row"
              spacing={1}
              useFlexGap
              sx={{ flexWrap: "wrap", mb: 2 }}
            >
              {options
                .filter((item): item is string => typeof item === "string")
                .map((option) => (
                  <Button
                    key={option}
                    variant="contained"
                    disabled={busy}
                    onClick={() => void answer(false, option)}
                  >
                    {option}
                  </Button>
                ))}
            </Stack>
          )}
          {interaction.request.environment ? (
            <Typography>
              Approve this environment to release its job after the wait timer.
            </Typography>
          ) : interaction.kind === "permission" ? (
            <FormControl fullWidth size="small">
              <InputLabel id={labelId} shrink>
                Your decision
              </InputLabel>
              <Select
                displayEmpty
                renderValue={
                  value === "" ? () => "Choose a response" : undefined
                }
                labelId={labelId}
                label="Your decision"
                value={value}
                onChange={(event) => setValue(event.target.value)}
              >
                {options.flatMap((item) => {
                  const option = object(item);
                  const id = typeof item === "string" ? item : option?.id;
                  return typeof id === "string"
                    ? [
                        <MenuItem key={id} value={id}>
                          {String(option?.name ?? id)}
                        </MenuItem>,
                      ]
                    : [];
                })}
              </Select>
            </FormControl>
          ) : interaction.kind === "elicitation" && simpleForm ? (
            <Stack spacing={1.5}>
              {Object.entries(fields ?? {}).map(([name, raw]) => {
                const field = object(raw) ?? {};
                const label = String(field.title ?? stageLabel(name));
                return field.type === "boolean" ? (
                  <FormControlLabel
                    key={name}
                    label={label}
                    control={
                      <Checkbox
                        checked={form[name] === true}
                        onChange={(event) =>
                          setForm((current) => ({
                            ...current,
                            [name]: event.target.checked,
                          }))
                        }
                      />
                    }
                  />
                ) : Array.isArray(field.enum) ? (
                  <FormControl key={name}>
                    <InputLabel id={`${labelId}-${name}`} shrink>
                      {label}
                    </InputLabel>
                    <Select
                      displayEmpty
                      renderValue={
                        form[name] === undefined
                          ? () => "Choose a value"
                          : undefined
                      }
                      labelId={`${labelId}-${name}`}
                      label={label}
                      value={String(form[name] ?? "")}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          [name]:
                            (Array.isArray(field.enum)
                              ? field.enum.find(
                                  (item) => String(item) === event.target.value,
                                )
                              : undefined) ?? event.target.value,
                        }))
                      }
                    >
                      {field.enum.map((item) => (
                        <MenuItem key={String(item)} value={String(item)}>
                          {String(item)}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                ) : (
                  <TextField
                    key={name}
                    label={label}
                    required={required.includes(name)}
                    helperText={
                      typeof field.description === "string"
                        ? field.description
                        : undefined
                    }
                    value={form[name] ?? ""}
                    type={
                      field.type === "number" || field.type === "integer"
                        ? "number"
                        : "text"
                    }
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        [name]:
                          field.type === "number" || field.type === "integer"
                            ? event.target.value === ""
                              ? ""
                              : Number(event.target.value)
                            : event.target.value,
                      }))
                    }
                  />
                );
              })}
            </Stack>
          ) : (
            <TextField
              fullWidth
              label={isReview ? "Your response" : "Response (JSON object)"}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              multiline
              minRows={2}
              maxRows={8}
              helperText={
                isReview
                  ? "Use the response requested in the instructions above. Sending it allows the next jobs to continue."
                  : "Enter the fields requested by the agent, or decline below."
              }
            />
          )}
        </Box>
        {!isReview && (
          <TextField
            label="Feedback for the agent (optional)"
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            multiline
            minRows={2}
            maxRows={8}
            helperText="Your decision answers this request. Feedback is sent in the same session after the agent finishes this turn; it does not grant permission."
          />
        )}
        <Typography variant="body2" color="text.secondary">
          {isReview
            ? "This is a human review. Relay will not approve it for you."
            : "Select a response deliberately. Relay resumes the agent with your answer."}
        </Typography>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
          <Button
            variant="contained"
            onClick={() => void answer()}
            disabled={busy || !ready}
          >
            {busy
              ? "Sending…"
              : interaction.request.environment
                ? "Approve environment"
                : "Send response and continue"}
          </Button>
          {interaction.kind === "elicitation" && (
            <Button disabled={busy} onClick={() => void answer(true)}>
              Decline request
            </Button>
          )}
        </Stack>
      </Stack>
    </Paper>
  );
}

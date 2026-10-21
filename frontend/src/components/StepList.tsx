import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Button,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Menu,
  Stack,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { actionLabel } from "../action-labels";
import { stepLabel, type ActionStep } from "../actions-workflow";
import { GUIDE, propertyHelp } from "../field-help";
import type { LanguageManifest } from "../workflow-language";
import { ActionIcon } from "./ActionIcon";
import { AdvancedJsonField } from "./AdvancedJsonField";
import { HelpLabel, HelpTextField } from "./HelpTip";
import { addStepOptions } from "./StepTypeOptions";

/** A job's steps in order, each selectable and movable, and Add step. */
export function StepList({
  steps,
  current,
  manifest,
  loopAvailable,
  onIndex,
  onMove,
  onAdd,
}: {
  steps: ActionStep[];
  current: number;
  manifest: LanguageManifest;
  loopAvailable: boolean;
  onIndex: (index: number) => void;
  onMove: (from: number, to: number) => void;
  /** Add a step of this type name. */
  onAdd: (name: string) => void;
}) {
  const [menu, setMenu] = useState<HTMLElement | null>(null);
  return (
    <>
      <Typography component="h3" variant="subtitle1">
        <HelpLabel
          topic={propertyHelp(
            manifest,
            "job-factory.steps",
            "Steps in this job",
          )}
        >
          Steps in this job
        </HelpLabel>
      </Typography>
      <List dense aria-label="Steps in this job" disablePadding>
        {steps.map((item, offset) => (
          <ListItem
            key={offset}
            disablePadding
            secondaryAction={
              <>
                <IconButton
                  size="small"
                  disabled={offset === 0}
                  aria-label={`Move step ${offset + 1} earlier`}
                  onClick={() => onMove(offset, offset - 1)}
                >
                  <ActionIcon name="up" />
                </IconButton>
                <IconButton
                  size="small"
                  disabled={offset === steps.length - 1}
                  aria-label={`Move step ${offset + 1} later`}
                  onClick={() => onMove(offset, offset + 1)}
                >
                  <ActionIcon name="down" />
                </IconButton>
              </>
            }
          >
            <ListItemButton
              selected={offset === current}
              aria-current={offset === current ? "step" : undefined}
              onClick={() => onIndex(offset)}
              sx={{ pr: 11 }}
            >
              <ListItemText
                primary={`${offset + 1}. ${stepLabel(item)}`}
                secondary={actionLabel(item.uses)}
                slotProps={{ primary: { sx: { overflowWrap: "anywhere" } } }}
              />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
      <Button
        sx={{ alignSelf: "start" }}
        aria-haspopup="menu"
        aria-expanded={Boolean(menu)}
        onClick={(event) => setMenu(event.currentTarget)}
        endIcon={<ActionIcon name="down" />}
      >
        Add step
      </Button>
      <Menu anchorEl={menu} open={Boolean(menu)} onClose={() => setMenu(null)}>
        {addStepOptions(manifest, loopAvailable, (name) => {
          setMenu(null);
          onAdd(name);
        })}
      </Menu>
    </>
  );
}

/** The raw action reference and inputs, for local actions and JSON edits. */
export function StepAdvanced({
  step,
  manifest,
  onStep,
  onInputs,
}: {
  step: ActionStep;
  manifest: LanguageManifest;
  onStep: (step: ActionStep) => void;
  onInputs: (inputs: unknown) => void;
}) {
  return (
    <Accordion
      disableGutters
      defaultExpanded={Boolean(step.uses?.startsWith("./"))}
    >
      <AccordionSummary expandIcon={<ActionIcon name="down" />}>
        Advanced
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          <HelpTextField
            topic={propertyHelp(
              manifest,
              "regular-step.uses",
              "Action reference",
              GUIDE.reusable,
            )}
            label="Action reference"
            width="wide"
            value={step.uses ?? ""}
            onChange={(event) =>
              onStep(
                event.target.value
                  ? { ...step, uses: event.target.value, run: undefined }
                  : { ...step, uses: undefined, run: "echo Ready" },
              )
            }
          />
          {step.uses && (
            <AdvancedJsonField
              label="Action inputs"
              help={propertyHelp(
                manifest,
                "regular-step.with",
                "Action inputs",
                GUIDE.reusable,
              )}
              object
              value={step.with ?? {}}
              onChange={onInputs}
            />
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}

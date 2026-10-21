import { Button, Stack, Typography } from "@mui/material";
import { HelpTextField } from "./HelpTip";

import { errorMessage } from "../api";

import type { WorkflowSettingsState } from "./useWorkflowSettings";
export function WorkflowLibrarySettings({
  state,
}: {
  state: WorkflowSettingsState;
}) {
  const {
    templates,
    exportTemplate,
    templateName,
    setTemplateName,
    description,
    setDescription,
    busy,
    mutate,
    yaml,
    bundle,
    setBundle,
    setError,
  } = state;
  return (
    <>
      {templates.map((item) => (
        <Stack direction="row" spacing={1} key={item.id}>
          <Typography sx={{ flex: 1 }}>
            {item.name} {item.description}
          </Typography>
          <Button onClick={() => void exportTemplate(item.id)}>
            Export {item.name}
          </Button>
        </Stack>
      ))}
      <HelpTextField
        topic="libraryName"
        label="Library workflow name"
        value={templateName}
        onChange={(e) => setTemplateName(e.target.value)}
      />
      <HelpTextField
        topic="libraryDescription"
        label="Library description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <Button
        disabled={busy || !templateName}
        onClick={() =>
          void mutate("/api/workflow-library", {
            yaml,
            metadata: { name: templateName, description },
            sources: {},
            include_project_sources: true,
          })
        }
      >
        Save current workflow to library
      </Button>
      <HelpTextField
        topic="libraryImport"
        label="Import workflow bundle"
        multiline
        minRows={4}
        value={bundle}
        onChange={(e) => setBundle(e.target.value)}
      />
      <Button
        disabled={busy || !bundle}
        onClick={() => {
          try {
            void mutate("/api/workflow-library", JSON.parse(bundle));
          } catch (e) {
            setError(errorMessage(e));
          }
        }}
      >
        Import bundle
      </Button>
    </>
  );
}

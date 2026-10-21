import {
  Alert,
  Button,
  FormHelperText,
  IconButton,
  Link,
  ListItemText,
  MenuItem,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { parseListInput } from "../list-input";
import type { AgentRecord } from "../types";
import { ActionIcon } from "./ActionIcon";
import { HelpGroup, HelpSelectField, type HelpSource } from "./HelpTip";

type Route = "saved" | "one" | "order";

function status(agent: AgentRecord | undefined): string {
  return agent?.installed ? "Installed" : "Not installed";
}

/**
 * Where an agent step runs: the saved order from Settings, one agent, or a
 * list to try in order. Changing the route clears the effort, which belongs
 * to one agent's model.
 */
export function AgentRouteField({
  inputs,
  agents,
  preferences,
  help,
  agentHelp,
  orderHelp,
  onChange,
  onEditYaml,
  onOpenGetStarted,
}: {
  inputs: Record<string, unknown>;
  agents: AgentRecord[];
  preferences: string[];
  help: HelpSource;
  agentHelp: HelpSource;
  orderHelp: HelpSource;
  onChange: (inputs: Record<string, unknown>) => void;
  onEditYaml: () => void;
  onOpenGetStarted?: () => void;
}) {
  const agent = inputs.agent === undefined ? "" : String(inputs.agent);
  const raw = inputs.agents === undefined ? "" : String(inputs.agents);
  const route: Route = agent ? "one" : raw ? "order" : "saved";
  const order = raw ? parseListInput(raw) : [];
  const byId = new Map(agents.map((item) => [item.id, item]));
  const name = (id: string) => byId.get(id)?.display_name ?? id;
  const expression = [agent, raw].find((value) => value.includes("${{"));
  function write(next: { agent?: string; agents?: string[] }): void {
    onChange({
      ...inputs,
      agent: next.agent || undefined,
      agents: next.agents?.length ? JSON.stringify(next.agents) : undefined,
      effort: undefined,
    });
  }
  function choose(next: Route | null): void {
    if (!next || next === route) return;
    const listed = order ?? [];
    if (next === "saved") write({});
    else if (next === "one") {
      const candidates = [...listed, ...preferences, ...byId.keys()];
      write({
        agent:
          candidates.find((id) => byId.get(id)?.installed) ?? candidates[0],
      });
    } else
      write({
        agents: agent
          ? [agent]
          : preferences.length
            ? preferences
            : agents.filter((item) => item.installed).map((item) => item.id),
      });
  }
  const shown =
    route === "one" ? [agent] : route === "order" ? (order ?? []) : [];
  const missing = shown.some((id) => !byId.get(id)?.installed);
  return (
    <HelpGroup topic={help} label="Runs on">
      {expression !== undefined ? (
        <Stack spacing={0.5}>
          <Typography sx={{ overflowWrap: "anywhere" }}>
            Set by an expression: {expression}
          </Typography>
          <Link
            component="button"
            type="button"
            sx={{ alignSelf: "start" }}
            onClick={onEditYaml}
          >
            Edit in YAML
          </Link>
        </Stack>
      ) : (
        <Stack spacing={1}>
          <ToggleButtonGroup
            exclusive
            size="small"
            aria-label="Runs on"
            value={route}
            onChange={(_, next: Route | null) => choose(next)}
            sx={{ flexWrap: "wrap" }}
          >
            <ToggleButton value="saved">Saved order</ToggleButton>
            <ToggleButton value="one">One agent</ToggleButton>
            <ToggleButton value="order">Try in order</ToggleButton>
          </ToggleButtonGroup>
          {route === "saved" && (
            <FormHelperText>
              Uses the order from Settings:{" "}
              {preferences.map(name).join(", ") || "none saved"}
            </FormHelperText>
          )}
          {route === "one" && (
            <HelpSelectField
              topic={agentHelp}
              label="Agent"
              size="small"
              value={agent}
              renderValue={(id) => name(String(id))}
              onChange={(event) => write({ agent: String(event.target.value) })}
            >
              {agents.map((item) => (
                <MenuItem
                  key={item.id}
                  value={item.id}
                  disabled={!item.installed && item.id !== agent}
                >
                  <ListItemText
                    primary={item.display_name}
                    secondary={status(item)}
                  />
                </MenuItem>
              ))}
              {!byId.has(agent) && (
                <MenuItem value={agent}>
                  <ListItemText primary={agent} secondary={status(undefined)} />
                </MenuItem>
              )}
            </HelpSelectField>
          )}
          {route === "order" && order === null && (
            <Alert severity="error">
              This agent list is not valid. Fix it in YAML or replace it here.
            </Alert>
          )}
          {route === "order" && (
            <>
              <Stack
                component="ol"
                aria-label="Agents to try in order"
                spacing={0.5}
                sx={{ m: 0, p: 0, listStyle: "none" }}
              >
                {(order ?? []).map((id, index, list) => (
                  <Stack
                    key={`${id}-${index}`}
                    component="li"
                    direction="row"
                    spacing={1}
                    sx={{ alignItems: "center" }}
                  >
                    <ListItemText
                      primary={`${index + 1}. ${name(id)}`}
                      secondary={status(byId.get(id))}
                    />
                    <IconButton
                      size="small"
                      disabled={index === 0}
                      aria-label={`Move ${name(id)} earlier`}
                      onClick={() => {
                        const next = [...list];
                        next.splice(index - 1, 0, ...next.splice(index, 1));
                        write({ agents: next });
                      }}
                    >
                      <ActionIcon name="up" />
                    </IconButton>
                    <IconButton
                      size="small"
                      disabled={index === list.length - 1}
                      aria-label={`Move ${name(id)} later`}
                      onClick={() => {
                        const next = [...list];
                        next.splice(index + 1, 0, ...next.splice(index, 1));
                        write({ agents: next });
                      }}
                    >
                      <ActionIcon name="down" />
                    </IconButton>
                    <Button
                      size="small"
                      aria-label={`Remove ${name(id)}`}
                      onClick={() =>
                        write({
                          agents: list.filter((_, offset) => offset !== index),
                        })
                      }
                    >
                      Remove
                    </Button>
                  </Stack>
                ))}
              </Stack>
              {agents.some((item) => !(order ?? []).includes(item.id)) && (
                <HelpSelectField
                  topic={orderHelp}
                  label="Add an agent"
                  size="small"
                  value=""
                  placeholder="Choose an agent"
                  onChange={(event) =>
                    write({
                      agents: [...(order ?? []), String(event.target.value)],
                    })
                  }
                >
                  {agents
                    .filter((item) => !(order ?? []).includes(item.id))
                    .map((item) => (
                      <MenuItem
                        key={item.id}
                        value={item.id}
                        disabled={!item.installed}
                      >
                        <ListItemText
                          primary={item.display_name}
                          secondary={status(item)}
                        />
                      </MenuItem>
                    ))}
                </HelpSelectField>
              )}
            </>
          )}
          {(missing || route !== "saved") &&
            agents.some((item) => !item.installed) &&
            onOpenGetStarted && (
              <FormHelperText component="div">
                Agents marked Not installed cannot run until they are set up.{" "}
                <Link
                  component="button"
                  type="button"
                  onClick={onOpenGetStarted}
                >
                  Open Get started
                </Link>
              </FormHelperText>
            )}
        </Stack>
      )}
    </HelpGroup>
  );
}

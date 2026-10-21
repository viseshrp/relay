import { Divider, ListItemText, ListSubheader, MenuItem } from "@mui/material";
import type { ReactNode } from "react";
import {
  ACTION_TYPES,
  PRIMARY_STEP_TYPES,
  type ActionType,
} from "../action-labels";
import { currentBuiltin } from "../builtin-actions";
import type { LanguageManifest } from "../workflow-language";

export const NEEDS_LOOP_TARGET = "Needs another workflow to repeat";

/** The step types this Relay offers: scripts and every current built-in. */
export function offeredTypes(manifest: LanguageManifest): ActionType[] {
  const names = new Set(
    Object.values(manifest.builtin_versions)
      .filter((version) => version.status === "current")
      .map((version) => version.name),
  );
  return ACTION_TYPES.filter(
    (type) => type.name === "script" || names.has(type.name),
  );
}

/** The reference a step of this type uses; scripts have none. */
export function typeReference(
  manifest: LanguageManifest,
  name: string,
): string {
  return name === "script" ? "" : currentBuiltin(manifest, name);
}

function option(
  type: ActionType,
  loopAvailable: boolean,
  onPick?: (name: string) => void,
): ReactNode {
  const blocked = type.name === "loop" && !loopAvailable;
  return (
    <MenuItem
      key={type.name}
      value={onPick ? undefined : type.name}
      disabled={blocked}
      onClick={onPick ? () => onPick(type.name) : undefined}
    >
      <ListItemText
        primary={type.label}
        secondary={blocked ? NEEDS_LOOP_TARGET : type.description}
      />
    </MenuItem>
  );
}

/** Select options under one subheader per group. */
export function groupedTypeOptions(
  manifest: LanguageManifest,
  loopAvailable: boolean,
): ReactNode[] {
  const types = offeredTypes(manifest);
  return [...new Set(types.map((type) => type.group))].flatMap((group) => [
    <ListSubheader key={`group-${group}`}>{group}</ListSubheader>,
    ...types
      .filter((type) => type.group === group)
      .map((type) => option(type, loopAvailable)),
  ]);
}

/** Add step's menu: the common types first, then the rest under More. */
export function addStepOptions(
  manifest: LanguageManifest,
  loopAvailable: boolean,
  onPick: (name: string) => void,
): ReactNode[] {
  const types = offeredTypes(manifest);
  const primary = PRIMARY_STEP_TYPES.flatMap(
    (name) => types.find((type) => type.name === name) ?? [],
  );
  const more = types.filter((type) => !PRIMARY_STEP_TYPES.includes(type.name));
  return [
    ...primary.map((type) => option(type, loopAvailable, onPick)),
    ...(more.length
      ? [
          <Divider key="divider" />,
          <ListSubheader key="more">More</ListSubheader>,
          ...more.map((type) => option(type, loopAvailable, onPick)),
        ]
      : []),
  ];
}

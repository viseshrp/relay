import { ActionIcon } from "./ActionIcon";
import { useThemeMode } from "../theme";
import { Box, Button, Menu, MenuItem } from "@mui/material";
import { useState } from "react";

export function ThemeToggle() {
  const { preference, resolvedTheme, setPreference } = useThemeMode();
  const [themeAnchor, setThemeAnchor] = useState<HTMLElement | null>(null);

  return (
    <>
      <Button
        aria-label={`Theme mode: ${preference === "system" ? `System (${resolvedTheme})` : preference}`}
        aria-haspopup="menu"
        aria-expanded={themeAnchor !== null}
        startIcon={
          <ActionIcon
            name={
              preference === "system"
                ? "monitor"
                : resolvedTheme === "dark"
                  ? "moon"
                  : "sun"
            }
            size={16}
          />
        }
        endIcon={<ActionIcon name="down" size={12} />}
        onClick={(event) => setThemeAnchor(event.currentTarget)}
      >
        {preference === "system"
          ? "Auto"
          : preference === "dark"
            ? "Dark"
            : "Light"}
      </Button>
      <Menu
        anchorEl={themeAnchor}
        open={themeAnchor !== null}
        onClose={() => setThemeAnchor(null)}
      >
        <MenuItem
          selected={preference === "system"}
          onClick={() => {
            setPreference("system");
            setThemeAnchor(null);
          }}
        >
          <ActionIcon name="monitor" size={16} />
          <Box component="span" sx={{ ml: 1, mr: 2, flex: 1 }}>
            System
          </Box>
          {preference === "system" && <ActionIcon name="check" size={16} />}
        </MenuItem>
        <MenuItem
          selected={preference === "light"}
          onClick={() => {
            setPreference("light");
            setThemeAnchor(null);
          }}
        >
          <ActionIcon name="sun" size={16} />
          <Box component="span" sx={{ ml: 1, mr: 2, flex: 1 }}>
            Light
          </Box>
          {preference === "light" && <ActionIcon name="check" size={16} />}
        </MenuItem>
        <MenuItem
          selected={preference === "dark"}
          onClick={() => {
            setPreference("dark");
            setThemeAnchor(null);
          }}
        >
          <ActionIcon name="moon" size={16} />
          <Box component="span" sx={{ ml: 1, mr: 2, flex: 1 }}>
            Dark
          </Box>
          {preference === "dark" && <ActionIcon name="check" size={16} />}
        </MenuItem>
      </Menu>
    </>
  );
}

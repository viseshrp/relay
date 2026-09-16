"""Wheel-only frontend build hook for Relay's packaged browser application."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, TypeAlias

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

BuildData: TypeAlias = dict[str, Any]


class CustomBuildHook(BuildHookInterface):
    """Compile deterministic static assets before Hatch collects the wheel."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: BuildData) -> None:
        """Build the Vite application only for a wheel target."""
        del version
        if self.target_name != "wheel":
            return

        root = Path(self.root)
        frontend = root / "frontend"
        static_root = root / "relay" / "static"
        # The build environment supplies npm on PATH on Windows and POSIX.
        subprocess.run(["npm", "ci"], cwd=frontend, check=True, shell=False)  # noqa: S607
        subprocess.run(
            ["npm", "run", "build"],  # noqa: S607
            cwd=frontend,
            check=True,
            shell=False,
        )

        index = static_root / "index.html"
        assets = static_root / "assets"
        if not index.is_file() or not any(path.is_file() for path in assets.rglob("*")):
            message = "The frontend build did not produce Relay's required static assets."
            raise RuntimeError(message)

        force_include = build_data.setdefault("force_include", {})
        if not isinstance(force_include, dict):
            message = "Hatch supplied an invalid force_include build mapping."
            raise TypeError(message)
        force_include[str(static_root)] = "relay/static"


__all__ = ["CustomBuildHook"]

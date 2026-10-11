"""Wheel-only frontend build hook for Relay's packaged browser application."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Any, TypeAlias

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

BuildData: TypeAlias = dict[str, Any]


class CustomBuildHook(BuildHookInterface):
    """Compile deterministic static assets before Hatch collects the wheel."""

    PLUGIN_NAME: str = "custom"

    def initialize(self, version: str, build_data: BuildData) -> None:
        """Build Vite for distributed wheels; editable checkouts build explicitly."""
        # Hatch's editable build is a wheel target with version "editable".
        if self.target_name != "wheel" or version == "editable":
            return

        root = Path(self.root)
        frontend = root / "frontend"
        static_root = root / "relay" / "static"
        # Resolve PATHEXT entries so Windows selects npm.cmd without a shell.
        npm = shutil.which("npm")
        if npm is None:
            message = "Building a Relay wheel requires npm on PATH."
            raise RuntimeError(message)
        # The build operator controls PATH; shell=False prevents command parsing.
        subprocess.run(  # noqa: S603
            [npm, "ci"], cwd=frontend, check=True, shell=False
        )
        subprocess.run(  # noqa: S603
            [npm, "run", "build:dist"],
            cwd=frontend,
            check=True,
            shell=False,
        )

        index = static_root / "index.html"
        assets = static_root / "assets"
        if not index.is_file() or not any(path.is_file() for path in assets.rglob("*")):
            message = "The frontend build did not produce Relay's required static assets."
            raise RuntimeError(message)

        # Development diagnostics never become public wheel assets.
        for source_map in static_root.rglob("*.map"):
            source_map.unlink()
        shutil.rmtree(static_root / ".vite", ignore_errors=True)
        (static_root / ".relay-builds.json").unlink(missing_ok=True)
        for build_manifest in static_root.glob(".relay-build-*.json"):
            build_manifest.unlink()

        force_include = build_data.setdefault("force_include", {})
        if not isinstance(force_include, dict):
            message = "Hatch supplied an invalid force_include build mapping."
            raise TypeError(message)
        force_include[str(static_root)] = "relay/static"


__all__ = ["CustomBuildHook"]

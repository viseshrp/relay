"""Probe offline agent versions without importing the ACP protocol implementation."""

from __future__ import annotations

from io import TextIOWrapper
import json
import os
from pathlib import Path
import sys


def main() -> None:
    if "--version" not in sys.argv:
        import runpy

        runpy.run_path(str(Path(__file__).with_name("fake_agent.py")), run_name="__main__")
        return

    # Match the protocol's UTF-8 pipes even under a Windows console code page.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    target = os.environ.get("FAKE_AGENT_TRACE")
    if target:
        with Path(target).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"version_probe": True}) + "\n")
    sys.stdout.write("fake-agent 1.2.3\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()

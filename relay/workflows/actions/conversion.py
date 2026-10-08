"""Preview only provable legacy conversions; never replace source on read."""

from __future__ import annotations

from io import StringIO
import json
from typing import Any

from ruamel.yaml import YAML

from relay.execution.timing import duration_seconds
from relay.workflows.loader import load_workflow_text


def preview(text: str) -> dict[str, Any]:
    definition = load_workflow_text(text).definition
    issues = []
    if definition.actions:
        return {"yaml": text, "issues": [], "complete": True}
    jobs = {}
    for key, node in definition.nodes.items():
        raw = node.model_dump(mode="json", by_alias=True, exclude_none=True)
        if raw.get("if") or raw.get("outputs") or raw.get("repair_rule") or raw.get("env"):
            issues.append(f"{key}: expressions, typed reports, or repairs need owner review.")
        if raw.get("writes") or raw.get("allow_no_commit") or raw.get("permission_profile"):
            issues.append(f"{key}: Git write and permission policies need owner review.")
        step: dict[str, Any] = {"id": key}
        if node.type == "command":
            run = raw["run"]
            step.update(
                {
                    "uses": "relay/command@v1",
                    "with": {"argv": json.dumps(run)}
                    if isinstance(run, list)
                    else {"command": run["command"]},
                }
            )
        elif node.type == "agent":
            step.update(
                {
                    "uses": "relay/agent@v1",
                    "with": {
                        "agents": json.dumps(raw["agents"] or definition.agents),
                        **(
                            {"model": raw.get("model") or definition.model}
                            if raw.get("model") or definition.model
                            else {}
                        ),
                        "prompt-files": "\n".join(
                            item.get("local", "global:" + item.get("global", ""))
                            for item in raw["prompts"]
                        ),
                    },
                }
            )
            if raw["agent_options"]:
                issues.append(f"{key}: review provider effort and operational defaults.")
        elif node.type == "human_wait":
            step.update({"uses": "relay/human-wait@v1", "with": {"prompt": raw["prompt"]}})
            if node.deadline:
                seconds = duration_seconds(node.deadline)
                if seconds is not None:
                    step["with"]["timeout-minutes"] = seconds / 60
            if raw.get("on_timeout"):
                issues.append(f"{key}: timeout branching needs an explicit followup job.")
        else:
            issues.append(f"{key}: {node.type} requires a manual control-flow conversion.")
            continue
        seconds = duration_seconds(node.timeout)
        jobs[key] = {
            "runs-on": "self-hosted",
            **({"timeout-minutes": seconds / 60} if seconds is not None else {}),
            **({"needs": raw["needs"]} if raw["needs"] else {}),
            "steps": [step],
        }
    inputs = {}
    for name, item in definition.inputs.items():
        raw = item.model_dump(mode="json", exclude_none=True)
        inputs[name] = {
            key: value
            for key, value in raw.items()
            if key in {"description", "required", "default"}
        }
        inputs[name]["type"] = {"enum": "choice", "integer": "number"}.get(item.type, item.type)
        if item.type == "enum":
            inputs[name]["options"] = raw["constraints"]["values"]
        elif raw.get("constraints") or item.type == "integer":
            issues.append(f"inputs.{name}: constraints need a relay/validate-input step.")
    value = {"name": definition.name, "on": {"workflow_dispatch": {"inputs": inputs}}, "jobs": jobs}
    if definition.env:
        value["env"] = dict(definition.env)
    buffer = StringIO()
    YAML().dump(value, buffer)
    return {
        "yaml": buffer.getvalue(),
        "issues": issues,
        "complete": not issues,
        "source_unchanged": True,
    }

"""Resolve a declared report once for agent instructions and output validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from relay.errors import NodeExecutionError
from relay.paths import safe_resolve
from relay.workflows.outputs import extract_outputs
from relay.workflows.schema import ExistsSelector, JsonPathSelector, LabelSelector, OutputSelector


@dataclass(frozen=True, slots=True)
class ReportContract:
    selector: OutputSelector

    @property
    def artifact(self) -> str:
        if isinstance(self.selector, ExistsSelector):
            return self.selector.exists
        if isinstance(self.selector, LabelSelector):
            return self.selector.label.artifact
        if isinstance(self.selector, JsonPathSelector):
            return self.selector.json_path.artifact
        return self.selector.yaml_path.artifact

    def read(self, worktree: Path) -> tuple[dict[str, object], dict[str, str]]:
        if isinstance(self.selector, ExistsSelector):
            exists = safe_resolve(worktree, self.artifact).is_file()
            return {"value": "true" if exists else "false"}, {}
        return extract_outputs(worktree, {"value": self.selector}), {"report": self.artifact}


def parse_report(inputs: Mapping[str, object]) -> ReportContract:
    artifact = str(inputs.get("report", inputs.get("path", "")))
    if "selector" in inputs:
        try:
            raw = json.loads(str(inputs["selector"]))
        except ValueError:
            message = "The report selector must be valid JSON."
            raise NodeExecutionError(message) from None
    else:
        format_name = inputs.get("format", "label")
        raw = (
            {"exists": artifact}
            if format_name == "exists"
            else {"label": {"artifact": artifact, "label": str(inputs.get("label", "Ready"))}}
            if format_name == "label"
            else {
                f"{format_name}_path": {
                    "artifact": artifact,
                    "path": str(inputs.get("field", "value")),
                }
            }
        )
    try:
        return ReportContract(TypeAdapter(OutputSelector).validate_python(raw))
    except ValidationError:
        message = "The report selector is invalid."
        raise NodeExecutionError(message) from None

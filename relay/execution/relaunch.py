"""Read previous inputs for an owner-reviewed fresh workflow launch."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from typing import Protocol

from relay.constants import API_MAX_PAGE_BYTES
from relay.errors import ConfigError
from relay.execution.state import RunStatus
from relay.workflows.loader import workflow_key_parts


@dataclass(frozen=True, slots=True)
class PreviousRunInputs:
    """Input values only; the next launch must capture its own source and routes."""

    project_id: str
    workflow_key: str
    status: str
    inputs: dict[str, object]


class PreviousRunStore(Protocol):
    def previous_run_inputs(self, run_id: str) -> PreviousRunInputs: ...


def read_previous_inputs(store: PreviousRunStore, run_id: str) -> PreviousRunInputs:
    source = store.previous_run_inputs(run_id)
    if source.status not in {
        RunStatus.FAILED.value,
        RunStatus.SUCCEEDED.value,
        RunStatus.CANCELED.value,
    }:
        message = "Wait for this run to finish before running all jobs again."
        raise ConfigError(message, context={"run": run_id})
    result = replace(source, workflow_key="/".join(workflow_key_parts(source.workflow_key)))
    if len(json.dumps(asdict(result)).encode("utf-8")) > API_MAX_PAGE_BYTES:
        message = "The previous inputs exceed the browser's read limit."
        raise ConfigError(
            message, next_action="Open the workflow and enter the inputs for a new run."
        )
    return result

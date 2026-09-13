"""Relay-owned errors and the stable public error envelope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar


class RelayError(Exception):
    """Base class for failures that may cross a Relay interface boundary."""

    error_code: ClassVar[str] = "relay_error"
    cli_exit_code: ClassVar[int] = 1
    http_status: ClassVar[int] = 500

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, str | None] | None = None,
        next_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.context: dict[str, str] = {
            key: value for key, value in (context or {}).items() if value is not None
        }
        self.next_action: str | None = next_action

    def to_envelope(self) -> dict[str, object]:
        """Return the versioned shape shared by CLI, HTTP, and events."""
        envelope: dict[str, object] = {
            "code": self.error_code,
            "message": self.message,
            "context": dict(self.context),
        }
        if self.next_action is not None:
            envelope["next_action"] = self.next_action
        return envelope

    def __str__(self) -> str:
        return self.message


def _error_type(name: str, code: str, cli_exit: int, http_status: int) -> type[RelayError]:
    """Create a Relay error subclass with immutable public identifiers."""
    return type(
        name,
        (RelayError,),
        {
            "error_code": code,
            "cli_exit_code": cli_exit,
            "http_status": http_status,
            "__module__": __name__,
        },
    )


ConfigError = _error_type("ConfigError", "config_error", 20, 400)
ProjectDiscoveryError = _error_type("ProjectDiscoveryError", "project_discovery_error", 21, 404)
ProjectRelinkError = _error_type("ProjectRelinkError", "project_relink_error", 22, 409)
SchemaVersionError = _error_type("SchemaVersionError", "schema_version_error", 23, 422)
WorkflowValidationError = _error_type(
    "WorkflowValidationError", "workflow_validation_error", 24, 422
)
PromptResolutionError = _error_type("PromptResolutionError", "prompt_resolution_error", 25, 422)
PathSafetyError = _error_type("PathSafetyError", "path_safety_error", 26, 400)
DirtyRepositoryError = _error_type("DirtyRepositoryError", "dirty_repository_error", 27, 409)
GitError = _error_type("GitError", "git_error", 28, 500)
WorktreeError = _error_type("WorktreeError", "worktree_error", 28, 500)
CommitValidationError = _error_type("CommitValidationError", "commit_validation_error", 28, 500)
ModelUnavailableError = _error_type("ModelUnavailableError", "model_unavailable_error", 29, 422)
ModelSelectorError = _error_type("ModelSelectorError", "model_selector_error", 29, 422)
ModelSelectionRejectedError = _error_type(
    "ModelSelectionRejectedError", "model_selection_rejected_error", 29, 422
)
AgentDiscoveryError = _error_type("AgentDiscoveryError", "agent_discovery_error", 30, 502)
AgentLaunchError = _error_type("AgentLaunchError", "agent_launch_error", 30, 502)
AgentAuthError = _error_type("AgentAuthError", "agent_auth_error", 30, 502)
AgentProtocolError = _error_type("AgentProtocolError", "agent_protocol_error", 30, 502)
PermissionFlowError = _error_type("PermissionFlowError", "permission_flow_error", 31, 409)
NodeExecutionError = _error_type("NodeExecutionError", "node_execution_error", 32, 500)
OutputValidationError = _error_type("OutputValidationError", "output_validation_error", 32, 500)
ArtifactPreservationError = _error_type(
    "ArtifactPreservationError", "artifact_preservation_error", 33, 500
)
CancellationError = _error_type("CancellationError", "cancellation_error", 34, 409)
DispatchError = _error_type("DispatchError", "dispatch_error", 35, 500)
PersistenceError = _error_type("PersistenceError", "persistence_error", 36, 503)

__all__ = [
    "AgentAuthError",
    "AgentDiscoveryError",
    "AgentLaunchError",
    "AgentProtocolError",
    "ArtifactPreservationError",
    "CancellationError",
    "CommitValidationError",
    "ConfigError",
    "DirtyRepositoryError",
    "DispatchError",
    "GitError",
    "ModelSelectionRejectedError",
    "ModelSelectorError",
    "ModelUnavailableError",
    "NodeExecutionError",
    "OutputValidationError",
    "PathSafetyError",
    "PermissionFlowError",
    "PersistenceError",
    "ProjectDiscoveryError",
    "ProjectRelinkError",
    "PromptResolutionError",
    "RelayError",
    "SchemaVersionError",
    "WorkflowValidationError",
    "WorktreeError",
]

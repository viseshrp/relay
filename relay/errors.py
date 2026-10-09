"""Relay-owned errors and the stable public error envelope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from . import constants


class RelayError(Exception):
    """Base class for failures that may cross a Relay interface boundary."""

    error_code: ClassVar[str] = "relay_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_RELAY_ERROR
    http_status: ClassVar[int] = constants.HTTP_INTERNAL_SERVER_ERROR

    message: str
    context: dict[str, str]
    next_action: str | None

    def __init__(
        self,
        message: str,
        *,
        context: Mapping[str, str | None] | None = None,
        next_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context = {key: value for key, value in (context or {}).items() if value is not None}
        self.next_action = next_action

    def to_envelope(self) -> dict[str, object]:
        """Return the versioned shape shared by CLI, HTTP, and events."""
        envelope = {
            "code": self.error_code,
            "message": self.message,
            "context": dict(self.context),
        }
        if self.next_action is not None:
            envelope["next_action"] = self.next_action
        return envelope

    def __str__(self) -> str:
        return self.message


class ConfigError(RelayError):
    error_code: ClassVar[str] = "config_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_CONFIG_ERROR
    http_status: ClassVar[int] = constants.HTTP_BAD_REQUEST


class ProjectDiscoveryError(RelayError):
    error_code: ClassVar[str] = "project_discovery_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_PROJECT_DISCOVERY_ERROR
    http_status: ClassVar[int] = constants.HTTP_NOT_FOUND


class ProjectRelinkError(RelayError):
    error_code: ClassVar[str] = "project_relink_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_PROJECT_RELINK_ERROR
    http_status: ClassVar[int] = constants.HTTP_CONFLICT


class SchemaVersionError(RelayError):
    error_code: ClassVar[str] = "schema_version_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_SCHEMA_VERSION_ERROR
    http_status: ClassVar[int] = constants.HTTP_UNPROCESSABLE_CONTENT


class WorkflowValidationError(RelayError):
    error_code: ClassVar[str] = "workflow_validation_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_WORKFLOW_VALIDATION_ERROR
    http_status: ClassVar[int] = constants.HTTP_UNPROCESSABLE_CONTENT


class PromptResolutionError(RelayError):
    error_code: ClassVar[str] = "prompt_resolution_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_PROMPT_RESOLUTION_ERROR
    http_status: ClassVar[int] = constants.HTTP_UNPROCESSABLE_CONTENT


class PathSafetyError(RelayError):
    error_code: ClassVar[str] = "path_safety_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_PATH_SAFETY_ERROR
    http_status: ClassVar[int] = constants.HTTP_BAD_REQUEST


class DirtyRepositoryError(RelayError):
    error_code: ClassVar[str] = "dirty_repository_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_DIRTY_REPOSITORY_ERROR
    http_status: ClassVar[int] = constants.HTTP_CONFLICT


class GitError(RelayError):
    error_code: ClassVar[str] = "git_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_GIT_ERROR
    http_status: ClassVar[int] = constants.HTTP_INTERNAL_SERVER_ERROR


class WorktreeError(RelayError):
    error_code: ClassVar[str] = "worktree_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_GIT_ERROR
    http_status: ClassVar[int] = constants.HTTP_INTERNAL_SERVER_ERROR


class RunMergeError(GitError):
    error_code: ClassVar[str] = "run_merge_failed"
    http_status: ClassVar[int] = constants.HTTP_CONFLICT


class CommitValidationError(RelayError):
    error_code: ClassVar[str] = "commit_validation_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_GIT_ERROR
    http_status: ClassVar[int] = constants.HTTP_INTERNAL_SERVER_ERROR


class ModelUnavailableError(RelayError):
    error_code: ClassVar[str] = "model_unavailable_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_MODEL_ERROR
    http_status: ClassVar[int] = constants.HTTP_UNPROCESSABLE_CONTENT


class ModelSelectorError(RelayError):
    error_code: ClassVar[str] = "model_selector_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_MODEL_ERROR
    http_status: ClassVar[int] = constants.HTTP_UNPROCESSABLE_CONTENT


class ModelSelectionRejectedError(RelayError):
    error_code: ClassVar[str] = "model_selection_rejected_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_MODEL_ERROR
    http_status: ClassVar[int] = constants.HTTP_UNPROCESSABLE_CONTENT


class AgentDiscoveryError(RelayError):
    error_code: ClassVar[str] = "agent_discovery_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_AGENT_ERROR
    http_status: ClassVar[int] = constants.HTTP_BAD_GATEWAY


class AgentLaunchError(RelayError):
    error_code: ClassVar[str] = "agent_launch_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_AGENT_ERROR
    http_status: ClassVar[int] = constants.HTTP_BAD_GATEWAY


class AgentAuthError(RelayError):
    error_code: ClassVar[str] = "agent_auth_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_AGENT_ERROR
    http_status: ClassVar[int] = constants.HTTP_BAD_GATEWAY


class AgentProtocolError(RelayError):
    error_code: ClassVar[str] = "agent_protocol_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_AGENT_ERROR
    http_status: ClassVar[int] = constants.HTTP_BAD_GATEWAY


class AgentUsageLimitError(RelayError):
    """The provider rejected a request because its usage window is full."""

    error_code: ClassVar[str] = "agent_usage_limit"
    cli_exit_code: ClassVar[int] = constants.EXIT_AGENT_ERROR
    http_status: ClassVar[int] = constants.HTTP_BAD_GATEWAY


class AgentConfigurationError(RelayError):
    error_code: ClassVar[str] = "agent_configuration_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_MODEL_ERROR
    http_status: ClassVar[int] = constants.HTTP_UNPROCESSABLE_CONTENT


class PermissionFlowError(RelayError):
    error_code: ClassVar[str] = "permission_flow_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_PERMISSION_FLOW_ERROR
    http_status: ClassVar[int] = constants.HTTP_CONFLICT


class NodeExecutionError(RelayError):
    error_code: ClassVar[str] = "node_execution_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_NODE_EXECUTION_ERROR
    http_status: ClassVar[int] = constants.HTTP_INTERNAL_SERVER_ERROR


class OutputValidationError(RelayError):
    error_code: ClassVar[str] = "output_validation_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_NODE_EXECUTION_ERROR
    http_status: ClassVar[int] = constants.HTTP_INTERNAL_SERVER_ERROR


class ArtifactPreservationError(RelayError):
    error_code: ClassVar[str] = "artifact_preservation_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_ARTIFACT_PRESERVATION_ERROR
    http_status: ClassVar[int] = constants.HTTP_INTERNAL_SERVER_ERROR


class CancellationError(RelayError):
    error_code: ClassVar[str] = "cancellation_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_CANCELLATION_ERROR
    http_status: ClassVar[int] = constants.HTTP_CONFLICT


class DispatchError(RelayError):
    error_code: ClassVar[str] = "dispatch_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_DISPATCH_ERROR
    http_status: ClassVar[int] = constants.HTTP_INTERNAL_SERVER_ERROR


class PersistenceError(RelayError):
    error_code: ClassVar[str] = "persistence_error"
    cli_exit_code: ClassVar[int] = constants.EXIT_PERSISTENCE_ERROR
    http_status: ClassVar[int] = constants.HTTP_SERVICE_UNAVAILABLE


__all__ = [
    "AgentAuthError",
    "AgentDiscoveryError",
    "AgentLaunchError",
    "AgentProtocolError",
    "AgentUsageLimitError",
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


class SettingsConflictError(RelayError):
    error_code: ClassVar[str] = "settings_conflict"
    cli_exit_code: ClassVar[int] = constants.EXIT_CONFIG_ERROR
    http_status: ClassVar[int] = constants.HTTP_CONFLICT

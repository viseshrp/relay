"""Translate agent SDK, protocol, and process failures into Relay errors."""

from __future__ import annotations

import logging

from acp import RequestError

from relay.errors import (
    AgentAuthError,
    AgentLaunchError,
    AgentProtocolError,
    ModelSelectionRejectedError,
    RelayError,
)

LOGGER = logging.getLogger(__name__)


def map_agent_exception(error: BaseException, *, agent_id: str) -> RelayError:
    """Return only Relay-owned error types while retaining full local trace context."""
    LOGGER.exception("Agent adapter failure", exc_info=error, extra={"agent_id": agent_id})
    if isinstance(error, RelayError):
        return error
    text = str(error).lower()
    context = {"agent": agent_id}
    if "auth" in text or "credential" in text or "login" in text:
        return AgentAuthError(
            f"Agent {agent_id!r} requires authentication.",
            context=context,
            next_action="Authenticate with the agent directly, then retry the probe.",
        )
    if isinstance(error, (FileNotFoundError, OSError)):
        return AgentLaunchError(
            f"Relay could not start agent {agent_id!r}.",
            context=context,
        )
    if isinstance(error, RequestError) and "config" in text:
        return ModelSelectionRejectedError(
            f"Agent {agent_id!r} rejected the exact model selection.",
            context=context,
        )
    return AgentProtocolError(
        f"Agent {agent_id!r} did not complete the Relay protocol exchange.",
        context=context,
    )


__all__ = ["map_agent_exception"]

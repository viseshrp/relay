"""Translate agent SDK, protocol, and process failures into Relay errors."""

from __future__ import annotations

import logging

from acp import RequestError

from relay.errors import (
    AgentAuthError,
    AgentLaunchError,
    AgentProtocolError,
    RelayError,
)

LOGGER = logging.getLogger(__name__)


def map_agent_exception(error: BaseException, *, agent_id: str) -> RelayError:
    """Return only Relay-owned error types while retaining full local trace context."""
    LOGGER.exception("Agent adapter failure", exc_info=error, extra={"agent_id": agent_id})
    if isinstance(error, RelayError):
        return error
    context = {"agent": agent_id}
    if isinstance(error, RequestError) and error.code == RequestError.auth_required().code:
        return AgentAuthError(
            f"Agent {agent_id!r} requires authentication.",
            context=context,
            next_action="Authenticate with the agent directly, then retry the probe.",
        )
    if isinstance(error, OSError) and not isinstance(error, (ConnectionError, BrokenPipeError)):
        return AgentLaunchError(
            f"Relay could not start agent {agent_id!r}.",
            context=context,
        )
    return AgentProtocolError(
        f"Agent {agent_id!r} did not complete the Relay protocol exchange.",
        context=context,
    )


__all__ = ["map_agent_exception"]

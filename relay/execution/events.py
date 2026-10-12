"""Output-only events do not invalidate persisted run-state snapshots."""

from typing import Final

OUTPUT_EVENT_TYPES: Final = frozenset(
    {
        "agent.message",
        "agent.thought",
        "agent.tool_call",
        "agent.tool_result",
        "agent.plan",
        "agent.provider_event",
        "agent.stderr",
        "agent.result",
        "agent.turn_started",
        "command.stdout",
        "command.stderr",
        "actions.summary",
        "actions.error",
        "actions.warning",
        "actions.notice",
        "actions.debug",
        "actions.group",
        "actions.endgroup",
    }
)

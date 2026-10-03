"""Pure, idempotent application of Relay's normative transition tables."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from relay.errors import PersistenceError

from .state import (
    CONTROL_TRANSITIONS,
    INTERACTION_TRANSITIONS,
    NODE_TRANSITIONS,
    RUN_TRANSITIONS,
    ChoiceEnum,
    Transition,
)


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """New durable value and the event to append in the same transaction."""

    status: str
    event: str
    changed: bool
    guard: str


def _text(value: str | ChoiceEnum | None) -> str | None:
    if isinstance(value, ChoiceEnum):
        return value.value
    return value


def apply_transition(
    current: str | ChoiceEnum | None,
    action: str,
    table: Sequence[Transition],
    *,
    subject: str,
) -> TransitionResult:
    """Apply one action or report that its post-state already holds."""
    current_value = _text(current)
    candidates = [transition for transition in table if transition.action == action]
    for transition in candidates:
        if _text(transition.source) == current_value:
            target = _text(transition.target)
            if target is None:
                message = f"Relay transition {subject}.{action} has no target."
                raise PersistenceError(message)
            return TransitionResult(target, transition.event, True, transition.guard)
    for transition in candidates:
        target = _text(transition.target)
        if target == current_value:
            if target is None:
                message = f"Relay transition {subject}.{action} has no target."
                raise PersistenceError(message)
            return TransitionResult(target, transition.event, False, transition.guard)
    message = f"Relay rejected {subject}.{action} from state {current_value!r}."
    raise PersistenceError(
        message,
        next_action="Inspect the local event history before changing durable state.",
    )


def transition_run(current: str | ChoiceEnum | None, action: str) -> TransitionResult:
    return apply_transition(current, action, RUN_TRANSITIONS, subject="run")


def transition_node(current: str | ChoiceEnum | None, action: str) -> TransitionResult:
    return apply_transition(current, action, NODE_TRANSITIONS, subject="node")


def transition_interaction(current: str | ChoiceEnum | None, action: str) -> TransitionResult:
    return apply_transition(current, action, INTERACTION_TRANSITIONS, subject="interaction")


def transition_control(current: str | ChoiceEnum | None, action: str) -> TransitionResult:
    return apply_transition(current, action, CONTROL_TRANSITIONS, subject="control")


__all__ = [
    "TransitionResult",
    "apply_transition",
    "transition_control",
    "transition_interaction",
    "transition_node",
    "transition_run",
]

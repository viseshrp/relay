import pytest

from relay.worker.orchestrator import PHASE_TRANSITIONS, WORKFLOW_TRANSITIONS, _assert_transition


def _invalid_transitions(transitions: dict[str, set[str]]) -> list[tuple[str, str]]:
    statuses = list(transitions)
    invalid: list[tuple[str, str]] = []
    for current in statuses:
        for target in statuses:
            if target == current:
                continue
            if target not in transitions[current]:
                invalid.append((current, target))
    return invalid


@pytest.mark.parametrize(("current", "target"), _invalid_transitions(WORKFLOW_TRANSITIONS))
def test_invalid_workflow_transitions_raise(current: str, target: str) -> None:
    with pytest.raises(ValueError):
        _assert_transition(current, target, WORKFLOW_TRANSITIONS, "workflow")


@pytest.mark.parametrize(("current", "target"), _invalid_transitions(PHASE_TRANSITIONS))
def test_invalid_phase_transitions_raise(current: str, target: str) -> None:
    with pytest.raises(ValueError):
        _assert_transition(current, target, PHASE_TRANSITIONS, "phase")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("queued", "running"),
        ("waiting_for_user", "completed"),
        ("waiting_for_user", "completed_with_unresolved_findings"),
    ],
)
def test_valid_workflow_transitions(current: str, target: str) -> None:
    _assert_transition(current, target, WORKFLOW_TRANSITIONS, "workflow")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("running", "succeeded"),
        ("cancelled", "running"),
        ("stale", "queued"),
        ("failed", "queued"),
    ],
)
def test_valid_phase_transitions(current: str, target: str) -> None:
    _assert_transition(current, target, PHASE_TRANSITIONS, "phase")

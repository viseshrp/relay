import pytest

from relay.worker.orchestrator import PHASE_TRANSITIONS, WORKFLOW_TRANSITIONS, _assert_transition


def test_valid_workflow_transition() -> None:
    _assert_transition("queued", "running", WORKFLOW_TRANSITIONS, "workflow")


def test_invalid_workflow_transition_raises() -> None:
    with pytest.raises(ValueError):
        _assert_transition("completed", "running", WORKFLOW_TRANSITIONS, "workflow")


def test_valid_phase_transition() -> None:
    _assert_transition("running", "succeeded", PHASE_TRANSITIONS, "phase")

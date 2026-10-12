"""Interaction status changes and their declared events commit together."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

from django.db import DatabaseError
import pytest

from relay.agents.models import AgentExecutionContext
from relay.errors import PersistenceError
from relay.execution.nodes import node_executors
from relay.execution.state import EventSensitivity, EventSource
from relay.web import repositories
from relay.web.actions_repository import approve_environment
from relay.web.models import (
    HumanInteraction,
    NodeAttempt,
    NodeRun,
    Run,
    RunEvent,
    WorkflowEnvironment,
)
from relay.web.repositories import DjangoExecutionStore
from tests.support import Clock, InlineEngine, RelayProject


def fail_event(monkeypatch: pytest.MonkeyPatch, rejected: str) -> None:
    append = repositories._append_event

    def reject(
        run: Run,
        event_type: str,
        source: EventSource,
        payload: Mapping[str, object],
        *,
        node: NodeRun | None = None,
        attempt: NodeAttempt | None = None,
        sensitivity: EventSensitivity = EventSensitivity.NORMAL,
    ) -> RunEvent:
        if event_type == rejected:
            message = "forced event persistence failure"
            raise DatabaseError(message)
        return append(
            run, event_type, source, payload, node=node, attempt=attempt, sensitivity=sensitivity
        )

    monkeypatch.setattr(repositories, "_append_event", reject)


def wait(project: RelayProject, tmp_path: Path, *, environment: bool = False) -> HumanInteraction:
    if environment:
        WorkflowEnvironment.objects.create(
            project_id=project.project_id, name="prod", approval_required=True
        )
    project.write_workflow(
        "wait-events",
        "name: Events\njobs:\n  main:\n"
        + ("    environment: prod\n" if environment else "")
        + "    steps:\n      - uses: relay/human-wait@v1\n"
        + "        with: {prompt: Continue?, timeout-minutes: 1}\n",
    )
    engine = InlineEngine(node_executors(), tmp_path / "artifacts")
    run_id = engine.launch(project, "wait-events")
    engine.drain(run_id)
    return HumanInteraction.objects.get(run_id=run_id, status="pending")


@pytest.mark.parametrize("rollback", [False, True])
def test_wait_expiry_appends_its_event(
    project: RelayProject,
    tmp_path: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    rollback: bool,
) -> None:
    interaction = wait(project, tmp_path)
    HumanInteraction.objects.filter(pk=interaction.pk).update(
        deadline=clock.instant + timedelta(seconds=1)
    )
    clock.advance(61)
    if rollback:
        fail_event(monkeypatch, "wait.expired")
        with pytest.raises(PersistenceError):
            DjangoExecutionStore().expire_human_waits()
    else:
        assert DjangoExecutionStore().expire_human_waits() == 1
        event = RunEvent.objects.get(
            type="wait.expired", attempt_id=repositories._foreign_key_text(interaction, "attempt")
        )
        assert event.payload["interaction_id"] == str(interaction.pk)
        assert event.payload["deadline"]
    interaction.refresh_from_db()
    assert interaction.status == ("pending" if rollback else "expired")


@pytest.mark.parametrize("kind", ["permission", "elicitation"])
@pytest.mark.parametrize("rollback", [False, True])
def test_lost_attempts_discard_requests_with_events(
    agent_context: AgentExecutionContext,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    rollback: bool,
) -> None:
    store = DjangoExecutionStore()
    attempt = agent_context.attempt.attempt
    interaction_id = store.request_agent_interaction(attempt.attempt_id, kind, "Continue?", ())
    if rollback:
        fail_event(monkeypatch, f"{kind}.discarded")
        with pytest.raises(PersistenceError):
            store.fail_worker_attempts()
    else:
        assert store.fail_worker_attempts() == 1
        event = RunEvent.objects.get(type=f"{kind}.discarded", attempt_id=attempt.attempt_id)
        assert event.payload["interaction_id"] == interaction_id
        assert event.payload["scope_path"] == attempt.scope_path
    assert HumanInteraction.objects.get(pk=interaction_id).status == (
        "pending" if rollback else "discarded"
    )


@pytest.mark.parametrize("rollback", [False, True])
def test_environment_approval_answers_with_an_event(
    project: RelayProject,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rollback: bool,
) -> None:
    interaction = wait(project, tmp_path, environment=True)
    if rollback:
        fail_event(monkeypatch, "wait.answered")
        with pytest.raises(DatabaseError):
            approve_environment(str(repositories._foreign_key_text(interaction, "attempt")))
    else:
        assert approve_environment(str(repositories._foreign_key_text(interaction, "attempt")))
        event = RunEvent.objects.get(
            type="wait.answered", attempt_id=repositories._foreign_key_text(interaction, "attempt")
        )
        assert event.payload["interaction_id"] == str(interaction.pk)
        assert event.payload["result"] == {"approved": True}
    interaction.refresh_from_db()
    assert interaction.status == ("pending" if rollback else "answered")

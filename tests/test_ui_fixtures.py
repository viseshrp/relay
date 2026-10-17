"""Browser fixtures resume held deliveries and preserve unrelated projects."""

from pathlib import Path

from relay.execution.control import ControlResult
from relay.projects.identity import canonical_path
from relay.web.models import HumanInteraction, NodeAttempt, Project, Run
from tests.e2e_server import advance_browser_runs
from tests.support import InlineEngine, RelayProject, create_project
from tests.ui_fixtures import seed_ui_fixture


def test_browser_consumer_redelivers_a_paused_waiting_scope(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "wait-child",
        (
            "on: workflow_call\n"
            "jobs: {approval: {steps: [{uses: relay/human-wait@v1, with: {prompt: "
            "Continue?}}]}}\n"
        ),
    )
    project.write_workflow(
        "nested-wait", "jobs: {rounds: {uses: ./.relay/workflows/wait-child.yaml}}\n"
    )
    run_id = engine.launch(project, "nested-wait")
    engine.drain(run_id)
    interaction = HumanInteraction.objects.get(run_id=run_id, status="pending")
    assert (
        engine.store.submit_control(
            str(interaction.attempt_id), "wait_answer", "answer", {"value": "YES"}, 600
        )
        is ControlResult.ACCEPTED
    )
    assert engine.store.resolve_human_wait_controls() == 1
    engine.advance(run_id)
    assert Run.objects.get(pk=run_id).status == "paused_wait"
    token = engine.tokens.popleft()
    assert engine.store.configure_dispatch_pause(run_id, True, "pause-delivery") is (
        ControlResult.ACCEPTED
    )
    assert engine.run_token(token) is None
    assert not engine.tokens
    assert engine.store.configure_dispatch_pause(run_id, False, "resume-delivery") is (
        ControlResult.ACCEPTED
    )

    advance_browser_runs(engine)

    assert token in engine.tokens
    engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "succeeded"
    assert (
        NodeAttempt.objects.filter(
            node_run__run_id=run_id, node_run__scope_path="root.rounds"
        ).count()
        == 1
    )


def test_reseeding_removes_launched_fixture_runs_only(tmp_path: Path, engine: InlineEngine) -> None:
    unrelated = create_project(tmp_path / "another-server" / "ui-fixture" / "project-0")
    unrelated.write_workflow(
        "check", "jobs:\n  check:\n    steps:\n      - run: print('ready')\n        shell: python\n"
    )
    unrelated_run = engine.launch(unrelated, "check")
    engine.drain(unrelated_run)
    root = tmp_path / "browser-server"
    seed_ui_fixture(root, worst=False)
    repository = root / "ui-fixture" / "project-0"
    record = Project.objects.get(canonical_path=canonical_path(repository))
    project = RelayProject(repository, repository / ".relay", str(record.pk))
    launched = engine.launch(project, "visual")
    engine.drain(launched)
    assert Run.objects.get(pk=launched).number == 7

    fixture = seed_ui_fixture(root, worst=True)

    assert not Run.objects.filter(pk=launched).exists()
    assert not Project.objects.filter(pk=project.project_id).exists()
    assert Project.objects.filter(pk=fixture["project"]).exists()
    assert Project.objects.filter(pk=unrelated.project_id).exists()
    assert Run.objects.get(pk=unrelated_run).status == "succeeded"

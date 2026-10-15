"""UI fixture reseeding removes its launched runs and preserves other projects."""

from pathlib import Path

from relay.projects.identity import canonical_path
from relay.web.models import Project, Run
from tests.support import InlineEngine, RelayProject, create_project
from tests.ui_fixtures import seed_ui_fixture


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

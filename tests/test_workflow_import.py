"""Import a GitHub Actions workflow file as a Relay workflow draft."""

import json
from pathlib import Path
from typing import Any

from django.http import HttpResponse
from django.test import Client
import pytest

from relay.errors import WorkflowValidationError
from relay.web.views.actions_language import _suggested_key
from relay.workflows.actions.language import workflow_diagnostics
from relay.workflows.importer import convert_github_workflow
from tests.support import RelayProject, git, symlink_or_skip

TYPICAL_CI = """\
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest
"""

EVERY_RULE = """\
# Release pipeline
name: Everything
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest  # hosted runner
    # Steps run in order.
    services:
      redis:
        image: redis
    container: node:20
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
          if-no-files-found: error
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: out
      - uses: actions/cache@v4
        with:
          key: deps
          path: node_modules
      - uses: actions/cache/restore@v4
        with:
          key: deps
          path: node_modules
          restore-keys: deps-
      - uses: actions/cache/save@v4
        with:
          key: deps
          path: node_modules
      - run: echo "sha=${{ github.sha }}" >> "$GITHUB_OUTPUT"  # keep this comment
      - uses: docker/build-push-action@v6
  release:
    needs: build
    uses: ./.github/workflows/release.yml
"""


def post(client: Client, url: str, body: dict[str, Any]) -> HttpResponse:
    return client.post(url, data=json.dumps(body), content_type="application/json")


@pytest.fixture
def owner(project: RelayProject, monkeypatch: pytest.MonkeyPatch) -> Client:
    monkeypatch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    client = Client()
    assert (
        post(
            client,
            "/api/auth/onboard",
            {"username": "owner", "password": "Relay-Test-Passphrase-2026!"},
        ).status_code
        == 201
    )
    return client


def test_typical_ci_converts_to_a_valid_workflow() -> None:
    result = convert_github_workflow(TYPICAL_CI)

    assert workflow_diagnostics(result.yaml) == []
    assert result.unresolved == ()
    assert result.changes == (
        "Removed runs-on from job test; jobs run on this computer.",
        "Removed the pull_request trigger; it has no local equivalent.",
        "Removed actions/checkout from job test; jobs already run in a working copy.",
        "Removed actions/setup-python@v5 from job test; use the tool installed on this computer.",
    )
    assert result.yaml == (
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: pip install -r requirements.txt\n"
        "      - run: pytest\n"
    )


def test_every_rule_reports_its_change_once() -> None:
    result = convert_github_workflow(EVERY_RULE)

    assert result.changes == (
        "Removed runs-on from job build; jobs run on this computer.",
        "Removed permissions from the workflow.",
        "Removed services from job build.",
        "Removed container from job build.",
        "Removed the pull_request trigger; it has no local equivalent.",
        "Added workflow_dispatch so the workflow can be run by hand.",
        "Removed actions/checkout from job build; jobs already run in a working copy.",
        "Removed actions/setup-node@v4 from job build; use the tool installed on this computer.",
        "Replaced actions/upload-artifact@v4 with relay/upload-artifact@v1 in job build.",
        "Dropped input if-no-files-found.",
        "Replaced actions/download-artifact@v4 with relay/download-artifact@v1 in job build.",
        "Replaced actions/cache@v4 with relay/cache@v1 in job build.",
        "Replaced actions/cache/restore@v4 with relay/restore-cache@v1 in job build.",
        "Replaced actions/cache/save@v4 with relay/save-cache@v1 in job build.",
        "Pointed job release at ./.relay/workflows/release.yml.",
        "Replaced github.ref with relay.ref (1 place).",
        "Replaced github.sha with relay.sha (1 place).",
        "Replaced $GITHUB_OUTPUT with $RELAY_OUTPUT (1 place).",
    )
    assert len(set(result.changes)) == len(result.changes)
    uses = "jobs.build.steps[6].uses: Only frozen local and versioned relay actions are supported."
    assert result.unresolved[:2] == (
        "Import .github/workflows/release.yml too.",
        "Step 7 in job build uses docker/build-push-action@v6. "
        "Replace it with a run step or a relay action.",
    )
    assert len(result.unresolved) == 3 and result.unresolved[2].startswith(uses)
    assert [issue.message for issue in workflow_diagnostics(result.yaml)] == [result.unresolved[2]]
    # Comments on kept lines and below removed lines survive; removed lines' own do not.
    assert result.yaml.startswith("# Release pipeline\nname: Everything\non: workflow_dispatch\n")
    assert "    # Steps run in order.\n    if: relay.ref == 'refs/heads/main'\n" in result.yaml
    assert '"$RELAY_OUTPUT"' in result.yaml and "# keep this comment" in result.yaml
    assert "hosted runner" not in result.yaml and "if-no-files-found" not in result.yaml
    assert "uses: ./.relay/workflows/release.yml" in result.yaml


@pytest.mark.parametrize(
    ("written", "replacement", "changes"),
    [
        (
            "echo ${{ github.event.inputs.task }} ${{ runner.os }} ${{ github.sha }}",
            "echo ${{ inputs.task }} ${{ host.os }} ${{ relay.sha }}",
            (
                "Replaced github.event.inputs.task with inputs.task (1 place).",
                "Replaced runner.os with host.os (1 place).",
                "Replaced github.sha with relay.sha (1 place).",
            ),
        ),
        (
            "echo ${{ format('{0} github.sha', github.sha, github.sha) }} github.sha",
            "echo ${{ format('{0} github.sha', relay.sha, relay.sha) }} github.sha",
            ("Replaced github.sha with relay.sha (2 places).",),
        ),
        (
            "echo ${{ github.token }} ${{ github.event_name }} ${{ github.event.ref }}",
            "echo ${{ github.token }} ${{ relay.event_name }} ${{ relay.event.ref }}",
            (
                "Replaced github.event_name with relay.event_name (1 place).",
                "Replaced github.event with relay.event (1 place).",
            ),
        ),
        (
            'echo a >> "$GITHUB_ENV"; echo b >> ${GITHUB_PATH}; echo c >> $GITHUB_STEP_SUMMARY',
            'echo a >> "$RELAY_ENV"; echo b >> ${RELAY_PATH}; echo c >> $RELAY_STEP_SUMMARY',
            (
                "Replaced $GITHUB_ENV with $RELAY_ENV (1 place).",
                "Replaced $GITHUB_PATH with $RELAY_PATH (1 place).",
                "Replaced $GITHUB_STEP_SUMMARY with $RELAY_STEP_SUMMARY (1 place).",
            ),
        ),
        ("echo $GITHUB_TOKEN $GITHUB_STATE", "echo $GITHUB_TOKEN $RELAY_STATE", None),
    ],
)
def test_names_are_renamed_inside_expressions_and_scripts(
    written: str, replacement: str, changes: tuple[str, ...] | None
) -> None:
    source = f"on: push\njobs:\n  a:\n    steps:\n      - run: {json.dumps(written)}\n"

    result = convert_github_workflow(source)

    assert json.dumps(replacement) in result.yaml
    assert result.changes == (changes or ("Replaced $GITHUB_STATE with $RELAY_STATE (1 place).",))


def test_block_scripts_and_quotes_keep_their_style() -> None:
    source = (
        "on: [push, pull_request]\n"
        "jobs:\n"
        "  a:\n"
        "    if: ${{ github.ref_name == 'main' }}\n"
        "    steps:\n"
        "      - name: 'Write ${{ github.sha }}'\n"
        "        run: |  # script\n"
        '          echo "x=1" >> "$GITHUB_OUTPUT"\n'
        '          echo "y=2" >> "$GITHUB_OUTPUT"\n'
    )

    result = convert_github_workflow(source)

    assert result.yaml == (
        "on: [push]\n"
        "jobs:\n"
        "  a:\n"
        "    if: ${{ relay.ref_name == 'main' }}\n"
        "    steps:\n"
        "      - name: 'Write ${{ relay.sha }}'\n"
        "        run: |  # script\n"
        '          echo "x=1" >> "$RELAY_OUTPUT"\n'
        '          echo "y=2" >> "$RELAY_OUTPUT"\n'
    )
    assert result.changes[-1] == "Replaced $GITHUB_OUTPUT with $RELAY_OUTPUT (2 places)."
    assert result.unresolved == ()


def test_unindented_sequences_and_missing_triggers() -> None:
    source = "jobs:\n  a:\n    steps:\n    - uses: actions/checkout@v4\n    # Test\n    - run: x\n"
    expected = "on: workflow_dispatch\njobs:\n  a:\n    steps:\n    # Test\n    - run: x\n"

    result = convert_github_workflow(source)

    assert result.yaml == expected
    assert result.changes[0] == "Added workflow_dispatch so the workflow can be run by hand."


def test_text_that_is_not_a_workflow_mapping_is_refused() -> None:
    with pytest.raises(WorkflowValidationError, match="Invalid YAML document"):
        convert_github_workflow("jobs: [unclosed\n")
    with pytest.raises(WorkflowValidationError, match="Duplicate YAML key"):
        convert_github_workflow("on: push\non: push\n")


def write_workflows(project: RelayProject) -> Path:
    folder = project.repository / ".github" / "workflows"
    project.write(".github/workflows/ci.yml", TYPICAL_CI)
    project.write(".github/workflows/deploy.yaml", "on: push\njobs: {}\n")
    project.write(".github/workflows/notes.txt", "Not a workflow\n")
    project.write(".github/workflows/nested/inner.yml", TYPICAL_CI)
    project.write(".github/workflows/huge.yml", "# " + "x" * 1_048_576 + "\n")
    return folder


def test_import_lists_workflow_files_directly_in_the_folder(
    owner: Client, project: RelayProject
) -> None:
    assert owner.get("/api/workflow-import").json() == {"files": []}
    folder = write_workflows(project)
    symlink_or_skip(folder / "linked.yml", folder / "ci.yml")

    assert owner.get("/api/workflow-import").json() == {
        "files": [
            {"path": ".github/workflows/ci.yml", "name": "CI"},
            {"path": ".github/workflows/deploy.yaml", "name": "deploy.yaml"},
        ]
    }
    assert Client().get("/api/workflow-import").status_code == 401
    wrong_method = owner.delete("/api/workflow-import")
    assert wrong_method.status_code == 405

    for index in range(101):
        project.write(f".github/workflows/many-{index:03}.yml", "on: push\n")
    assert len(owner.get("/api/workflow-import").json()["files"]) == 100


def test_import_converts_a_file_without_writing(owner: Client, project: RelayProject) -> None:
    write_workflows(project)
    status = git(project.repository, "status", "--porcelain=v1", "--untracked-files=all")
    workflows = sorted(path.name for path in (project.relay_root / "workflows").iterdir())

    response = post(owner, "/api/workflow-import", {"path": ".github/workflows/ci.yml"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "yaml": convert_github_workflow(TYPICAL_CI).yaml,
        "changes": list(convert_github_workflow(TYPICAL_CI).changes),
        "unresolved": [],
        "suggested_key": "ci.yml",
    }
    assert git(project.repository, "status", "--porcelain=v1", "--untracked-files=all") == status
    assert sorted(path.name for path in (project.relay_root / "workflows").iterdir()) == workflows
    project.write(".relay/workflows/ci.yml", TYPICAL_CI)
    again = post(owner, "/api/workflow-import", {"path": ".github/workflows/ci.yml"})
    assert again.json()["suggested_key"] == "ci-2.yml"


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/../../.relay/workflows/workflow.yaml",
        "../../.relay/workflows/workflow.yaml",
        ".github/workflows/../../../outside.yml",
    ],
)
def test_import_refuses_paths_that_leave_the_folder(
    owner: Client, project: RelayProject, path: str
) -> None:
    write_workflows(project)

    response = post(owner, "/api/workflow-import", {"path": path})

    assert response.status_code == 400
    assert response.json()["code"] == "path_safety_error"


@pytest.mark.parametrize("inside", [True, False])
def test_import_refuses_a_symlinked_file(
    owner: Client, project: RelayProject, tmp_path: Path, inside: bool
) -> None:
    folder = write_workflows(project)
    target = folder / "ci.yml" if inside else tmp_path / "outside.yml"
    target.write_text(TYPICAL_CI, encoding="utf-8")
    symlink_or_skip(folder / "linked.yml", target)

    response = post(owner, "/api/workflow-import", {"path": ".github/workflows/linked.yml"})

    assert response.status_code == 400
    assert response.json()["code"] == "path_safety_error"


@pytest.mark.parametrize(
    ("path", "status", "message"),
    [
        (".github/workflows/notes.txt", 400, "Choose a .yml or .yaml file directly in"),
        (".github/workflows/nested/inner.yml", 400, "Choose a .yml or .yaml file directly in"),
        (".github/workflows/missing.yml", 400, "Choose a .yml or .yaml file directly in"),
        (".github/workflows/huge.yml", 422, "A source file exceeds the editor's size limit."),
    ],
)
def test_import_refuses_files_it_does_not_list(
    owner: Client, project: RelayProject, path: str, status: int, message: str
) -> None:
    write_workflows(project)

    response = post(owner, "/api/workflow-import", {"path": path})

    assert response.status_code == status
    assert response.json()["message"].startswith(message)


@pytest.mark.parametrize(
    ("file_name", "existing", "expected"),
    [
        ("ci.yml", [], "ci.yml"),
        ("ci.yml", ["ci.yml", "ci-2.yml"], "ci-3.yml"),
        ("Release Build.yaml", [], "Release Build.yaml"),
        ("nul.yml", [], "workflow-nul.yml"),
        ("build:all.yml", [], "build-all.yml"),
    ],
)
def test_suggested_keys_are_free_and_portable(
    tmp_path: Path, file_name: str, existing: list[str], expected: str
) -> None:
    for name in existing:
        (tmp_path / name).write_text("on: push\n", encoding="utf-8")

    assert _suggested_key(file_name, tmp_path) == expected


def test_a_single_hosted_trigger_becomes_a_manual_trigger() -> None:
    result = convert_github_workflow(
        "on: pull_request\njobs:\n  a:\n    steps:\n      - run: echo\n"
    )

    assert result.changes == (
        "Removed the pull_request trigger; it has no local equivalent.",
        "Added workflow_dispatch so the workflow can be run by hand.",
    )
    assert result.yaml.startswith("on: workflow_dispatch\n")
    assert workflow_diagnostics(result.yaml) == []


def test_jobs_that_are_not_a_mapping_are_left_to_validation() -> None:
    result = convert_github_workflow("on: push\njobs: []\n")

    assert result.changes == ()
    assert result.yaml == "on: push\njobs: []\n"
    assert result.unresolved


def test_a_replaced_action_without_inputs_gets_no_with_block() -> None:
    source = (
        "on: push\n"
        "jobs:\n"
        "  a:\n"
        "    timeout-minutes: 5\n"
        "    steps:\n"
        "      - uses: actions/upload-artifact@v4\n"
    )

    result = convert_github_workflow(source)

    assert result.changes == (
        "Replaced actions/upload-artifact@v4 with relay/upload-artifact@v1 in job a.",
    )
    assert "      - uses: relay/upload-artifact@v1\n" in result.yaml
    assert "with:" not in result.yaml
    assert "timeout-minutes: 5" in result.yaml


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "on: push\njobs:\n  a:\n    runs-on: x\n    # Run the tests.\n"
            "    steps:\n      - run: pytest\n",
            "on: push\njobs:\n  a:\n    # Run the tests.\n    steps:\n      - run: pytest\n",
        ),
        (
            "on: push\njobs:\n  a:\n    runs-on: x\n    # One.\n    permissions: {}\n"
            "    # Two.\n    steps:\n      - run: pytest\n",
            "on: push\njobs:\n  a:\n    # One.\n    # Two.\n    steps:\n      - run: pytest\n",
        ),
        (
            "on: push\njobs:\n  a:\n    name: A\n    runs-on: x\n    # Next.\n"
            "    steps:\n      - run: pytest\n",
            "on: push\njobs:\n  a:\n    name: A\n    # Next.\n    steps:\n      - run: pytest\n",
        ),
        (
            "on: push\njobs:\n  a:\n    name: A  # Label.\n    runs-on: x\n    # Next.\n"
            "    steps:\n      - run: pytest\n",
            "on: push\njobs:\n  a:\n    name: A  # Label.\n    # Next.\n"
            "    steps:\n      - run: pytest\n",
        ),
        (
            "on: push\njobs:\n  a:\n    # Hosted.\n    runs-on: x\n    # Next.\n"
            "    steps:\n      - run: pytest\n",
            "on: push\njobs:\n  a:\n    # Hosted.\n    # Next.\n    steps:\n      - run: pytest\n",
        ),
        (
            "on: push\njobs:\n  a:  # Job a.\n    runs-on: x\n    # Next.\n"
            "    steps:\n      - run: pytest\n",
            "on: push\njobs:\n  a:  # Job a.\n    # Next.\n    steps:\n      - run: pytest\n",
        ),
    ],
)
def test_comments_after_a_removed_key_move_up(source: str, expected: str) -> None:
    assert convert_github_workflow(source).yaml == expected


def test_listing_names_an_unreadable_workflow_by_its_file_name(
    owner: Client, project: RelayProject
) -> None:
    project.write(".github/workflows/broken.yml", "name: [unclosed\n")

    files = owner.get("/api/workflow-import").json()["files"]

    assert {"path": ".github/workflows/broken.yml", "name": "broken.yml"} in files


def test_import_refuses_a_file_that_is_not_utf8(owner: Client, project: RelayProject) -> None:
    folder = project.repository / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "latin.yml").write_bytes(b"name: \xff\non: push\n")

    response = post(owner, "/api/workflow-import", {"path": ".github/workflows/latin.yml"})

    assert response.status_code == 400
    assert response.json()["message"] == "The workflow file is not UTF-8 text."

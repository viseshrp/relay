"""Owner language and settings APIs against isolated projects and storage."""

from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
from typing import Any
import uuid
from zipfile import ZipFile

from django.http import HttpResponse
from django.test import Client
from django.utils import timezone
import pytest

from relay.execution.action_products import capture
from relay.execution.nodes import node_executors
from relay.web.models import ActionsArtifact, NodeAttempt, WorkflowBinding, WorkflowEnvironment
from tests.support import InlineEngine, RelayProject

BASE = "name: Owner source\njobs: {main: {runs-on: self-hosted, steps: [{run: echo ready}]}}\n"


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


def test_language_manifest_conversion_and_method_boundaries(owner: Client) -> None:
    manifest = owner.get("/api/workflow-language").json()
    assert manifest["job_execution"] == "serial" and manifest["limits"]["matrix_variants"] == 256
    converted = post(
        owner,
        "/api/workflow-language/convert",
        {
            "yaml": "version: 1\nname: Legacy\n"
            "nodes: {check: {type: command, run: [git, status], timeout: 3m}}"
        },
    )
    assert converted.status_code == 200 and converted.json()["complete"]
    assert post(
        owner, "/api/workflow-language/validate", {"yaml": converted.json()["yaml"]}
    ).json()["valid"]
    for url in (
        "/api/workflow-library",
        "/api/workflow-bindings",
        "/api/workflow-environments",
        "/api/workflow-triggers",
    ):
        assert owner.delete(url).status_code == 405
        assert Client().get(url).status_code == 401
    assert owner.get("/api/workflow-language/convert").status_code == 405


def test_library_import_export_captures_project_prompts_and_transitive_actions(
    owner: Client, project: RelayProject
) -> None:
    project.write(".relay/prompts/owner.md", "Owner bytes é\n")
    project.write(
        ".relay/actions/local/action.yml",
        "name: Local\ndescription: Frozen\nruns: {using: node20, main: main.js}\n",
    )
    project.write(".relay/actions/local/main.js", "process.stdout.write('ready');\n")
    source = (
        "# Preserve me\njobs: {main: {runs-on: self-hosted, "
        "steps: [{uses: ./.relay/actions/local}]}}\n"
    )
    response = post(
        owner,
        "/api/workflow-library",
        {"metadata": {"name": "Owner template"}, "yaml": source, "include_project_sources": True},
    )
    assert response.status_code == 201
    identity = response.json()["id"]
    exported = owner.get("/api/workflow-library", {"id": identity}).json()
    assert exported["yaml"] == source
    assert exported["sources"][".relay/prompts/owner.md"] == "Owner bytes é\n"
    assert exported["sources"][".relay/actions/local/main.js"] == "process.stdout.write('ready');\n"
    templates = owner.get("/api/workflow-library").json()["templates"]
    assert templates[0]["id"] == "owner:" + identity and templates[0]["jobs"] == ["main"]
    assert owner.get("/api/workflow-library", {"id": "invalid"}).status_code == 422
    project.write(".relay/prompts/oversized.md", "x" * 1048577)
    response = post(
        owner,
        "/api/workflow-library",
        {"metadata": {"name": "Too large"}, "yaml": BASE, "include_project_sources": True},
    )
    assert response.status_code == 400 and "1 MiB" in response.json()["message"]
    assert len(owner.get("/api/workflow-library").json()["templates"]) == 1


@pytest.mark.parametrize(
    "bundle",
    [
        {"yaml": 1},
        {"yaml": BASE, "metadata": []},
        {"yaml": BASE, "metadata": {}},
        {"yaml": BASE, "metadata": {"name": ""}},
        {"yaml": BASE, "metadata": {"name": "x", "unsupported": True}},
        {"yaml": BASE, "metadata": {"name": "x", "categories": [1]}},
        {"yaml": BASE, "metadata": {"name": "x", "filePatterns": "*.py"}},
        {"yaml": BASE, "metadata": {"name": "x", "description": "x" * 2049}},
        {"yaml": BASE, "metadata": {"name": "x"}, "sources": {"outside.txt": "unsafe"}},
        {
            "yaml": BASE,
            "metadata": {"name": "x"},
            "sources": {".relay/prompts/../../escape": "unsafe"},
        },
        {
            "yaml": BASE,
            "metadata": {"name": "x"},
            "sources": {f".relay/prompts/{i}": "" for i in range(101)},
        },
    ],
)
def test_invalid_library_bundles_never_create_templates(
    owner: Client, bundle: dict[str, Any]
) -> None:
    assert post(owner, "/api/workflow-library", bundle).status_code in {400, 422}
    assert owner.get("/api/workflow-library").json()["templates"] == []


def test_scoped_bindings_round_trip_revision_delete_and_secret_redaction(
    owner: Client, project: RelayProject
) -> None:
    assert (
        post(
            owner,
            "/api/workflow-environments",
            {
                "name": "prod",
                "branches": ["main", "!private/**"],
                "wait_minutes": 2,
                "approval_required": True,
                "url": "https://example.invalid/deploy",
            },
        ).status_code
        == 200
    )
    for scope in ("installation", "project", "environment"):
        body = {
            "scope": scope,
            "environment": "prod",
            "name": "value",
            "kind": "variable",
            "value": scope,
        }
        assert post(owner, "/api/workflow-bindings", body).status_code == 200
    assert (
        post(
            owner,
            "/api/workflow-bindings",
            {
                "scope": "environment",
                "environment": "prod",
                "name": "TOKEN",
                "kind": "secret",
                "source": "environment",
                "reference": "OWNER_TOKEN",
            },
        ).status_code
        == 200
    )
    rows = owner.get("/api/workflow-bindings").json()["bindings"]
    assert len(rows) == 4 and all(row["revision"] for row in rows)
    assert next(row for row in rows if row["kind"] == "secret")["value"] == ""
    assert {row["value"] for row in rows if row["kind"] == "variable"} == {
        "installation",
        "project",
        "environment",
    }
    previous = WorkflowBinding.objects.get(
        scope=f"project:{project.project_id}", name="VALUE"
    ).revision
    assert (
        post(
            owner,
            "/api/workflow-bindings",
            {"name": "value", "kind": "variable", "value": "updated"},
        ).status_code
        == 200
    )
    assert (
        WorkflowBinding.objects.get(scope=f"project:{project.project_id}", name="VALUE").revision
        != previous
    )
    assert (
        post(
            owner, "/api/workflow-bindings", {"name": "value", "kind": "variable", "delete": True}
        ).status_code
        == 200
    )
    assert not WorkflowBinding.objects.filter(scope=f"project:{project.project_id}").exists()


@pytest.mark.parametrize(
    "addition",
    [
        {"scope": "unknown"},
        {"scope": "environment", "environment": "missing"},
        {"value": 1},
        {"source": []},
        {"reference": False},
        {"name": "GITHUB_TOKEN"},
        {"name": "bad.name"},
        {"name": "x" * 101},
        {"kind": "other"},
        {"value": "x" * 49153},
        {"kind": "secret", "source": "invalid"},
        {"kind": "secret", "source": "environment", "reference": "bad.name"},
        {"kind": "secret", "source": "environment", "reference": "KEY", "value": "private"},
    ],
)
def test_invalid_bindings_do_not_persist(owner: Client, addition: dict[str, Any]) -> None:
    response = post(
        owner, "/api/workflow-bindings", {"name": "VALUE", "kind": "variable", **addition}
    )
    assert response.status_code == 400
    assert not WorkflowBinding.objects.exists()


@pytest.mark.parametrize(
    "addition",
    [
        {"name": "x" * 256},
        {"branches": "main"},
        {"branches": [1]},
        {"branches": ["x"] * 101},
        {"branches": ["x" * 257]},
        {"branches": ["invalid\\"]},
        {"wait_minutes": True},
        {"wait_minutes": -1},
        {"wait_minutes": 43201},
        {"approval_required": "true"},
        {"url": 1},
        {"url": "https://" + "x" * 2048},
        {"url": "file:///private"},
    ],
)
def test_invalid_environments_do_not_persist(owner: Client, addition: dict[str, Any]) -> None:
    assert post(owner, "/api/workflow-environments", {"name": "prod", **addition}).status_code in {
        400,
        422,
    }
    assert not WorkflowEnvironment.objects.exists()


def test_environment_and_binding_caps_allow_updates_but_reject_new_rows(
    owner: Client, project: RelayProject
) -> None:
    WorkflowEnvironment.objects.bulk_create(
        [WorkflowEnvironment(project_id=project.project_id, name=f"env{i}") for i in range(100)]
    )
    assert post(owner, "/api/workflow-environments", {"name": "another"}).status_code == 400
    assert (
        post(owner, "/api/workflow-environments", {"name": "env0", "wait_minutes": 3}).status_code
        == 200
    )
    WorkflowBinding.objects.bulk_create(
        [
            WorkflowBinding(
                scope=f"project:{project.project_id}", name=f"VALUE{i}", kind="variable"
            )
            for i in range(100)
        ]
    )
    assert (
        post(owner, "/api/workflow-bindings", {"name": "ANOTHER", "kind": "variable"}).status_code
        == 400
    )
    assert (
        post(
            owner,
            "/api/workflow-bindings",
            {"name": "VALUE0", "kind": "variable", "value": "updated"},
        ).status_code
        == 200
    )
    assert WorkflowBinding.objects.get(name="VALUE0").value == "updated"


def test_trigger_api_requires_explicit_writer_decision_and_dispatch_object(
    owner: Client, project: RelayProject
) -> None:
    project.write_workflow("dispatch", "on: repository_dispatch\n" + BASE)
    for addition in ({}, {"enabled": True}, {"enabled": True, "allow_writers": 1}):
        assert (
            post(
                owner,
                "/api/workflow-triggers",
                {"key": "dispatch", "event": "repository_dispatch", **addition},
            ).status_code
            == 400
        )
    body = {
        "key": "dispatch",
        "event": "repository_dispatch",
        "enabled": True,
        "allow_writers": True,
    }
    assert post(owner, "/api/workflow-triggers", body).status_code == 200
    assert (
        post(
            owner,
            "/api/repository-dispatch",
            {"event_type": "build", "idempotency_key": "once", "client_payload": []},
        ).status_code
        == 400
    )
    assert post(
        owner,
        "/api/repository-dispatch",
        {"event_type": "build", "idempotency_key": "once", "client_payload": {"target": "local"}},
    ).json() == {"accepted": True}
    inventory = owner.get("/api/workflow-triggers").json()
    assert inventory["triggers"][0]["enabled"] and len(inventory["deliveries"]) == 1
    assert inventory["deliveries"][0]["run_id"] is None
    assert post(owner, "/api/attempts/123/environment", {}).status_code == 400


def test_named_products_download_exact_bytes_and_reject_expired_or_corrupt_data(
    owner: Client, project: RelayProject, tmp_path: Path
) -> None:
    project.write_workflow(
        "products",
        "jobs: {main: {runs-on: self-hosted, steps: "
        "[{uses: relay/human-wait@v1, with: {prompt: Continue?}}]}}",
    )
    engine = InlineEngine(node_executors(), tmp_path / "attempt-artifacts")
    run_id = engine.launch(project, "products")
    engine.drain(run_id)
    attempt = NodeAttempt.objects.filter(node_run__run_id=run_id).last()
    assert attempt is not None
    source = tmp_path / "product-source"
    source.mkdir()
    (source / "result.txt").write_bytes(b"exact\r\nbytes\xff")
    directory, manifest, size, digest = capture(source, ["**"], "artifacts", run_id)
    artifact = ActionsArtifact.objects.create(
        run_id=run_id,
        attempt_id=attempt.pk,
        name="result",
        directory=str(directory),
        manifest=manifest,
        bytes=size,
        digest=digest,
    )
    response = owner.get(f"/api/workflow-artifacts/{artifact.pk}/download")
    assert response.status_code == 200
    with ZipFile(BytesIO(b"".join(response.streaming_content))) as archive:
        assert archive.namelist() == ["result.txt"]
        assert archive.read("result.txt") == b"exact\r\nbytes\xff"
    products = owner.get(f"/api/runs/{run_id}/products").json()
    assert products["artifacts"][0]["digest"] == digest and products["queues"] == []
    assert owner.get(f"/api/runs/{uuid.uuid4()}/products").status_code == 404
    assert owner.get(f"/api/workflow-artifacts/{uuid.uuid4()}/download").status_code == 400
    artifact.expires_at = timezone.now() - timedelta(seconds=1)
    artifact.save(update_fields=["expires_at"])
    assert owner.get(f"/api/workflow-artifacts/{artifact.pk}/download").status_code == 400
    artifact.expires_at = None
    artifact.save(update_fields=["expires_at"])
    (directory / "result.txt").write_bytes(b"corrupt")
    rejected = owner.get(f"/api/workflow-artifacts/{artifact.pk}/download")
    assert rejected.status_code == 500 and rejected.json()["code"] == "node_execution_error"
    assert ActionsArtifact.objects.filter(pk=artifact.pk).exists()

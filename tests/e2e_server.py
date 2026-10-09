"""Serve the real browser application against scratch storage and wire-level providers.

Only this test process exposes reset/commit helpers and an inline dispatch consumer.
It never uses the owner's projects, database, credentials, or installed agents.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
import os
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Event, Thread
import time
from types import SimpleNamespace
from typing import TypeVar
from uuid import uuid4

import pytest

ThreadResult = TypeVar("ThreadResult")
WORKFLOW = (
    "name: Configuration\non: workflow_dispatch\njobs:\n"
    "  work:\n    steps:\n"
    "      - id: agent\n        uses: relay/agent@v1\n"
    '        with: {agents: \'["codex","claude"]\', model: m1}\n'
)


def serve(root: Path, port: int, *, login_required: bool = True) -> None:
    for name, value in {
        "DJANGO_SETTINGS_MODULE": "relay.web.settings",
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_STATE_HOME": str(root / "state"),
        "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(root / "local"),
        "RELAY_DATABASE_PATH": str(root / "relay.db"),
        "RELAY_HUEY_DATABASE_PATH": str(root / "huey.db"),
        "RELAY_MIGRATION_LOCK_PATH": str(root / "migrate.lock"),
        "RELAY_LOG_PATH": str(root / "relay.log"),
        "RELAY_DJANGO_SECRET_KEY": "relay-browser-tests-only-0123456789abcdefghijklmnopqrstuvwxyz",
        "RELAY_LOGIN_REQUIRED": "true" if login_required else "false",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(root / "empty-gitconfig"),
    }.items():
        os.environ[name] = value
    import django
    from django.db import connections
    from django.http import HttpRequest, JsonResponse
    from django.test import Client
    from django.urls import path
    from django.views.decorators.http import require_POST
    import uvicorn

    django.setup()
    from django.contrib.auth.models import User

    from relay.agents import discovery, registry
    from relay.agents.driver import RoutedAgentNodeDriver
    from relay.errors import ConfigError
    from relay.execution.nodes import node_executors
    from relay.execution.scheduler import dispatch_ready_nodes
    from relay.execution.state import EventSource
    from relay.manage import apply_migrations
    from relay.paths import artifacts_dir, settings_path
    from relay.projects import folders
    from relay.projects.service import initialize_project
    from relay.web.auth import owner_required
    from relay.web.models import EditorLease, Installation, NodeAttempt, Project, Run, WorkflowDraft
    from relay.web.repositories import DjangoExecutionStore
    from relay.web.urls import urlpatterns
    from relay.web.views import actions, api_errors, json_body
    from tests.support import (
        FakeAgents,
        InlineEngine,
        RegistryNetwork,
        create_project,
        fake_executable,
        git,
    )

    apply_migrations()
    patch = pytest.MonkeyPatch()
    patch.setattr(folders, "_home_directory", lambda: root)
    if assets_root := os.environ.get("RELAY_TEST_ASSETS_ROOT"):
        from relay.web import static_view

        # Scratch builds exercise new browser code without replacing live assets.
        patch.setattr(static_view, "STATIC_ROOT", Path(assets_root))
        patch.setattr(static_view, "_STATIC_ASSETS", static_view._asset_catalog())
    providers = FakeAgents(root / "agents", root / "provider-transcript.jsonl", patch)
    providers.directory.mkdir()
    interpreter_directories = {
        str(Path(executable).parent)
        for name in ("bash", "sh", "pwsh", "powershell", "cmd")
        if (executable := shutil.which(name)) is not None
    }
    providers.isolate_path()
    patch.setenv("PATH", os.pathsep.join([os.environ["PATH"], *sorted(interpreter_directories)]))
    providers.install("codex", mode="configuration")
    providers.install("claude", mode="configuration")
    providers.install("antigravity", mode="configuration")
    patch.setattr(discovery, "shutil", SimpleNamespace(which=providers.find_executable))
    patch.setattr(registry, "urlopen", RegistryNetwork().open)
    project = create_project(root / "repo")
    project.write_workflow("workflow", WORKFLOW)
    patch.setenv("RELAY_PROJECT_ROOT", str(project.repository))
    if login_required:
        response = Client().post(
            "/api/auth/onboard",
            data='{"username":"owner","password":"Relay-Test-Passphrase-2026!"}',
            content_type="application/json",
            HTTP_HOST="127.0.0.1",
        )
        if response.status_code != 201:
            message = "The browser-test owner could not be created."
            raise RuntimeError(message)

    engine = InlineEngine(
        node_executors(agent_driver=RoutedAgentNodeDriver()), artifacts_dir(create=True)
    )
    patch.setattr(actions, "_enqueue_claim", engine.tokens.append)
    stopped = Event()

    @owner_required
    @require_POST
    def reset(request: HttpRequest) -> JsonResponse:
        del request
        from relay.execution.cancellation import request_cancellation

        for run_id in Run.objects.filter(
            status__in=("running", "paused_wait", "pending", "canceling")
        )[:100].values_list("pk", flat=True):
            request_cancellation(engine.store, str(run_id), "browser-fixture-reset")
        deadline = time.monotonic() + 10
        while Run.objects.filter(status="canceling").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if Run.objects.filter(status="canceling").exists():
            return JsonResponse({"message": "The preceding fixture has not stopped."}, status=503)
        # The feedback scenario replaces Codex and the shared ACP mode.
        # Restore its configuration so later tests get the normal capabilities.
        shutil.rmtree(providers.directory)
        providers.directory.mkdir()
        for agent_id in ("codex", "claude", "antigravity"):
            providers.install(agent_id, mode="configuration")
        WorkflowDraft.objects.all().delete()
        EditorLease.objects.all().delete()
        settings_path().unlink(missing_ok=True)
        Project.objects.filter(pk=project.project_id).update(defaults={})
        project.write_workflow("workflow", WORKFLOW)
        return JsonResponse({"ok": True, "python": sys.executable})

    @owner_required
    @require_POST
    def starter_project(request: HttpRequest) -> JsonResponse:
        body = json_body(request)
        fresh_owner = body.get("fresh_owner") is True
        full_workflow = body.get("full_workflow") is True
        WorkflowDraft.objects.all().delete()
        EditorLease.objects.all().delete()
        # Only this server owns the scratch repository and fake-provider directory.
        shutil.rmtree(project.relay_root)
        initialize_project(project.repository)
        project.commit("Restore untouched initialization files")
        shutil.rmtree(providers.directory)
        providers.directory.mkdir()
        if full_workflow:
            counters = root / "ai-starter-counters"
            shutil.rmtree(counters, ignore_errors=True)
            counters.mkdir()
            patch.setenv("FAKE_AI_COUNTER_ROOT", str(counters))
            for agent in ("codex", "claude"):
                providers.install(agent, mode="configuration-ai-starter")
        else:
            providers.install("codex", mode="configuration-starters")
        fake_executable(
            providers.directory,
            "python",
            (
                "from pathlib import Path\n"
                "import sys\n"
                "if len(sys.argv) > 2 and sys.argv[1] == '-c':\n"
                "    Path('AUDIT_CHECKPOINT.json').write_text('{\"ready\":true,\"exit_code\":0}')\n"
                "print('Fake pytest: all tests passed')\n"
            ),
        )
        fake_executable(providers.directory, "npm", "print('Fake npm test: all tests passed')\n")
        if fresh_owner:
            User.objects.all().delete()
            Installation.objects.all().delete()
        return JsonResponse({"ok": True})

    @owner_required
    @require_POST
    def commit(request: HttpRequest) -> JsonResponse:
        del request
        project.commit("Save browser-test workflow")
        return JsonResponse({"ok": True})

    @owner_required
    @require_POST
    def storage_project(request: HttpRequest) -> JsonResponse:
        del request
        isolated = create_project(root / f"storage-{uuid4().hex}")
        (isolated.relay_root / "workflows/workflow.yaml").unlink()
        isolated.commit("Keep the disposable storage project empty")
        return JsonResponse({"project_id": isolated.project_id})

    @api_errors
    @owner_required
    @require_POST
    def resource_remnant(request: HttpRequest) -> JsonResponse:
        from relay.execution.resources import allocate_attempt_resources

        run_id = json_body(request).get("run_id")
        if not isinstance(run_id, str):
            message = "The test resource requires a run ID."
            raise ConfigError(message)
        attempt = NodeAttempt.objects.filter(
            node_run__run_id=run_id, ended_at__isnull=False
        ).first()
        if attempt is None:
            message = "The test resource requires an ended attempt."
            raise ConfigError(message)
        allocate_attempt_resources(run_id, str(attempt.pk))
        return JsonResponse({"created": True})

    @api_errors
    @owner_required
    @require_POST
    def launch_files(request: HttpRequest) -> JsonResponse:
        mode = json_body(request).get("mode")
        if mode == "blockers":
            project.write("README.md", "Browser-test staged change\n")
            git(project.repository, "add", "README.md")
            project.write("untracked code.py", "Browser-test code\n")
            project.write("REVIEW.md", "Browser-test owner review\n")
        elif mode == "race":
            target = project.repository / "racing code.py"
            previous = target.read_text() if target.exists() else ""
            project.write("racing code.py", previous + "Browser-test later change\n")
        elif mode != "inspect":
            message = "The browser-test launch file mode is invalid."
            raise ConfigError(message)
        return JsonResponse(
            {
                "head": git(project.repository, "rev-parse", "HEAD"),
                "status": git(project.repository, "status", "--porcelain=v1"),
                "index": git(project.repository, "diff", "--cached"),
            }
        )

    @owner_required
    @require_POST
    def report(request: HttpRequest) -> JsonResponse:
        del request
        project.write("REVIEW.md", "Ready: Yes\nRead this report before approving.\n")
        project.commit("Add browser-test review material")
        return JsonResponse({"ok": True})

    @api_errors
    @owner_required
    @require_POST
    def historical_workflow(request: HttpRequest) -> JsonResponse:
        """Seed old source only to exercise retained-run monitoring contracts."""
        from relay.workflows.editor import _atomic_create
        from relay.workflows.loader import load_workflow_text, resolve_workflow_path

        body = json_body(request)
        key, source = body.get("key"), body.get("yaml")
        if not isinstance(key, str) or not isinstance(source, str):
            message = "A historical fixture requires a key and YAML source."
            raise ConfigError(message)
        relay_root, _project = actions.current_project(request)
        loaded = load_workflow_text(source)
        if loaded.definition.actions:
            message = "Use the public API for current workflow fixtures."
            raise ConfigError(message)
        path = resolve_workflow_path(relay_root / "workflows", key)
        _atomic_create(path, source)
        return JsonResponse({"key": path.name, "yaml": source}, status=201)

    @api_errors
    @owner_required
    @require_POST
    def historical_run(request: HttpRequest) -> JsonResponse:
        """Capture a legacy snapshot through its internal compatibility service."""
        from relay.execution.launch import LaunchRequest, launch_workflow
        from relay.owner_settings import effective_config
        from relay.web.settings_repository import DjangoSettingsStore

        body = json_body(request)
        relay_root, selected = actions.current_project(request)
        config = effective_config(DjangoSettingsStore(), selected.id)
        result = launch_workflow(
            engine.store,
            relay_root,
            selected.id,
            LaunchRequest(
                workflow_key=body["workflow_key"],
                inputs=body.get("inputs", {}),
                model=body.get("model"),
                cleanup_policy=body.get("cleanup_policy", config.cleanup_policy),
                entry_point=body.get("entry_point"),
                owner_agents=config.agent_preferences,
                launcher="owner",
                defaults=config.workflow_defaults,
            ),
            engine.tokens.append,
        )
        return JsonResponse({"run_id": result.run_id}, status=201)

    @owner_required
    @require_POST
    def feedback_provider(request: HttpRequest) -> JsonResponse:
        del request
        providers.install("codex", mode="feedback")
        return JsonResponse({"ok": True})

    @owner_required
    @require_POST
    def elicitation_provider(request: HttpRequest) -> JsonResponse:
        del request
        providers.install("codex", mode="elicitation")
        return JsonResponse({"ok": True})

    @owner_required
    @require_POST
    def recovery_provider(request: HttpRequest) -> JsonResponse:
        del request
        providers.install("codex", mode="configuration-recovery")
        return JsonResponse({"ok": True})

    @api_errors
    @owner_required
    @require_POST
    def activity(request: HttpRequest) -> JsonResponse:
        body = json_body(request)
        run_id, scope, event_type, payload = (
            body.get(field) for field in ("run_id", "scope", "type", "payload")
        )
        allowed = {"agent.message", "agent.thought", "agent.tool_call", "agent.tool_result"}
        if (
            not isinstance(run_id, str)
            or not isinstance(scope, str)
            or not isinstance(event_type, str)
            or event_type not in allowed
            or not isinstance(payload, dict)
        ):
            message = "The browser-test activity record is invalid."
            raise ConfigError(message)
        attempt = (
            NodeAttempt.objects.filter(node_run__run_id=run_id, node_run__scope_path=scope)
            .order_by("-attempt_number")
            .first()
        )
        if attempt is None:
            message = "The browser-test job has no attempt."
            raise ConfigError(message)
        DjangoExecutionStore().append_attempt_event(
            str(attempt.pk), event_type, EventSource.AGENT, payload
        )
        return JsonResponse({"ok": True})

    urlpatterns.insert(0, path("__test__/reset", reset))
    urlpatterns.insert(0, path("__test__/starter-project", starter_project))
    urlpatterns.insert(0, path("__test__/commit", commit))
    urlpatterns.insert(0, path("__test__/storage-project", storage_project))
    urlpatterns.insert(0, path("__test__/resource-remnant", resource_remnant))
    urlpatterns.insert(0, path("__test__/launch-files", launch_files))
    urlpatterns.insert(0, path("__test__/report", report))
    urlpatterns.insert(0, path("__test__/historical-workflows", historical_workflow))
    urlpatterns.insert(0, path("__test__/historical-runs", historical_run))
    urlpatterns.insert(0, path("__test__/feedback-provider", feedback_provider))
    urlpatterns.insert(0, path("__test__/elicitation-provider", elicitation_provider))
    urlpatterns.insert(0, path("__test__/recovery-provider", recovery_provider))
    urlpatterns.insert(0, path("__test__/activity", activity))

    # Close each SDK callback's database connection in its owning thread.
    original_to_thread = asyncio.to_thread

    async def to_thread(
        function: Callable[..., ThreadResult], *args: object, **kwargs: object
    ) -> ThreadResult:
        def invoke() -> ThreadResult:
            try:
                return function(*args, **kwargs)
            finally:
                connections.close_all()

        return await original_to_thread(invoke)

    patch.setattr(asyncio, "to_thread", to_thread)

    def consume() -> None:
        try:
            while not stopped.wait(0.02):
                engine.store.resolve_human_wait_controls()
                engine.store.resume_automatic_retries()
                if engine.tokens:
                    engine.run_token(engine.tokens.popleft())
                for run_id in Run.objects.filter(status="running").values_list("id", flat=True):
                    dispatch_ready_nodes(engine.store, str(run_id), engine.tokens.append)
        finally:
            connections.close_all()

    consumer = Thread(target=consume, name="browser-test-consumer", daemon=True)
    consumer.start()
    try:
        uvicorn.run("relay.web.asgi:application", host="127.0.0.1", port=port, log_level="warning")
    finally:
        stopped.set()
        consumer.join(timeout=10)
        connections.close_all()
        patch.undo()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--no-login", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="relay-browser-tests-") as directory:
        serve(Path(directory), args.port, login_required=not args.no_login)


if __name__ == "__main__":
    main()

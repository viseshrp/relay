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
import tempfile
from threading import Event, Thread
from types import SimpleNamespace
from typing import TypeVar

import pytest

ThreadResult = TypeVar("ThreadResult")
WORKFLOW = (
    "version: 1\nname: Configuration\nmodel: m1\nagents: [codex, claude]\n"
    "nodes:\n  work: {type: agent}\n"
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
    from relay.agents import discovery, registry
    from relay.agents.driver import RoutedAgentNodeDriver
    from relay.execution.nodes import node_executors
    from relay.execution.scheduler import dispatch_ready_nodes
    from relay.manage import apply_migrations
    from relay.paths import artifacts_dir
    from relay.web.auth import owner_required
    from relay.web.models import EditorLease, Run, WorkflowDraft
    from relay.web.urls import urlpatterns
    from relay.web.views import actions
    from tests.support import FakeAgents, InlineEngine, RegistryNetwork, create_project

    apply_migrations()
    patch = pytest.MonkeyPatch()
    providers = FakeAgents(root / "agents", root / "provider-transcript.jsonl", patch)
    providers.directory.mkdir()
    providers.isolate_path()
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
        # The feedback scenario replaces Codex and the shared ACP mode.
        # Restore its configuration so later tests get the normal capabilities.
        providers.install("codex", mode="configuration")
        WorkflowDraft.objects.all().delete()
        EditorLease.objects.all().delete()
        project.write_workflow("workflow", WORKFLOW)
        return JsonResponse({"ok": True})

    @owner_required
    @require_POST
    def commit(request: HttpRequest) -> JsonResponse:
        del request
        project.commit("Save browser-test workflow")
        return JsonResponse({"ok": True})

    @owner_required
    @require_POST
    def report(request: HttpRequest) -> JsonResponse:
        del request
        project.write("REVIEW.md", "Ready: Yes\nRead this report before approving.\n")
        project.commit("Add browser-test review material")
        return JsonResponse({"ok": True})

    @owner_required
    @require_POST
    def feedback_provider(request: HttpRequest) -> JsonResponse:
        del request
        providers.install("codex", mode="feedback")
        return JsonResponse({"ok": True})

    @owner_required
    @require_POST
    def recovery_provider(request: HttpRequest) -> JsonResponse:
        del request
        providers.install("codex", mode="configuration-recovery")
        return JsonResponse({"ok": True})

    urlpatterns.insert(0, path("__test__/reset", reset))
    urlpatterns.insert(0, path("__test__/commit", commit))
    urlpatterns.insert(0, path("__test__/report", report))
    urlpatterns.insert(0, path("__test__/feedback-provider", feedback_provider))
    urlpatterns.insert(0, path("__test__/recovery-provider", recovery_provider))

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

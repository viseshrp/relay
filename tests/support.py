"""Test helpers: Git repositories, initialized Relay projects, and an inline engine."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import Request

import pytest

from relay.execution.dispatch import set_dispatch_notifier
from relay.execution.launch import LaunchRequest, launch_workflow
from relay.execution.runner import (
    AttemptContext,
    AttemptExecutor,
    ExecutionOutcome,
    OutcomeKind,
    run_claim_token,
)
from relay.execution.scheduler import dispatch_ready_nodes
from relay.execution.state import EventSource
from relay.projects.service import initialize_project, register_current_project
from relay.web.models import HumanInteraction, NodeRun, Run, RunEvent
from relay.web.repositories import DjangoExecutionStore, DjangoProjectStore
from relay.workflows.schema import AgentNode

PYTHON = Path(sys.executable).as_posix()


@dataclass
class Clock:
    """Advance elapsed time and UTC together without waiting for a wall clock."""

    elapsed: float = 1_000.0
    instant: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return self.instant

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds
        self.instant += timedelta(seconds=seconds)


def git(repository: Path, *arguments: str) -> str:
    """Run Git in a test repository and return its trimmed standard output."""
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(repository), *arguments],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def symlink_or_skip(link: Path, target: Path) -> None:
    """Create a symlink, skipping where the platform denies the privilege (Windows)."""
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as error:
        pytest.skip(f"symlinks are unavailable here: {error}")


def init_repository(path: Path) -> Path:
    """Create a Git repository with deterministic identity and one commit."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Relay Tests")
    git(path, "config", "user.email", "relay-tests@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.autocrlf", "false")
    (path / "README.md").write_text("Relay test repository\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "Initial commit")
    return path


@dataclass(frozen=True, slots=True)
class RelayProject:
    """A committed repository with an initialized and registered `.relay/` tree."""

    repository: Path
    relay_root: Path
    project_id: str

    def write(self, relative: str, text: str) -> Path:
        """Write a repository file, creating parent directories as needed."""
        path = self.repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def write_workflow(self, key: str, text: str) -> None:
        """Write `.relay/workflows/<key>.yaml` and commit it so launch sees a clean tree."""
        self.write(f".relay/workflows/{key}.yaml", text)
        self.commit(f"Add workflow {key}")

    def commit(self, message: str) -> None:
        git(self.repository, "add", "-A")
        git(self.repository, "commit", "-q", "--allow-empty", "-m", message)


def create_project(path: Path) -> RelayProject:
    """Initialize, commit, and register a Relay project at `path`."""
    repository = init_repository(path)
    initialize_project(repository)
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", "Initialize Relay")
    record = register_current_project(DjangoProjectStore(), repository)
    return RelayProject(repository, repository / ".relay", record.id)


@dataclass
class InlineEngine:
    """Launch runs and execute dispatched tokens in this process, in order."""

    executors: Mapping[str, AttemptExecutor]
    artifact_root: Path
    worker_id: str = "test-worker"
    tokens: deque[str] = field(default_factory=deque)

    def __post_init__(self) -> None:
        set_dispatch_notifier(self.tokens.append)

    @property
    def store(self) -> DjangoExecutionStore:
        return DjangoExecutionStore()

    def launch(
        self,
        project: RelayProject,
        workflow_key: str,
        *,
        inputs: Mapping[str, object] | None = None,
        model: str | None = None,
        cleanup_policy: str = "retain",
        entry_point: str | None = None,
        owner_agents: Sequence[str] = (),
    ) -> str:
        request = LaunchRequest(
            workflow_key,
            dict(inputs or {}),
            model,
            cleanup_policy,
            entry_point,
            tuple(owner_agents),
            "owner",
        )
        result = launch_workflow(
            self.store, project.relay_root, project.project_id, request, self.tokens.append
        )
        return result.run_id

    def run_token(self, token: str) -> ExecutionOutcome | None:
        """Claim and execute one dispatched token on this engine's executors."""
        return run_claim_token(
            self.store, token, self.worker_id, self.executors, artifact_root=self.artifact_root
        )

    def drain(self, run_id: str, *, max_steps: int = 200) -> list[ExecutionOutcome | None]:
        """Run every dispatched token, scheduling successors after each attempt."""
        outcomes = []
        steps = 0
        while self.tokens:
            if steps >= max_steps:
                message = f"Run {run_id} did not settle within {max_steps} attempts."
                raise AssertionError(message)
            outcomes.append(self.run_token(self.tokens.popleft()))
            dispatch_ready_nodes(self.store, run_id, self.tokens.append)
            steps += 1
        return outcomes


def run_status(run_id: str) -> str:
    return str(Run.objects.get(pk=run_id).status)


def node_statuses(run_id: str) -> dict[str, str]:
    return {
        str(scope): str(status)
        for scope, status in NodeRun.objects.filter(run_id=run_id).values_list(
            "scope_path", "status"
        )
    }


def event_types(run_id: str, prefix: str = "") -> list[str]:
    return [
        str(kind)
        for kind in RunEvent.objects.filter(run_id=run_id, type__startswith=prefix)
        .order_by("id")
        .values_list("type", flat=True)
    ]


@dataclass
class FakeAgentDriver:
    """Agent driver stand-in: writes `agent-output.md` and commits it for writers."""

    calls: list[str] = field(default_factory=list)
    outcome_kind: OutcomeKind = OutcomeKind.SUCCEEDED

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        self.calls.append(context.attempt.scope_path)
        context.runtime.append_attempt_event(
            context.attempt.attempt_id,
            "agent.message",
            EventSource.AGENT,
            {"text": f"working on {context.attempt.scope_path}"},
        )
        if self.outcome_kind is not OutcomeKind.SUCCEEDED:
            return ExecutionOutcome(self.outcome_kind, error_code="agent_failed")
        if node.writes:
            (context.worktree / "agent-output.md").write_text(
                f"Ready: Yes\nScope: {context.attempt.scope_path}\n", encoding="utf-8"
            )
            git(context.worktree, "add", "agent-output.md")
            git(context.worktree, "commit", "-q", "-m", f"Agent {context.attempt.scope_path}")
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


def answer_wait(engine: InlineEngine, run_id: str, *, key: str = "answer-1") -> str:
    """Answer the run's pending wait, resolve it, and drain the resumed work."""
    interaction = HumanInteraction.objects.get(run_id=run_id, kind="wait", status="pending")
    result = engine.store.submit_control(
        str(interaction.attempt_id), "wait_answer", key, {"value": "go"}, 600.0
    )
    engine.store.resolve_human_wait_controls()
    dispatch_ready_nodes(engine.store, run_id, engine.tokens.append)
    engine.drain(run_id)
    return result.value


def fake_executable(
    directory: Path, name: str, source: str | Path, args: tuple[str, ...] = ()
) -> Path:
    """Create a Python launcher; 'codex-acp' resolves to 'codex-acp.cmd' on Windows."""
    directory.mkdir(parents=True, exist_ok=True)
    if isinstance(source, Path):
        script = source.resolve()
    else:
        script = directory / f"{name}_impl.py"
        script.write_text(source, encoding="utf-8")
    arguments = " ".join(args)
    if sys.platform == "win32":
        launcher = directory / f"{name}.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" {arguments} %*\r\n', encoding="utf-8")
    else:
        launcher = directory / name
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" {arguments} "$@"\n', encoding="utf-8"
        )
        launcher.chmod(0o755)
    return launcher


def registry_document() -> dict[str, object]:
    """A minimal registry listing the four ACP agents with npx distributions."""
    return {
        "version": "2026.10.02",
        "agents": [
            {
                "id": registry_id,
                "name": registry_id,
                "version": "1.0.0",
                "repository": f"https://example.invalid/{registry_id}",
                "authMethods": [{"id": "login"}],
                "distribution": {"npx": {"package": f"@acp/{registry_id}@1.0.0", "args": []}},
            }
            for registry_id in ("codex-acp", "claude-acp", "github-copilot-cli", "cursor")
        ],
    }


class RegistryResponse(BytesIO):
    """The read/status/context-manager boundary used by urllib registry fetches."""

    status: int

    def __init__(self, body: bytes, status: int) -> None:
        super().__init__(body)
        self.status = status


@dataclass
class RegistryNetwork:
    """An offline registry server; all cache and validation code still runs."""

    document: object = field(default_factory=registry_document)
    status: int = 200
    error: Exception | None = None
    requests: list[str] = field(default_factory=list)

    def open(self, request: Request, *, timeout: float) -> RegistryResponse:
        del timeout
        self.requests.append(request.full_url)
        if self.error is not None:
            raise self.error
        return RegistryResponse(json.dumps(self.document).encode(), self.status)


@dataclass
class FakeAgents:
    """Expose only test providers and Git on PATH, with isolated wire transcripts."""

    directory: Path
    transcript: Path
    monkeypatch: pytest.MonkeyPatch
    host_path: str = ""

    def install(self, agent_id: str, *, mode: str = "success") -> Path:
        from relay.agents.profiles import PROFILES

        profile = PROFILES[agent_id]
        transport = "agy" if profile.driver == "antigravity" else "acp"
        self.monkeypatch.setenv("FAKE_AGENT_TRACE", str(self.transcript))
        self.monkeypatch.setenv("FAKE_AGY_MODE" if transport == "agy" else "FAKE_ACP_MODE", mode)
        return fake_executable(
            self.directory,
            profile.executable_names[0],
            Path(__file__).with_name("fake_agent.py"),
            (transport,),
        )

    def messages(self) -> list[dict[str, object]]:
        if not self.transcript.exists():
            return []
        return [
            json.loads(line) for line in self.transcript.read_text(encoding="utf-8").splitlines()
        ]

    def find_executable(self, name: str) -> str | None:
        """Resolve providers only in the test directory, even when Git shares PATH."""
        return shutil.which(name, path=str(self.directory))

    def isolate_path(self) -> None:
        self.host_path = os.environ.get("PATH", "")
        executable = shutil.which("git")
        if executable is None:
            message = "Git is required for the repository tests."
            raise RuntimeError(message)
        directories = [str(self.directory), str(Path(executable).parent)]
        if os.name == "nt":
            directories.append(str(Path(os.environ["SYSTEMROOT"]) / "System32"))
        self.monkeypatch.setenv("PATH", os.pathsep.join(directories))

    def allow_commands(self, *names: str) -> None:
        """Expose selected installed commands without enabling real provider discovery."""
        directories = os.environ["PATH"].split(os.pathsep)
        for name in names:
            executable = shutil.which(name, path=self.host_path)
            if executable is not None:
                directory = str(Path(executable).parent)
                if directory not in directories:
                    directories.append(directory)
        self.monkeypatch.setenv("PATH", os.pathsep.join(directories))

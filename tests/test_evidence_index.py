"""Failed attempts retain a map of their evidence for the next repair."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from relay.constants import RETRY_HANDOFF_MAX_BYTES
from relay.errors import ArtifactPreservationError
from relay.execution.automatic import recovery_instruction
from relay.vcs.artifacts import (
    EVIDENCE_INDEX_MESSAGE_MAX_BYTES,
    EVIDENCE_INDEX_SOURCE,
    AttemptFailure,
    preserve_attempt_evidence,
    validate_attempt_evidence,
)
from relay.web.models import Artifact, AutomaticRetry
from tests.support import FakeAgents, RelayProject, git, init_repository
from tests.test_automatic_recovery import ReportDriver, launch_report_run

RUN_ID = "index-run"
ATTEMPT_ID = "index-attempt"


def _failed_attempt(tmp_path: Path, message: str) -> tuple[Path, str, Path]:
    repository = init_repository(tmp_path / "repository")
    head = git(repository, "rev-parse", "HEAD")
    (repository / "notes.txt").write_text("partial\n", encoding="utf-8")
    (repository / "REVIEW.md").write_text("Ready: No\n", encoding="utf-8")
    evidence = preserve_attempt_evidence(
        repository,
        repository,
        RUN_ID,
        ATTEMPT_ID,
        head,
        declared_artifacts={"report": "REVIEW.md"},
        failure=AttemptFailure("output_validation_error", message),
    )
    return repository, head, evidence.directory / "INDEX.md"


def test_failed_attempt_index_lists_retained_files_and_the_full_failure(
    tmp_path: Path,
) -> None:
    repository, head, index = _failed_attempt(tmp_path, "Missing label 'Created by'.")
    text = index.read_text(encoding="utf-8")
    assert "Error code: output_validation_error" in text
    assert "| `diff.patch` |" in text
    assert "| `commits.txt` |" in text
    assert "| `untracked/notes.txt` |" in text
    assert "(`report`)" in text
    assert "Missing label 'Created by'." in text
    # The index is part of the hashed manifest, so tampering blocks recovery.
    validate_attempt_evidence(repository, RUN_ID, ATTEMPT_ID, head)
    index.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ArtifactPreservationError):
        validate_attempt_evidence(repository, RUN_ID, ATTEMPT_ID, head)


def test_successful_attempts_have_no_index(tmp_path: Path) -> None:
    repository = init_repository(tmp_path / "repository")
    head = git(repository, "rev-parse", "HEAD")
    evidence = preserve_attempt_evidence(repository, repository, RUN_ID, ATTEMPT_ID, head)
    assert not (evidence.directory / "INDEX.md").exists()
    assert all(item.source_path != EVIDENCE_INDEX_SOURCE for item in evidence.files)


def test_index_bounds_the_message_and_keeps_its_code_fence_closed(tmp_path: Path) -> None:
    message = "```\nescape\n" + "é" * EVIDENCE_INDEX_MESSAGE_MAX_BYTES
    _repository, _head, index = _failed_attempt(tmp_path, message)
    text = index.read_text(encoding="utf-8")
    body = text.split("```text\n", 1)[1].rsplit("\n```", 1)[0]
    assert "```" not in body
    assert len(body.encode("utf-8")) <= EVIDENCE_INDEX_MESSAGE_MAX_BYTES + 8


def test_instruction_names_the_index_within_its_byte_limit() -> None:
    path = "/data/artifacts/run/attempt/INDEX.md"
    note, _digest = recovery_instruction(
        "root.critique.review", "output_validation_error", "🙂" * 5_000, evidence_index=path
    )
    assert f"Evidence index: {path}\n" in note
    assert len(note.encode("utf-8")) <= RETRY_HANDOFF_MAX_BYTES
    oversized, _ = recovery_instruction(
        "root.step", "node_timeout", "late", evidence_index="/" + "x" * RETRY_HANDOFF_MAX_BYTES
    )
    assert "Evidence index:" not in oversized
    assert recovery_instruction("root.step", "node_timeout", "late") == recovery_instruction(
        "root.step", "node_timeout", "late", evidence_index=None
    )


def test_recovering_agent_receives_the_retained_index(
    project: RelayProject, tmp_path: Path, fake_agents: FakeAgents
) -> None:
    driver = ReportDriver()
    launch_report_run(project, tmp_path, fake_agents, driver, enabled=True)
    assert len(driver.calls) == 2
    index = Artifact.objects.get(
        attempt__node_run__scope_path="root.critique.review",
        attempt__attempt_number=1,
        source_path=EVIDENCE_INDEX_SOURCE,
    )
    instruction = driver.calls[1].attempt.prompt_contents[-1]
    assert f"Evidence index: {index.retained_path}\n" in instruction
    assert AutomaticRetry.objects.get(state="resumed").instruction == instruction
    text = Path(index.retained_path).read_text(encoding="utf-8")
    assert "output_validation_error" in text
    assert "(`report`)" in text


def test_index_masks_registered_run_secrets(tmp_path: Path) -> None:
    from relay.execution.dispatch import ClaimedAttempt
    from relay.execution.masking import redactor, release_redactor
    from relay.execution.runner import ExecutionOutcome, OutcomeKind, _preserve

    repository = init_repository(tmp_path / "masked")
    head = git(repository, "rev-parse", "HEAD")
    redactor("masked-run").register("s3cr3t-token")
    claim = ClaimedAttempt(
        claim_token=str(uuid4()),
        attempt_id="masked-attempt",
        attempt_number=1,
        worker_id="worker",
        run_id="masked-run",
        node_run_id="node",
        project_path=str(repository),
        primary_worktree=str(repository),
        scope_path="root.work.step",
        node_id="step",
        node_type="actions_step",
        frozen_def={},
        inputs={},
        upstream_outputs={},
        run_metadata={},
        prompt_contents=(),
        route={},
        writes=False,
        starting_head=head,
        recorded_head=head,
    )
    try:
        evidence = _preserve(
            claim,
            repository,
            ExecutionOutcome(
                OutcomeKind.FAILED,
                error_code="node_timeout",
                error_message="Command printed s3cr3t-token before timing out.",
            ),
            artifact_root=tmp_path / "artifacts",
        )
    finally:
        release_redactor("masked-run")
    text = (evidence.directory / "INDEX.md").read_text(encoding="utf-8")
    assert "s3cr3t-token" not in text
    assert "Command printed *** before timing out." in text

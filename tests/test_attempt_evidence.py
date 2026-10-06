"""Archived bytes and commits must survive intact before recovery can reset work."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from relay.errors import ArtifactPreservationError
from relay.vcs.artifacts import (
    PreservationResult,
    preserve_attempt_evidence,
    validate_attempt_evidence,
)
from tests.support import git, init_repository, symlink_or_skip

RUN_ID = "evidence-run"
ATTEMPT_ID = "failed-attempt"
PARTIAL_BYTES = b"Unfinished owner work\n"


@dataclass(frozen=True)
class ArchivedAttempt:
    repository: Path
    starting_head: str
    evidence: PreservationResult

    @property
    def manifest(self) -> Path:
        return self.evidence.directory / "manifest.json"

    def validate(self) -> None:
        validate_attempt_evidence(self.repository, RUN_ID, ATTEMPT_ID, self.starting_head)


@pytest.fixture
def archived_attempt(tmp_path: Path) -> ArchivedAttempt:
    repository = init_repository(tmp_path / "attempt-repository")
    starting_head = git(repository, "rev-parse", "HEAD")
    (repository / "committed.txt").write_bytes(b"Partial committed feature\n")
    git(repository, "add", "committed.txt")
    git(repository, "commit", "-q", "-m", "Partial attempt commit")
    (repository / "unfinished.txt").write_bytes(PARTIAL_BYTES)
    evidence = preserve_attempt_evidence(repository, repository, RUN_ID, ATTEMPT_ID, starting_head)
    return ArchivedAttempt(repository, starting_head, evidence)


def test_unchanged_archived_bytes_and_partial_commit_pass_validation(
    archived_attempt: ArchivedAttempt,
) -> None:
    archived_attempt.validate()
    assert git(
        archived_attempt.repository, "rev-parse", archived_attempt.evidence.retained_ref
    ) == (archived_attempt.evidence.ending_head)
    assert (archived_attempt.repository / "unfinished.txt").read_bytes() == PARTIAL_BYTES


@pytest.mark.parametrize("payload", [b"{", b"\xff", b"null", b"[]"])
def test_unreadable_or_non_object_manifest_blocks_recovery(
    archived_attempt: ArchivedAttempt, payload: bytes
) -> None:
    archived_attempt.manifest.write_bytes(payload)
    with pytest.raises(ArtifactPreservationError):
        archived_attempt.validate()
    assert (archived_attempt.repository / "unfinished.txt").read_bytes() == PARTIAL_BYTES


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("version", 2),
        ("run_id", "another-run"),
        ("attempt_id", "another-attempt"),
        ("starting_head", "another-commit"),
        ("retained_ref", "refs/heads/main"),
        ("ending_head", "another-commit"),
        ("files", []),
        ("files", {}),
        ("files", [None]),
    ],
)
def test_manifest_identity_and_inventory_must_match_the_attempt(
    archived_attempt: ArchivedAttempt, field: str, value: object
) -> None:
    manifest = json.loads(archived_attempt.manifest.read_text(encoding="utf-8"))
    manifest[field] = value
    archived_attempt.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactPreservationError):
        archived_attempt.validate()
    assert (archived_attempt.repository / "unfinished.txt").read_bytes() == PARTIAL_BYTES


@pytest.mark.parametrize(
    ("field", "value"),
    [("retained_path", None), ("sha256", None), ("bytes", True), ("bytes", -1)],
)
def test_invalid_file_metadata_cannot_authorize_a_reset(
    archived_attempt: ArchivedAttempt, field: str, value: object
) -> None:
    manifest = json.loads(archived_attempt.manifest.read_text(encoding="utf-8"))
    manifest["files"][0][field] = value
    archived_attempt.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactPreservationError):
        archived_attempt.validate()


def test_a_manifest_cannot_use_current_work_as_its_retained_copy(
    archived_attempt: ArchivedAttempt,
) -> None:
    manifest = json.loads(archived_attempt.manifest.read_text(encoding="utf-8"))
    manifest["files"][-1]["retained_path"] = str(archived_attempt.repository / "unfinished.txt")
    archived_attempt.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactPreservationError):
        archived_attempt.validate()
    assert (archived_attempt.repository / "unfinished.txt").read_bytes() == PARTIAL_BYTES


@pytest.mark.parametrize("relative", [False, True])
def test_a_retained_file_symlink_is_rejected_even_when_its_target_matches(
    archived_attempt: ArchivedAttempt, relative: bool
) -> None:
    manifest = json.loads(archived_attempt.manifest.read_text(encoding="utf-8"))
    record = manifest["files"][-1]
    retained = Path(record["retained_path"])
    target = retained.with_name("unchanged-copy.txt")
    retained.rename(target)
    symlink_or_skip(retained, target)
    if relative:
        record["retained_path"] = str(retained.relative_to(archived_attempt.evidence.directory))
        archived_attempt.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactPreservationError):
        archived_attempt.validate()
    assert target.read_bytes() == PARTIAL_BYTES


@pytest.mark.parametrize("change", ["missing", "moved"])
def test_a_missing_or_moved_retained_ref_blocks_recovery(
    archived_attempt: ArchivedAttempt, change: str
) -> None:
    reference = archived_attempt.evidence.retained_ref
    if change == "missing":
        git(archived_attempt.repository, "update-ref", "-d", reference)
    else:
        git(archived_attempt.repository, "update-ref", reference, archived_attempt.starting_head)
    with pytest.raises(ArtifactPreservationError):
        archived_attempt.validate()
    assert (archived_attempt.repository / "unfinished.txt").read_bytes() == PARTIAL_BYTES

"""Recovery preserves report bytes across conflicts and filesystem failures."""

from __future__ import annotations

from pathlib import Path
from typing import IO

import pytest

from relay.errors import ArtifactPreservationError, PathSafetyError
from relay.vcs.artifacts import (
    RecoveryReport,
    preserve_recovery_reports,
    restore_recovery_reports,
    validate_recovery_reports,
)
from tests.support import symlink_or_skip

REPORT_NAME = "PLAN_CRITIQUE.md"
REPORT_BYTES = b"Created by: Reviewer\nReady: No\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    directory = tmp_path / "workspace"
    directory.mkdir()
    return directory


@pytest.fixture
def retained_report(workspace: Path) -> RecoveryReport:
    (workspace / REPORT_NAME).write_bytes(REPORT_BYTES)
    record = preserve_recovery_reports(workspace, "report-run", "attempt", (REPORT_NAME,))[0]
    return RecoveryReport(REPORT_NAME, record.retained_path, record.sha256)


def test_repeated_capture_reuses_identical_evidence_without_overwriting_it(
    workspace: Path, retained_report: RecoveryReport
) -> None:
    retained = Path(retained_report.retained_path)
    modified = retained.stat().st_mtime_ns
    again = preserve_recovery_reports(workspace, "report-run", "attempt", (REPORT_NAME,))
    assert again[0].sha256 == retained_report.sha256
    assert retained.read_bytes() == REPORT_BYTES
    assert retained.stat().st_mtime_ns == modified


def test_changed_source_cannot_replace_the_failed_attempts_retained_report(
    workspace: Path, retained_report: RecoveryReport
) -> None:
    source = workspace / REPORT_NAME
    changed = b"Ready: Yes\n"
    source.write_bytes(changed)
    with pytest.raises(ArtifactPreservationError):
        preserve_recovery_reports(workspace, "report-run", "attempt", (REPORT_NAME,))
    assert Path(retained_report.retained_path).read_bytes() == REPORT_BYTES
    assert source.read_bytes() == changed


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink"])
def test_non_files_are_not_retained_as_report_bytes(workspace: Path, kind: str) -> None:
    source = workspace / REPORT_NAME
    if kind == "directory":
        source.mkdir()
    elif kind == "symlink":
        target = workspace / "other-report.md"
        target.write_bytes(REPORT_BYTES)
        symlink_or_skip(source, target)
    assert preserve_recovery_reports(workspace, "report-run", "attempt", (REPORT_NAME,)) == ()


def test_a_report_link_cannot_retain_bytes_outside_the_worktree(
    workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "owner-report.md"
    outside.write_bytes(REPORT_BYTES)
    symlink_or_skip(workspace / REPORT_NAME, outside)
    with pytest.raises(PathSafetyError):
        preserve_recovery_reports(workspace, "report-run", "attempt", (REPORT_NAME,))
    assert outside.read_bytes() == REPORT_BYTES


def test_missing_retained_bytes_fail_integrity_validation(
    retained_report: RecoveryReport,
) -> None:
    Path(retained_report.retained_path).unlink()
    with pytest.raises(ArtifactPreservationError):
        validate_recovery_reports((retained_report,))


def test_restoring_an_identical_report_preserves_its_existing_file(
    workspace: Path, retained_report: RecoveryReport
) -> None:
    source = workspace / REPORT_NAME
    modified = source.stat().st_mtime_ns
    restore_recovery_reports(workspace, (retained_report,))
    assert source.read_bytes() == REPORT_BYTES
    assert source.stat().st_mtime_ns == modified


def test_restoration_never_overwrites_a_conflicting_owner_file(
    workspace: Path, retained_report: RecoveryReport
) -> None:
    destination = workspace / REPORT_NAME
    owner_bytes = b"Owner's newer review\n"
    destination.write_bytes(owner_bytes)
    with pytest.raises(ArtifactPreservationError):
        restore_recovery_reports(workspace, (retained_report,))
    assert destination.read_bytes() == owner_bytes
    assert Path(retained_report.retained_path).read_bytes() == REPORT_BYTES


def test_restoration_never_writes_through_a_report_symlink(
    workspace: Path, retained_report: RecoveryReport
) -> None:
    destination = workspace / REPORT_NAME
    destination.unlink()
    target = workspace / "owner.txt"
    target.write_bytes(b"Owner bytes\n")
    symlink_or_skip(destination, target)
    with pytest.raises(ArtifactPreservationError):
        restore_recovery_reports(workspace, (retained_report,))
    assert destination.is_symlink()
    assert target.read_bytes() == b"Owner bytes\n"


@pytest.mark.parametrize("operation", ["capture", "validate", "restore"])
def test_filesystem_denial_surfaces_a_preservation_error_without_losing_bytes(
    workspace: Path,
    retained_report: RecoveryReport,
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = workspace / REPORT_NAME
    retained = Path(retained_report.retained_path)
    if operation == "capture":
        retained.unlink()
        denied = source
    elif operation == "validate":
        denied = retained
    else:
        source.unlink()
        denied = source
    open_file = Path.open

    def deny_open(path: Path, mode: str) -> IO[bytes]:
        if path == denied:
            message = "The report file is locked."
            raise PermissionError(message)
        return open_file(path, mode)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", deny_open)
        with pytest.raises(ArtifactPreservationError):
            if operation == "capture":
                preserve_recovery_reports(workspace, "report-run", "attempt", (REPORT_NAME,))
            elif operation == "validate":
                validate_recovery_reports((retained_report,))
            else:
                restore_recovery_reports(workspace, (retained_report,))
    assert (source if operation == "capture" else retained).read_bytes() == REPORT_BYTES

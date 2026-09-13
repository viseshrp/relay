"""Preserve commit, diff, untracked, and declared evidence before cleanup."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from relay.errors import ArtifactPreservationError, GitError, PathSafetyError
from relay.paths import artifacts_dir, ensure_private_dir, safe_resolve

from .commits import commits_between, current_head
from .git import run_git, run_git_bytes, run_git_to_file
from .worktree import reset_worktree

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_COPY_CHUNK_BYTES = 1024 * 1024
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreservedArtifact:
    """One retained file and its integrity metadata."""

    name: str
    source_path: str
    retained_path: str
    sha256: str
    bytes: int
    media_type: str
    kind: str


@dataclass(frozen=True, slots=True)
class PreservationResult:
    """Atomic evidence directory and all files recorded in its manifest."""

    directory: Path
    retained_ref: str
    starting_head: str
    ending_head: str
    files: tuple[PreservedArtifact, ...]


def _component(value: str, label: str) -> str:
    if _COMPONENT.fullmatch(value) is None or value in {".", ".."}:
        message = f"The {label} is not safe for retained evidence."
        raise ArtifactPreservationError(message)
    return value


def retained_attempt_ref(run_id: str, attempt_id: str) -> str:
    """Transform run `abc` attempt `12` into `refs/relay/attempts/abc/12`."""
    safe_run = _component(run_id, "run id")
    safe_attempt = _component(attempt_id, "attempt id")
    return f"refs/relay/attempts/{safe_run}/{safe_attempt}"


def _hash_file(path: Path) -> tuple[str, int]:
    digest = sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_COPY_CHUNK_BYTES):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def _copy_file(source: Path, destination: Path) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        while chunk := input_stream.read(_COPY_CHUNK_BYTES):
            output_stream.write(chunk)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    return _hash_file(destination)


def _write_text(destination: Path, content: str) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return _hash_file(destination)


def _record(
    *,
    name: str,
    source: str,
    retained: Path,
    digest: str,
    size: int,
    kind: str,
) -> PreservedArtifact:
    media_type = mimetypes.guess_type(retained.name)[0] or "application/octet-stream"
    return PreservedArtifact(name, source, str(retained), digest, size, media_type, kind)


def _preserve_diff(worktree: Path, staging: Path) -> PreservedArtifact:
    destination = staging / "diff.patch"
    with destination.open("xb") as stream:
        run_git_to_file(worktree, ["diff", "--binary", "HEAD", "--"], stream)
        stream.flush()
        os.fsync(stream.fileno())
    digest, size = _hash_file(destination)
    return _record(
        name="worktree_diff",
        source="git diff --binary HEAD --",
        retained=destination,
        digest=digest,
        size=size,
        kind="diff",
    )


def _untracked_paths(worktree: Path) -> tuple[Path, ...]:
    result = run_git_bytes(
        worktree,
        ["ls-files", "--others", "--exclude-standard", "-z"],
    )
    paths: list[Path] = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(os.fsdecode(raw_path))
        if relative.is_absolute() or ".." in relative.parts:
            message = "Git returned an unsafe untracked path during evidence preservation."
            raise ArtifactPreservationError(message)
        paths.append(relative)
    return tuple(paths)


def _preserve_untracked(worktree: Path, staging: Path) -> list[PreservedArtifact]:
    records: list[PreservedArtifact] = []
    for relative in _untracked_paths(worktree):
        source = worktree / relative
        try:
            mode = source.lstat().st_mode
        except OSError:
            message = f"Untracked evidence {relative.as_posix()!r} disappeared before copying."
            raise ArtifactPreservationError(message) from None
        if stat.S_ISLNK(mode):
            destination = staging / "untracked-symlinks" / relative
            target = os.readlink(source)
            digest, size = _write_text(destination, target)
            kind = "untracked_symlink_target"
        elif stat.S_ISREG(mode):
            destination = staging / "untracked" / relative
            digest, size = _copy_file(source, destination)
            kind = "untracked"
        else:
            message = f"Untracked evidence {relative.as_posix()!r} is not a regular file."
            raise ArtifactPreservationError(message)
        records.append(
            _record(
                name=relative.as_posix(),
                source=str(source),
                retained=destination,
                digest=digest,
                size=size,
                kind=kind,
            )
        )
    return records


def _preserve_declared(
    worktree: Path,
    staging: Path,
    declared: dict[str, str],
) -> list[PreservedArtifact]:
    records: list[PreservedArtifact] = []
    for name, reference in declared.items():
        safe_name = _component(name, "artifact name")
        try:
            source = safe_resolve(worktree, reference)
        except PathSafetyError:
            message = f"Declared artifact {reference!r} escapes the attempt worktree."
            raise ArtifactPreservationError(message) from None
        if not source.is_file():
            message = f"Declared artifact {reference!r} does not exist."
            raise ArtifactPreservationError(message)
        destination = staging / "declared" / safe_name
        try:
            digest, size = _copy_file(source, destination)
        except OSError:
            message = f"Declared artifact {reference!r} could not be preserved."
            raise ArtifactPreservationError(message) from None
        records.append(
            _record(
                name=name,
                source=str(source),
                retained=destination,
                digest=digest,
                size=size,
                kind="declared",
            )
        )
    return records


def _preserve_commits(
    worktree: Path,
    staging: Path,
    starting_head: str,
    ending_head: str,
) -> PreservedArtifact:
    commits = commits_between(worktree, starting_head, ending_head)
    destination = staging / "commits.txt"
    content = "\n".join(commits) + ("\n" if commits else "")
    digest, size = _write_text(destination, content)
    return _record(
        name="commits",
        source=f"{starting_head}..{ending_head}",
        retained=destination,
        digest=digest,
        size=size,
        kind="commits",
    )


def _write_manifest(
    staging: Path,
    *,
    run_id: str,
    attempt_id: str,
    reference: str,
    starting_head: str,
    ending_head: str,
    files: list[PreservedArtifact],
) -> None:
    manifest = {
        "version": 1,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "retained_ref": reference,
        "starting_head": starting_head,
        "ending_head": ending_head,
        "files": [asdict(item) for item in files],
    }
    destination = staging / "manifest.json"
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _require_new_ref(repository: Path, reference: str) -> None:
    existing_ref = run_git(
        repository,
        ["show-ref", "--verify", "--quiet", reference],
        check=False,
    )
    if existing_ref.returncode == 0:
        message = f"Retained attempt ref {reference} already exists."
        raise ArtifactPreservationError(message)
    if existing_ref.returncode != 1:
        message = "Git could not check the retained attempt namespace."
        raise ArtifactPreservationError(message)


def preserve_attempt_evidence(
    repository: Path,
    worktree: Path,
    run_id: str,
    attempt_id: str,
    starting_head: str,
    *,
    declared_artifacts: dict[str, str] | None = None,
    root: Path | None = None,
) -> PreservationResult:
    """Atomically retain every recoverable attempt byte before reset or removal."""
    safe_run = _component(run_id, "run id")
    safe_attempt = _component(attempt_id, "attempt id")
    base = ensure_private_dir(root) if root is not None else artifacts_dir(create=True)
    run_directory = ensure_private_dir(base / safe_run)
    target = run_directory / safe_attempt
    if target.exists():
        message = f"Attempt evidence already exists at {target}."
        raise ArtifactPreservationError(message)

    ending_head = current_head(worktree)
    reference = retained_attempt_ref(safe_run, safe_attempt)
    try:
        # Preserve partial commits first; the ref survives even if a later copy fails.
        _require_new_ref(repository, reference)
        run_git(repository, ["update-ref", reference, ending_head])
        staging = Path(tempfile.mkdtemp(prefix=f".{safe_attempt}-", dir=run_directory))
        files = [_preserve_commits(worktree, staging, starting_head, ending_head)]
        files.append(_preserve_diff(worktree, staging))
        files.extend(_preserve_untracked(worktree, staging))
        files.extend(_preserve_declared(worktree, staging, declared_artifacts or {}))
        final_files = [
            replace(
                item,
                retained_path=str(target / Path(item.retained_path).relative_to(staging)),
            )
            for item in files
        ]
        _write_manifest(
            staging,
            run_id=safe_run,
            attempt_id=safe_attempt,
            reference=reference,
            starting_head=starting_head,
            ending_head=ending_head,
            files=final_files,
        )
        staging.replace(target)
        if os.name != "nt":
            descriptor = os.open(run_directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except (ArtifactPreservationError, GitError, OSError):
        LOGGER.exception(
            "Attempt evidence preservation failed",
            extra={"run_id": safe_run, "attempt_id": safe_attempt},
        )
        if "staging" in locals() and staging.exists():
            shutil.rmtree(staging)
        message = "Relay could not preserve all attempt evidence."
        raise ArtifactPreservationError(
            message,
            context={"project": str(repository)},
            next_action="Do not reset or remove the worktree; inspect the retained ref and logs.",
        ) from None
    return PreservationResult(
        target,
        reference,
        starting_head,
        ending_head,
        tuple(final_files),
    )


def preserve_then_reset(
    repository: Path,
    worktree: Path,
    run_id: str,
    attempt_id: str,
    starting_head: str,
    *,
    protected_head: str,
    declared_artifacts: dict[str, str] | None = None,
    root: Path | None = None,
) -> PreservationResult:
    """Enforce evidence-before-reset ordering for rerun and resume."""
    result = preserve_attempt_evidence(
        repository,
        worktree,
        run_id,
        attempt_id,
        starting_head,
        declared_artifacts=declared_artifacts,
        root=root,
    )
    # A reset failure propagates while the successfully retained evidence remains intact.
    reset_worktree(worktree, starting_head, protected_head=protected_head)
    return result


__all__ = [
    "PreservationResult",
    "PreservedArtifact",
    "preserve_attempt_evidence",
    "preserve_then_reset",
    "retained_attempt_ref",
]

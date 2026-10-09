"""Bounded archives of verified retained bytes, never of live worktrees."""

from __future__ import annotations

from hashlib import sha256
from pathlib import PurePath
import re
from tempfile import SpooledTemporaryFile
from typing import NoReturn, cast
from zipfile import ZIP_DEFLATED, ZipFile

from relay.errors import ConfigError

from .models import Artifact
from .repositories import DjangoReadStore

MAX_ARCHIVE_FILES = 1000
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


def _reject(message: str) -> NoReturn:
    raise ConfigError(message)


def run_artifact_archive(run_id: str) -> SpooledTemporaryFile[bytes]:
    """Return a spooled ZIP after every retained file passes its recorded digest."""
    store = DjangoReadStore()
    # Also distinguishes an empty existing run from an unknown run.
    store.page_artifacts(run_id, 0, 1)
    rows = list(
        Artifact.objects.filter(attempt__node_run__run_id=run_id)
        .select_related("attempt__node_run")
        .order_by("pk")[: MAX_ARCHIVE_FILES + 1]
    )
    if (
        len(rows) > MAX_ARCHIVE_FILES
        or sum(cast(int, row.bytes) for row in rows) > MAX_ARCHIVE_BYTES
    ):
        _reject("This run exceeds the archive limit. Download its artifacts separately.")
    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")  # noqa: SIM115 - FileResponse owns the stream
    total = 0
    try:
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for row in rows:
                path, name, _media = store.artifact_file(str(row.pk))
                basename = PurePath(name.replace("\\", "/")).name
                basename = re.sub(r"[^\w. -]", "_", basename)[:160] or "artifact"
                scope = re.sub(r"[^\w.-]", "_", str(row.attempt.node_run.scope_path))[:160]
                member = f"{scope}/attempt-{row.attempt.attempt_number}/{row.pk}-{basename}"
                digest = sha256()
                size = 0
                with path.open("rb") as source, archive.open(member, "w") as destination:
                    while block := source.read(64 * 1024):
                        size += len(block)
                        total += len(block)
                        if total > MAX_ARCHIVE_BYTES:
                            _reject("The retained files exceed the archive size limit.")
                        digest.update(block)
                        destination.write(block)
                if size != row.bytes or digest.hexdigest() != row.sha256:
                    _reject("A retained artifact no longer matches its recorded bytes.")
    except OSError:
        output.close()
        _reject("The retained artifact could not be read.")
    except Exception:
        output.close()
        raise
    else:
        output.seek(0)
        return output

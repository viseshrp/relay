"""Deterministic MIME types independent of host registries and MIME files."""

import mimetypes
from pathlib import Path

_MIME_TYPES: mimetypes.MimeTypes = mimetypes.MimeTypes()


def media_type_for(path: Path) -> str:
    """A file `report.txt` becomes `text/plain`; unknown extensions use binary."""
    media_type, _encoding = _MIME_TYPES.guess_type(path.resolve().as_uri())
    return media_type or "application/octet-stream"

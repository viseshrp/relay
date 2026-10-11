"""Read exact UTF-8 source bytes while exposing normalized editor text."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from relay.errors import WorkflowValidationError


@dataclass(frozen=True, slots=True)
class SourceText:
    raw_text: str
    base_hash: str

    @property
    def text(self) -> str:
        return self.raw_text.replace("\r\n", "\n").replace("\r", "\n")

    def replacement(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return normalized.replace("\n", "\r\n") if "\r\n" in self.raw_text else normalized


def read_source(path: Path, *, max_bytes: int | None = None) -> SourceText:
    """Hash disk bytes before newline normalization; optionally bound editor reads."""
    with path.open("rb") as stream:
        raw = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
    if max_bytes is not None and len(raw) > max_bytes:
        message = "A source file exceeds the editor's size limit."
        raise WorkflowValidationError(message)
    return SourceText(raw.decode("utf-8"), sha256(raw).hexdigest())

"""Shared parsing, context, output, and event helpers for node executors."""

from __future__ import annotations

import codecs
from collections.abc import Iterator
from typing import IO, TypeVar

from pydantic import ValidationError

from relay.errors import NodeExecutionError
from relay.execution.runner import AttemptContext
from relay.execution.state import EventSource
from relay.workflows.schema import NodeBase

NodeT = TypeVar("NodeT", bound=NodeBase)
_OUTPUT_READ_BYTES = 8_192


def parse_node(context: AttemptContext, expected: type[NodeT]) -> NodeT:
    """Validate an executor's operation arguments before starting its process."""
    try:
        return expected.model_validate(dict(context.attempt.frozen_def))
    except ValidationError:
        message = "The frozen operation definition is invalid."
        raise NodeExecutionError(message, context={"node": context.attempt.scope_path}) from None


def decoded_chunks(stream: IO[bytes]) -> Iterator[str]:
    """Decode every output byte in bounded chunks, escaping malformed UTF-8."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="backslashreplace")
    while data := stream.read(_OUTPUT_READ_BYTES):
        text = decoder.decode(data)
        if text:
            yield text
    tail = decoder.decode(b"", final=True)
    if tail:
        yield tail


def emit_output_stream(context: AttemptContext, stream: IO[bytes], event_type: str) -> None:
    """Persist a complete command stream as bounded ordered event chunks."""
    stream.seek(0)
    for chunk in decoded_chunks(stream):
        context.runtime.append_attempt_event(
            context.attempt.attempt_id,
            event_type,
            EventSource.COMMAND,
            {"chunk": chunk},
        )


__all__ = ["decoded_chunks", "emit_output_stream", "parse_node"]

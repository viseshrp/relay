"""Render structured diagnostic context and mark the log files Relay creates."""

from io import TextIOWrapper
import json
import logging
import logging.handlers
import os

from relay.constants import APPLICATION_LOG_OWNERSHIP_LINE

_STANDARD_FIELDS: frozenset[str] = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


class ContextFormatter(logging.Formatter):
    """Include extra fields: path `a\nb` is rendered as JSON `"a\\nb"`."""

    def format(self, record: logging.LogRecord) -> str:
        context = {
            key: value for key, value in record.__dict__.items() if key not in _STANDARD_FIELDS
        }
        output = super().format(record)
        if not context:
            return output
        encoded = json.dumps(context, ensure_ascii=True, sort_keys=True, default=str)
        return f"{output} context={encoded}"


class OwnedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Start each new or rolled-over file with Relay's ownership line.

    Retention and data cleanup change only files that begin with this line, so a
    shared `RELAY_LOG_PATH` directory keeps other programs' files intact. A
    rotation is a rename, so `relay-42.log.1` keeps the line it was created with.
    """

    def _open(self) -> TextIOWrapper:
        stream = super()._open()
        if os.fstat(stream.fileno()).st_size == 0:
            # Text mode ends the line with LF on Linux and CRLF on Windows.
            stream.write(f"{APPLICATION_LOG_OWNERSHIP_LINE}\n")
            stream.flush()
        return stream

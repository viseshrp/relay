"""Render structured diagnostic context without permitting forged log lines."""

import json
import logging

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

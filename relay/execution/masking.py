"""Secret redaction before public persistence, including split stream chunks."""

from __future__ import annotations

from collections.abc import Mapping
import threading

from relay.errors import NodeExecutionError


class Redactor:
    values: set[str]
    pending: dict[str, str]
    lock: threading.RLock

    def __init__(self) -> None:
        self.values = set()
        self.pending = {}
        self.lock = threading.RLock()

    def register(self, value: str) -> None:
        if not value:
            return
        with self.lock:
            if len(value) > 65_536 or (len(self.values) >= 2000 and value not in self.values):
                message = "Secret masking exceeds the resource limit."
                raise NodeExecutionError(message)
            self.values.add(value)

    def contains(self, value: str) -> bool:
        return any(secret in value for secret in self.values)

    def text(self, value: str) -> str:
        with self.lock:
            for secret in sorted(self.values, key=len, reverse=True):
                value = value.replace(secret, "***")
            return value

    def payload(self, value: object) -> object:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {self.text(str(key)): self.payload(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.payload(item) for item in value]
        return value

    def stream(self, key: str, chunk: str, *, final: bool = False) -> str:
        """Hold only a possible suffix of a secret; emit safe prefixes immediately."""
        with self.lock:
            value = self.pending.pop(key, "") + chunk
            value = self.text(value)
            if not final:
                hold = 0
                for secret in self.values:
                    for length in range(min(len(value), len(secret) - 1), 0, -1):
                        if value.endswith(secret[:length]):
                            hold = max(hold, length)
                            break
                if hold:
                    self.pending[key] = value[-hold:]
                    value = value[:-hold]
            return self.text(value)


_REDACTORS: dict[str, Redactor] = {}
_GUARD = threading.Lock()


def redactor(run_id: str) -> Redactor:
    with _GUARD:
        return _REDACTORS.setdefault(run_id, Redactor())


def release_redactor(run_id: str) -> None:
    with _GUARD:
        _REDACTORS.pop(run_id, None)

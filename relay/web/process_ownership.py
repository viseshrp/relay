"""Durable ownership of supervisor children, retained across an abrupt parent exit."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass, field
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid

from relay.constants import (
    EVENT_MAX_PAYLOAD_BYTES,
    PROCESS_EXIT_GRACE_SECONDS,
    PROCESS_EXIT_POLL_SECONDS,
    PROCESS_IDENTITY_MAX_CHARS,
    SHUTDOWN_TIMEOUT_SECONDS,
)
from relay.errors import ConfigError, PersistenceError
from relay.execution.cancellation import signal_process_tree
from relay.execution.process_identity import ProcessIdentity, process_identity
from relay.paths import data_dir

_VERSION = 1
_CHILD_ROLES = frozenset({"web", "worker"})
LOGGER = logging.getLogger(__name__)


def ownership_path() -> Path:
    return data_dir() / "supervisor-processes.json"


@dataclass(frozen=True, slots=True)
class ChildOwnership:
    role: str
    identity: ProcessIdentity


@dataclass
class SupervisorOwnership:
    instance_id: str
    owner: ProcessIdentity
    children: list[ChildOwnership] = field(default_factory=list)

    @classmethod
    def current(cls, instance_id: str) -> SupervisorOwnership:
        identity = process_identity(os.getpid())
        if identity is None:
            message = "Relay could not record its own supervisor identity."
            raise PersistenceError(message)
        return cls(instance_id, identity)

    def record_child(self, role: str, pid: int) -> None:
        identity = process_identity(pid)
        if identity is None:
            message = "Relay's child exited before its ownership could be recorded."
            raise PersistenceError(message)
        self.children.append(ChildOwnership(role, identity))
        self.save()

    def save(self) -> None:
        path = ownership_path()
        if path.is_symlink():
            message = "Relay's supervisor ownership record was replaced by a link."
            raise PersistenceError(message)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(
                    {
                        "version": _VERSION,
                        "instance_id": self.instance_id,
                        "host": socket.gethostname(),
                        "owner": asdict(self.owner),
                        "children": [asdict(child) for child in self.children],
                    },
                    stream,
                )
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        except OSError:
            message = "Relay could not persist its supervisor child ownership."
            raise PersistenceError(message) from None
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def clear(self) -> None:
        """Remove only our exact record, after all of its children have exited."""
        current = read_ownership()
        if (
            current is not None
            and current.instance_id == self.instance_id
            and current.owner == self.owner
            and not any(
                process_identity(child.identity.pid) == child.identity for child in current.children
            )
        ):
            ownership_path().unlink(missing_ok=True)


def _identity(value: object) -> ProcessIdentity:
    if isinstance(value, dict):
        pid, started = value.get("pid"), value.get("started")
        if (
            isinstance(pid, int)
            and not isinstance(pid, bool)
            and pid > 1
            and isinstance(started, str)
            and 0 < len(started) <= PROCESS_IDENTITY_MAX_CHARS
        ):
            return ProcessIdentity(pid, started)
    message = "Relay's supervisor ownership record has an invalid process identity."
    raise PersistenceError(message)


def read_ownership() -> SupervisorOwnership | None:
    path = ownership_path()
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink():
            message = "Relay's supervisor ownership record was replaced by a link."
            raise PersistenceError(message)
        with path.open(encoding="utf-8") as stream:
            raw = json.loads(stream.read(EVENT_MAX_PAYLOAD_BYTES))
        if (
            not isinstance(raw, dict)
            or raw.get("version") != _VERSION
            or raw.get("host") != socket.gethostname()
        ):
            message = "Relay cannot verify the host of its supervisor ownership record."
            raise PersistenceError(message)
        if not isinstance(raw.get("instance_id"), str):
            message = "Relay's supervisor ownership has an invalid instance identifier."
            raise PersistenceError(message)
        instance_id = str(uuid.UUID(raw["instance_id"]))
        owner = _identity(raw.get("owner"))
        children = raw.get("children")
        if not isinstance(children, list) or len(children) > len(_CHILD_ROLES):
            message = "Relay's supervisor child ownership list is invalid."
            raise PersistenceError(message)
        records = []
        roles = set()
        for child in children:
            if (
                not isinstance(child, dict)
                or child.get("role") not in _CHILD_ROLES
                or child["role"] in roles
            ):
                message = "Relay's supervisor child role is invalid."
                raise PersistenceError(message)
            identity = _identity(child.get("identity"))
            if identity.pid == owner.pid or any(
                record.identity.pid == identity.pid for record in records
            ):
                message = "Relay's supervisor ownership contains a repeated process."
                raise PersistenceError(message)
            records.append(ChildOwnership(child["role"], identity))
            roles.add(child["role"])
        return SupervisorOwnership(instance_id, owner, records)
    except (OSError, ValueError, KeyError, TypeError):
        message = "Relay could not read its supervisor child ownership record."
        raise PersistenceError(message) from None


def abandoned_ownership() -> SupervisorOwnership | None:
    """A matching live supervisor always wins, even if its heartbeat is old."""
    record = read_ownership()
    if record is not None and process_identity(record.owner.pid) == record.owner:
        message = "Relay's recorded supervisor is still running."
        raise ConfigError(message, next_action="Use its existing web app or stop it normally.")
    return record


def stop_owned_children(record: SupervisorOwnership) -> None:
    """Stop only children whose birth still matches; recheck before escalation."""
    identities = [child.identity for child in record.children]
    for identity in identities:
        if process_identity(identity.pid) == identity:
            try:
                signal_process_tree(identity.pid, graceful_signal=signal.SIGINT)
            except OSError:
                # Windows console breaks can fail for detached children. The
                # bounded escalation below rechecks ownership before taskkill.
                LOGGER.warning("Abandoned child did not accept a graceful stop", exc_info=True)
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        remaining = [
            identity for identity in identities if process_identity(identity.pid) == identity
        ]
        if not remaining:
            return
        threading.Event().wait(PROCESS_EXIT_POLL_SECONDS)
    for identity in identities:
        if process_identity(identity.pid) == identity:
            try:
                signal_process_tree(identity.pid, force=True)
            except (OSError, subprocess.SubprocessError):
                message = "Relay could not stop its verified abandoned child."
                raise PersistenceError(message) from None
    deadline = time.monotonic() + PROCESS_EXIT_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not any(process_identity(identity.pid) == identity for identity in identities):
            return
        threading.Event().wait(PROCESS_EXIT_POLL_SECONDS)
    message = "Relay could not stop its abandoned children within the shutdown deadline."
    raise PersistenceError(message)

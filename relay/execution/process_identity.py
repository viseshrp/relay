"""OS creation identities used before signaling a previously recorded process."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import subprocess
import sys
from typing import ClassVar

from relay.constants import (
    WINDOWS_ERROR_INVALID_PARAMETER,
    WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION,
    WINDOWS_PROCESS_STILL_ACTIVE,
)
from relay.errors import PersistenceError

_PROC_PIDTBSDINFO = 3
_BSD_ZOMBIE = 5
_SNAP_PROCESS = 2


class WindowsProcessEntry(ctypes.Structure):
    """PROCESSENTRY32W used to observe descendants before closing their job."""

    pid: int
    parent_pid: int
    size: int
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("size", ctypes.c_uint32),
        ("usage", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("heap", ctypes.c_size_t),
        ("module", ctypes.c_uint32),
        ("threads", ctypes.c_uint32),
        ("parent_pid", ctypes.c_uint32),
        ("priority", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
        ("executable", ctypes.c_wchar * 260),
    ]


def _windows_descendants(root: ProcessIdentity) -> tuple[ProcessIdentity, ...]:
    from ctypes import WinDLL, wintypes

    kernel = WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = (wintypes.HANDLE, ctypes.POINTER(WindowsProcessEntry))
        function.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(_SNAP_PROCESS, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        message = "Relay could not enumerate its Windows process tree."
        raise PersistenceError(message)
    try:
        entry = WindowsProcessEntry()
        entry.size = ctypes.sizeof(entry)
        parents: dict[int, int] = {}
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            parents[entry.pid] = entry.parent_pid
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        descendants = {root.pid}
        while True:
            added = {pid for pid, parent in parents.items() if parent in descendants}
            if added <= descendants:
                break
            descendants.update(added)
        return tuple(
            identity
            for pid in descendants
            if (identity := process_identity(pid)) is not None
            and int(identity.started.split(":")[1]) >= int(root.started.split(":")[1])
        )
    finally:
        kernel.CloseHandle(snapshot)


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """A PID alone is insufficient; creation identifies its current occupant."""

    pid: int
    started: str


class BsdProcessInfo(ctypes.Structure):
    """The fixed-width PROC_PIDTBSDINFO layout from Apple's proc_info.h."""

    header: ctypes.Array[ctypes.c_uint32]
    command: bytes
    name: bytes
    scheduling: ctypes.Array[ctypes.c_uint32]
    start_seconds: int
    start_microseconds: int
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("header", ctypes.c_uint32 * 12),
        ("command", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("scheduling", ctypes.c_uint32 * 6),
        ("start_seconds", ctypes.c_uint64),
        ("start_microseconds", ctypes.c_uint64),
    ]


def _windows_identity(pid: int) -> ProcessIdentity | None:
    if os.name != "nt":
        return None
    from ctypes import WinDLL, get_last_error, wintypes

    kernel = WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(WINDOWS_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        if get_last_error() == WINDOWS_ERROR_INVALID_PARAMETER:
            return None
        message = "Relay could not verify a recorded process's creation time."
        raise PersistenceError(message)
    try:
        status = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(status)):
            message = "Relay could not verify whether a recorded process has exited."
            raise PersistenceError(message)
        if status.value != WINDOWS_PROCESS_STILL_ACTIVE:
            return None
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(system),
            ctypes.byref(user),
        ):
            message = "Relay could not read a recorded process's creation time."
            raise PersistenceError(message)
        timestamp = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return ProcessIdentity(pid, f"windows:{timestamp}")
    finally:
        kernel.CloseHandle(handle)


def _darwin_identity(pid: int) -> ProcessIdentity | None:
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pidinfo.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    library.proc_pidinfo.restype = ctypes.c_int
    info = BsdProcessInfo()
    count = library.proc_pidinfo(pid, _PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    if count == 0 and ctypes.get_errno() == errno.ESRCH:
        return None
    if count != ctypes.sizeof(info):
        message = "Relay could not verify a recorded process's creation time."
        raise PersistenceError(message)
    if info.header[1] == _BSD_ZOMBIE:
        return None
    return ProcessIdentity(pid, f"darwin:{info.start_seconds}:{info.start_microseconds}")


def process_identity(pid: int) -> ProcessIdentity | None:
    """Return the current creation token, None for exit, or fail closed on uncertainty."""
    maximum = (1 << (32 if os.name == "nt" else 31)) - 1
    if isinstance(pid, bool) or not 1 < pid <= maximum:
        message = "Relay refused an unsafe process identifier."
        raise PersistenceError(message)
    try:
        if os.name == "nt":
            return _windows_identity(pid)
        if sys.platform == "darwin":
            return _darwin_identity(pid)
        # The comm field may contain spaces or ')'. Split after its final ')',
        # so `123 (a ) b) S ...` still starts the numeric fields at state S.
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat.rsplit(")", 1)[1].split()
        if fields[0] in {"Z", "X"}:
            return None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        return ProcessIdentity(pid, f"linux:{boot}:{fields[19]}")
    except FileNotFoundError:
        return None
    except (OSError, ValueError, IndexError):
        message = "Relay could not verify a recorded process's creation time."
        raise PersistenceError(message) from None


def process_group_members(group_id: int) -> tuple[ProcessIdentity, ...]:
    """Observe a POSIX group, including children left behind by an exited leader."""
    if os.name == "nt":
        # Attempt launchers use a kill-on-close Windows Job Object. Their exit
        # closes its non-inheritable handle and terminates the contained tree.
        identity = process_identity(group_id)
        return _windows_descendants(identity) if identity is not None else ()
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,pgid="],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        members = []
        for line in result.stdout.splitlines():
            pid, group = map(int, line.split())
            if group == group_id and pid > 1:
                identity = process_identity(pid)
                if identity is not None:
                    members.append(identity)
        return tuple(members)
    except (OSError, ValueError, subprocess.SubprocessError):
        message = "Relay could not verify whether an owned process group has exited."
        raise PersistenceError(message) from None

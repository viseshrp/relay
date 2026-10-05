"""OS creation identities used before signaling a previously recorded process."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import os
from pathlib import Path
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

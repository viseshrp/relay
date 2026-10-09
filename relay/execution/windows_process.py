"""Keep a Windows attempt and its descendants in a job owned by this launcher.

The launcher joins the job before starting the target, so even an immediately
spawned child is contained. Windows closes the launcher's non-inheritable job
handle on exit and stops surviving descendants, including on a worker crash.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from typing import ClassVar

from relay.constants import EXIT_RELAY_ERROR

_JOB_EXTENDED_LIMIT_INFORMATION = 9
_JOB_KILL_ON_CLOSE = 0x2000


class BasicLimits(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_uint32),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority", ctypes.c_uint32),
        ("scheduling", ctypes.c_uint32),
    ]
    flags: int
    process_time: int
    job_time: int
    minimum_working_set: int
    maximum_working_set: int
    active_process_limit: int
    affinity: int
    priority: int
    scheduling: int


class IoCounters(ctypes.Structure):
    read_operations: int
    write_operations: int
    other_operations: int
    read_bytes: int
    write_bytes: int
    other_bytes: int
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("read_operations", ctypes.c_uint64),
        ("write_operations", ctypes.c_uint64),
        ("other_operations", ctypes.c_uint64),
        ("read_bytes", ctypes.c_uint64),
        ("write_bytes", ctypes.c_uint64),
        ("other_bytes", ctypes.c_uint64),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("basic", BasicLimits),
        ("io", IoCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]
    basic: BasicLimits
    io: IoCounters
    process_memory: int
    job_memory: int
    peak_process_memory: int
    peak_job_memory: int


def run_owned_command(arguments: list[str]) -> int:
    """Join an unnamed kill-on-close job, then run the target with inherited stdio."""
    if os.name != "nt" or not arguments:
        return EXIT_RELAY_ERROR
    from ctypes import WinDLL

    kernel = WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel.CreateJobObjectW.restype = ctypes.c_void_p
    kernel.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel.SetInformationJobObject.restype = ctypes.c_int
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.AssignProcessToJobObject.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = _JOB_KILL_ON_CLOSE
    if not job:
        return EXIT_RELAY_ERROR
    if not kernel.SetInformationJobObject(
        job, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
    ) or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        return EXIT_RELAY_ERROR
    # Keep the job handle open until ExitProcess; closing it here would also
    # terminate this launcher before its target's exit code can be returned.
    try:
        # CreateProcess searches the launcher's application directory before
        # PATH. Resolve here, after inheriting the attempt's environment and
        # working directory, so a workflow-selected executable takes priority.
        executable = shutil.which(arguments[0])
        if executable is None:
            return EXIT_RELAY_ERROR
        return subprocess.call(  # noqa: S603
            [os.path.abspath(executable), *arguments[1:]], shell=False
        )
    except (OSError, KeyboardInterrupt):
        return EXIT_RELAY_ERROR


if __name__ == "__main__":
    sys.exit(run_owned_command(sys.argv[1:]))

"""Retain owner access to private Windows storage."""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys
from typing import ClassVar

_OWNER_SECURITY_INFORMATION = 1
_DACL_SECURITY_INFORMATION = 4
_SE_FILE_OBJECT = 1
_FILE_ALL_ACCESS = 0x1F01FF
_INHERIT_CHILDREN = 3


class _Trustee(ctypes.Structure):
    sid: int | None
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("multiple", ctypes.c_void_p),
        ("operation", ctypes.c_int),
        ("form", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("sid", ctypes.c_void_p),
    ]


class _ExplicitAccess(ctypes.Structure):
    permissions: int
    mode: int
    inheritance: int
    trustee: _Trustee
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("permissions", ctypes.c_uint32),
        ("mode", ctypes.c_int),
        ("inheritance", ctypes.c_uint32),
        ("trustee", _Trustee),
    ]


class _AclSize(ctypes.Structure):
    count: int
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("count", ctypes.c_uint32),
        ("used", ctypes.c_uint32),
        ("free", ctypes.c_uint32),
    ]


class _AllowedAce(ctypes.Structure):
    kind: int
    flags: int
    permissions: int
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("kind", ctypes.c_ubyte),
        ("flags", ctypes.c_ubyte),
        ("size", ctypes.c_uint16),
        ("permissions", ctypes.c_uint32),
    ]


def _owner_grant(sid: int) -> _ExplicitAccess:
    entry = _ExplicitAccess()
    entry.permissions = _FILE_ALL_ACCESS
    entry.mode = 1  # GRANT_ACCESS merges grants without replacing other trustees.
    entry.inheritance = _INHERIT_CHILDREN
    entry.trustee.sid = sid
    return entry


def ensure_private_directory_acl(path: Path) -> None:
    """Preserve existing ACL entries and add inheritable access for the directory owner."""
    if sys.platform != "win32":
        message = "Windows directory ACLs require Windows."
        raise OSError(message)
    import ctypes.wintypes as wintypes

    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    output_pointer = ctypes.POINTER(pointer)
    security.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        output_pointer,
        output_pointer,
        output_pointer,
        output_pointer,
        output_pointer,
    )
    security.GetNamedSecurityInfoW.restype = wintypes.DWORD
    security.GetAclInformation.argtypes = (pointer, pointer, wintypes.DWORD, ctypes.c_int)
    security.GetAclInformation.restype = wintypes.BOOL
    security.GetAce.argtypes = (pointer, wintypes.DWORD, output_pointer)
    security.GetAce.restype = wintypes.BOOL
    security.EqualSid.argtypes = (pointer, pointer)
    security.EqualSid.restype = wintypes.BOOL
    security.SetEntriesInAclW.argtypes = (
        wintypes.ULONG,
        ctypes.POINTER(_ExplicitAccess),
        pointer,
        output_pointer,
    )
    security.SetEntriesInAclW.restype = wintypes.DWORD
    security.SetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        pointer,
        pointer,
        pointer,
        pointer,
    )
    security.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = (pointer,)
    kernel.LocalFree.restype = pointer
    owner = pointer()
    dacl = pointer()
    descriptor = pointer()
    updated = pointer()
    try:
        error = security.GetNamedSecurityInfoW(
            str(path),
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if error:
            raise ctypes.WinError(error)
        if not owner.value or not dacl.value:
            message = "Relay requires an owned Windows directory with an access-control list."
            raise OSError(message)
        size = _AclSize()
        if not security.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2):
            raise ctypes.WinError(ctypes.get_last_error())
        owner_inherits = False
        for index in range(size.count):
            address = pointer()
            if not security.GetAce(dacl, index, ctypes.byref(address)):
                raise ctypes.WinError(ctypes.get_last_error())
            if address.value is None:
                message = "Windows returned an empty directory access-control entry."
                raise OSError(message)
            ace = _AllowedAce.from_address(address.value)
            if ace.kind != 0:
                continue
            sid = pointer(address.value + ctypes.sizeof(_AllowedAce))
            if security.EqualSid(owner, sid):
                owner_inherits |= (
                    ace.flags & _INHERIT_CHILDREN == _INHERIT_CHILDREN
                    and ace.permissions & _FILE_ALL_ACCESS == _FILE_ALL_ACCESS
                )
        if owner_inherits:
            return
        entry = _owner_grant(owner.value)
        error = security.SetEntriesInAclW(1, ctypes.byref(entry), dacl, ctypes.byref(updated))
        if error:
            raise ctypes.WinError(error)
        error = security.SetNamedSecurityInfoW(
            str(path),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            updated,
            None,
        )
        if error:
            raise ctypes.WinError(error)
    finally:
        for allocation in (updated, descriptor):
            if allocation:
                kernel.LocalFree(allocation)


__all__ = ["ensure_private_directory_acl"]

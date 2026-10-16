"""Preserve private Windows storage access across sandbox account boundaries."""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys
from typing import ClassVar

_OWNER_SECURITY_INFORMATION = 1
_DACL_SECURITY_INFORMATION = 4
_SE_FILE_OBJECT = 1
_FILE_ALL_ACCESS = 0x1F01FF
_FILE_READ_ATTRIBUTES = 0x80
_INHERIT_CHILDREN = 3
_INHERIT_ONLY = 8
_AUTHENTICATED_USERS_SID = "S-1-5-11"


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


def _grant(sid: int, permissions: int, inheritance: int) -> _ExplicitAccess:
    entry = _ExplicitAccess()
    entry.permissions = permissions
    entry.mode = 1  # GRANT_ACCESS merges grants without replacing other trustees.
    entry.inheritance = inheritance
    entry.trustee.sid = sid
    return entry


def ensure_private_directory_acl(path: Path) -> None:
    """Retain owner access and the directory attributes needed to resolve sandbox paths."""
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
    security.ConvertStringSidToSidW.argtypes = (wintypes.LPCWSTR, output_pointer)
    security.ConvertStringSidToSidW.restype = wintypes.BOOL
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
    authenticated = pointer()
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
        if not security.ConvertStringSidToSidW(
            _AUTHENTICATED_USERS_SID, ctypes.byref(authenticated)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not authenticated.value:
            message = "Windows returned an empty authenticated-account identity."
            raise OSError(message)
        size = _AclSize()
        if not security.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2):
            raise ctypes.WinError(ctypes.get_last_error())
        owner_inherits = False
        attributes_readable = False
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
            if security.EqualSid(authenticated, sid):
                attributes_readable |= (
                    not ace.flags & _INHERIT_ONLY
                    and ace.permissions & _FILE_READ_ATTRIBUTES == _FILE_READ_ATTRIBUTES
                )
        entries = []
        if not owner_inherits:
            entries.append(_grant(owner.value, _FILE_ALL_ACCESS, _INHERIT_CHILDREN))
        if not attributes_readable:
            # Node and PowerShell inspect parent directory attributes when resolving
            # a workspace. This directory-only grant permits no listing or file reads.
            entries.append(_grant(authenticated.value, _FILE_READ_ATTRIBUTES, 0))
        if not entries:
            return
        array = (_ExplicitAccess * len(entries))(*entries)
        error = security.SetEntriesInAclW(len(entries), array, dacl, ctypes.byref(updated))
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
        for allocation in (updated, descriptor, authenticated):
            if allocation:
                kernel.LocalFree(allocation)


__all__ = ["ensure_private_directory_acl"]

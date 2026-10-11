"""Bound rendered display titles without splitting Unicode grapheme clusters."""

from __future__ import annotations

import unicodedata


def _hangul(character: str) -> str:
    value = ord(character)
    if 0x1100 <= value <= 0x115F or 0xA960 <= value <= 0xA97C:
        return "L"
    if 0x1160 <= value <= 0x11A7 or 0xD7B0 <= value <= 0xD7C6:
        return "V"
    if 0x11A8 <= value <= 0x11FF or 0xD7CB <= value <= 0xD7FB:
        return "T"
    if 0xAC00 <= value <= 0xD7A3:
        return "LVT" if (value - 0xAC00) % 28 else "LV"
    return ""


def _extends(character: str) -> bool:
    value = ord(character)
    return (
        unicodedata.category(character) in {"Mn", "Me", "Mc"}
        or character in {"\u200c", "\u200d"}
        or 0x1F3FB <= value <= 0x1F3FF
        or 0xE0020 <= value <= 0xE007F
    )


def _prepend(character: str) -> bool:
    value = ord(character)
    return (
        0x600 <= value <= 0x605
        or 0x890 <= value <= 0x891
        or 0x111C2 <= value <= 0x111C3
        or 0x11A84 <= value <= 0x11A89
        or value
        in {
            0x6DD,
            0x70F,
            0x8E2,
            0xD4E,
            0x110BD,
            0x110CD,
            0x1193F,
            0x11941,
            0x11A3A,
            0x11D46,
            0x11F02,
        }
    )


def truncate_run_title(value: str, limit: int = 1000) -> str:
    """Leave complete titles intact; reserve one character for the truncation mark."""
    if len(value) <= limit:
        return value
    boundary = 0
    regional_count = 1 if 0x1F1E6 <= ord(value[0]) <= 0x1F1FF else 0
    linker = unicodedata.combining(value[0]) == 9
    for index in range(1, len(value)):
        previous, current = value[index - 1], value[index]
        left, right = _hangul(previous), _hangul(current)
        regional = 0x1F1E6 <= ord(current) <= 0x1F1FF
        joined = (
            (previous == "\r" and current == "\n")
            or _extends(current)
            or previous == "\u200d"
            or _prepend(previous)
            or (left == "L" and right in {"L", "V", "LV", "LVT"})
            or (left in {"LV", "V"} and right in {"V", "T"})
            or (left in {"LVT", "T"} and right == "T")
            or (regional and regional_count % 2 == 1)
            or (linker and unicodedata.category(current).startswith("L"))
        )
        if not joined:
            if index > limit - 1:
                break
            boundary = index
            linker = False
        regional_count = regional_count + 1 if regional else 0
        linker = linker or unicodedata.combining(current) == 9
    return value[:boundary] + "…"

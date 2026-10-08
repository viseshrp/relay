"""Local schedules and observation filters; no remote Git operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from relay.errors import WorkflowValidationError
from relay.workflows.actions.patterns import matches


def _field(source: str, lower: int, upper: int) -> set[int]:
    result: set[int] = set()
    for item in source.split(","):
        raw, separator, interval = item.partition("/")
        step = int(interval) if separator and interval.isdigit() else 1
        if separator and (not interval.isdigit() or step < 1):
            message = "Cron intervals must be positive integers."
            raise WorkflowValidationError(message)
        if raw == "*":
            start, end = lower, upper
        elif re.fullmatch(r"\d+-\d+", raw):
            start, end = map(int, raw.split("-"))
        elif raw.isdigit():
            start, end = int(raw), upper if separator else int(raw)
        else:
            message = "Use POSIX five-field cron syntax."
            raise WorkflowValidationError(message)
        if not lower <= start <= end <= upper:
            message = "Cron field exceeds its allowed range."
            raise WorkflowValidationError(message)
        result.update(range(start, end + 1, step))
    return result


def cron_fields(source: str) -> tuple[set[int], ...]:
    fields = source.split()
    if len(fields) != 5:
        message = "Use POSIX five-field cron syntax."
        raise WorkflowValidationError(message)
    return tuple(
        _field(item, low, high)
        for item, (low, high) in zip(
            fields, ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7)), strict=True
        )
    )


def validate_schedule(value: Mapping[str, Any]) -> None:
    fields = cron_fields(str(value.get("cron", "")))
    ordered = sorted(hour * 60 + minute for hour in fields[1] for minute in fields[0])
    if any(
        right - left < 5
        for left, right in zip(ordered, [*ordered[1:], ordered[0] + 1440], strict=True)
    ):
        message = "Schedule intervals must be at least five minutes."
        raise WorkflowValidationError(message)
    try:
        ZoneInfo(str(value.get("timezone", "UTC")))
    except ZoneInfoNotFoundError:
        message = "Schedule timezone must be a supported IANA timezone."
        raise WorkflowValidationError(message) from None


def occurrences(
    schedule: Mapping[str, Any], after: datetime, through: datetime
) -> list[tuple[str, datetime]]:
    """Wall time identities coalesce a repeated clock and advance gaps once."""
    validate_schedule(schedule)
    minutes, hours, days, months, weekdays = cron_fields(str(schedule["cron"]))
    zone = ZoneInfo(str(schedule.get("timezone", "UTC")))
    start = max(
        after.astimezone(zone).date(), (through - timedelta(days=400)).astimezone(zone).date()
    )
    finish = through.astimezone(zone).date()
    day = start
    result = []
    day_any, week_any = str(schedule["cron"]).split()[2::2]
    while day <= finish:
        weekday = (day.weekday() + 1) % 7
        selected_day = day.day in days
        selected_week = weekday in weekdays or (weekday == 0 and 7 in weekdays)
        selected = (
            (selected_day or selected_week)
            if day_any != "*" and week_any != "*"
            else selected_day and selected_week
        )
        if day.month in months and selected:
            for hour in sorted(hours):
                for minute in sorted(minutes):
                    wall = datetime(day.year, day.month, day.day, hour, minute)
                    candidate = wall.replace(tzinfo=zone, fold=0)
                    # During a gap advance to the first actual local minute.
                    for _ in range(181):
                        if candidate.astimezone(timezone.utc).astimezone(zone).replace(
                            tzinfo=None
                        ) == candidate.replace(tzinfo=None):
                            break
                        candidate += timedelta(minutes=1)
                    else:
                        message = "Schedule timezone has an unsupported clock gap."
                        raise WorkflowValidationError(message)
                    instant = candidate.astimezone(timezone.utc)
                    if after < instant <= through:
                        result.append(
                            (
                                f"{schedule['cron']}:{zone.key}:{wall.isoformat(timespec='minutes')}",
                                instant,
                            )
                        )
        day += timedelta(days=1)
    return sorted(result, key=lambda item: item[1])


def filter_ref(config: Mapping[str, Any], reference: str, paths: Sequence[str]) -> bool:
    kind = "tags" if reference.startswith("refs/tags/") else "branches"
    name = reference.removeprefix("refs/tags/").removeprefix("refs/heads/")
    if kind in config and not matches(name, config[kind]):
        return False
    if f"{kind}-ignore" in config and matches(name, config[f"{kind}-ignore"]):
        return False
    other = "branches" if kind == "tags" else "tags"
    if other in config and kind not in config and f"{kind}-ignore" not in config:
        return False
    if kind != "tags":
        if "paths" in config and not any(
            matches(path, config["paths"], file_glob=True) for path in paths
        ):
            return False
        if (
            "paths-ignore" in config
            and paths
            and all(matches(path, config["paths-ignore"], file_glob=True) for path in paths)
        ):
            return False
    return True

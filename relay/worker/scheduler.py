from __future__ import annotations

import os

import psutil


class Scheduler:
    def __init__(self, concurrency_limit: int | None = None) -> None:
        self.concurrency_limit = concurrency_limit or self._detect_concurrency_limit()

    def _detect_concurrency_limit(self) -> int:
        cpu_count = max(1, (os.cpu_count() or 1) // 2)
        available_ram_gb = max(1, int(psutil.virtual_memory().available / (1024**3)) // 4)
        return max(1, min(cpu_count, available_ram_gb, 8))

    def has_capacity(self, active_count: int) -> bool:
        return active_count < self.concurrency_limit

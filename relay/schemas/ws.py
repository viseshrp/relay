from __future__ import annotations

from pydantic import BaseModel


class SubscribeMessage(BaseModel):
    type: str
    run_id: str | None = None

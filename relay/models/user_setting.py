from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from relay.db import Base


class UserSetting(Base):
    __tablename__ = "user_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

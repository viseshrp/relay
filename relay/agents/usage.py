"""Provider-reported attempt usage kept as diagnostic data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AttemptUsage:
    """Provider-reported token and cost totals for one attempt's session.

    `None` means the provider did not report that value; it is never zero.
    Relay keeps these as diagnostics and never derives decisions from them.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    thought_tokens: int | None = None
    cached_read_tokens: int | None = None
    cached_write_tokens: int | None = None
    total_tokens: int | None = None
    cost_amount: float | None = None
    cost_currency: str | None = None

    def reported(self) -> bool:
        return any(value is not None for value in self.fields().values())

    def fields(self) -> dict[str, int | float | str | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thought_tokens": self.thought_tokens,
            "cached_read_tokens": self.cached_read_tokens,
            "cached_write_tokens": self.cached_write_tokens,
            "total_tokens": self.total_tokens,
            "cost_amount": self.cost_amount,
            "cost_currency": self.cost_currency,
        }


__all__ = ["AttemptUsage"]

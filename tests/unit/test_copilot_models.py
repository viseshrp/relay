from __future__ import annotations

import pytest

from relay.copilot.models import DEFAULT_MODEL, discover_available_models, parse_available_models


HELP_OUTPUT = """
Some unrelated intro text.

`model`:
Choose the model Relay should use.
- "gpt-5.4"
- "claude-sonnet-4.6"
- "gemini-3-pro-preview"

`theme`:
- "dark"
"""


def test_parse_available_models_reads_model_section_only() -> None:
    options = parse_available_models(HELP_OUTPUT)

    assert [option.id for option in options] == [
        "gpt-5.4",
        "claude-sonnet-4.6",
        "gemini-3-pro-preview",
    ]
    assert [option.name for option in options] == [
        "GPT-5.4",
        "Claude Sonnet 4.6",
        "Gemini 3 Pro Preview",
    ]


def test_parse_available_models_deduplicates_repeated_entries() -> None:
    options = parse_available_models(
        """
        `model`:
        - "gpt-5.4"
        - "gpt-5.4"
        - "gpt-5.4-mini"
        """
    )

    assert [option.id for option in options] == ["gpt-5.4", "gpt-5.4-mini"]


@pytest.mark.asyncio
async def test_discover_available_models_falls_back_when_command_fails(monkeypatch) -> None:
    async def fail_exec(*_args: object, **_kwargs: object) -> object:
        raise OSError("missing copilot")

    monkeypatch.setattr("relay.copilot.models.resolve_copilot_cli_path", lambda configured: configured)
    monkeypatch.setattr("relay.copilot.models.asyncio.create_subprocess_exec", fail_exec)

    options = await discover_available_models("copilot")

    assert options[0].id == DEFAULT_MODEL
    assert options[1].id == "gpt-5.4"


@pytest.mark.asyncio
async def test_discover_available_models_uses_cli_output_when_available(monkeypatch) -> None:
    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return HELP_OUTPUT.encode("utf-8"), b""

    async def fake_exec(*_args: object, **_kwargs: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr("relay.copilot.models.resolve_copilot_cli_path", lambda configured: configured)
    monkeypatch.setattr("relay.copilot.models.asyncio.create_subprocess_exec", fake_exec)

    options = await discover_available_models("copilot")

    assert options[0].id == DEFAULT_MODEL
    assert [option.id for option in options[1:]] == [
        "gpt-5.4",
        "claude-sonnet-4.6",
        "gemini-3-pro-preview",
    ]

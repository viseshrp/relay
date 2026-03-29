from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass

from relay.copilot.session import resolve_copilot_cli_path


DEFAULT_MODEL = ""
_MODEL_LINE_PATTERN = re.compile(r'^-\s+"([^"]+)"$')


@dataclass(slots=True, frozen=True)
class ModelOption:
    id: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# This fallback list exists only so the UI can stay functional if the Copilot
# CLI is temporarily unavailable during startup. The backend still rebuilds the
# preferred list from `copilot help config` on every fresh app launch.
FALLBACK_MODELS: tuple[ModelOption, ...] = (
    ModelOption(id=DEFAULT_MODEL, name="Default (Copilot default)"),
    ModelOption(id="gpt-5.4", name="GPT-5.4"),
    ModelOption(id="gpt-5.4-mini", name="GPT-5.4 Mini"),
    ModelOption(id="gpt-5.3-codex", name="GPT-5.3 Codex"),
    ModelOption(id="gpt-5.2-codex", name="GPT-5.2 Codex"),
    ModelOption(id="gpt-5.2", name="GPT-5.2"),
    ModelOption(id="gpt-5.1-codex-max", name="GPT-5.1 Codex Max"),
    ModelOption(id="gpt-5.1-codex", name="GPT-5.1 Codex"),
    ModelOption(id="gpt-5.1", name="GPT-5.1"),
    ModelOption(id="gpt-5.1-codex-mini", name="GPT-5.1 Codex Mini"),
    ModelOption(id="gpt-5-mini", name="GPT-5 Mini"),
    ModelOption(id="gpt-4.1", name="GPT-4.1"),
    ModelOption(id="claude-sonnet-4.6", name="Claude Sonnet 4.6"),
    ModelOption(id="claude-sonnet-4.5", name="Claude Sonnet 4.5"),
    ModelOption(id="claude-haiku-4.5", name="Claude Haiku 4.5"),
    ModelOption(id="claude-opus-4.6", name="Claude Opus 4.6"),
    ModelOption(id="claude-opus-4.6-fast", name="Claude Opus 4.6 Fast"),
    ModelOption(id="claude-opus-4.5", name="Claude Opus 4.5"),
    ModelOption(id="claude-sonnet-4", name="Claude Sonnet 4"),
    ModelOption(id="gemini-3-pro-preview", name="Gemini 3 Pro Preview"),
)
# Legacy internal alias for modules that still import `KNOWN_MODELS`. The
# startup-discovered catalog is preferred, but the fallback catalog remains a
# safe compatibility default inside the backend.
KNOWN_MODELS = FALLBACK_MODELS


def fallback_model_options() -> list[ModelOption]:
    return list(FALLBACK_MODELS)


async def discover_available_models(copilot_cli_path: str) -> list[ModelOption]:
    # `copilot help config` is the CLI's own source of truth for supported
    # models, so rebuilding from that output avoids shipping stale frontend
    # constants that drift behind the installed CLI version.
    command = [resolve_copilot_cli_path(copilot_cli_path), "help", "config"]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _stderr = await process.communicate()
    except OSError:
        return fallback_model_options()

    if process.returncode != 0:
        return fallback_model_options()

    parsed = parse_available_models(stdout.decode("utf-8", errors="replace"))
    if not parsed:
        return fallback_model_options()
    return [ModelOption(id=DEFAULT_MODEL, name="Default (Copilot default)"), *parsed]


def parse_available_models(help_output: str) -> list[ModelOption]:
    # The help text contains many config keys. We only collect the contiguous
    # bullet list under the `model` section so the parser stays linear and does
    # not accidentally scrape unrelated values.
    options: list[ModelOption] = []
    in_model_section = False
    collecting_values = False

    for line in help_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("`model`:"):
            in_model_section = True
            collecting_values = False
            continue
        if not in_model_section:
            continue

        match = _MODEL_LINE_PATTERN.match(stripped)
        if match is not None:
            collecting_values = True
            model_id = match.group(1)
            options.append(ModelOption(id=model_id, name=humanize_model_name(model_id)))
            continue

        if collecting_values and not stripped.startswith("- "):
            break

    deduplicated: list[ModelOption] = []
    seen_ids: set[str] = set()
    for option in options:
        if option.id in seen_ids:
            continue
        seen_ids.add(option.id)
        deduplicated.append(option)
    return deduplicated


def humanize_model_name(model_id: str) -> str:
    if model_id.startswith("gpt-"):
        suffix = model_id.removeprefix("gpt-")
        formatted = suffix.replace("-mini", " Mini").replace("-codex", " Codex").replace("-max", " Max")
        return "GPT-" + formatted
    if model_id.startswith("claude-"):
        suffix = model_id.removeprefix("claude-")
        return "Claude " + _humanize_segments(suffix)
    if model_id.startswith("gemini-"):
        suffix = model_id.removeprefix("gemini-")
        return "Gemini " + _humanize_segments(suffix)
    return model_id


def _humanize_segments(raw_value: str) -> str:
    parts: list[str] = []
    for part in raw_value.split("-"):
        parts.append(part.capitalize() if not part.replace(".", "").isdigit() else part)
    return " ".join(parts)

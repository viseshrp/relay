"""Loaded source and validated execution records shared by workflow services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .graph import CompiledGraph
from .prompts import ResolvedPrompt
from .schema import WorkflowDefinition


@dataclass(frozen=True, slots=True)
class LoadedWorkflow:
    """Validated workflow paired with its exact source bytes and parsed tree."""

    path: Path
    text: str
    document: Mapping[str, object]
    definition: WorkflowDefinition


@dataclass(frozen=True, slots=True)
class ValidatedWorkflow:
    """Validated root, dependency indexes, and resolved prompts."""

    root: LoadedWorkflow
    graph: CompiledGraph
    prompts: tuple[ResolvedPrompt, ...]

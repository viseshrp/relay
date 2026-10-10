"""Safe, ordered resolution of static local and owner-global prompts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from relay.errors import PathSafetyError, PromptResolutionError
from relay.paths import global_prompts_dir, safe_resolve

from .schema import ActionsJobNode, AgentNode, GlobalPrompt, LocalPrompt, LoopNode, NodeDefinition
from .source_text import read_source


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    """One prompt's provenance and exact immutable UTF-8 content."""

    source: str
    reference: str
    path: str
    content: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def iter_agent_nodes(nodes: Mapping[str, NodeDefinition]) -> Iterable[AgentNode]:
    """Yield agent nodes in YAML insertion order, including loop bodies."""
    for node in nodes.values():
        if isinstance(node, AgentNode):
            yield node
        elif isinstance(node, ActionsJobNode):
            yield from node.bound_agents.values()
        elif isinstance(node, LoopNode):
            yield from iter_agent_nodes(node.body)


def resolve_prompt(reference: LocalPrompt | GlobalPrompt, relay_root: Path) -> ResolvedPrompt:
    """Resolve one reference without substitution or path traversal."""
    if isinstance(reference, LocalPrompt):
        source = "local"
        value = reference.local
        root = relay_root
    else:
        source = "global"
        value = reference.global_
        root = global_prompts_dir()
    try:
        path = safe_resolve(root, value)
    except PathSafetyError:
        message = f"{source.capitalize()} prompt {value!r} escapes its allowed directory."
        raise PromptResolutionError(message, context={"workflow": str(relay_root)}) from None
    if not path.is_file():
        message = f"{source.capitalize()} prompt {value!r} does not exist."
        raise PromptResolutionError(
            message,
            context={"workflow": str(relay_root)},
            next_action="Create the prompt file or correct the workflow reference.",
        )
    try:
        document = read_source(path)
    except (OSError, UnicodeError):
        message = f"{source.capitalize()} prompt {value!r} could not be read as UTF-8."
        raise PromptResolutionError(message, context={"workflow": str(relay_root)}) from None
    return ResolvedPrompt(source, value, str(path), document.raw_text, document.base_hash)


__all__ = ["ResolvedPrompt", "iter_agent_nodes", "resolve_prompt"]

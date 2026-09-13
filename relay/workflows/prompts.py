"""Safe, ordered resolution of static local and owner-global prompts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from relay.errors import PathSafetyError, PromptResolutionError
from relay.paths import global_prompts_dir, safe_resolve

from .schema import AgentNode, GlobalPrompt, LocalPrompt, LoopNode, NodeDefinition


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
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        message = f"{source.capitalize()} prompt {value!r} could not be read as UTF-8."
        raise PromptResolutionError(message, context={"workflow": str(relay_root)}) from None
    digest = sha256(content.encode("utf-8")).hexdigest()
    return ResolvedPrompt(source, value, str(path), content, digest)


def resolve_prompts(nodes: Mapping[str, NodeDefinition], relay_root: Path) -> list[ResolvedPrompt]:
    """Resolve every declared prompt in deterministic node and list order."""
    prompts: list[ResolvedPrompt] = []
    for node in iter_agent_nodes(nodes):
        prompts.extend(resolve_prompt(reference, relay_root) for reference in node.prompts)
    return prompts


__all__ = ["ResolvedPrompt", "iter_agent_nodes", "resolve_prompt", "resolve_prompts"]

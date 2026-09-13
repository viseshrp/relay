"""Normative Pydantic schema for Relay workflow version 1."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from relay.constants import MAX_LOOP_ITERATIONS

NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
DURATION_PATTERN = re.compile(r"^[0-9]+(?:ms|s|m|h)$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

Scalar = str | int | float | bool | None


class StrictModel(BaseModel):
    """Base for versioned records that must reject unknown keys."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)


class StringConstraints(StrictModel):
    """Bounds accepted for a string launch input."""

    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    pattern: str | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> StringConstraints:
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            message = "min_length must not exceed max_length"
            raise ValueError(message)
        return self


class NumberConstraints(StrictModel):
    """Bounds accepted for an integer or number launch input."""

    min: int | float | None = None
    max: int | float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> NumberConstraints:
        if self.min is not None and self.max is not None and self.min > self.max:
            message = "min must not exceed max"
            raise ValueError(message)
        return self


class BooleanConstraints(StrictModel):
    """Boolean inputs intentionally accept no constraints."""


class EnumConstraints(StrictModel):
    """The finite values accepted for an enum launch input."""

    values: list[Scalar] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def validate_unique_values(cls, values: list[Scalar]) -> list[Scalar]:
        del cls
        for index, value in enumerate(values):
            if value in values[:index]:
                message = "enum values must be unique"
                raise ValueError(message)
        return values


class InputBase(StrictModel):
    """Fields shared by every typed launch input."""

    description: str = ""
    required: bool = False


class StringInput(InputBase):
    type: Literal["string"]
    default: str | None = None
    constraints: StringConstraints = Field(default_factory=StringConstraints)


class IntegerInput(InputBase):
    type: Literal["integer"]
    default: int | None = None
    constraints: NumberConstraints = Field(default_factory=NumberConstraints)


class NumberInput(InputBase):
    type: Literal["number"]
    default: int | float | None = None
    constraints: NumberConstraints = Field(default_factory=NumberConstraints)


class BooleanInput(InputBase):
    type: Literal["boolean"]
    default: bool | None = None
    constraints: BooleanConstraints = Field(default_factory=BooleanConstraints)


class EnumInput(InputBase):
    type: Literal["enum"]
    default: Scalar = None
    constraints: EnumConstraints

    @model_validator(mode="after")
    def validate_default(self) -> EnumInput:
        if self.default is not None and self.default not in self.constraints.values:
            message = "enum default must be one of constraints.values"
            raise ValueError(message)
        return self


InputDefinition = Annotated[
    StringInput | IntegerInput | NumberInput | BooleanInput | EnumInput,
    Field(discriminator="type"),
]


class LocalPrompt(StrictModel):
    """A prompt resolved beneath the current project's .relay directory."""

    local: str = Field(min_length=1)


class GlobalPrompt(StrictModel):
    """A prompt resolved beneath the owner's global prompt directory."""

    global_: str = Field(alias="global", min_length=1)


PromptReference = LocalPrompt | GlobalPrompt


class ExistsSelector(StrictModel):
    """True when an artifact exists beneath the node worktree."""

    exists: str = Field(min_length=1)


class LabelSelectorValue(StrictModel):
    artifact: str = Field(min_length=1)
    label: str = Field(min_length=1)


class LabelSelector(StrictModel):
    """Text after the first exact '<label>: ' artifact line."""

    label: LabelSelectorValue


class DataPathSelectorValue(StrictModel):
    artifact: str = Field(min_length=1)
    path: str = Field(min_length=1)


class JsonPathSelector(StrictModel):
    """A dotted mapping-key lookup in a JSON artifact."""

    json_path: DataPathSelectorValue


class YamlPathSelector(StrictModel):
    """A dotted mapping-key lookup in a YAML artifact."""

    yaml_path: DataPathSelectorValue


OutputSelector = ExistsSelector | LabelSelector | JsonPathSelector | YamlPathSelector


def _duration(value: str | None) -> str | None:
    if value is not None and DURATION_PATTERN.fullmatch(value) is None:
        message = "duration must be digits followed by ms, s, m, or h"
        raise ValueError(message)
    return value


class NodeBase(StrictModel):
    """Fields shared by all six node types."""

    needs: list[str] = Field(default_factory=list)
    condition: str | None = Field(default=None, alias="if")
    timeout: str | None = None
    on_timeout: str | None = None

    validate_timeout = field_validator("timeout")(_duration)

    @field_validator("needs")
    @classmethod
    def validate_unique_needs(cls, needs: list[str]) -> list[str]:
        del cls
        if len(needs) != len(set(needs)):
            message = "needs must not contain duplicates"
            raise ValueError(message)
        return needs


class AgentNode(NodeBase):
    """A coding-agent attempt using an exact model route."""

    type: Literal["agent"]
    writes: bool = False
    allow_no_commit: bool = False
    outputs: dict[str, OutputSelector] = Field(default_factory=dict)
    prompts: list[PromptReference] = Field(default_factory=list)
    model: str | None = None
    agents: list[str] = Field(default_factory=list)
    permission_profile: str | None = None


class CommandNode(NodeBase):
    """A shell-free argument-vector process."""

    type: Literal["command"]
    writes: bool = False
    allow_no_commit: bool = False
    outputs: dict[str, OutputSelector] = Field(default_factory=dict)
    run: list[str] = Field(min_length=1)
    env: dict[str, str] = Field(default_factory=dict)


class HumanWaitNode(NodeBase):
    """An owner interaction that may remain open indefinitely."""

    type: Literal["human_wait"]
    prompt: str = Field(min_length=1)
    deadline: str | None = None

    validate_deadline = field_validator("deadline")(_duration)


class ConditionNode(NodeBase):
    """A deterministic expression selecting one named branch."""

    type: Literal["condition"]
    expr: str = Field(min_length=1)
    branches: dict[str, str] = Field(min_length=1)


class LoopNode(NodeBase):
    """A bounded, scoped subgraph repeated until its condition holds."""

    type: Literal["loop"]
    body: dict[str, NodeDefinition] = Field(min_length=1)
    max_iterations: int = Field(ge=1, le=MAX_LOOP_ITERATIONS)
    until: str | None = None
    exhausted: str


class SubworkflowNode(NodeBase):
    """A synchronous, scoped invocation of another workflow file."""

    type: Literal["subworkflow"]
    workflow: str = Field(min_length=1)
    inputs: dict[str, Scalar] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)


NodeDefinition = Annotated[
    AgentNode | CommandNode | HumanWaitNode | ConditionNode | LoopNode | SubworkflowNode,
    Field(discriminator="type"),
]


class EntryArtifact(StrictModel):
    """Hash-pinned artifact required by a midstream entry point."""

    path: str = Field(min_length=1)
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        del cls
        if SHA256_PATTERN.fullmatch(value) is None:
            message = "sha256 must contain exactly 64 lowercase hex characters"
            raise ValueError(message)
        return value


class EntryPoint(StrictModel):
    """Inputs and retained artifacts required to start at one node scope."""

    scope_path: str = Field(min_length=1)
    inputs: list[str] = Field(default_factory=list)
    artifacts: dict[str, EntryArtifact] = Field(default_factory=dict)


class WorkflowDefinition(StrictModel):
    """One complete Relay workflow document."""

    version: int
    name: str = Field(min_length=1)
    inputs: dict[str, InputDefinition] = Field(default_factory=dict)
    model: str | None = None
    agents: list[str] = Field(default_factory=list)
    nodes: dict[str, NodeDefinition]
    entrypoints: list[EntryPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identifiers(self) -> WorkflowDefinition:
        _validate_node_map(self.nodes, "nodes")
        for name in self.inputs:
            if NODE_ID_PATTERN.fullmatch(name) is None:
                message = f"input id {name!r} must match {NODE_ID_PATTERN.pattern}"
                raise ValueError(message)
        scopes = [entry.scope_path for entry in self.entrypoints]
        if len(scopes) != len(set(scopes)):
            message = "entrypoint scope_path values must be unique"
            raise ValueError(message)
        return self


def _validate_node_map(nodes: dict[str, NodeDefinition], location: str) -> None:
    for node_id, node in nodes.items():
        if NODE_ID_PATTERN.fullmatch(node_id) is None:
            message = f"{location} id {node_id!r} must match {NODE_ID_PATTERN.pattern}"
            raise ValueError(message)
        if isinstance(node, LoopNode):
            _validate_node_map(node.body, f"{location}.{node_id}.body")


LoopNode.model_rebuild()
WorkflowDefinition.model_rebuild()

__all__ = [
    "AgentNode",
    "BooleanInput",
    "CommandNode",
    "ConditionNode",
    "DataPathSelectorValue",
    "EntryArtifact",
    "EntryPoint",
    "EnumInput",
    "ExistsSelector",
    "GlobalPrompt",
    "HumanWaitNode",
    "InputDefinition",
    "IntegerInput",
    "JsonPathSelector",
    "LabelSelector",
    "LocalPrompt",
    "LoopNode",
    "NodeDefinition",
    "NumberInput",
    "OutputSelector",
    "PromptReference",
    "StringInput",
    "SubworkflowNode",
    "WorkflowDefinition",
    "YamlPathSelector",
]

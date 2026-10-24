"""Show what a launch would tell each step, without creating a run or probing agents."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from relay.constants import API_MAX_PAGE_BYTES
from relay.errors import RelayError
from relay.workflows.actions import expressions
from relay.workflows.actions.builtins import is_builtin
from relay.workflows.notes import FrozenNote, notes_block
from relay.workflows.schema import ActionsJobNode, GlobalPrompt, LocalPrompt

from .launch import launch_relay_context
from .launch_request import FrozenLaunchBindings
from .preflight import load_launch_workflow

PREVIEW_PROMPT_MAX_BYTES = 64 * 1024
# Reusable workflows, loops, and composite actions can nest; deeper levels are named only.
PREVIEW_DEPTH_MAX = 4
PREVIEW_MAX_BYTES = API_MAX_PAGE_BYTES // 2
REPORT_FIELDS = ("report", "path", "format", "label", "field", "selector")


@dataclass(frozen=True, slots=True)
class PreviewText:
    """Launch-static text; runtime expressions stay visible as `${{ ... }}`.

    For example, `Fix ${{ inputs.target }} after ${{ steps.plan.outputs.file }}`
    with `target=api` becomes `Fix api after ${{ steps.plan.outputs.file }}`
    and lists `steps.plan.outputs.file` in `runtime`.
    """

    text: str
    runtime: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreviewPrompt:
    reference: str
    sha256: str
    bytes: int
    text: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class PreviewStep:
    id: str
    name: str
    kind: str
    uses: str | None = None
    agents: PreviewText | None = None
    model: PreviewText | None = None
    effort: PreviewText | None = None
    prompt_files: tuple[PreviewPrompt, ...] = ()
    prompt_files_runtime: PreviewText | None = None
    prompt: PreviewText | None = None
    report: PreviewText | None = None
    command: PreviewText | None = None
    # A composite action's own steps, or the jobs a loop repeats.
    steps: tuple[PreviewStep, ...] = ()
    jobs: tuple[PreviewJob, ...] = ()
    repeat: PreviewText | None = None


@dataclass(frozen=True, slots=True)
class PreviewJob:
    id: str
    name: str
    needs: tuple[str, ...]
    matrix: bool
    uses: str | None
    steps: tuple[PreviewStep, ...] = field(default_factory=tuple)
    # The called workflow's jobs when `uses` names a local reusable workflow.
    jobs: tuple[PreviewJob, ...] = ()


@dataclass(frozen=True, slots=True)
class LaunchPreview:
    workflow: str
    run_name: PreviewText
    jobs: tuple[PreviewJob, ...]
    truncated: bool
    # The exact block every agent step receives when notes are chosen.
    notes: str | None = None


def _render(raw: object, values: Mapping[str, object]) -> PreviewText:
    """Evaluate launch-static segments; keep runtime-only segments as written."""
    if not isinstance(raw, str):
        return PreviewText(json.dumps(raw, ensure_ascii=False) if raw is not None else "")
    parts: list[str] = []
    runtime: list[str] = []
    for enabled, text in expressions.segments(raw):
        if not enabled:
            parts.append(text)
            continue
        try:
            tree = expressions.parse(text, contexts=tuple(values))
            expressions.check_launch_context(tree)
            parts.append(expressions.string(expressions.evaluate(text, values)))
        except RelayError:
            # `steps`, `needs`, `matrix`, `env`, and `hashFiles` exist only
            # once a run reaches the step, so they stay as runtime placeholders.
            runtime.append(text.strip())
            parts.append("${{ " + text.strip() + " }}")
    return PreviewText("".join(parts), tuple(runtime))


def _prompt_files(
    rendered: PreviewText, relay_root: Path
) -> tuple[tuple[PreviewPrompt, ...], PreviewText | None]:
    from relay.workflows.prompts import resolve_prompt

    if rendered.runtime:
        return (), rendered
    prompts = []
    for line in rendered.text.splitlines():
        reference = line.strip()
        if not reference:
            continue
        target = (
            GlobalPrompt(global_=reference[7:])
            if reference.startswith("global:")
            else LocalPrompt(local=reference.removeprefix(".relay/"))
        )
        resolved = resolve_prompt(target, relay_root)
        encoded = resolved.content.encode("utf-8")
        prompts.append(
            PreviewPrompt(
                reference=reference,
                sha256=resolved.sha256,
                bytes=len(encoded),
                text=encoded[:PREVIEW_PROMPT_MAX_BYTES].decode("utf-8", errors="ignore"),
                truncated=len(encoded) > PREVIEW_PROMPT_MAX_BYTES,
            )
        )
    return tuple(prompts), None


def _report(raw: Mapping[str, Any], values: Mapping[str, object]) -> PreviewText | None:
    """Show the selector JSON the agent will receive as its output contract."""
    if "report" not in raw:
        return None
    from relay.execution.action_reports import parse_report

    fields = {name: _render(raw[name], values) for name in REPORT_FIELDS if name in raw}
    runtime = tuple(item for value in fields.values() for item in value.runtime)
    if runtime:
        return PreviewText(_render(raw["report"], values).text, runtime)
    contract = parse_report({name: value.text for name, value in fields.items()})
    return PreviewText(
        json.dumps(
            {"value": contract.selector.model_dump(mode="json", by_alias=True)},
            sort_keys=True,
            ensure_ascii=False,
        )
    )


def _called_inputs(
    declared: Mapping[str, Any], supplied: object, values: Mapping[str, object]
) -> dict[str, object]:
    """Start from declared defaults and render each supplied value statically.

    A value that needs run state stays as its `${{ ... }}` text, so the child's
    own `${{ inputs.name }}` shows where that value will come from.
    """
    inputs: dict[str, object] = {
        name: item.get("default", "")
        for name, item in declared.items()
        if isinstance(item, Mapping)
    }
    if isinstance(supplied, Mapping):
        for name, raw in supplied.items():
            inputs[str(name)] = _render(raw, values).text
    return inputs


class _Expander:
    """Preview steps and jobs, following local sources captured with the workflow."""

    def __init__(self, root: Path, sources: Mapping[str, str]) -> None:
        self.root = root
        self.sources = sources

    def _workflow(self, reference: object) -> dict[str, Any] | None:
        from relay.workflows.actions.language import load

        text = self.sources.get(str(reference).removeprefix("./"))
        return load(text).value if isinstance(reference, str) and text else None

    def _action(self, reference: str) -> dict[str, Any] | None:
        from relay.workflows.actions.metadata import load_action

        path = reference.removeprefix("./").rstrip("/")
        text = self.sources.get(f"{path}/action.yml", self.sources.get(f"{path}/action.yaml"))
        if not text:
            return None
        action = load_action(text)
        return action if action["runs"].get("using") == "composite" else None

    def jobs(
        self, document: Mapping[str, Any], values: Mapping[str, object], depth: int
    ) -> tuple[PreviewJob, ...]:
        from relay.workflows.actions.language import input_definitions, topological_jobs

        jobs = document.get("jobs", {})
        result = []
        for job_id in topological_jobs(jobs):
            job = jobs[job_id]
            uses = job.get("uses")
            needs = job.get("needs", [])
            called = self._workflow(uses) if uses and depth < PREVIEW_DEPTH_MAX else None
            result.append(
                PreviewJob(
                    id=job_id,
                    name=_render(job.get("name", job_id), values).text,
                    needs=(needs,) if isinstance(needs, str) else tuple(needs),
                    matrix="matrix" in job.get("strategy", {}),
                    uses=str(uses) if uses else None,
                    steps=self.steps(job.get("steps", []), values, depth),
                    jobs=self.jobs(
                        called,
                        {
                            **values,
                            "inputs": _called_inputs(
                                input_definitions(called, "workflow_call"),
                                job.get("with", {}),
                                values,
                            ),
                        },
                        depth + 1,
                    )
                    if called is not None
                    else (),
                )
            )
        return tuple(result)

    def steps(
        self, steps: list[Any], values: Mapping[str, object], depth: int
    ) -> tuple[PreviewStep, ...]:
        return tuple(self.step(index, step, values, depth) for index, step in enumerate(steps))

    def step(
        self, index: int, step: Mapping[str, Any], values: Mapping[str, object], depth: int
    ) -> PreviewStep:
        from relay.workflows.actions.language import input_definitions

        step_id = str(step.get("id") or f"step-{index + 1}")
        name = _render(step.get("name", step_id), values).text
        uses = step.get("uses")
        raw = step.get("with", {})
        if is_builtin(uses, "agent"):
            files, files_runtime = _prompt_files(
                _render(raw.get("prompt-files", ""), values), self.root
            )
            return PreviewStep(
                id=step_id,
                name=name,
                kind="agent",
                uses=uses,
                agents=_render(raw.get("agents", raw.get("agent")), values)
                if "agents" in raw or "agent" in raw
                else None,
                model=_render(raw["model"], values) if "model" in raw else None,
                effort=_render(raw["effort"], values) if "effort" in raw else None,
                prompt_files=files,
                prompt_files_runtime=files_runtime,
                prompt=_render(raw["prompt"], values) if "prompt" in raw else None,
                report=_report(raw, values),
            )
        if "run" in step:
            return PreviewStep(
                id=step_id, name=name, kind="command", command=_render(step["run"], values)
            )
        nested = depth < PREVIEW_DEPTH_MAX
        if is_builtin(uses, "loop") and nested:
            called = self._workflow(raw.get("workflow"))
            supplied = _render(raw.get("inputs", "{}"), values)
            try:
                literal = json.loads(supplied.text) if not supplied.runtime else {}
            except ValueError:
                literal = {}
            return PreviewStep(
                id=step_id,
                name=name,
                kind="action",
                uses=str(uses),
                repeat=_render(raw.get("max-iterations"), values),
                jobs=self.jobs(
                    called,
                    {
                        **values,
                        "inputs": _called_inputs(
                            input_definitions(called, "workflow_call"), literal, values
                        ),
                    },
                    depth + 1,
                )
                if called is not None
                else (),
            )
        action = self._action(uses) if isinstance(uses, str) and nested else None
        if action is not None:
            return PreviewStep(
                id=step_id,
                name=name,
                kind="action",
                uses=str(uses),
                steps=self.steps(
                    action["runs"].get("steps", []),
                    {**values, "inputs": _called_inputs(action.get("inputs", {}), raw, values)},
                    depth + 1,
                ),
            )
        return PreviewStep(id=step_id, name=name, kind="action", uses=str(uses) if uses else None)


def _bounded(jobs: list[PreviewJob]) -> tuple[tuple[PreviewJob, ...], bool]:
    """Keep whole jobs in order until the next one would exceed the preview budget."""
    kept: list[PreviewJob] = []
    used = 0
    for job in jobs:
        size = len(json.dumps(asdict(job), ensure_ascii=False).encode("utf-8"))
        if used + size > PREVIEW_MAX_BYTES:
            return tuple(kept), True
        kept.append(job)
        used += size
    return tuple(kept), False


def preview_launch(
    relay_root: Path,
    workflow_key: str,
    inputs: Mapping[str, object],
    bindings: FrozenLaunchBindings,
    *,
    launcher: str,
    notes: Sequence[FrozenNote] = (),
) -> LaunchPreview:
    """Resolve the launch-static parts of every top-level job and step.

    This reads the same sources, prompts, and input rules as launch. It creates
    no run, snapshot, or worktree and starts no agent, so it never proves that
    a model is available; launch still performs that check.
    """
    from relay.workflows.actions.language import resolve_inputs

    workflow = load_launch_workflow(relay_root, workflow_key)
    actions = workflow.root.definition.actions
    typed_inputs = resolve_inputs(actions, inputs, environments=tuple(bindings["environments"]))
    values: dict[str, object] = {
        "inputs": typed_inputs,
        "vars": bindings["vars"],
        "relay": launch_relay_context(
            relay_root, workflow, workflow_key, launcher, typed_inputs, {}
        ),
    }
    node = next(iter(workflow.root.definition.nodes.values()), None)
    sources = node.sources if isinstance(node, ActionsJobNode) else {}
    jobs = list(_Expander(relay_root, sources).jobs(actions, values, 0))
    kept, truncated = _bounded(jobs)
    return LaunchPreview(
        workflow=workflow.root.definition.name,
        run_name=_render(actions.get("run-name", workflow.root.definition.name), values),
        jobs=kept,
        truncated=truncated,
        notes=notes_block(notes) if notes else None,
    )


__all__ = ["LaunchPreview", "preview_launch"]

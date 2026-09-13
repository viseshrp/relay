"""Execute every tagged workflow example in the durable workflow guide."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import tempfile

from relay.errors import RelayError
from relay.workflows.loader import load_workflow
from relay.workflows.validation import validate_loaded_workflow

EXAMPLE_PATTERN = re.compile(
    r"<!-- relay-example: (?P<expectation>valid|invalid) (?P<name>[a-z0-9_-]+) -->"
    r"\s*```yaml\n(?P<source>.*?)```",
    re.DOTALL,
)

CHILD_WORKFLOW = """version: 1
name: Child verifier
inputs:
  target:
    type: string
    required: true
nodes:
  check:
    type: command
    run: [python, -c, \"print('checked')\"]
    outputs:
      ready:
        exists: report.json
"""


def check_examples(path: Path) -> int:
    """Return zero only when each tagged example has its documented outcome."""
    text = path.read_text(encoding="utf-8")
    examples = list(EXAMPLE_PATTERN.finditer(text))
    if not examples:
        print(f"{path}: no tagged workflow examples found")
        return 1

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="relay-doc-examples-") as temporary:
        relay_root = Path(temporary) / ".relay"
        workflows = relay_root / "workflows"
        prompts = relay_root / "prompts"
        workflows.mkdir(parents=True)
        prompts.mkdir()
        (prompts / "review.md").write_text("Review the repository.\n", encoding="utf-8")
        (workflows / "child.yaml").write_text(CHILD_WORKFLOW, encoding="utf-8")
        for index, match in enumerate(examples, start=1):
            name = match.group("name")
            expectation = match.group("expectation")
            workflow_path = workflows / f"example-{index}.yaml"
            workflow_path.write_text(match.group("source"), encoding="utf-8")
            rejected = False
            try:
                loaded = load_workflow(workflow_path)
                validate_loaded_workflow(loaded, relay_root)
            except RelayError:
                rejected = True
            if (expectation == "invalid") != rejected:
                actual = "rejected" if rejected else "accepted"
                failures.append(f"{name}: expected {expectation}, validator {actual} it")

    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(f"validated {len(examples)} workflow example(s) in {path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    raise SystemExit(check_examples(args.path))


if __name__ == "__main__":
    main()

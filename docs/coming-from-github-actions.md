# Coming from GitHub Actions

Relay keeps familiar jobs, steps, dependencies, expressions, inputs, and logs.
Execution happens locally through your installed coding agents and commands.

| GitHub Actions | Relay |
| --- | --- |
| Actions | Runs |
| Workflow | Workflow, saved under `.relay/workflows/` |
| Job | A job containing ordered steps |
| Run workflow | Run workflow with typed inputs and launch checks |
| runs-on | Agent and model on a `relay/agent@v1` step |
| Environment approval | Environment approval or `relay/human-wait@v1` |
| Re-run jobs / Cancel | Re-run jobs / Cancel run |
| Artifacts | Retained reports and named uploaded artifacts |

A script and its dependencies use familiar syntax:

<!-- relay-example: valid local-checks -->
```yaml
name: Local checks
on: workflow_dispatch
jobs:
  check:
    steps:
      - run: python -m pytest tests -q
  describe:
    needs: check
    steps:
      - run: echo Checks completed
```

A coding agent is an explicit local action. Select an exact model advertised by
that installed tool; Relay validates it before launch:

<!-- relay-example: valid ask-local-agent -->
```yaml
name: Ask an agent
on:
  workflow_dispatch:
    inputs:
      task: {type: string, required: true}
jobs:
  implement:
    steps:
      - uses: relay/agent@v1
        with:
          agent: codex
          prompt: ${{ inputs.task }}
```

An approval can offer buttons and pass its answer to later steps:

<!-- relay-example: valid owner-approval -->
```yaml
name: Review then continue
on: workflow_dispatch
jobs:
  review:
    steps:
      - id: approval
        uses: relay/human-wait@v1
        with:
          prompt: Review the retained results before continuing.
          options: '["Approve", "Reject"]'
      - if: ${{ steps.approval.outputs.answer == 'Approve' }}
        run: echo Approved
```

Hosted runners, containers, remote marketplace actions, remote workers, and
automatic merges are not implicit features. Use a local script or a frozen local
reusable workflow where the language supports it. Relay's validator explains
unsupported fields. Run work uses isolated working copies, and saved launch
sources and prompts remain immutable for that run.

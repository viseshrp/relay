# Coming from GitHub Actions

Relay keeps familiar jobs, steps, dependencies, expressions, inputs, and logs.
Execution happens locally through your installed coding agents and commands.

| GitHub Actions | Relay |
| --- | --- |
| Actions | Runs |
| Workflow | Workflow, saved under `.relay/workflows/` |
| `.github/workflows/` | `.relay/workflows/`; **Import from GitHub Actions** converts a file |
| Job | A job containing ordered steps |
| Run workflow | Run workflow with typed inputs and launch checks |
| `runs-on` | Not needed; jobs run on this computer. To have an AI agent do the work, add a `relay/agent@v1` step |
| `permissions`, `services`, `container` | Not supported; your installed tools handle sign-in, services start outside Relay, and scripts replace containers |
| Environment approval | Environment approval or `relay/human-wait@v1` |
| Re-run jobs / Cancel | Re-run jobs / Cancel run |
| Artifacts | Retained reports and named uploaded artifacts |
| `github` context | `relay` context; see the table in [Workflows](workflows.md#expressions-and-conditions) |
| `github.event.inputs.<name>` | `inputs.<name>` |
| `runner` context | `host` context: `os`, `arch`, `name`, `temp` |
| Step output, environment, path, state, and summary files | `$RELAY_OUTPUT`, `$RELAY_ENV`, `$RELAY_PATH`, `$RELAY_STATE`, `$RELAY_STEP_SUMMARY` |
| `actions/checkout` | Not needed; jobs run in a working copy of the repository |
| `actions/setup-*` | Use the tools installed on this computer |
| `actions/upload-artifact`, `actions/download-artifact` | `relay/upload-artifact@v1`, `relay/download-artifact@v1` |
| `actions/cache` | `relay/cache@v1`, `relay/restore-cache@v1`, `relay/save-cache@v1` |
| Local actions in `.github/actions/` | `./.relay/actions/<name>` |
| `docker://` images and marketplace actions | Not supported; use a `run` step, `relay/command@v1`, or a local action |
| `pull_request` and other hosted events | Not supported; use `push`, `schedule`, or `workflow_dispatch` |
| A matrix axis set from an expression | Not supported; set the whole matrix: `matrix: ${{ fromJSON(...) }}` |
| `strategy.max-parallel` | Not supported; matrix jobs run one at a time |
| Lists in `with:` | One value per line under `\|`, or a JSON array string |
| `secrets.GITHUB_TOKEN`, `github.token` | Not created; bind a secret or rely on the tool's own sign-in |

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

A typical CI file needs a few changes. Relay rejects this one because of
`runs-on`, the `pull_request` trigger, and the checkout and setup actions:

<!-- relay-example: invalid github-ci -->
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest
```

Choose **New workflow**, then **Import from GitHub Actions**, and pick the file
from `.github/workflows/`. **Changes** lists each edit: it removes `runs-on`,
the `pull_request` trigger, `actions/checkout`, and `actions/setup-python@v5`.
The `run` steps stay as written. **Create workflow** opens the result as an
unsaved draft, and the original file never changes:

<!-- relay-example: valid imported-ci -->
```yaml
name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    steps:
      - run: pip install -r requirements.txt
      - run: pytest
```

Hosted runners, containers, remote marketplace actions, remote workers, and
automatic merges are not implicit features. Use a local script or a frozen local
reusable workflow where the language supports it. Relay's validator explains
unsupported fields. Run work uses isolated working copies, and saved launch
sources and prompts remain immutable for that run.

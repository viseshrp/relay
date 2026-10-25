# Build your first workflow

This guide builds a two-job workflow in the editor. An agent reviews the
README, then a command runs the tests. You need a project open in Relay and
one coding agent that **Get started** shows as **Ready to connect**. Try it in
a disposable repository or branch first.

Each step shows the YAML that the editor writes. The visual editor and the
YAML edit the same file, so you can follow along in either one.

## 1. Create a blank workflow

1. Open **Workflows** and choose **New workflow**.
2. Choose **Blank workflow** and enter `Review and test` as the **Workflow
   name**.
3. Choose **Create workflow**.

Relay saves `.relay/workflows/review-and-test.yaml` with one job, `check`,
that prints `Ready`. `on: workflow_dispatch` means you start it yourself with
**Run workflow**.

<!-- relay-example: valid first-workflow-blank -->
```yaml
name: "Review and test"
on: workflow_dispatch
jobs:
  check:
    steps:
      - run: echo Ready
```

The editor opens in **Split** mode, which shows the job canvas and the YAML
together.

## 2. Make the first job an agent review

1. Select the `check` job on the canvas to open its settings.
2. On **General**, set **Job name** to `Review`.
3. Choose **Rename job ID**, enter `review`, and choose **Rename**. Run views
   show the name; **Start after** and expressions use the ID.
4. Open **Steps**. With the first step selected, set **Step type** to
   **Agent**.
5. Under **Runs on**, choose **One agent** and pick your agent in **Agent**.
6. Choose a **Model**. **Refresh model choices** asks the agent which models
   it offers now. Leave the field empty only if **Settings** saves a default
   model for this agent.
7. Replace the **Agent prompt** with
   `Review README.md and list anything unclear.`
8. Close the job settings.

<!-- relay-example: valid first-workflow-review -->
```yaml
name: "Review and test"
on: workflow_dispatch
jobs:
  review:
    steps:
      - uses: relay/agent@v1
        with:
          prompt: Review README.md and list anything unclear.
          agent: codex
          model: exact-model-value
    name: Review
```

Your file names the agent and the exact model you chose; `codex` and
`exact-model-value` stand in for them here. The editor adds new fields at the
end of a job. Their order does not matter.

## 3. Add a job that runs the tests

1. Set **New job type** to **Command** and choose **Add job**. The new job
   opens on **Steps** with `echo` and `Ready` as its program and arguments.
2. Under **Program and arguments**, change the first item to `python` and the
   second to `-m`. Choose **Add Program and arguments item** and enter
   `pytest`. Each item is one argument; no shell reads them.
3. On **General**, set **Job name** to `Test`. Use **Rename job ID** to change
   its ID to `test`.
4. Set **Start after** to **Review (review)**, then close the job settings.

<!-- relay-example: valid first-workflow-review-and-test -->
```yaml
name: "Review and test"
on: workflow_dispatch
jobs:
  review:
    steps:
      - uses: relay/agent@v1
        with:
          prompt: Review README.md and list anything unclear.
          agent: codex
          model: exact-model-value
    name: Review
  test:
    steps:
      - uses: relay/command@v1
        with:
          argv: '["python","-m","pytest"]'
    name: Test
    needs:
      - review
```

`needs` makes Test wait until Review succeeds. If your project tests another
way, enter that program instead: `python -m pytest` fails when pytest is not
installed or finds no tests.

## 4. Save and run it

1. Choose **Save**. Relay validates the workflow, then shows "Workflow and
   instructions saved and validated."
2. Choose **Run workflow** in the workflow header. The panel checks your
   project files. The new workflow file is listed under **1 new workflow file
   can stay uncommitted**, and committing it is optional.
3. Choose **Run workflow** in the panel. The run page opens.
4. If the agent asks for permission while it works, the request appears under
   **Waiting for you**. Choose **Respond** to answer it.
5. Follow the jobs in the list on the left. Select **Review** and read the
   agent's findings under **Agent conversation**. Select **Test** to read
   **Command output**.

When both jobs succeed, the summary says "Work is complete. Review the saved
documents and code changes below." The run works in its own copy of the
repository, so your checkout does not change. If a job changed files, the
summary says how many changed on which run branch and gives the commands
that bring them into your branch.

## 5. Fix a mistake

1. Open **Workflows** again and select **Review and test**.
2. In the YAML, change `steps:` under `review:` to `stpes:`.
3. The editor marks the field and shows
   `workflow.jobs.review.stpes: Unknown workflow field. Did you mean steps?`
   **Save** stays disabled while an error remains, and **Open job** opens the
   job's settings.
4. Change `stpes:` back to `steps:`. The error disappears.

<!-- relay-example: invalid first-workflow-typo -->
```yaml
name: "Review and test"
on: workflow_dispatch
jobs:
  review:
    stpes:
      - uses: relay/agent@v1
        with:
          prompt: Review README.md and list anything unclear.
          agent: codex
          model: exact-model-value
    name: Review
```

Validation messages name the field, and most say how to fix it. While you
type in the YAML, completion lists the fields and values that fit at the
cursor.

## Built-in actions

Each step is a script (`run`) or an action (`uses`). **Step type** offers
**Script** for `run` and these built-in actions. Inputs go under `with`.
Later steps in the same job read an output as `steps.<id>.outputs.<name>`,
where `<id>` is the step's **Step ID**.

| Step type | Reference | Purpose | Required inputs | Optional inputs | Outputs |
| --- | --- | --- | --- | --- | --- |
| Agent | `relay/agent@v1` | Ask an installed coding agent to do work in the job's working copy. | None | `agent`, `agents`, `allowed-paths`, `auto-retry`, `effort`, `field`, `format`, `label`, `model`, `prompt`, `prompt-files`, `report`, `retry-limit`, `selector` | `value`, read from `report` when it is set |
| Command | `relay/command@v1` | Run a program with exact arguments in the job's working copy, without a shell. | None | `argv`, `command` | None |
| Approval | `relay/human-wait@v1` | Pause the job until you answer a question in Relay. | `prompt` | `options`, `timeout-minutes` | `answer` |
| Check a report | `relay/validate-report@v1` | Check a report file in the job's working copy and export a value read from it. | None | `field`, `format`, `label`, `path`, `report`, `selector` | `value` |
| Check a value | `relay/validate-input@v1` | Check that a value has the expected type and limits; the step fails when it does not. | `type`, `value` | `constraints` | `value`, `valid` |
| Upload artifact | `relay/upload-artifact@v1` | Save files from the job's working copy as a named artifact of this run. | `path` | `name`, `retention-days` | `artifact-id`, `artifact-digest` |
| Download artifact | `relay/download-artifact@v1` | Copy a saved artifact from this run, or an earlier run of the same project, into the job's working copy. | `name` | `path`, `run-id` | `download-path` |
| Cache | `relay/cache@v1` | Restore files from the project cache, and save them under key when the job succeeds. | `key`, `path` | `restore-keys` | `cache-hit`, `cache-primary-key`, `cache-matched-key` |
| Restore cache | `relay/restore-cache@v1` | Restore files from the project cache without saving them later. | `key`, `path` | `restore-keys` | `cache-hit`, `cache-primary-key`, `cache-matched-key` |
| Save cache | `relay/save-cache@v1` | Save files from the job's working copy to the project cache under a key. | `key`, `path` | None | `cache-primary-key` |
| Repeat a workflow | `relay/loop@v1` | Run a local workflow again and again until one of its outputs has a chosen value or the limit is reached. | `max-iterations`, `workflow` | `equals`, `inputs`, `until-output` | The repeated workflow's `workflow_call` outputs |

Some inputs are required in combination:

- A command needs exactly one of `argv` or `command`.
- A report check needs `path`, `report`, or `selector`.
- An agent step needs an agent and an exact model, from the step or from
  **Settings**.

Scripts and commands can also set outputs by writing `name=value` lines to
the file named by `$RELAY_OUTPUT`. Hover over an input in the YAML, or use its
question-mark button in the form, to read its description. See
[Workflows](workflows.md) for every field and its limits.

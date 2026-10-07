# Local web runtime

Relay's browser application controls work in registered local repositories.
It runs on loopback and has no remote deployment mode in Phase 1.

## Start Relay

Run this inside a Git repository:

```bash
relay up
```

If the repository has no `.relay` directory, Relay creates the same blank
project files as `relay init`. Existing project files stay unchanged, including
a project discovered in a repository subdirectory. Startup never commits them.

Relay applies database migrations, reconciles durable work, starts Uvicorn and
one Huey consumer, waits for the HTTP API to become ready, and then opens the
browser. Uvicorn 0.52.4 is pinned as the ASGI server and uses its plain `h11`
HTTP implementation. The wheel supplies Uvicorn; an owner does not install or
run a separate web server.

When ready, `relay up` prints the URL, whether login is on, and how to stop
with Ctrl+C. Open that URL to create your first workflow. `relay up --json`
keeps the earlier startup text and JSON error envelopes for existing scripts.

The command accepts these options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Loopback address: `127.0.0.1`, `localhost`, or `::1` |
| `--port` | `7845` | TCP port from 1 through 65535 |
| `--workers` | `1` | Number of Huey thread workers |
| `--no-browser` | off | Start without opening the system browser |
| `--login / --no-login` | login required | Require owner credentials, or open the local app directly |

Command-line values override `host`, `port`, `workers`, and `login_required`
in Relay's settings file. A second live supervisor or an occupied address fails
before another pair of children starts. Configuration and bind failures exit
with status 4. A child or supervision failure exits with status 5.

Relay binds only to loopback. `--host 0.0.0.0` and non-loopback names are
rejected. IPv6 `::1` is rendered in the browser URL as
`http://[::1]:7845/`; `127.0.0.1` becomes `http://127.0.0.1:7845/`.

## First login

Login is required by default. The first browser session shows owner onboarding.
Choose a username and a password for this computer's Relay. The form shows
the configured password rules before you submit it. The server enforces them
when creating the account.
Relay ships no username or password. Onboarding creates one Django superuser in
a transaction, signs that browser session in, and rejects later attempts to
create another owner.

Later sessions use the same local credentials. Session cookies are HTTP-only,
same-site strict, and expire when the browser closes. Browser actions use a
same-site CSRF cookie and header. Relay does not issue bearer tokens.

If the first authentication request fails, Relay shows the error and a Retry
button. A failed sign-out request also shows its error and can be retried.

### Open without a login

Start with `relay up --no-login` to skip both onboarding and sign-in. The app
opens directly and shows **Login disabled** instead of an account name and
Sign out button. Anyone who can reach this computer's loopback service can
use its project, run, and cleanup controls. Browser actions still require the
CSRF cookie and header; host checks and the loopback-only bind remain in place.

To keep this choice for later starts, set `"login_required": false` in the
installation's [settings.json](projects-and-storage.md#owner-settings).
Restart Relay to apply the saved choice. `relay up --login` overrides it and
restores the existing owner login, or onboarding if no owner was created.
Disabling login leaves stored passwords, sessions, projects, and runs intact.
Actions started without a login are attributed to `local`.

## Get started

Every project uses the same workflow and run workspace, including projects
with no previous runs. After sign-in, or immediately with login disabled, a
small welcome prompt offers **Get started**. Opening the checklist or choosing
**Dismiss welcome** hides this prompt across all projects in that browser,
including after a reload. This choice does not change project settings.

The checklist opens in a dialog from the welcome prompt or **Help › Get
started**, including on the settings page. It shows the selected project,
all five supported agents, workflow choices, and first-run controls. Close it
at any time with **Close checklist**, Escape, or a click outside the dialog;
focus returns to **Help**. Opening the checklist starts a bounded agent
connection check; switching projects with it closed does not probe agents.
Launching a workflow closes it and opens the run page.

Agent cards show **Ready to connect**, **Sign in required**, **Check failed**,
or **Not installed**, with text and a status symbol. **Check again** uses the
same bounded probe as `relay doctor`. A successful connection check reads
models; it does not prove the account is signed in. Only a structured
authentication error gets the sign-in label. Cards provide install links and
commands to copy; Relay never installs an agent or signs it in.

Choose **Start from a template**, select a starter, and create the workflow.
The checklist shows its sample inputs and an exact model from a fresh probe.
You can edit those inputs or change the model before pressing **Run workflow**.
Launch uses the existing validation and preflight services. With no working
agent, the checklist explains the fix and disables the run button.
**Blank workflow** opens the same gallery with the blank option available;
close the checklist and add its jobs in the editor before running it.

## Choose a project and workflow

The project bar stays visible above both views. Choose a registered project,
or use **Open another project** and enter its local Git repository path. Relay
can initialize a blank `.relay` surface there. Each browser keeps its own
selection; changing projects does not change another browser's selection.

**Workflows** sets up stages, instructions, and inputs. **Runs** shows work
already started. The run header names its captured workflow and project,
shows its run number and source branch, and states what happens next.
Internal IDs and provider JSON are under advanced views. Cleanup controls live
in **Settings > Storage**.

**New workflow** opens the same six-starter gallery as the checklist. Each
card shows its purpose, job graph preview, required agent, and input types.
Selection copies sources into `.relay/workflows/` and `.relay/prompts/` without
overwriting owner files. The editor and launch use those copies. A blank
workflow still accepts a name and opens with an empty canvas.

## Author workflows

Choose a saved workflow from the menu, or use **New workflow** to create one
in the selected project. **Add stage** asks for a name and an action. Commands,
agent work, and human reviews have ordinary form fields. The new stage starts
after the previous one; **Start after** changes its dependencies. An empty
workflow explains how to add the first stage.

The stage list stays readable beside the canvas. Use **Find a stage** to
filter it by name, then choose a stage to center it at a readable scale and
open its settings below. Keyboard selection also brings the canvas into view
and moves focus there. Choose the same stage again to restore its view after
panning or zooming. **Fit View** provides an overview; the list lets you return
to an individual stage without finding its small label in that overview.

Loading another workflow clears the search and starts the canvas at its first
stage, with fresh positions and zoom. Navigation does not edit the workflow
or its instructions. Unsaved agent instructions must be saved before choosing
another stage.

Advanced workflow settings expose the YAML editor and workflow key. `review`
and `review.yaml` both refer
to `review.yaml`, and nested keys use `/`. Empty segments, backslashes, `.`,
and `..` are rejected. The canvas and CodeMirror edit one eemeli `yaml`
document. Typing valid YAML redraws the graph. Adding, deleting, or configuring
a canvas node rewrites that same document instead of maintaining a second graph
model.

The stage panel covers all six node types. Dependencies are selected by stage
name. Commands have a Program field and one argument per line. For example,
program `git` with arguments `status\n--short` saves
`run: [git, status, --short]`; a line `a b` stays one argument. Relay does not
invoke a shell. An optional advanced field accepts an explicit JSON argument
array. Invalid JSON stays in that field and is not applied.

Agent instructions can be written and saved in the stage panel. They live in
the selected project's `.relay/prompts` folder. Saving checks the loaded file
hash and requires the workflow's editing lease. Unsaved instructions block
stage and project changes, workflow saving, and launch until they are saved.
Use the model menu to select an advertised exact value; **Load available
models** refreshes installed tools. A model read never grants permissions or
changes provider defaults. The exact-value field remains available for a
provider value already known to the owner.

Workflow reads warn about `exists` report outputs in root, loop, and child
workflows. **Retain the report** explains file-retaining selectors and verdict
checks. Warnings never rewrite outputs or answer a human review.

Agent nodes show the effective tools from node, workflow, and owner preferences.
The Agent tools field adds node preferences in selection order. Each tool has
an Effort dropdown for the selected exact model and a Permission mode dropdown.
Both start at **Provider default**, leaving the override absent from YAML and
provider requests. Choosing a value saves it under the node's per-tool
`agent_options`; choosing Provider default removes it.

Choices come from a fresh disposable tool session after model selection. While
loading, the dropdowns are disabled. A failed read shows an error and Retry.
Changing the node's model override resets effort and loads its new choices.
Unsupported saved values stay visible for correction and fail launch preflight.
A tool without a separate selector offers only Provider default. Native
Antigravity effort is included in the exact model slug; choose another exact
model to change it. See [Coding agents](agents.md#effort-and-permission-modes).

Canvas changes use canonical YAML formatting. Explicit Save compares the
canonical text with the editor text and asks before normalizing collection
style or spacing. For example, `nodes: {}` stays a valid compact empty mapping,
while structurally edited mappings use block formatting. Comments and scalar
values remain part of the parsed document. The dialog warns about formatting
changes because round-trip libraries cannot preserve every presentation choice
after structural canvas edits.

## Drafts, leases, and conflicts

Each browser tab gets an opaque holder ID in session storage. Loading a
workflow acquires its 60-second editor lease; the tab renews the lease every 30
seconds. Draft and Save requests must present that live holder ID. Another tab
can read the file but cannot autosave or replace it until the lease expires.

Changed editor text autosaves to the database after 600 milliseconds without
changing the Git-owned workflow file. Invalid YAML is retained as an `invalid`
recovery draft. Reloading the workflow restores the newest draft and shows its
validation state.

Switching views, workflows, or projects flushes the recovery draft first.
Requests are serialized so an older draft cannot overwrite a newer one.
Leaving the page with unsaved changes triggers the browser's warning.

Save validates the complete workflow, prompts, and subworkflows, then replaces
one file atomically. It also sends the SHA-256 hash of the exact bytes loaded by
the tab. If another process changed the file, Relay returns a conflict and
keeps the recovery draft. Reload the saved file, reconcile the draft, and Save
again. A successful Save clears the draft and refreshes the base hash.

## Launch a run

Choose **Run workflow** in the workflow header or its run history. The
panel shows the current Git branch read-only; a detached checkout shows its
commit instead. Each run still captures a fresh immutable snapshot through
the existing launch service. The branch preview is advisory; launch checks the
current source again.

The panel uses the workflow's typed `inputs` mapping. It shows each input's
`description` and prefilled default. Strings expand to multiple lines for long
text, integer and number inputs use numeric fields, booleans use checkboxes,
and enums show their declared values. An untouched input stays omitted so the
server applies its default or resolves an optional input to `null`. Edited
values preserve their JSON types.

The panel explains each blocked state beside **Run workflow**: loading or
saving, no selected workflow, unsaved instructions, invalid YAML, unsaved
workflow changes, an empty workflow, unavailable Git source, or a missing first
commit. Unsaved workflow changes offer **Save** when this browser can save;
lease conflicts and unsaved instructions explain what to fix in the editor.
Launch failures appear in the panel, and the owner can retry after fixing them.

When the saved workflow is ready, **Project files** checks launch cleanliness
before enabling **Run workflow**. It lists blocking files with their Git
reasons and puts permitted changes under **Allowed files**, explaining each
exemption. A bounded preview shows full counts when the file list is truncated.
**Check files again** refreshes the file check and current branch.

Blocked previews offer **Copy** for `git commit` and `git stash -u`. Relay
copies these commands; the owner chooses what to stage or set aside and runs
them in the project folder. Stashing with `-u` also removes untracked workflow
files and reports until restored. The preview uses saved sources. After
**Save**, the panel checks them again. A later file change can still block the
server's launch check and appears as an error in the panel.

**Advanced options** explains **Override model for this run**, **After a
successful run**, and **Start from job**. Cached models are suggestions; Relay
sends the exact entered value. Working copies can be deleted on success or
kept; saved reports and commits remain available. Start points list only jobs
declared in `entrypoints`. The server validates their required inputs and
artifact evidence. **Automatic recovery** is a workflow setting in
**Advanced workflow settings and YAML** and requires saving the workflow.

The server repeats validation, clean-Git, artifact, and exact-model preflight
before it creates a run.

The **After a successful run** choice in global defaults, project defaults,
and Run workflow includes **Merge into the active branch, then delete working
copies**. The launch panel shows when this choice is inherited and checks all
changed files. Commit workflow and report edits before launching. Relay
captures the branch selected at launch, fast-forwards it after every job
succeeds, and removes the run working copies. The checkout must remain clean
and on that branch. A diverged branch fails and requires a manual merge.
The run shows **Merging and cleaning up**, then the merged branch and commit.
Failure keeps the working copy and shows the error under Annotations. If
cleanup fails after the merge, the summary distinguishes the completed merge
from the retained working copy. History, reports, and run branches remain.
See [Run integration](git-and-artifacts.md#opt-in-run-integration).

## Monitor and control runs

The run header keeps its controls visible in both **Summary** and a job log.
Active runs offer **Pause** and **Cancel run**; pausing changes the action to
**Resume**. A pending launch can be paused, but cannot be canceled until its
worktree is ready. Canceling and interrupted runs show no new control action.
The cancellation confirmation keeps finished jobs, reports, and commits.

Finished runs offer **Re-run all jobs**. It opens **Run workflow** with the
previous typed inputs prefilled, using the current saved workflow and branch.
This creates a new run through the usual preflight and snapshot capture. Input
names removed from the workflow are omitted; changed definitions are validated
again. The previous run and its snapshot remain unchanged. A stale request
shows an error instead of creating a run.

A failed run offers **Open job log** beside each failed job. **Re-run job** and
**Re-run with settings** live in that job's view and use the existing retry
service. Settings are read again when the dialog opens. Re-running one job
preserves completed upstream work and the original launch snapshot.

Choose **Pause** to hold work before the next agent starts. An already running
agent keeps its session and can finish normally. The header and history show
**New jobs paused**, including after reload or restart. The pause also holds
automatic error recovery and quota retries; deadlines continue to apply.
Choose **Resume** explicitly when ready.

While paused, the header says: "Paused. Running jobs will finish; nothing new
will start until you resume." Upcoming agent jobs have an **Edit** icon in the
job list, available from both Summary and job logs. Relay prefetches their
provider choices, shares probes for identical agent/model routes, and limits
the number of routes loading at once. The icon becomes available when the
dialog can open populated. A failed probe shows **Check again** beside the job.
Switching runs or resuming discards pending probes and edit controls.

Choose **Edit** to select an advertised tool, model, effort, or permission mode.
The dialog uses provider labels for current effort and permission choices;
defaults remain the provider defaults. Cancel or Escape returns focus to the
job's edit control. A changed tool/model reveals editable **Handoff
instructions** for the unstarted job;
effort and permission changes alone keep that editor hidden. **Save settings**
keeps the run paused. The server validates changed choices afresh before
saving. Completed work, captured instructions, saved outputs, and other jobs
stay unchanged. Settings for active or completed attempts
cannot be changed through this control.

The Runs tab lists history for the selected project. A selected run shows
its title, number, state, source, duration, and controls. Pending requests appear
before the graph. Annotations open failed job logs, where **Re-run job**
retries a job. Agent failures also offer **Re-run with settings**, which lets
the owner keep the current tool and model or select another installed tool
and one of its freshly loaded models.
Every failed agent step has this control, including other failures below the
run's initiating problem notice.
For the current selection, keep its effort and permission mode, select
advertised values, or choose Provider default. A replacement loads its own
effort and permission choices, initially using Provider default. Antigravity
shows the effort encoded
in its exact model. Choose Auto approve explicitly when that is intended.
The choice applies to that step's new attempts, including later quota retries;
the launch snapshot, earlier attempts, completed steps, and other steps' tool
selections stay saved.
Changing the tool or exact model reveals **Handoff instructions**, prefilled
with Relay's continuation prompt. Edit that text to guide the new model, or
choose **Use default handoff** to restore it. Returning to the original
selection hides the editor; effort and permission changes alone keep it hidden.
Relay adds the chosen instructions after the original step prompts and retains
them for future retries.
The left column lists jobs with a status symbol, text, and the latest attempt's
duration. Loop iterations, child workflows, and repair rounds retain their
own groups and scope paths, with children indented beneath their parent.
Waiting and failed jobs move to the top with their parent and repair context;
each loaded job appears once, including iteration markers. **Load more jobs**
extends the same list. The Summary has one graph without a duplicate chip
block. Select **Summary** for the run graph, approvals, and overall status.
Selecting a job in the list, graph, or failure notice opens its log in the
right column. The URL records
`job=<scope path>` so a reload or shared link opens the same job.

The job header shows its name, agent and exact model, duration, attempt picker,
and **Re-run job** when the existing retry service allows it. Sections show
**Set up**, captured read-only **Instructions**, **Agent conversation** or
**Command output**, declared **Outputs**, this attempt's committed **Changes**,
and **Complete**. A failed attempt opens its output and places its public
error and recent stderr at the top, independently of whole-run event pages.
Earlier log pages load automatically. A failed history fetch keeps a
**Retry log history** control for recovery. Attempts keep their own load
control. Command lines show line numbers and safe ANSI colors; escape
sequences never become HTML or links. **Log options** contains **Copy output**
and **Download logs** for the complete selected attempt's command streams.
Captured instruction previews are bounded and show when text is omitted.
Outputs describe the latest attempt; older attempts keep their own events
and committed changes. Re-running a job uses the existing control service
and preserves completed upstream work and the launch snapshot.
The selected run's history entry uses its live status, so it agrees with the
detail view when work waits, finishes, stops, or restarts. Refresh reloads the
history list and selected run's state, requests, saved files, and recent events.
It reconnects live updates when another owner client retried a stopped run.
Refresh and the failed-step retry controls stay disabled until these reads
finish, so a retry dialog uses the refreshed effort and permission settings.
Workflows continue automatically until a configured stage or tool requests input.
Retrying a failed child also marks its enclosing failed loop iterations
**In progress**. Their earlier failure stays in history; completed steps and
iterations keep their results. Stopping that retry before its loop starts
marks its unfinished iterations **Stopped**.
Interaction updates refresh the current step state after event replay, so a
waiting stage stays labeled **Needs your input** when a historical stream opens.
The captured state cursor prevents replayed progress from replacing current
progress. Older terminal events remain in history and cannot close a retried
run's live stream.
Steps that finish during initial loading update progress before live updates
start. The browser confirms the current run state before treating a stream as
finished, so a recent retry can keep receiving updates.

The graph uses captured dependencies and control targets, so editing today's
workflow cannot redraw a past run's connections. Connected rows show stage
order and branches. Nested workflows and loop iterations keep their concrete
scope paths; completion junctions join child branches and order iterations.
Progress updates and **Refresh** retain each unchanged job's measured layout,
so its connections stay visible while the run detail is reloaded.

The monitor combines the SSE stream with paginated database reads:

- Activity joins adjacent text fragments and command stream bytes into readable
  messages, with stage, tool, time, and attempt attribution. Turn, message,
  attempt, stage, and stdout/stderr boundaries stay separate. Split tool JSON
  is assembled before readable summaries are shown. For example, `"Hello "` plus
  `"world\n"` becomes `"Hello world\n"` within one message;
  opaque tool IDs remain in diagnostics, and duplicate command titles appear
  once. For example, a `git status` title and command show one `git status`;
- original events and normalized public provider payloads remain available
  under **Advanced diagnostics and saved files > Details**;
- event history loads forward by the last durable event ID, then starts its
  live stream after the last loaded event;
- node, interaction, and artifact lists load bounded pages by record ID;
- pending permission, elicitation, and human-wait records show distinct forms;
- failed nodes expose a manual rerun action;
- retained artifacts expose authenticated download links.

Activity renders Markdown headings, emphasis, lists, quotes, tables, and code
blocks through React. Raw HTML and images stay inert; links accept only HTTP,
HTTPS, email, or fragment targets. Tool calls and their results become one
expandable row, matched by job, attempt, turn, and tool ID. Each row has a short
title, a status symbol and text, and expandable input and output. Recorded run
and reader-folder prefixes become relative paths in the display; other paths
and original event bytes remain unchanged. Thoughts are collapsed by default.
Agent messages, thoughts, and tool results use purple text on a light lavender
background in Summary and job logs. Job and agent labels identify the source
without relying on color; command logs keep their terminal and ANSI colors.

**Filter by job** and **Search activity** search the loaded Summary messages.
Job logs use **Search logs** across the selected attempt and scroll within
their panel. The Summary feed uses the page's vertical scroll. **Follow latest**
keeps new output visible while reading a live feed; opening a run leaves its
header and requests in view. Scrolling up stops following. **Jump to latest**
returns to the tail and resumes following. Filters and loading earlier output
also stop following so the page keeps the owner's reading position.

Pending owner requests appear above Summary and job logs in a yellow
**Waiting for you** banner. Each banner names the job, shows its question,
and has a **Respond** button that opens the response form in place and moves
keyboard focus to its first field. This applies to approvals, tool permissions,
and agent questions, including requests inside loops, child workflows, and
repair rounds. Request links open their form directly. A waiting coordinator
without a pending request uses neutral **Waiting** text. A dispatch pause uses
**New jobs paused**; a failed job keeps its error status.

The **Runs** tab and browser title show the count of waiting runs across
projects. Run history marks those runs with a waiting symbol and
**Waiting for you** text. Counts refresh every five seconds, when the window
gets focus, and when the open run's requests change. Selecting **Runs** from
Workflows opens a waiting run when one exists. The count depends on actual
pending requests, including those beyond a detail page's first 200 records.

**Help > Enable desktop notifications** asks for browser permission after
you choose it. Notifications report new waiting runs and run completion;
opening one selects its run. They contain no request text or provider output.
The choice is saved for this browser. **Disable desktop notifications** stops
them; a denied permission shows how to allow notifications in site settings.
The first attention read after opening Relay establishes a baseline, so old
completions do not produce notifications.

When an approval is pending, its response form includes review instructions
and retained material. At other times the panel is titled
**Changes and documents** and does not ask for a response.

When a step fails, Summary annotations show its name, the failure description
or exit code, and the provider's last public message when available.
**Show stopped step** opens that job's log and error, including when it is
already selected.
Provider quota notices and reset
times stay visible above Activity, including after a reload and in older runs
whose saved failure summary is empty. Reset times and time zones keep the
provider's wording. Relay does not infer subscription limits from context-token
usage or inspect private thoughts. When the provider supplies a structured,
rejected usage window and a confirmed future reset, the notice shows the
automatic retry time in your local time zone and offers **Cancel automatic
retry**. The next-action banner says Relay will retry automatically, so you
do not need to submit a manual retry. Relay's consumer resumes the same step
with its frozen settings; the
schedule survives a restart. Keep Relay running for it to execute when due.
The stream stays connected while that schedule is pending. A missing reset or
a recovery failure shows why automatic retry is blocked. Public prose-only
reset messages still require a manual retry.
Completed steps remain saved. Starting a retry clears the old failure notice;
a new failure shows its own cause. Long provider messages show a partial-text
notice, with their full recorded text available in Activity.

At a human review, instructions and the response requested by the workflow
appear beside retained reports and the committed source-to-run-head diff.
Choose a file in the changes viewer to see its additions, removals, and line
numbers. Syntax coloring helps distinguish code, and stronger highlights mark
changed words within edited lines. **Inline** shows edits in one column;
**Side by side** compares the before and after columns. **Wrap lines** keeps
long code inside the viewer; turn it off to scroll horizontally. Added and
deleted files show their single available column. **Full screen** gives the
comparison more space without submitting or clearing your review response.
Closing it returns keyboard focus to **Full screen**. Renames, mode changes,
and binary files remain listed, with Git metadata under **File details**.

**Show original patch** keeps the complete preview available as literal text,
including whitespace and Git headers. Source text is never executed or rendered
as HTML. For example, `<img src=x>` in an added line displays those characters.
If a patch ends inside a hunk or the comparison cannot load, its original text
appears with a notice. Reports remain plain text. All previews are bounded to
256 KiB. A truncated diff shows a warning. Counts and messages about absent text
changes apply only to the preview; a file may have further changes beyond it.
Download full reports when a preview is truncated; inspect the retained branch
under Advanced diagnostics for a full large diff. Relay does not guess or
submit the approval response.

Tool permission requests require an explicit offered decision. Simple agent
forms have typed fields; complex forms retain a JSON fallback. Optional
feedback is sent into the same live ACP session after its current turn ends.
This does not restart the worker or edit static instructions.

**Link to run** and **Link to request** include the project, run, and interaction.
Reload preserves the selection. A bare app URL restores the last selection.
An already answered request is identified, and current pending requests remain
visible. Answer submission includes the exact interaction ID, so a late
response cannot answer a newer request in the same attempt.

Stop work opens a dialog explaining that completed results remain available.
Confirmation creates one durable, idempotent control request and fans it out
to live attempts. A stale or duplicate answer cannot reach a later attempt. Manual
rerun is available only for a failed run and failed node; Relay preserves
evidence and creates a new attempt. A nested failed node also reopens its failed
loop or subworkflow parents, while successful siblings remain complete. An
interrupted run resumes automatically when `relay up` restarts, also as a new
attempt. Restart recovery never resumes an old provider session; feedback
during a live permission or elicitation pause continues that existing session.
Node completion leaves the live stream open. Only a run-level `succeeded`,
`failed`, or `canceled` event closes it. Interrupted runs keep their stream
open, and an accepted rerun reopens a completed stream without changing the
selected run. Events arriving in one browser frame update history together;
ordered pages merge without sorting the entire history for each event.

## History, artifacts, and cleanup

Relay automatically releases attempt scratch folders and surviving processes.
**Settings > Storage** exposes **Retry temporary resource cleanup** after you
choose a completed run. The list includes succeeded, failed, and canceled runs
from the selected project, with pagination for older runs. No run is selected
initially. Confirmation names the run and explains what stays. This touches
only marked folders from ended attempts; it keeps code, evidence, credentials,
and personal browser profiles. The server checks eligibility again, so a run
that starts retrying after selection cannot bypass its cleanup guard. See
[Run-owned resources](projects-and-storage.md#run-owned-resources).

History, snapshots, output, interactions, and artifacts remain until explicit
cleanup. **Settings > Storage** selects working copies, run references, run
history, or everything for the project. Nothing is selected initially;
deletion requires a confirmation dialog. Everything also requires typing the
project name. Relay rejects cleanup while any run for
the project is active. Worktree removal preserves evidence first, and cleanup
never changes the launch branch. A disposable reader left by an interruption
is removed before its primary run worktree. Run-record cleanup is rejected
until that run's worktree, retained branch, and attempt refs are gone; the
`all` scope applies the safe worktree, Git-ref, then record order.

## Browser support

Relay supports current desktop releases of Chrome, Edge, Firefox, and Safari.
The browser must support modules, `EventSource`, `crypto.randomUUID`, CSS grid,
and session storage. JavaScript and same-site cookies must be enabled. The UI
has responsive single-column layouts for narrow windows, but Phase 1 does not
target mobile browsers or expose a remote web service.

## Live events and replay

The run monitor connects to `GET /api/runs/{id}/stream` with an `EventSource`.
It sends the owner session when login is required; the same stream is available
without a session when login is disabled. Each frame has the durable database
event ID, the versioned event type, and one JSON event object:

```text
id: 17
event: agent.message
data: {"id":17,"payload":{"text":"Done."},"source":"agent","ts":"...","type":"agent.message","version":1}
```

The initial URL may contain `?since=17` when event pages already include ID 17.
The client keeps the last received ID. Reconnecting with
`Last-Event-ID: 17` returns only rows whose ID is greater than 17; the header
takes precedence over the URL cursor. Reads use the
indexed `(run, id)` order, at most 100 events per database batch, a 500 ms poll
cadence while a run remains active, and frames no larger than 65,536 bytes.
Provider and command output is split before persistence so visible bytes are
not truncated. A client ignores an event type or version it does not know.

Event types are internal identifiers. Relay defensively converts a carriage
return or newline in a stored event type to a space before framing it. For
example, `agent.message\nignored` becomes `agent.message ignored`; ordinary
`agent.message` is unchanged. The JSON payload still comes from the stored
event row.

The stream closes after replaying all events for a terminal run. A dropped
browser connection cancels the async generator. Django's ASGI request context
closes the request's database connections in their owning executor thread.
Paginated history remains available at
`GET /api/runs/{id}/events`.

## Automatic step recovery

**Automatic recovery** in Start work is off unless a workflow or saved owner
default enables it. Turn it
on, save, and launch to retry eligible agent failures up to twice. Select an
agent stage and turn off **Allow automatic retries for this step** to opt out.

The run view also has **Automatic recovery**, including for an already failed
run. Its policy override leaves the frozen workflow and prompts intact. It
shows **Preparing retry** while the run drains or the workspace is restored,
then **Retrying step — 1 of 2** when the same agent resumes. Unsafe failures
and an exhausted budget show their blocking reason. Turning recovery off
cancels queued error recovery. **Stop work** also cancels a pending retry.

Open **Automatic retry instruction** to read the exact added instruction,
source step, retry number, and decision state. The same model, effort, and
permissions are retained. Completed work stays complete; rejected reports
remain evidence. Changing a model through **Retry with settings** still uses
its separate handoff editor. Provider quota resets retain their own notice and
confirmed schedule. Automatic recovery never answers a declared human wait.

## Stage repairs

Select an agent or command stage in the editor and open **Repairs**. Enable
automatic repairs, choose the verdict output and accepted value, and set the
number of fix-and-verify rounds. Configure the **Fixer** and **Verifier** with
their own tools, exact models, effort, permissions, and instructions. Agent
settings start at the provider defaults. Report fields choose the retained
file and selector without requiring YAML edits.

Save unsaved prompt text before changing settings or closing the dialog. **Done**
returns to the workflow editor; **Save** validates and persists the policy.
Deleting a stage or choosing an action that cannot use repairs removes its
rule. Agent and command stages require the configured result output. See
[Stage repair rules](workflows.md#stage-repair-rules) for defaults and bounds.

The run map and stage list show the main stages. **Repairing** and **Repairs
stopped** identify a source stage whose repair work is active or failed. Open
the **Repairs** panel to inspect its round, budget, roles, instructions, and
child attempt statuses. Reports and activity remain available. Run settings
are captured; **Edit repairs for future runs** opens the editable workflow.
The panel shows saved settings for an unstarted or failed role, including
owner-selected model, effort, and permission overrides. Other role settings
are labeled as workflow defaults. A held repair shows **Repairs paused**.

An existing captured loop can be grouped through the
[repair presentation API](http-api.md#repair-presentation) while dispatch is
paused. This changes its display without changing prompts, attempts, outputs,
or execution order. Ordinary loops stay visible unless explicitly grouped.

## Supervisor and shutdown

The parent process owns one heartbeat-backed database lease and supervises two
children:

1. Uvicorn serves Django's HTTP, SSE, and packaged static files.
2. Huey runs with thread workers and a 15-second shutdown timeout.

Press Ctrl+C once to stop. Windows console-break requests follow the same
orderly shutdown path. Relay first writes a durable shutdown marker, closes
new-run admission, marks running and paused runs `interrupted`, and sends each active
attempt an `orderly_shutdown` cancellation request. On POSIX, Huey receives
`SIGINT`, its graceful signal. On Windows, Relay does not depend on a console
event that Huey 3.4.0 does not handle; workers observe the durable request and
the parent terminates the consumer within the same bound. A process that misses
the grace is force-stopped. Interrupted attempts in canceling runs settle as
canceled; other in-flight attempts are recorded as interrupted. Attempts that
finish successfully keep their outputs and protected commits, and failed
attempts keep their failure details.

An orderly restart preserves attempt evidence before resetting a writer or
removing a disposable reader worktree. It reopens each interrupted run and
creates a new attempt; it never resumes an old agent session. Failed attempts
remain failed unless the owner retries them or a confirmed provider-reset
schedule becomes due. A worker process that dies without the shutdown
marker is recorded as `worker_lost` and fails the run instead.
Runs already canceling retain that status and drain to `canceled` or `failed`,
including after restart. Relay never reopens work canceled by the owner.

Startup holds a lifetime kernel lock and checks the old supervisor's recorded
creation identity before recovering its abandoned web and worker children.
It signals only matching creation identities and leaves reused PIDs alone.
Verified attempt processes must exit before workspace recovery. Unknown
legacy identities remain untouched and can block recovery. See
[Restart after a lost supervisor](execution.md#restart-after-a-lost-supervisor).

Relay removes the supervisor lease and shutdown marker only after a clean stop.
If startup or shutdown reconciliation fails, retained state and the marker stay
available for the next bounded reconciliation pass. Full trace context is in
the platform-specific `relay-{pid}.log` files described in
[Projects and storage](projects-and-storage.md#central-paths).

## Actions layout and live job logs

The header keeps the current project and **Workflows** and **Runs** tabs.
Workflows have a sidebar, a file header, and the existing visual/YAML editor.
`view=workflows` is the canonical editor URL; older `view=author` links open
that view and update the URL. The Runs tab opens history. When a run needs a
response, it returns to that run; visiting Workflows preserves the current
waiting run so another request does not replace it. The history sidebar
selects all workflows or one workflow.
History rows show the captured title, permanent project run number, source
commit and branch, launcher, time, and duration. Search, status, and branch
filters apply on the server across history pages.

A selected run keeps one header and job sidebar across **Summary** and job
logs. The header shows the title and number, run controls, and refresh action.
**Re-run jobs** contains **Re-run all jobs**, which opens the existing fresh
launch panel. Failed runs also offer **Re-run failed jobs…**, which opens a
job chooser. Select a failed job and use its existing **Re-run job** control;
retries retain the runtime's single-job recovery rules. **Run settings**
contains automatic recovery. Paused jobs and repair settings keep their
existing controls.

Summary shows source, status, total duration, and artifact count above a
horizontal dependency graph. Equivalent parallel groups with more than five
jobs become one card with **Show all jobs**; its dialog opens any member's
log. Job lists still include each scope and iteration. The graph's wheel does
not intercept page scrolling. **Artifacts** is a visible summary section,
with the existing authenticated downloads and hashes. Annotations link to
failed jobs. Agent messages, approvals, repairs, and code review stay in the
same run.

Job logs use compact, collapsible sections and a **Search logs** toolbar.
The viewer automatically loads every public event page for the selected
attempt, merging it with the run's existing live stream by event ID. Search
covers all loaded output, including rows outside the visible viewport; the
history-loading notice remains visible until all pages arrive. Enter and
Shift+Enter move through matches, as do the next and previous buttons.
Command lines keep their number and ANSI colors. Only visible command rows
render, so a long log keeps streaming without a fixed line cutoff. Agent
conversations keep Markdown, collapsed thoughts, and combined tool results.
Selecting a search match opens its collapsed thought or tool details.

**Log options** offers timestamps, full screen, raw logs, copying, and a text
download. Full screen also responds to Shift+F while the log has focus; Escape
closes it. Downloads wait for complete history and preserve the command's
original output bytes, including ANSI codes. Search, scrolling away from the
bottom, or **Stop following** pauses automatic scrolling. **Jump to latest**
returns to the newest output and resumes following. Logs scroll within their
panel. Active run and job durations update each second and freeze at the
recorded end time; durations over an hour display hours, minutes, and seconds.

## Settings

The header's **Settings** tab opens `view=settings`. Its sidebar contains
**Global defaults**, **Project defaults**, **Server and account**,
**Notifications**, and **Storage**, using the same colors and typography as
the workflow and run views. The setup checklist stays hidden here.

Global defaults cover ordered agents, exact shared and per-agent models,
thinking effort, agent permissions, job timeouts, retry participation,
recovery budgets, working-copy cleanup, and defaults for new repair rules.
They also include **Shared commands** with a name, program, and one argument
per line, and **Environment variables** with name/value rows. Add and remove
controls edit the maps. **Advanced command arguments** accepts JSON for empty
arguments or newlines inside one argument. Variable values can span lines.
Duplicate names cannot overwrite another row. Server validation checks command
names, programs, and process environment values.
Project switches enable independent command and variable maps; removing every
row keeps an empty project override. Turning a switch off inherits global rows.
Model and option refreshes use the existing discovery endpoints. Changing an
agent model clears its options; provider choices preserve their descriptions
and exact values. Saved workflow choices take precedence as described in the
[inventory](projects-and-storage.md#global-defaults-and-project-overrides).

Project controls start disabled while inheriting their saved global value.
Turn on an override to edit it. Turning it off previews the inherited value
through the server before saving. Global and project saves have distinct
buttons, error states, and conflict recovery. Unsaved settings block tab and
project navigation and warn before closing the browser. **Discard changes**
restores the loaded values. **Reload settings** resolves stale edits.

Server and account displays the current account and active login policy.
Changes to login, loopback address, port, and workers show a restart notice;
startup flags still override saved choices. Notifications retain the existing
browser-specific permission and preference. Storage shows installation paths
and the selected project's sizes, counts, and confirmed cleanup controls.
All cleanup actions live in Storage, including retries for temporary run
resources. Run summaries, job logs, and advanced diagnostics have no cleanup
controls. Failed cleanup keeps its confirmation open with the Relay error;
canceling returns focus to the button. The completed-run list can be refreshed
or paged without changing the selected deletion category.

Run workflow leaves cleanup unspecified until you select an override, allowing
project/global defaults to apply. Job effort and permission menus offer
**Use project and global defaults** when saved agent defaults exist, plus
**Agent's default** to save an explicit null and skip inheritance for that
option. Existing YAML editing, leases, prompts, and launch validation remain
the source of workflow edits.

Command job forms, including fixer and verifier roles, offer **Command source**:
**Program and arguments** or **Shared command from Settings**. Shared commands
show their saved arguments. A missing name remains visible as **not configured**
and blocks launch. **Use inherited environment variables** and variable rows
edit the job's `inherit_env` and `env` in the same YAML document.
**Advanced workflow settings and YAML** has workflow variable rows and
**Use project and global environment variables**. YAML edits populate these
controls, and form edits update YAML. Arguments keep their literal boundaries;
no shell syntax is expanded. Settings changes affect future launches; existing
runs retain their resolved arguments and variables.

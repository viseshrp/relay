export const help = {
  project: [
    "Projects",
    "A project is a local Git repository. Switching projects changes the workflows and run history you see. It does not switch the repository’s Git branch.",
  ],
  workflows: [
    "Workflows",
    "Choose a saved workflow or create one from a starter. Each workflow describes its jobs, dependencies, instructions, and inputs. Save edits before starting a run.",
  ],
  runs: [
    "Runs",
    "A run captures the saved workflow, inputs, exact models, and instructions. Open a job to follow live output, search its logs, or answer a review request.",
  ],
  save: [
    "Save workflow",
    "Save validates the workflow and checks that its loaded file has not changed elsewhere. Recovery drafts are saved separately; they do not update the project file until you press Save.",
  ],
  stages: [
    "Workflow stages",
    "Select a stage in the list or canvas to edit it. Arrows show dependencies. A job becomes eligible only after its dependencies and conditions permit it to start.",
  ],
  agentOrder: [
    "Default agent order",
    "Job and workflow agent choices come first, followed by this order. Relay requires the same exact model from an available agent; it never substitutes a different model.",
  ],
  sharedModel: [
    "Shared default model",
    "Used when the job, run override, and workflow omit a model. Leave it blank to use the configured model of the first preferred agent. Values are exact and case-sensitive.",
  ],
  providers: [
    "Agent models and thinking",
    "Save one exact model per agent. Thinking effort and permissions inherit only for that same model. Changing a model clears its saved options. Unsupported choices block launch.",
  ],
  model: [
    "Model",
    "Choose a model advertised by an installed agent or enter its exact value. Loading models does not start a workflow. Relay checks model availability again when launching and executing.",
  ],
  instructions: [
    "Agent instructions",
    "Explain the task, required output, and acceptance checks. Instructions are saved in the project’s prompt files and captured at launch. Save changed instructions before saving or launching the workflow.",
  ],
  effort: [
    "Thinking effort",
    "Controls how much reasoning the selected agent uses, when it exposes this option. Choices come from that agent and exact model. Agent’s default leaves the override unset; native Antigravity includes effort in its model value.",
  ],
  permissions: [
    "Agent permissions",
    "Controls which actions the selected agent may take or must ask you to approve. Choices come from that agent. Review its description; choosing a model does not grant permissions.",
  ],
  commands: [
    "Shared commands",
    "Save a name with a program and argument list, then select that name in a command step. Each new run captures the resolved list. Relay executes arguments directly without a shell or shell expansion.",
  ],
  environment: [
    "Environment variables",
    "Defaults apply to command processes. Workflow, job, and step values take precedence. A project override replaces the whole global map. Ordinary values are stored locally and in run snapshots; use a secret binding to register output masking.",
  ],
  variableName: [
    "Variable name",
    "Use the name the program expects, such as TEST_MODE. Names must be nonempty and cannot contain an equals sign or a NUL character. Duplicate names are rejected.",
  ],
  variableValue: [
    "Variable value",
    "Passed as a literal string in the command’s environment. Relay does not expand references inside arguments or hide the value if the program prints it.",
  ],
  commandName: [
    "Command name",
    "A lowercase identifier such as test or build lets command jobs select this saved argument list. Renaming a command requires updating jobs that refer to its old name.",
  ],
  program: [
    "Program",
    "The executable to start, such as python or git. Arguments stay separate. Shell operators, variable references, and pipes are not interpreted.",
  ],
  arguments: [
    "Arguments",
    "Enter one argument per line. Spaces within a line stay in that argument. Use the advanced JSON array for exact empty arguments or arguments containing newlines.",
  ],
  timeout: [
    "Job timeout",
    "A limit for jobs that omit timeout-minutes. Use 30s, 15m, or 2h. Blank keeps workflow and provider limits. Human review deadlines remain explicit workflow choices.",
  ],
  autoRetry: [
    "Automatic job retries",
    "Lets eligible jobs participate in an enabled recovery policy. It does not enable recovery by itself. Jobs can opt out, and unsafe failures still stop for your review.",
  ],
  recovery: [
    "Automatic recovery",
    "Retries eligible failed agent steps within the configured budget. Captured models, permissions, original instructions, and completed work stay intact. Unsafe failures and exhausted budgets require your review.",
  ],
  retryLimit: [
    "Maximum automatic retries",
    "One or two extra attempts per eligible failed agent step. The budget does not reset after a restart or an owner retry. Command jobs are not automatically rerun by this policy.",
  ],
  cleanup: [
    "After a successful run",
    "Delete removes the working copy while retaining reports, commits, and history. Keep retains it. Merge fast-forwards the branch captured at launch, then removes working copies; a dirty, switched, or diverged checkout fails and retains the workspace.",
  ],
  override: [
    "Project overrides",
    "Turn an override on to edit this project’s value. Turn it off to inherit the current global value. Command and variable overrides replace the whole map. Changes apply to future launches.",
  ],
  login: [
    "Require login",
    "Requires this installation’s local owner account after Relay restarts. Disabling it allows anyone able to reach this computer’s loopback service to use the app. Accounts and retained data are preserved.",
  ],
  host: [
    "Loopback address",
    "The local address Relay listens on after restart. Only this computer’s loopback addresses are allowed: 127.0.0.1, localhost, or ::1. Startup flags can override the saved value.",
  ],
  port: [
    "Port",
    "The local TCP port used after restart, from 1 to 65535. Open the new address after changing it. Startup flags can override this saved value.",
  ],
  notifications: [
    "Desktop notifications",
    "Optional browser notifications for waiting and completed runs across projects. The browser asks for permission. This browser keeps its own preference; notifications omit questions and agent output.",
  ],
  storage: [
    "Storage",
    "Inspect installation folders and retained data. Cleanup requires explicit confirmation and ownership checks. Temporary-resource recovery is separate from deleting reports, Git refs, and run history.",
  ],
  onboarding: [
    "Welcome and guided tour",
    "The welcome slides and spotlight tour appear once in this browser. Skip or close to stop them. Replay either here, or reset both to show them on the next app opening. This does not change projects or runs.",
  ],
  stageType: [
    "Stage action",
    "Choose agent work, a command, human review, a conditional step, repeated steps, or another workflow. Changing the type changes the fields required by the workflow validator.",
  ],
  dependencies: [
    "Start after",
    "Jobs listed here must complete as required before this stage can start. Selecting multiple jobs joins their paths. Dependencies cannot create a cycle.",
  ],
  retry: [
    "Retry settings",
    "Choose the tool and exact model for this job’s new attempts. Relay checks availability and retains completed work, original prompts, and earlier attempts. Saving an upcoming job’s settings leaves the run paused.",
  ],
  temporaryCleanup: [
    "Temporary resource cleanup",
    "Retry removal of marked temporary folders for a completed run. Ownership checks preserve unrelated files, personal browser profiles, credentials, working copies, and retained evidence.",
  ],
  humanReview: [
    "Human review",
    "Explain what the owner should review and what response is expected. The run waits for an explicit answer attached to the current attempt; a tour or tooltip never answers it.",
  ],
  expression: [
    "Result expression",
    "A safe workflow expression controls a step condition or decides when a loop should stop. Expressions read declared inputs and outputs; they do not execute arbitrary code.",
  ],
  loop: [
    "Loop settings",
    "Repeat the declared body until its stop expression passes or the maximum iteration count is reached. Exhausting the bound fails the loop with its retained iteration results. The body calls a captured reusable workflow.",
  ],
  subworkflow: [
    "Child workflow",
    "Runs another saved workflow with its own jobs and variables, captured at launch. Its inputs and outputs must satisfy the declared mappings.",
  ],
  launch: [
    "Run workflow",
    "Launch uses the saved files and current branch to create a new immutable snapshot and isolated working copy. Preflight checks Git cleanliness, inputs, agents, and exact models before work starts.",
  ],
  entry: [
    "Start from job",
    "Only declared entry points are available. Relay validates their required inputs and retained reports; this is not a way to bypass missing upstream evidence.",
  ],
  logs: [
    "Job logs",
    "New public output streams into this view. Search highlights matching lines; pause following to read earlier output, then return to live logs. Agent messages and command output have distinct presentation.",
  ],
  workflowKey: [
    "Workflow file",
    "The path relative to .relay/workflows, including .yaml or .yml. Load opens that saved workflow. It does not rename the file or run its jobs.",
  ],
  inputs: [
    "Workflow inputs",
    "Values supplied to this run and captured in its snapshot. Required fields and declared types are validated before launch. The workflow can provide descriptions, defaults, and allowed choices.",
  ],
  pause: [
    "Pause and resume",
    "Pause stops new jobs from starting; running jobs finish. Resume lets eligible jobs start again. Pausing does not cancel work or answer a review request.",
  ],
  cancel: [
    "Cancel run",
    "Requests an orderly stop of this run's active work. Relay retains attempts, reports, and code evidence. Cancellation may take time while owned processes shut down.",
  ],
  rerun: [
    "Re-run jobs",
    "Re-run all jobs creates a new run from the saved workflow, current branch, previous inputs, and fresh preflight checks. Re-run failed jobs opens the existing run's failed jobs for explicit retry; successful upstream work stays complete.",
  ],
  artifacts: [
    "Artifacts",
    "Retained files from individual jobs and attempts. Downloads use the preserved bytes and recorded hashes, so they remain available after working-copy cleanup. A file's details identify its source and attempt.",
  ],
  bindingScope: [
    "Scope",
    "Where a variable or secret applies: every project, this project, or one environment. Project values override values for all projects, and an environment's values override the project's.",
  ],
  bindingEnvironment: [
    "Binding environment",
    "The environment whose jobs receive this value. A job uses an environment's values only when its environment field names it.",
  ],
  bindingName: [
    "Binding name",
    "The name workflows read as vars.<name> or secrets.<name>. Saving a name that already exists in this scope replaces its value.",
  ],
  bindingType: [
    "Binding type",
    "A variable is plain text that appears in run snapshots. A secret is masked in logs and its saved value is never shown again.",
  ],
  secretSource: [
    "Secret source",
    "Read the secret from an environment variable of the Relay process, or save it in this computer's credential store.",
  ],
  secretReference: [
    "Environment variable reference",
    "The name of the environment variable, in the Relay process, that holds the secret. Relay reads it when a run starts.",
  ],
  bindingValue: [
    "Value",
    "The text this name stands for. A secret value is written to the credential store and never returned to this editor.",
  ],
  environmentName: [
    "Environment name",
    "The name a job's environment field uses to pick these rules and values. Saving an existing name updates it.",
  ],
  environmentApproval: [
    "Require approval",
    "Jobs that use this environment wait for your approval before they start.",
  ],
  environmentWait: [
    "Wait timer",
    "Minutes a job that uses this environment waits before it starts. Zero starts it at once.",
  ],
  environmentBranches: [
    "Allowed branch patterns",
    "Branches whose runs may use this environment, one pattern per line. Leave it empty to allow every branch.",
  ],
  environmentUrl: [
    "Environment URL",
    "An optional link shown with jobs that use this environment, such as the address of a local server.",
  ],
  libraryName: [
    "Library workflow name",
    "The name this workflow is saved under in your library, where other projects can copy it from.",
  ],
  libraryDescription: [
    "Library description",
    "A short note shown with the saved workflow in the library.",
  ],
  libraryImport: [
    "Import workflow bundle",
    "Paste a bundle exported from a library. Importing adds it to your library; it does not change this workflow.",
  ],
  newJobType: [
    "New job type",
    "The kind of step the next job added with Add job starts with. Every type starts with values that validate; edit them in the job's Steps tab.",
  ],
} as const;
export type HelpTopic = keyof typeof help;

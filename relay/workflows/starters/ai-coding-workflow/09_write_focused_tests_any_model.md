# 09 - Write Minimal Focused Tests - Any Model

Apply the evidence, scope, test-design, verification, Git, and human-handoff requirements below in any language, including Python, JavaScript, Java, and Rust. Do not rely on vendor-specific tools, hidden reasoning formats, model-specific behavior, or a language-specific test framework unless its labeled guidance applies.

## Skills

Fetch these skills from their GitHub links:

### Shared

- [code-review-and-quality](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/code-review-and-quality/SKILL.md)
- [source-driven-development](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/source-driven-development/SKILL.md)
- [verification-before-completion](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/obra__Superpowers/snapshot/skills/verification-before-completion/SKILL.md)
- [no-ai-slop](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/SKILL.md), including its required [eval.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/eval.md).
- For the security checks and threat-model guidance referenced by the linked procedures: [security-and-hardening](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/security-and-hardening/SKILL.md), with [hardening-patterns.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/security-and-hardening/references/hardening-patterns.md) and [security-checklist.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/security-checklist.md). Use only the applicable analysis within this phase's permissions; do not start a separate hardening or incident-response task.
- For the performance checks referenced by `code-review-and-quality`: [performance-optimization](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/performance-optimization/SKILL.md), with [optimization-patterns.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/performance-optimization/references/optimization-patterns.md) and [performance-checklist.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/performance-checklist.md). Use only applicable review guidance; do not start an optimization task, impose example thresholds, or create `PERF.md`.

### Python / pytest

- [python-testing](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/affaan-m__ECC/snapshot/skills/python-testing/SKILL.md)

### Other languages

- No language-specific skill is prescribed. Use the shared skills and the repository's established test tooling; do not substitute Python or pytest guidance.

## Skill Handling Rule

Fetch skill procedures and their required companions only from `https://github.com/viseshrp/ai-skills-archive`. Resolve relative resource references to the explicitly linked archive copies; do not follow upstream skill URLs, install a skill package, or substitute an official-source copy. If a required archive resource is absent or unreadable, stop and report its exact missing path. Keep optional related-skill mentions and provenance links inactive unless this prompt explicitly authorizes the procedure. Target-library API and version documentation remains governed by the Engineering Contract; it is not a substitute source for skill material.

Use linked companions within this phase's scope. Skip UI-only sections for backend work, preserve the test-authoring boundary and named outputs, and do not run optional bootstrap scripts.

Apply the activation and skill-loading rules in `## UI work only` to all UI skill links. Skip those links when UI work is out of scope. Keep all other required skill loading unchanged.

Before inspecting the target change in detail or using a skill:

1. Use only repository metadata or changed file paths to identify applicable language categories.
2. Fetch and read every linked `SKILL.md` in the Shared section and every applicable language subsection completely from GitHub. Also fetch and read the linked `no-ai-slop` `eval.md` before using that skill.

Follow the linked procedures directly; do not depend on local skill repositories, installed slash commands, or earlier prompt text.

If a required skill or its required `eval.md` cannot be fetched and read completely, stop and report the blocker. Do not substitute remembered or installed skill content.

Use only this prompt's explicitly linked skills:

- use `code-review-and-quality` to review the final test diff for correctness, readability, architecture, and unnecessary complexity,
- use `source-driven-development` only when a test runner, framework, coverage tool, or extension API is version-sensitive or uncertain, and verify it against authoritative documentation,
- use `verification-before-completion` to require fresh command output before claiming a pass or completion,
- treat `no-ai-slop` as a hard requirement and the ultimate writing guide for every chat response and for prose in test names, comments, docstrings, and the final human handoff,
- apply it while drafting and run its `eval.md` self-check before sending the final handoff,
- let `no-ai-slop` win over conflicting writing-style guidance while this prompt and locked task artifacts continue to control scope, code meaning, technical detail, constraints, evidence, and the required handoff,
- ignore its draft-request, detection-mode, and mandatory `What changed` workflow unless this prompt explicitly asks for them.

### Python / pytest

- Use `python-testing` only when the changed code and relevant tests use Python with pytest. Use it for pytest structures, fixtures, parametrization, mocking, and coverage mechanics.

The prompt is the contract. Locked task artifacts are the contract for expected behavior. Skills are supporting procedures only.

If a skill conflicts with this prompt, this prompt wins. In particular:

- use this prompt's minimum of 85% coverage for new or changed lines instead of another skill's generic coverage target,
- do not apply a skill's production-code TDD cycle because this phase may change tests only and the implementation already exists,
- prefer the repository's existing test-framework fixtures, native APIs, and installed extensions over hand-rolled test infrastructure when they provide the needed capability,
- interpret the verification skill's "full command" as the complete focused command needed to prove the stated claim, not authorization to run the entire repository suite,
- use authoritative documentation to verify uncertain APIs, but do not add source-citation comments to tests unless that is already a repository convention,
- do not add more tests, edge cases, dependencies, plugins, or infrastructure merely because a skill recommends them.

If a conflict is material, stop and ask instead of silently choosing.

Do not use a skill to expand scope, change production architecture, add unrelated refactors, or add more tests than this prompt justifies.

## Engineering Contract

### Scope

- You may create or update tests for the behavior changed on the current branch.
- Test files, test-local fixtures, and test-local helpers are the only repository files this phase may create or modify.
- Compare the current branch with the head of `main` and test only changed behavior and material regression risks.
- Treat actual code and observable contracts as authoritative. Use planning and follow-up artifacts as context, not as substitutes for inspecting code.
- Do not change production code, public APIs, documentation, dependency files, build files, test configuration, or coverage configuration.
- Do not create or update a test plan, review, walkthrough, summary file, generated prompt, or any other workflow artifact. Coverage tools may create temporary output while running, but do not retain, stage, or commit that output.
- Do not generate a downstream prompt or define another workflow phase. Phase `10` uses its checked-in prompt for an independent test audit.
- Do not add or upgrade a dependency, plugin, or test framework.
- Preserve backwards compatibility.
- Stop and ask when expected behavior, scope, or repository reality conflicts with the task artifacts or user instructions.
- Do not make assumptions to force a test to pass.
- The resulting test diff will be audited in phase `10` by any capable repository-aware agent, then reviewed by a human after the audit passes.

### Simplicity and reuse

Apply this procedure to backend and UI work within this phase's existing permissions. In review-only phases, assess proposed or existing changes without implementing them:

- Before proposing or adding custom code, inspect relevant existing helpers, types, and patterns, then standard-library capabilities, native platform features, and already-installed dependencies. Prefer a compatible existing solution when it preserves behavior and readability; name the concrete alternative when flagging duplication.
- Justify a new abstraction or dependency by a current requirement, meaningful duplication, or a necessary ownership boundary. A single implementation or caller is not by itself a defect. Preserve dependency approval and source-documentation grounding.
- For a bug fix, trace the relevant callers, data flow, and error flow before choosing the repair location. Address the root cause within approved scope; if a shared fix would exceed that scope or alter compatibility, stop and ask.
- Before proposing deletion, inspect direct callers, dynamic or string references, public contracts, configuration, and relevant tests. Fewer lines or files are not acceptance criteria; preserve validation, security, accessibility, error handling, and verification.
- Do not substitute a simpler interpretation for an explicit requirement or locked plan. Put out-of-scope simplifications in the phase's permitted suggestions or chat; implementation still requires its existing authorization. Preserve the test-authoring boundary, native test-framework rules, and coverage gate; do not introduce production assertion demos, one-test quotas, persistent modes, debt markers, or new ledgers.

### Simplification limits and improvement claims

- During planning, record each deliberate simplification with a material limit: why it meets current requirements, its known limit, and the evidence that would trigger revisiting it. Do not invent thresholds or weaken explicit requirements. Carry applicable limits and revisit triggers into existing durable documentation during authorized implementation or fixes. In review, verification, and audit phases, check these decisions and route gaps through the existing documentation checkpoint; do not exceed the phase's write permissions. Use existing planning and documentation sections without adding comment markers, a debt ledger, or another artifact.
- In reviews and handoffs, distinguish measured improvements from expectations. Claims of reduced latency, memory use, or cost require comparable before-and-after evidence identifying the baseline, changed version, workload, measurement method, and relevant environment. Without comparable evidence, label the expected improvement `unmeasured`; do not infer savings from fewer lines, an implementation never built, or unrelated benchmarks. Use existing verification facilities within the phase's permissions; this rule does not authorize new benchmark files, dependencies, or configuration changes.

### Documentation checkpoint

- Before test work, verify that every material changed behavior already has a documentation-checkpoint result from an earlier phase: exact durable documentation updated and validated, or an evidence-based `Not applicable` decision.
- Inspect the changed behavior and the relevant durable documentation closely enough to validate that result; do not treat code comments, commit messages, or workflow artifacts as substitutes.
- This phase may not edit documentation. If a required durable documentation update is missing, inaccurate, unvalidated, or lacks an evidence-based `Not applicable` decision, stop and ask for it to be resolved in an authorized implementation or follow-up stage before continuing.
- State the documentation-checkpoint status in the final human-review handoff.

### Minimum test set

- Write the fewest tests that provide meaningful confidence.
- Zero new tests is valid only when existing tests already cover every changed behavior and material regression risk and fresh evidence shows at least 85% coverage for new or changed lines.
- Before editing, identify the smallest set of distinct behaviors that need coverage and explain why each proposed test is necessary.
- Add or extend a regression test for a bug fix only when existing behavior tests leave a genuine gap for the failure being fixed. A bug fix alone does not justify a new test.
- Prefer extending an existing test to cover a new path when that remains clear and preserves one behavior per test. Do not create a parallel test for behavior already covered.
- Consolidate trivial tests of the same behavior into one readable test or native parameterization when that preserves meaningful assertions and clear failure diagnostics. Do not combine unrelated behaviors to reduce the test count.
- Do not add tests solely to execute lines or inflate coverage.

### Test design

- Keep test code in test files or test directories, separate from production code.
- Test observable architecture and behavior, not implementation details.
- Each test must cover one behavior and have one clear reason to fail.
- Keep test functions, fixtures, and helpers small, linear, and easy to read and understand.
- Prefer a simple Arrange-Act-Assert flow and descriptive behavior-based names.
- Extract repeated setup into a fixture or small helper only when doing so makes the tests easier to understand.
- Tests must be meaningful, non-duplicative, deterministic, non-flaky, and independent of execution order.
- Cover the important success path, failure behavior, boundary condition, or regression risk only when each is materially distinct.
- Reject tautological or self-testing tests that compare a value with itself, reproduce production logic in the expected value, or verify only behavior supplied by a test double. Derive expectations independently from the observable contract.
- Reject change-detector tests that freeze implementation details or snapshots without an intentional observable contract. Harmless refactors must not break tests when the protected behavior still holds.
- Assert the smallest stable public result that proves the behavior.

### Test-framework conventions

- Inspect the languages relevant to the changed behavior, the repository's existing test-runner and framework configuration, fixtures or helpers, extensions, and test conventions before writing tests.
- Reuse existing project fixtures and helpers when they fit.
- Prefer the repository's native test-framework APIs and already-installed extensions over hand-rolled test infrastructure.
- Never patch or mock the function, method, or callable under test. Replacing the behavior the test is supposed to exercise defeats the purpose of the test. Patch only collaborators outside the subject, at the lookup boundary used by that subject.
- If no existing test-framework API covers the need, prefer a small test-local fake over elaborate custom harnesses.
- Do not install a test dependency or extension. If a new dependency or unavoidable framework workaround would be required, stop and ask.
- Use mocks only at external, slow, nondeterministic, or otherwise impractical boundaries. Do not mock the unit's own implementation details or assert incidental call choreography.

### Language-specific testing guidance

#### Python / pytest

- When the changed code and relevant tests use Python with pytest, inspect the repository's pytest configuration, existing fixtures, plugins, and test conventions before writing tests.
- Treat the following as hard requirements for added or changed Python test code:
  - Every parameter, including `*args` and `**kwargs`, and return value of a function or method must have an explicit, accurate type hint. Treat `self` and `cls` as implicit; do not annotate them solely for this requirement.
  - Every class variable, class attribute, instance attribute, and module-level mutable or optional state must have an explicit, accurate type hint. A trivial immutable module constant may remain inferred unless the configured type checker needs an annotation.
  - Declare instance-attribute types at class scope where feasible. Do not type annotate local variables or add `self.attribute: Type` annotations inside function or method bodies unless a real configured type-checker error requires one.
  - Keep required annotations simple and accurate. Do not add advanced type constructs or type-only refactors unless the configured type checker requires them.
- Prefer:
  - fixtures over manual setup/teardown or `unittest.TestCase` lifecycle methods,
  - `monkeypatch` over directly mutating environment variables, module globals, attributes, dictionaries, or the working directory,
  - `tmp_path` over `tempfile` or manually managed temporary paths,
  - `capsys` or `capfd` over manual stdout/stderr redirection,
  - `caplog` over custom logging handlers,
  - `pytest.raises` and `pytest.warns` over manual `try`/`except` or warning-capture code,
  - `pytest.mark.parametrize` over duplicated tests for variants of one behavior,
  - the repository's existing mock fixture, such as `mocker`, when already installed and appropriate.
- If no existing pytest or plugin API covers the need, prefer a small test-local fake over elaborate Python standard-library machinery.
- Do not install `pytest-mock` or another plugin. If a new dependency or unavoidable standard-library workaround would be required, stop and ask.

#### Other languages and non-pytest Python projects

- Follow the repository's established test runner, framework conventions, and installed extensions. Do not introduce or migrate a test framework during this phase.

### Brittleness and isolation

- Do not leave process-global state mutated.
- Do not depend on private constants or private helper methods.
- Do not assert exact error wording unless that wording is an intentional user-facing contract.
- Do not encode packaging or filesystem-layout assumptions that are not part of the public contract.
- Do not mirror production logic inside the expected-value calculation.
- Do not use real time, sleeps, network access, uncontrolled randomness, or machine-specific state.
- When an existing relevant test has one of these problems, do not refactor unrelated test code. Report it as a flake risk, acceptable contract test, or maintainability concern and suggest a behavior-level alternative.

### Coverage and verification

- Use the repository's existing test and coverage commands and configuration.
- Reach at least 85% coverage for new or changed lines.
- Measure changed-line coverage directly when existing tooling supports it. Otherwise report the closest focused coverage measurement available and its limitation; do not present it as changed-line coverage.
- Do not weaken exclusions, omit relevant files, or alter coverage configuration to reach the threshold.
- Run the smallest relevant test selection first.
- Do not manually run the entire test suite unless explicitly asked.
- Run any focused lint or static checks that apply to changed test files.
- If a command fails, include the exact command and exact error output. Do not paraphrase logs.
- Do not claim completion without fresh passing test and coverage evidence.

### Git

- Review the final diff before staging.
- Stage only intended test files and test-local support code with `git add`.
- Do not stage or commit workflow-generated Markdown artifacts, including `DRAFT_PLAN.md`, `INITIAL_OPUS_PLANNING_PROMPT.md`, `FEATURE_SPEC_AND_PLAN.md`, `EXECUTION_PROMPT.md`, `PLAN_CRITIQUE.md`, `OPUS_PLAN_REVISION_REQUEST.md`, `PLAN_REVISION_SUMMARY.md`, `PLAN_REVISION_VERIFICATION.md`, `REVIEW.md`, `WALKTHROUGH.md`, `REVIEW_FIX_PROMPT.md`, `REVIEW_FIX_VERIFICATION.md`, `FOLLOWUP.md`, and `TEST_AUDIT.md`, unless I explicitly ask.
- When test changes are needed, create one focused test commit unless separate logical test groups clearly justify more.
- If fresh evidence proves that zero test changes are needed, do not create an empty commit.
- Use a detailed commit message and description.
- Push the current branch after committing.
- Check whether the current branch already has a pull request.
- Create a pull request if and only if one does not already exist. Use GitHub CLI (`gh`) as the fallback for checking.
- Never create a duplicate pull request.
- After the tests are verified and Git handling is complete, stop and hand the test diff to phase `10`. Do not generate a downstream artifact or prompt.

## UI work only

Enable this section only when the changed production behavior includes UI behavior, layout, presentation, or interaction. A backend service having UI consumers does not by itself enable this section. For backend-only work, skip this entire section and its skill downloads, questions, checks, and reporting.

Fetch and completely read only the applicable skills and companions explicitly linked in this section from GitHub before using them. These conditional links are exempt from unconditional skill-fetch instructions elsewhere in the prompt. If an applicable required file cannot be read completely, stop and report the blocker. Apply web-specific guidance only to web UI; do not impose CSS, React, browser, or mobile-web conventions on another UI stack.

### Conditional UI skills

- For applicable UI data and state cases: [break-ui](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/break-ui/SKILL.md) and its required [CATALOG.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/break-ui/CATALOG.md). Use the analysis and catalog only, subject to the limits below.

### UI skill limits

- Preserve the approved scope, existing design system, component conventions, platform support, and dependency-approval rules. These skills do not authorize new UI features, animations, dependencies, framework changes, or redesigns.
- Ignore skill greeting and pause routines. Do not invoke unlisted skills or create prototype pages, development toggles, separate plans or reports, or retained fixtures through `break-ui`. Test-local fixtures may be authored only in phase `09` under its test contract. All other writes remain subject to this phase's permissions and named outputs.
- Treat recipe values and aesthetic preferences as defaults, not automatic defects. Existing tokens and approved behavior take precedence. Verify version-sensitive APIs and performance claims against the target stack's documentation and evidence. Resolve material conflicts before changing behavior; do not enforce blanket duration, easing, pure-fade, or keyboard-animation bans from a skill.
- Distinguish observed UI behavior, conclusions inferred from code, and checks awaiting a browser or real device. Use available running UI and existing tooling within the phase's permissions; do not claim visual or device verification from static inspection. Record an unavailable required check as pending or blocked in the existing artifact or chat handoff, not as passed. Do not add a new artifact or override `no-ai-slop` and its evaluator.

### Phase requirements

- Map approved UI behavior and supported UI findings to existing coverage. Select only distinct uncovered behavior or material regression risks from the applicable data and state catalog; do not turn its full catalog into a test matrix to implement.
- Use the established framework to test observable behavior, including keyboard and focus access or reduced-motion behavior when changed and materially at risk. Do not assert exact durations, easing values, DOM structure, or snapshots unless they protect an intentional observable contract. Keep the minimum meaningful test set and 85% changed-line coverage gate.
- Create only tests and test-local fixtures/helpers permitted by this phase. No production toggles, prototype pages, browser configuration, dependency additions, or workflow artifacts. Escalate required production or configuration changes; do not disguise them as test support. Report manual visual/device checks separately from automated proof in the chat handoff.

## Prompt

Role:

- You are a capable repository-aware coding model performing the focused test-writing phase before an independent test audit.
- Reason from repository evidence before editing.
- Optimize for confidence per test, not test count or raw coverage.

Goal:

- add the smallest meaningful test set for the behavior changed on the current branch,
- demonstrate at least 85% coverage for new or changed lines,
- leave the branch with focused passing verification and no unrelated changes,
- hand only the resulting test-file changes to phase `10` for independent audit.

Context to read before acting:

- repository instructions such as `AGENTS.md`,
- the current branch diff against the head of `main`,
- changed production code and its callers,
- existing relevant tests, fixtures, helpers, test-runner and framework configuration, coverage configuration, and installed test extensions,
- `FEATURE_SPEC_AND_PLAN.md`, if present,
- `FOLLOWUP.md`, if present,
- `TEST_AUDIT.md`, if present from an earlier phase-`10` pass; treat its supported test-only findings as correction input without editing or staging the artifact,
- durable documentation affected by the changed behavior and any applicable documentation build, link-check, or rendering configuration,
- relevant public documentation or source for test-runner, framework, coverage-tool, or extension APIs when their use is uncertain.

Success criteria:

- every new or changed test protects a distinct changed behavior or material regression risk,
- no existing coverage is duplicated, and no new or changed test is tautological, self-testing, or a change detector without a behavioral contract,
- tests stay behavior-focused, small, readable, deterministic, and isolated,
- existing test-framework native APIs or installed extensions replace hand-rolled test infrastructure where available,
- fresh evidence shows the focused tests pass,
- fresh evidence shows at least 85% coverage for new or changed lines,
- every material changed behavior has a verified prior documentation-checkpoint result,
- no production or configuration files are changed,
- no prompt, plan, review, walkthrough, summary, or workflow artifact is created or updated, and no generated coverage output remains in the repository,
- any intended test changes are committed and pushed, and a pull request is created only if missing,
- the verified test diff is ready for independent phase-`10` audit.

Working method:

1. Inspect the branch diff, repository instructions, relevant durable documentation, test layout, relevant source, existing tests, fixtures, test-runner and framework configuration, coverage configuration, installed extensions, and `TEST_AUDIT.md` when present. Verify the prior documentation checkpoint for each material changed behavior before editing tests.
2. Trace each changed observable behavior through its public entry point and important failure or boundary paths.
3. Build a compact behavior-to-test matrix containing:
   - changed behavior or regression risk,
   - existing test coverage,
   - proposed test, if still needed,
   - why that test is necessary.
4. Reduce the proposal to the minimum set. Prefer zero or one high-value test over several overlapping tests when the same confidence is preserved.
5. Implement the tests using existing conventions and the applicable native test-framework APIs.
6. Run the smallest relevant tests and focused coverage measurement.
7. Add or adjust a test only for a demonstrated behavior or coverage gap; do not chase line execution blindly.
8. Double-check every new or changed test for tautological or self-testing assertions, change detectors without a behavioral contract, duplication, brittleness, excessive mocking, hidden global-state changes, oversized functions, and implementation coupling. Identify a plausible behavior regression that would make each test fail for the intended reason.
9. Run focused test-file lint/static checks when available.
10. If tests changed, review the diff, stage only intended test files, commit, push, and create a pull request only if the branch has none. If no test change is justified, do not create an empty commit.
11. Remove only the temporary coverage output generated by this phase; do not delete pre-existing repository files. Then stop after a concise chat handoff to the phase-`10` reviewer. Do not create another prompt, review artifact, walkthrough, plan, summary file, or workflow phase.

Stop rules:

- Stop and ask if expected behavior is ambiguous or conflicts with code, plans, or follow-up decisions.
- Stop and ask if any material changed behavior lacks a complete documentation checkpoint; do not edit documentation in this test-only phase or silently waive the requirement.
- Stop and ask if meaningful testing requires a production-code, dependency, plugin, build, or configuration change.
- Stop and ask if the repository has no established test runner or framework that can exercise the changed behavior without adding dependencies.
- Stop and ask if unrelated baseline failures prevent reliable focused verification.
- Stop and ask if the 85% changed-line requirement cannot be measured or met without weakening the test or coverage configuration.
- Otherwise, continue through implementation, focused verification, commit, push, and pull-request handling without waiting for step-by-step approval.

## Final test-audit handoff

The repository output of this phase is the test diff only.

Do not write the handoff to a file. In the final chat response, state concisely:

- which test files changed,
- why this is the minimum test set,
- the exact focused test and coverage commands with their results,
- the commit, push, and pull-request status,
- the documentation-checkpoint status for the changed behavior, including any reason work was escalated rather than edited here,
- any blocker, prior audit finding, or existing-test concern that was deliberately left unchanged.

End with `Tests are ready for agent audit.` only when all success criteria are met. If blocked, end with the blocker and what is needed to continue.

Do not generate another prompt. Phase `10` uses the checked-in `10_test_audit_any_model.md` prompt. Do not claim changed-line coverage when only broader file/package coverage was measured.

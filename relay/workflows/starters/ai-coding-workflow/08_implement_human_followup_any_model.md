# 08 - Implement Human-Approved FOLLOWUP.md - Any Model

## Skills

- [incremental-implementation](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/incremental-implementation/SKILL.md)
- [source-driven-development](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/source-driven-development/SKILL.md)
- [verification-before-completion](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/obra__Superpowers/snapshot/skills/verification-before-completion/SKILL.md)
- [receiving-code-review](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/obra__Superpowers/snapshot/skills/receiving-code-review/SKILL.md)
- [no-ai-slop](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/SKILL.md), including its required [eval.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/eval.md)
- Required planning and incremental-verification companion: [definition-of-done.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/definition-of-done.md). Apply it within this phase's scope, artifact policy, and test-authoring boundary.
- For the security checks and threat-model guidance referenced by the linked procedures: [security-and-hardening](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/security-and-hardening/SKILL.md), with [hardening-patterns.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/security-and-hardening/references/hardening-patterns.md) and [security-checklist.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/security-checklist.md). Use only the applicable analysis within this phase's permissions; do not start a separate hardening or incident-response task.
- For the stack-discovery procedure referenced by `incremental-implementation`: [test-driven-development](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/test-driven-development/SKILL.md), including [testing-patterns.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/testing-patterns.md). Use only stack discovery and existing-test verification here; do not author tests or invoke its test-first implementation cycle. Apply JavaScript/TypeScript examples only to a matching stack.

## Skill Handling Rule

Fetch skill procedures and their required companions only from `https://github.com/viseshrp/ai-skills-archive`. Resolve relative resource references to the explicitly linked archive copies; do not follow upstream skill URLs, install a skill package, or substitute an official-source copy. If a required archive resource is absent or unreadable, stop and report its exact missing path. Keep optional related-skill mentions and provenance links inactive unless this prompt explicitly authorizes the procedure. Target-library API and version documentation remains governed by the Engineering Contract; it is not a substitute source for skill material.

Use linked companions within this phase's scope. Skip UI-only sections for backend work, preserve the test-authoring boundary and named outputs, and do not run optional bootstrap scripts.

Apply the activation and skill-loading rules in `## UI work only` to all UI skill links. Skip those links when UI work is out of scope. Keep all other required skill loading unchanged.

Use only this prompt's explicitly linked skills.

Fetch and read each linked skill and required companion completely from its GitHub URL before use. Follow the linked procedures directly; do not depend on local skill repositories, installed slash commands, or earlier prompt text.

The prompt is the contract. The locked task artifact is the contract for execution. Skills are supporting procedures only.

If a skill conflicts with this prompt, this prompt wins.

If a conflict is material, stop and ask instead of silently choosing.

Do not use any skill to expand scope, add architecture changes, add tests, add unrelated refactors, or override my explicit instructions.

`no-ai-slop` is mandatory for every Markdown document this phase creates or revises. Treat it as the ultimate writing guide and final authority for prose and presentation after satisfying this prompt's factual, technical, structural, and output requirements. If another skill or instruction conflicts only on writing style, `no-ai-slop` wins; this prompt and locked task artifacts still control scope, meaning, required structure, artifact names, constraints, and evidence.

Apply `no-ai-slop` while drafting and run its `eval.md` self-check before saving each Markdown artifact or sending the final response. If its `SKILL.md` or `eval.md` cannot be read and applied, stop before creating or revising Markdown and report the blocker. Ignore its draft-request, detection-mode, and mandatory `What changed` workflow unless this prompt explicitly asks for them.


## Engineering Contract

Apply this contract during planning, execution, review, and review fixes.

### Plan adherence

- If there is a plan, and only when a plan is provided by me explicitly, follow the plan exactly.
- No divergence.
- No creativity.
- No architecture changes.
- Just execute what is written.
- If the plan, code reality, or user request conflicts with another instruction, stop and ask.
- If you have questions, cannot make a decision, do not have enough context, or hit conflicts, DO NOT MAKE ASSUMPTIONS. STOP. ASK. GET CONFIRMATION. THEN PROCEED.

### Scope control

- Do not change, refactor, or reorganize unrelated code unless absolutely necessary.
- Put suggestions to improve surrounding code in a separate “Not Doing / Suggestions” section; do not implement them.
- Ignore DevOps, packaging, building, and test-related work unless otherwise specified in the plan or prompt.
- Keep UI changes within UI code unless the plan explicitly requires changes elsewhere.
- Match existing style guidelines.
- Do not write the changelog.

### Performance and complexity

- No time-based waiting hacks.
- No hacky retry loops.
- Check algorithmic time and space complexity.
- Use the best solution after weighing options.
- Do not choose brute-force methods or quadratic operations unless the plan explicitly justifies them and the data size makes them safe.
- Write readable code.
- Prefer readable code over overcomplicated performance or time-complexity optimizations.
- If a change I request reduces performance, stop and tell me before implementing it.
- Explain performance concerns in enough detail for a junior developer to understand.

### Dependencies, frameworks, and documentation grounding

- No third-party libraries without explicit approval.
- If a third-party library is approved, verify library/framework usage against the correct documentation; ground 100% of usage in those docs.
- Always ground development work involving libraries 100% in documentation with zero assumptions.
- If documentation is poor and the library is open source, find its source code, clone it in a temporary folder, and read it thoroughly to supplement the documentation.
- Ensure usage follows the latest APIs.
- Flag outdated APIs.
- Check that library/framework usage is necessary and justified.

### Public APIs and exceptions

- Backwards compatibility is top priority.
- Changes in user-facing APIs must be backwards compatible, unless the app version is unreleased.
- If a third-party library is used in a public-facing API, the user should never see library/framework-specific exceptions raised.
- Use custom errors/exception classes instead. Reuse existing classes in the codebase or create custom ones if needed.
- Do not chain exceptions when doing so would expose implementation/library details to users.
- If logging is used and available, log the trace with the logger for debugging.
- If changes touch public APIs or add new public APIs, ensure they are user-friendly, intuitive, blend well with the existing public API set, and have appropriate names.

### Code quality and maintainability

- Use the target language and its standard library idiomatically.
- Reuse existing code wherever possible.
- Keep code DRY.
- Follow separation of concerns.
- Follow the single responsibility principle.
- Use proper imports.
- Do not load files as blobs and execute the code within another block of code.
- Use assert statements only in test files, never in production code.
- Surface all assumptions.
- If changes reinvent or duplicate something already in the source code, stop and flag it.
- Do not hardcode numbers, versions, or other constants. Reuse existing constants, or create new constants in the right places and reuse them appropriately.

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

### Types

- When adding types, use correct ones.
- Keep type declarations and annotations proportionate and readable. Do not use deeply nested, repetitive, or unnecessarily complex annotations that crowd code or obscure intent; prefer the simplest accurate type or a well-named type alias when that is clearer.
- Do not use filler types.
- Do not use overly generic types just to satisfy a checker.
- Do not use type-ignore comments to pass CI temporarily.
- Do not use `typing.Cast` or other casts merely to satisfy type checkers.

### Python

Apply this subsection only when the target repository uses Python.

The following typing coverage is a hard requirement:

- Every parameter, including `*args` and `**kwargs`, and return value of an added or changed function or method must have an explicit, accurate type hint. Treat `self` and `cls` as implicit; do not annotate them solely for this requirement.
- Every added or changed class variable, class attribute, instance attribute, and module-level mutable or optional state must have an explicit, accurate type hint. A trivial immutable module constant may remain inferred unless the configured type checker needs an annotation.
- Declare instance-attribute types at class scope where feasible; do not add `self.attribute: Type` annotations inside a method merely to satisfy this requirement.
- Do not type annotate local variables inside function or method bodies. Rely on inference; add a local annotation only to resolve a real configured type-checker error.
- Keep required annotations simple and accurate. Do not add advanced type constructs or type-only refactors unless the configured type checker requires them.

### Comments and documentation

- Document every added or changed string transformation with concrete examples showing representative input and expected output.
- Always add brief, detailed comments where they help readers understand the code with little effort.
- Comments must help readers understand the code with little effort.
- Comments must address the code itself, not be meta commentary about the task.
- Cleaning up stale comments is encouraged.
- Ensure every non-obvious change has an explanatory comment.
- Avoid bloated comment blocks. Include enough detail for junior engineers to understand easily.
- Always update related documentation.
- Find the correct docs folder by tracing GitHub Actions workflows, Makefiles, or other docs-build configuration.
- Append to the appropriate sections, or create new ones if required.
- Do not write the changelog.

### Documentation checkpoint

- Complete a documentation checkpoint at every planning, implementation, review, verification, and handoff stage.
- Before a checkpoint can pass, identify the user-, operator-, API-, configuration-, or developer-facing documentation affected by the planned or changed behavior.
- Require the exact durable documentation files/sections, their in-change-set update, and applicable docs build, link check, rendering check, or focused validation; if no durable documentation change is needed, require an evidence-based `Not applicable` decision.
- Code comments, commit messages, and workflow artifacts do not substitute for durable documentation. Do not write the changelog unless explicitly requested.

### Cross-platform behavior

- All changes must be strictly cross-platform and must work on both Linux and Windows.
- Mac is not a concern.

### Git and verification

- Commit often in small increments when committing is allowed.
- Split large commits into sensible parts.
- Add detailed commit messages.
- Explain the work in commit descriptions with as much detail as needed; no length limit.
- Do not claim work is complete without fresh verification evidence.
- Run linter and smoke test if any on every commit, unless the prompt explicitly forbids command execution.
- If a command fails, paste the exact error/log back. Never paraphrase logs.

### Tests

- Do not create, modify, or delete tests in this follow-up implementation phase.
- Run only focused existing tests or checks needed to verify approved production changes; do not manually run the entire suite.
- If `FOLLOWUP.md` contains test-authoring work, leave that work for the dedicated model-agnostic `09_write_focused_tests_any_model.md` phase and state the deferral in the handoff.
- Phase `09` exclusively owns the detailed test-authoring contract.

## UI work only

Enable this section only when the approved task or reviewed change includes UI behavior, layout, presentation, or interaction. A backend service having UI consumers does not by itself enable this section. For backend-only work, skip this entire section and its skill downloads, questions, checks, and reporting.

Fetch and completely read only the applicable skills and companions explicitly linked in this section from GitHub before using them. These conditional links are exempt from unconditional skill-fetch instructions elsewhere in the prompt. If an applicable required file cannot be read completely, stop and report the blocker. Apply web-specific guidance only to web UI; do not impose CSS, React, browser, or mobile-web conventions on another UI stack.

### Conditional UI skills

- Only for eligible visual web surfaces under the frontend design gate: [design-taste-frontend](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/Leonxlnx__taste-skill/snapshot/skills/taste-skill/SKILL.md).
- For web UI design decisions: [emil-design-eng](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/emil-design-eng/SKILL.md).
- For applicable UI data and state cases: [break-ui](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/break-ui/SKILL.md) and its required [CATALOG.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/break-ui/CATALOG.md). Use the analysis and catalog only, subject to the limits below.
- When implementing web motion: [animate](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/animate/SKILL.md) and its required [RECIPES.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/animate/RECIPES.md).
- Only when motion work requires choosing a web UI primitive: [pick-ui-library](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/pick-ui-library/SKILL.md), the procedure referenced by `animate`. Use it to evaluate existing options; new dependencies still require explicit approval.
- When mobile-web behavior is in scope: [mobile-native](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/mobile-native/SKILL.md). Use it for planning or review only in phases that prohibit implementation.

### Frontend design gate

Apply `design-taste-frontend` only to landing or marketing pages, portfolios, editorial or brand pages, and explicitly approved visual redesigns of those surfaces. Exclude backend-only work, dashboards, admin or dense product interfaces, data tables, multi-step forms, native mobile UI, and general refactors. For mixed work, apply it only to the eligible surface; other UI skills keep their own activation rules.

The user request, locked planning artifacts, existing brand and design system, repository conventions, accessibility, SEO, analytics, and approved dependencies override every skill default. The skill cannot authorize new dependencies, framework or design-system changes, generated assets, added motion or color modes, route or slug changes, primary-navigation or form-field changes, analytics-event changes, content or information-architecture rewrites, or architecture or scope expansion.

Treat its dials, font and palette bans, layout recipes, and content or motion preferences as suggestions unless the approved contract requires them. Use only relevant objective preflight checks. A preference alone is not a blocking or non-blocking defect that requires a fix.

Do not activate `gpt-taste`. Specialized sibling skills such as `image-to-code`, `brandkit`, or `redesign-existing-projects` require explicit task-specific authorization and their own archive links; do not load them through this skill.

For ineligible UI work, skip this skill's download and procedures and record `Frontend design: Not applicable` in the existing artifact or chat. Backend-only work skips this entire UI section, including that reporting.

### UI skill limits

- Preserve the approved scope, existing design system, component conventions, platform support, and dependency-approval rules. These skills do not authorize new UI features, animations, dependencies, framework changes, or redesigns.
- Ignore skill greeting and pause routines. Do not invoke unlisted skills or create prototype pages, development toggles, separate plans or reports, or retained fixtures through `break-ui`. Test-local fixtures may be authored only in phase `09` under its test contract. All other writes remain subject to this phase's permissions and named outputs.
- Treat recipe values and aesthetic preferences as defaults, not automatic defects. Existing tokens and approved behavior take precedence. Verify version-sensitive APIs and performance claims against the target stack's documentation and evidence. Resolve material conflicts before changing behavior; do not enforce blanket duration, easing, pure-fade, or keyboard-animation bans from a skill.
- Distinguish observed UI behavior, conclusions inferred from code, and checks awaiting a browser or real device. Use available running UI and existing tooling within the phase's permissions; do not claim visual or device verification from static inspection. Record an unavailable required check as pending or blocked in the existing artifact or chat handoff, not as passed. Do not add a new artifact or override `no-ai-slop` and its evaluator.

### Phase requirements

- Use `design-taste-frontend` only for an explicitly human-approved eligible item in `FOLLOWUP.md`. That item, the existing brand/design system, and any locked `Frontend Design Contract` bound the change; do not redesign adjacent surfaces or add unapproved work.
- For eligible follow-up changes, verify the affected rendered desktop/mobile viewports with existing tooling. In the final response's `## Frontend Design Verification`, record the approved item or contract, viewports, tooling, rendered results, responsive and accessibility checks, protected behavior, and pending checks alongside the documentation checkpoint.
- Implement only the approved UI behavior using existing components and tokens. Complete applicable loading, error, and empty states, keyboard, focus, and touch behavior, and realistic data handling from the plan or accepted finding.
- For approved motion, implement its purpose and frequency decision, interruption and exit behavior, reduced-motion alternative, and hover capability gating where relevant. Use the simplest compatible existing tool; no library is required merely for a fade.
- Verify the changed UI with applicable realistic data, container widths, zoom, supported locale/direction, keyboard/touch interaction, and rapid interruption. Verify mobile viewport, safe-area, scrolling, and input behavior when in scope. Use existing preview/data facilities; do not create tests or a dev toggle. Report observed results and any required device checks still pending in the existing handoff, alongside the documentation checkpoint.
- `FOLLOWUP.md` remains the sole authorization for changes. Do not use UI checks to add unapproved work; report new concerns and preserve the existing test-authoring deferral to `09`.

## Prompt

Goal:

- execute the human-approved `FOLLOWUP.md` items end-to-end and stop only when you have a verified result or a concrete blocker.

Success criteria:

- only approved `FOLLOWUP.md` items are implemented,
- each completed item is checked off only after the change and its verification are done,
- the smallest correct changes are made,
- each completed `FOLLOWUP.md` item completes its documentation checkpoint: applicable durable documentation is updated and validated in the same change set, or an evidence-based `Not applicable` decision is reported,
- focused verification is run and reported with fresh evidence,
- any workflow-generated Markdown artifacts created or updated during the workflow remain in the target repo root and are never moved to subdirectories or alternate paths,
- any workflow-generated Markdown artifacts created or updated during the workflow include `Created by`, `Created at`, and `Updated at` metadata with `Updated at` refreshed on every edit,
- scope stays limited to the approved follow-up work,
- verification evidence is reported clearly,
- workflow-generated Markdown artifacts are not staged or committed unless I explicitly ask for that,
- if committing is allowed, each commit strictly corresponds to one approved `FOLLOWUP.md` item and does not mix work from multiple follow-up items,
- if committing is allowed, commits are small, focused, and split into sensible parts rather than one broad commit,
- the final execution flow stages changes, commits them, pushes the branch, and creates a pull request only if the current branch does not already have one,
- no AI review loop is restarted after this phase; the workflow proceeds to the final focused test-writing phase.

Context to read before acting:

- `REVIEW.md`,
- `WALKTHROUGH.md`,
- `FOLLOWUP.md`,
- `FEATURE_SPEC_AND_PLAN.md`, if present,
- current branch diff against `main`.

Execution posture:

- work autonomously: gather context, implement, run the smallest relevant checks, refine, then report,
- understand the context of the current PR before editing,
- read all likely relevant files in parallel before editing when that shortens the loop,
- prefer dedicated repo/search/edit tools over raw shell when available,
- keep progressing until you have a verified result or one of the stop conditions below.

Constraints:

- `FOLLOWUP.md` is the execution contract for this phase,
- `REVIEW.md` and `WALKTHROUGH.md` are reference context only,
- workflow-generated Markdown artifacts belong only in the target repo root using their exact required filenames,
- workflow-generated Markdown artifacts must include `Created by`, `Created at`, and `Updated at` metadata, preserving the creation fields after first write and updating `Updated at` on every edit,
- address all items in `FOLLOWUP.md` and check them off the list,
- only implement items that are explicitly present in `FOLLOWUP.md`,
- before checking off an item, complete the documentation checkpoint specified by that item; if it is missing or ambiguous, stop and ask instead of silently treating documentation as `Not applicable`,
- do not add new follow-up items,
- do not expand scope,
- do not implement optional suggestions unless they are explicitly in `FOLLOWUP.md`,
- follow the approved `FOLLOWUP.md` items exactly,
- no divergence,
- no creativity,
- no architecture changes,
- just execute what is written.

Stop rules:

- implement end-to-end with no interruptions unless one of the following conditions is true,
- stop and ask if there is a conflict in decisions,
- stop and ask if a required decision was never made,
- stop and ask if a `FOLLOWUP.md` item is wrong, stale, ambiguous, conflicts with the current code, or needs a design decision,
- stop and ask if following `FOLLOWUP.md` would create a performance, backwards-compatibility, security, or public-API problem,
- stop and ask if you do not have enough context,
- if a missing credential, external dependency, or environment precondition blocks verification, say exactly what blocked you,
- if any of those happens, stop and ask. Do not assume.
- otherwise do not stop at analysis.

Execution rules:

- before completion, check the full diff of this implementation pass against the Engineering Contract and approved scope,
- inspect all changes made by this follow-up pass for possible regressions, including indirect effects on existing callers, behavior, compatibility, and error paths. Fix regressions within the approved `FOLLOWUP.md` items; stop and ask if a fix would exceed them,
- inspect the changes made by this pass for added or changed meta content wherever it appears, including in comments, docstrings, durable documentation, or user-facing text: descriptions of the branch, task, implementation process, or the fact that a change was made instead of the resulting code or behavior. Remove or rewrite it within the approved scope,
- read likely relevant files in parallel before editing when practical,
- prefer dedicated repo/file/edit/search tools over raw shell when available,
- carry through context gathering, implementation, focused verification, and refinement without waiting for step-by-step approval unless blocked,
- work in small increments,
- if committing is allowed, each commit must map to exactly one approved `FOLLOWUP.md` item,
- if committing is allowed, commit often in small focused increments,
- do not bundle multiple follow-up items, partial work for unrelated items, or unrelated cleanup into the same commit,
- split large commits into sensible smaller focused parts,
- use detailed commit messages and descriptions,
- do not make unrelated refactors,
- do not create, modify, or delete tests in this phase; defer test-authoring items in `FOLLOWUP.md` to `09_write_focused_tests_any_model.md` and report the deferral in the handoff,
- run focused verification relevant to the approved follow-up items,
- run linter and smoke test if any on every commit, unless command execution is unavailable or explicitly disallowed,
- if a command fails, paste the exact error/log back. Never paraphrase logs.
- before marking each approved item complete, update and validate the exact durable documentation in the same change set, or report the item's evidence-based `Not applicable` decision,
- do not substitute code comments, commit messages, or workflow artifacts for durable documentation,
- do not write the changelog,
- after verification, stage the intended files with `git add`,
- do not stage or commit workflow-generated Markdown artifacts by default, including `DRAFT_PLAN.md`, `INITIAL_OPUS_PLANNING_PROMPT.md`, `FEATURE_SPEC_AND_PLAN.md`, `EXECUTION_PROMPT.md`, `PLAN_CRITIQUE.md`, `OPUS_PLAN_REVISION_REQUEST.md`, `PLAN_REVISION_SUMMARY.md`, `PLAN_REVISION_VERIFICATION.md`, `REVIEW.md`, `WALKTHROUGH.md`, `REVIEW_FIX_PROMPT.md`, `REVIEW_FIX_VERIFICATION.md`, `FOLLOWUP.md`, and `TEST_AUDIT.md`, unless I explicitly ask for them to be committed,
- create focused commit(s) with detailed messages,
- push the current branch after committing,
- check whether the current branch already has a pull request before creating one,
- create a pull request if and only if the current branch does not already have one,
- if unsure how to check whether the current branch already has a pull request, use GitHub CLI (`gh`) to determine that,
- do not create a duplicate pull request for the same branch,
- do not create a new AI review prompt,
- do not run another AI review in this phase,
- keep interim narration minimal and save the full report for the final response unless blocked.

After this phase, I will run `09_write_focused_tests_any_model.md` with any capable repository-aware model. That phase may change test files only and must not create another prompt or workflow artifact. I will then run `10_test_audit_any_model.md` with any capable repository-aware agent before I review the audited test diff myself.

## Required final response

For eligible frontend follow-up changes, insert `## Frontend Design Verification` after `## Verification Evidence` and include the evidence required by the UI section. Omit that additional section for other work.

```markdown
# Human Follow-Up Implementation Summary

## What Changed

## Files Changed

## FOLLOWUP.md Items Completed

## Verification Evidence

## Documentation Checkpoints

## Commits Created

## Push Status

## Pull Request

## Not Done / Blocked

## Suggestions Not Implemented Because Out Of Scope

## Remaining Manual Review Notes
```

In `## Commits Created`, list each commit together with the exact `FOLLOWUP.md` item it corresponds to.

In `## Documentation Checkpoints`, list each completed `FOLLOWUP.md` item's documentation status, the exact durable documentation and validation evidence when applicable, or the evidence-based `Not applicable` rationale.

Do not claim completion without fresh verification evidence.

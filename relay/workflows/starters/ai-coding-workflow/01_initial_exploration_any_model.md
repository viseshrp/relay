# 01 — Initial Exploration / Grilling / Interviewing + Opus Planning Prompt Generation — Any Model

## Skills

- [interview-me](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/interview-me/SKILL.md)
- [grill-me](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/mattpocock__skills/snapshot/skills/productivity/grill-me/SKILL.md)
- [grilling](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/mattpocock__skills/snapshot/skills/productivity/grilling/SKILL.md), the required procedure called by `grill-me`. Read and apply it directly, keeping this prompt's one-question-at-a-time rule.
- [idea-refine](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/idea-refine/SKILL.md)
- [context-engineering](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/context-engineering/SKILL.md)
- [no-ai-slop](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/SKILL.md), including its required [eval.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/eval.md)
- Required `idea-refine` companions: [frameworks.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/idea-refine/frameworks.md), [refinement-criteria.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/idea-refine/refinement-criteria.md), [examples.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/idea-refine/examples.md).

## Skill Handling Rule

Fetch skill procedures and their required companions only from `https://github.com/viseshrp/ai-skills-archive`. Resolve relative resource references to the explicitly linked archive copies; do not follow upstream skill URLs, install a skill package, or substitute an official-source copy. If a required archive resource is absent or unreadable, stop and report its exact missing path. Keep optional related-skill mentions and provenance links inactive unless this prompt explicitly authorizes the procedure. Target-library API and version documentation remains governed by the Engineering Contract; it is not a substitute source for skill material.

Use linked companions within this phase's scope. Skip UI-only sections for backend work, preserve the test-authoring boundary and named outputs, and do not run optional bootstrap scripts. When `spec-driven-development` is explicitly linked, use only its specification and planning procedures; do not invoke its implementation-stage skills. When this phase generates a downstream prompt, embed this archive-only rule, every applicable explicit skill and companion link, and the same scope limits.

Apply the activation and skill-loading rules in `## UI work only` to all UI skill links, including generated-prompt templates. Skip those links when UI work is out of scope. Keep all other required skill loading unchanged.

Use only this prompt's explicitly linked skills.

Fetch and read each linked skill and required companion completely from its GitHub URL before use. Follow the linked procedures directly; do not depend on local skill repositories, installed slash commands, or earlier prompt text.

The prompt is the contract. The locked task artifact is the contract for execution. Skills are supporting procedures only.

If a skill conflicts with this prompt, this prompt wins.

If a conflict is material, stop and ask instead of silently choosing.

Do not use any skill to expand scope, add architecture changes, add tests, add unrelated refactors, or override my explicit instructions.

`no-ai-slop` is mandatory for every Markdown document this phase creates or revises. Treat it as the ultimate writing guide and final authority for prose and presentation after satisfying this prompt's factual, technical, structural, and output requirements. If another skill or instruction conflicts only on writing style, `no-ai-slop` wins; this prompt and locked task artifacts still control scope, meaning, required structure, artifact names, constraints, and evidence.

Apply `no-ai-slop` while drafting and run its `eval.md` self-check before saving each Markdown artifact or sending the final response. If its `SKILL.md` or `eval.md` cannot be read and applied, stop before creating or revising Markdown and report the blocker. Ignore its draft-request, detection-mode, and mandatory `What changed` workflow unless this prompt explicitly asks for them.

## Documentation checkpoint

Complete a documentation checkpoint during planning. During exploration, identify the documentation impact of each likely implementation step and carry it into both generated planning artifacts as an exact durable documentation update and validation, or an evidence-based `Not applicable` decision.

Apply the Engineering Contract's Simplicity and reuse procedure during exploration for both backend and UI work. Do not implement changes.

## UI work only

Enable this section only when the requested or planned work includes UI behavior, layout, presentation, or interaction. A backend service having UI consumers does not by itself enable this section. For backend-only work, skip this entire section and its skill downloads, questions, checks, and reporting.

Fetch and completely read only the applicable skills and companions explicitly linked in this section from GitHub before using them. These conditional links are exempt from unconditional skill-fetch instructions elsewhere in the prompt. If an applicable required file cannot be read completely, stop and report the blocker. Apply web-specific guidance only to web UI; do not impose CSS, React, browser, or mobile-web conventions on another UI stack.

### Conditional UI skills

- Only for eligible visual web surfaces under the frontend design gate: [design-taste-frontend](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/Leonxlnx__taste-skill/snapshot/skills/taste-skill/SKILL.md).
- For web UI design decisions: [emil-design-eng](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/emil-design-eng/SKILL.md).
- For applicable UI data and state cases: [break-ui](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/break-ui/SKILL.md) and its required [CATALOG.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/break-ui/CATALOG.md). Use the analysis and catalog only, subject to the limits below.
- Only when a requested motion effect needs clarification: [animation-vocabulary](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/animation-vocabulary/SKILL.md).
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

- For an eligible surface, record the page kind, audience, visual direction and references, existing brand/assets, preserve-versus-overhaul mode, required design decisions, asset policy, protected behavior, approved dependencies, and desktop/mobile validation viewports in `DRAFT_PLAN.md`. Carry them into `INITIAL_OPUS_PLANNING_PROMPT.md` so planning locks a dedicated `## Frontend Design Contract` in `FEATURE_SPEC_AND_PLAN.md` before execution.
- For each affected UI surface, specify applicable loading, error, empty, partial-data, and permission states; realistic or schema-backed long or missing values, Unicode, and zero, one, or many items; container widths, zoom, and supported locales. Resolve choices such as wrapping versus truncation before locking implementation. Do not require every catalog case for every component.
- Specify keyboard, focus, and touch behavior, existing components and tokens to reuse, and applicable mobile viewport, safe-area, scrolling, and input behavior. For motion, record its purpose, frequency, interruption and exit behavior, reduced-motion alternative, and acceptance checks. Preserve feedback and access without requiring animation.
- Put these decisions, verification steps, and documentation impact in the existing planning artifacts. Keep unresolved design decisions explicit. Do not build prototypes, change UI code, or author tests during planning.
- Carry the resolved UI decisions into `DRAFT_PLAN.md` and `INITIAL_OPUS_PLANNING_PROMPT.md`.

## Prompt

Goal:

- turn a vague or partially formed idea into a concrete draft plan and an actionable Opus planning prompt,
- surface scope, constraints, non-goals, risks, and definition of done before planning is locked.

Success criteria:

- the intended outcome is concrete enough that Opus will not need to guess,
- the important constraints, risks, and non-goals are explicit,
- every material question is either answered from repo/context exploration or explicitly resolved with me before artifacts are finalized,
- `DRAFT_PLAN.md` preserves anything Opus must not lose,
- `INITIAL_OPUS_PLANNING_PROMPT.md` is the final paste-ready Opus planning prompt for the main planning phase,
- both generated artifacts are created in the target repo root using the exact required filenames and nowhere else,
- this phase stops at `DRAFT_PLAN.md` and `INITIAL_OPUS_PLANNING_PROMPT.md`; it does not perform the Opus planning phase itself.

Constraints:

- do not implement code,
- do not write tests,
- do not create unrelated files,
- create workflow-generated Markdown artifacts only in the target repo root using the exact required filenames,
- every workflow-generated Markdown artifact must include `Created by`, `Created at`, and `Updated at` fields,
- use only the linked skills as supporting procedures.

Working method:

- work interactively first,
- keep collaboration practical and outcome-first; explain decisions in enough depth,
- ask only when the answer would materially change the plan,
- if a question can be answered by exploring the codebase or provided context, explore first instead of asking me,
- if your environment supports repo exploration and parallel context gathering, gather the most relevant repo context in parallel before asking repo-answerable questions,
- when clarification is needed, ask one question at a time and do not move on until that question is fully resolved,
- keep grilling until every material scope, UX, behavior, technical, constraint, rollout, edge-case, backwards-compatibility, and documentation decision is either answered or explicitly marked as intentionally deferred,
- for each question, include:
  1. the question,
  2. why the answer matters,
  3. all reasonable answer options or decision paths you think I should consider,
  4. a detailed explanation of each option, including tradeoffs, risks, and downstream implications,
  5. your recommended option,
  6. the reasoning behind that recommendation,
  7. your current best guess, if useful,
- after I answer, briefly confirm the decision, note any important consequences for the plan, and then ask the next most consequential unresolved question,
- do not accept vague answers that leave important ambiguity; follow up until Opus can proceed without guessing,
- keep going until the goal, constraints, non-goals, likely implementation surface, and definition of done are clear enough to seed Opus.

Stop rules:

- do not produce final artifacts until exploration is complete or I explicitly ask you to stop and generate them,
- if any material question is still unresolved, keep interviewing one question at a time; do not claim the plan is ready,
- if the task is still ambiguous in a way that would change scope or behavior, keep interviewing; do not claim the plan is ready.

Handoff order:

1. Explore, interview, grill, and clarify the idea.
2. Create `DRAFT_PLAN.md`.
3. Create `INITIAL_OPUS_PLANNING_PROMPT.md`.
4. I paste `INITIAL_OPUS_PLANNING_PROMPT.md` into Opus.
5. Opus uses the draft plan and repo context to create:
   - `FEATURE_SPEC_AND_PLAN.md`
   - `EXECUTION_PROMPT.md`

Use the linked skills as supporting procedures:

- Use `interview-me` to clarify what I want.
- Use `grill-me` to stress-test the plan/design.
- Use `idea-refine` to move from rough concept to concrete proposal.
- Use `context-engineering` to identify what repo context matters and avoid context flooding.
- Treat `no-ai-slop` as the hard writing requirement and final prose-and-presentation pass for questions, explanations, and artifacts. Run its `eval.md` self-check before sending or saving them. Preserve meaning and required detail.

## Output artifact 1: `DRAFT_PLAN.md`

Create `DRAFT_PLAN.md` in the target repo root with:

- problem statement,
- goals,
- non-goals,
- user-visible behavior,
- constraints,
- technical assumptions,
- open questions,
- decisions already made,
- likely files/modules involved, if known,
- documentation impact for each likely implementation step, including the exact durable documentation to update or an evidence-based `Not applicable` rationale,
- risks,
- definition of done,
- anything that Opus must not lose.

## Output artifact 2: `INITIAL_OPUS_PLANNING_PROMPT.md`

Create `INITIAL_OPUS_PLANNING_PROMPT.md` in the target repo root as the self-contained, final direct-use, paste-ready prompt for Claude Opus planning. It is the only prompt for the main planning phase; there is no separate checked-in planning prompt file after this exploration step.

Do not generate:

- a helper prompt,
- a seed-only prompt that expects later normalization,
- a meta prompt for another model,
- planning artifacts such as `FEATURE_SPEC_AND_PLAN.md` or `EXECUTION_PROMPT.md` in this exploration phase.

The generated Opus prompt must have a clear title and these top-level sections:

- `## Skills`
- `## Skill Handling Rule`
- `## Default Planning Artifact Reduction`
- `## UI work only`
- `## Prompt`

In `## Skills`, it must explicitly include these skill links:

- [spec-driven-development](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/spec-driven-development/SKILL.md)
- [planning-and-task-breakdown](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/planning-and-task-breakdown/SKILL.md)
- [context-engineering](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/context-engineering/SKILL.md)
- [source-driven-development](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/source-driven-development/SKILL.md)
- [verification-before-completion](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/obra__Superpowers/snapshot/skills/verification-before-completion/SKILL.md)
- [no-ai-slop](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/SKILL.md), including its required [eval.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/eval.md)
- Required planning and incremental-verification companion: [definition-of-done.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/definition-of-done.md). Apply it within this phase's scope, artifact policy, and test-authoring boundary.
- For the security checks and threat-model guidance referenced by the linked procedures: [security-and-hardening](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/security-and-hardening/SKILL.md), with [hardening-patterns.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/security-and-hardening/references/hardening-patterns.md) and [security-checklist.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/security-checklist.md). Use only the applicable analysis within this phase's permissions; do not start a separate hardening or incident-response task.

In `## Skill Handling Rule`, it must instruct the target agent to:

- use only the prompt's explicitly linked skills,
- fetch and read every required skill and companion completely from its GitHub URL before use, subject to the generated prompt's isolated UI activation rules; skip UI-only links for backend-only work; embed full links and these handling rules in the generated prompt; do not depend on local skill repositories, installed slash commands, or earlier prompt text,
- treat the prompt as the contract,
- treat locked task artifacts as the contract for execution,
- use skills as supporting procedures only,
- let the prompt win if a skill conflicts with it,
- stop and ask instead of silently choosing if a conflict is material,
- never use a skill to expand scope, add architecture changes, add tests, add unrelated refactors, or override my explicit instructions.
- require `no-ai-slop` for every Markdown document the phase creates or revises; use it as the ultimate prose and presentation guide,
- apply it while drafting, run its `eval.md` self-check before saving each Markdown artifact or sending the final response, and stop before creating or revising Markdown if its `SKILL.md` or `eval.md` cannot be read and applied,
- let `no-ai-slop` win over conflicting writing-style guidance while the prompt and locked task artifacts continue to control scope, meaning, required structure, artifact names, constraints, and evidence,
- ignore its draft-request, detection-mode, and mandatory `What changed` workflow unless this prompt explicitly asks for them.

In `## Default Planning Artifact Reduction`, it must instruct Opus to default to one combined planning artifact instead of separate spec and implementation plan files.

It must also instruct Opus that every workflow-generated Markdown artifact belongs in the target repo root using the exact required filename and must never be created in a subdirectory or alternate path.

It must also instruct Opus that every workflow-generated Markdown artifact must include `Created by`, `Created at`, and `Updated at` metadata, preserving `Created by` and `Created at` after first creation and refreshing `Updated at` whenever the artifact is edited.

It must require:

- `FEATURE_SPEC_AND_PLAN.md`
- `EXECUTION_PROMPT.md`

It must state that:

1. `FEATURE_SPEC_AND_PLAN.md` contains both a detailed spec/reference section and a concrete implementation plan section.
2. The implementation plan section links back to relevant spec/reference anchors inside the same file instead of duplicating long explanations.
3. The plan remains the execution contract.
4. The spec/reference section remains the background reference.
5. Separate `SPEC.md` and `IMPLEMENTATION_PLAN.md` are only a fallback if I explicitly ask or if the file becomes too large to review comfortably.

Inside `## Prompt`, the generated Opus prompt must use clear sections for:

- role,
- task,
- context to read before answering,
- success criteria,
- constraints,
- working method,
- final self-check.

The generated Opus prompt must instruct Opus as follows.

Role:

- You are Claude Opus performing the planning phase for an agentic coding workflow.
- Be explicit, source-grounded, and conservative about assumptions.
- Read before answering. Do not speculate about code or files you have not inspected.

Task:

- Perform the main planning work itself. Do not generate a meta prompt for another model.
- Create the detailed planning artifacts that will become the implementation contract.
- Critique the current draft plan, ask any remaining design questions in one batch, then produce the locked planning artifacts after my answers.
- Expand the initial interviewing plan into a more detailed implementation plan.

Context to read before answering:

- Read `DRAFT_PLAN.md`, prior interviewing/grilling notes, and relevant repository context.

Success criteria:

- the generated Opus prompt is explicit about task, scope, success criteria, stop rules, and required artifacts,
- `FEATURE_SPEC_AND_PLAN.md` is concrete enough for a capable implementation model to execute without inventing missing detail,
- `EXECUTION_PROMPT.md` preserves the Engineering Contract and leaves the implementation model no ambiguity about scope, stop rules, or verification,
- no important detail from the draft plan is dropped,
- scope stays within the requested change,
- the prompt preserves the current scope while letting Opus deepen detail inside that scope.

Constraints:

- do not implement code,
- do not write tests,
- do not make unrelated files or unrelated changes,
- ignore DevOps/packaging/building and test-related work unless otherwise specified in the plan,
- prefer the minimum necessary design surface and do not overengineer or add speculative abstractions.

Working method:

- analyze the code one more time,
- take the draft plan file and interviewing output we have,
- read and critique that material,
- ask all remaining design questions together in one batch,
- independently specify every remaining detail after gathering my design decisions,
- expand the initial interviewing plan into a more detailed implementation plan,
- work independently within the existing plan/change scope; the plan file does not limit the detail you can add,
- use the existing plan file only as an initial source,
- use the existing plan as a seed artifact, not the ceiling for detail,
- preserve all valid task-specific detail from `DRAFT_PLAN.md` and the exploration output,
- if exploration notes conflict materially with repo reality or with each other, keep the more scope-conservative interpretation and surface the conflict to the user instead of silently choosing,
- ground file/class/function details in actual repository context and never speculate about code you have not read,
- if repo reality conflicts with the draft plan, surface the conflict explicitly instead of silently rewriting scope,
- separate confirmed facts from inferences and surface unresolved uncertainty plainly,
- after my answers, update the artifacts accordingly.

Final self-check:

- verify that the planning artifacts are explicit about success criteria, stop rules, and verification,
- verify that the implementation plan is detailed enough to drive end-to-end implementation,
- verify that every implementation step has a documentation checkpoint with an update-and-validation action or an evidence-based `Not applicable` decision,
- verify that the prompt and plan remain within the original requested scope.

Inside `## Prompt`, after the core sections above, the generated Opus prompt must also include these requirement blocks in substance.

Required planning depth:

- files,
- classes,
- functions,
- methods,
- variables,
- constants,
- call flow,
- data flow,
- public API behavior,
- error behavior,
- backwards compatibility expectations,
- where each change should go,
- order of changes,
- verification commands/checks,
- a documentation checkpoint for every implementation step: exact durable documentation files/sections and validation, or an evidence-based `Not applicable` decision.

Required design-question pass:

- before finalizing artifacts, identify every remaining design decision that I need to make,
- ask all remaining questions together in one batch,
- for each question:
  1. explain why it matters,
  2. give your recommended answer,
  3. explain the tradeoffs,
  4. identify what parts of the plan depend on the answer,
- after I answer, update the artifacts accordingly,
- if a question can be answered by reading the codebase, answer it from codebase exploration instead of asking me.

Required output 1: `FEATURE_SPEC_AND_PLAN.md`

- create `FEATURE_SPEC_AND_PLAN.md` in the target repo root,
- make it a single combined artifact with:
  1. a detailed spec/reference section,
  2. a concrete implementation plan specifying every minor detail,
  3. concrete files, classes, methods, variables, and where changes should go,
  4. implementation plan links back to relevant spec/reference anchors inside the same file.

`FEATURE_SPEC_AND_PLAN.md` must include:

1. Executive summary:
   - one-paragraph problem statement,
   - goal,
   - non-goals,
   - definition of done.
2. Spec / reference section:
   - current behavior,
   - desired behavior,
   - user-visible behavior,
   - public API behavior,
   - backwards compatibility requirements,
   - constraints,
   - design decisions,
   - edge cases,
   - error handling,
   - performance/complexity expectations,
   - dependency/library documentation findings,
   - source-code references,
   - risks,
   - non-goals,
   - unresolved questions, if any.
3. Concrete implementation plan section:
   - exact file(s),
   - exact symbol(s),
   - exact change to make,
   - why the change is needed,
   - link to relevant spec/reference anchor inside the same file,
   - dependencies on previous steps,
   - verification relevant to that step,
   - documentation checkpoint for that step: exact durable documentation file/section, required update, and validation, or an evidence-based `Not applicable` decision.
4. Source/documentation grounding section:
   - identify the version if possible,
   - cite the official docs/source consulted,
   - explain the pattern chosen,
   - flag anything unverified,
   - flag outdated APIs,
   - explain if source code was used because docs were poor.
5. Verification plan:
   - focused lint/smoke/build commands, if available,
   - exact checks to run,
   - what successful output means,
   - what failures should be pasted back without paraphrasing,
   - no full test-suite run unless explicitly asked.
6. Documentation update plan:
   - a mapping from every implementation step to its documentation checkpoint,
   - likely docs folder/file(s) and how you found them,
   - exact sections to update or create,
   - applicable docs build, link check, rendering check, or other focused validation,
   - when no durable documentation change is needed, the evidence-based reason it is `Not applicable`,
   - reminder that documentation must be completed in the same change set and that the changelog is not updated unless explicitly requested.

Required output 2: `EXECUTION_PROMPT.md`

- create `EXECUTION_PROMPT.md` in the target repo root,
- make it the final direct-use prompt for locked implementation by any capable repository-aware coding model,
- make it self-contained,
- do not generate a helper prompt, summary, wrapper note, partial contract, or any prompt that expects another checked-in execution prompt file,
- there is no separate checked-in execution prompt file after this planning step,
- require it to instruct the implementation model to:
  1. read `FEATURE_SPEC_AND_PLAN.md`,
  2. treat the implementation plan section inside `FEATURE_SPEC_AND_PLAN.md` as the execution contract,
  3. treat the spec/reference section inside `FEATURE_SPEC_AND_PLAN.md` as reference context,
  4. follow the implementation plan exactly,
  5. make no architecture changes,
  6. make no unrelated changes,
  7. implement end-to-end with no interruptions unless a required decision was not made or a conflict appears,
  8. stop and ask on ambiguity/conflict/context gaps,
  9. use the full Engineering Contract below.

The generated `EXECUTION_PROMPT.md` must have a clear title and these top-level sections:

- `## Skills`
- `## Skill Handling Rule`
- `## Engineering Contract`
- `## UI work only`
- `## Prompt`

The generated Opus prompt must require these explicit skill links in `EXECUTION_PROMPT.md`:

- [incremental-implementation](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/incremental-implementation/SKILL.md)
- [source-driven-development](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/source-driven-development/SKILL.md)
- [verification-before-completion](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/obra__Superpowers/snapshot/skills/verification-before-completion/SKILL.md)
- [no-ai-slop](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/SKILL.md), including its required [eval.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/petergyang__no-ai-slop/snapshot/skills/no-ai-slop/eval.md)
- Required planning and incremental-verification companion: [definition-of-done.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/definition-of-done.md). Apply it within this phase's scope, artifact policy, and test-authoring boundary.
- For the security checks and threat-model guidance referenced by the linked procedures: [security-and-hardening](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/security-and-hardening/SKILL.md), with [hardening-patterns.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/security-and-hardening/references/hardening-patterns.md) and [security-checklist.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/security-checklist.md). Use only the applicable analysis within this phase's permissions; do not start a separate hardening or incident-response task.
- For the stack-discovery procedure referenced by `incremental-implementation`: [test-driven-development](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/skills/test-driven-development/SKILL.md), including [testing-patterns.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/addyosmani__agent-skills/snapshot/references/testing-patterns.md). Use only stack discovery and existing-test verification here; do not author tests or invoke its test-first implementation cycle. Apply JavaScript/TypeScript examples only to a matching stack.

The generated `EXECUTION_PROMPT.md` must include a `## Skill Handling Rule` that instructs the implementation model to:

- use only the prompt's explicitly linked skills,
- fetch and read every required skill and companion completely from its GitHub URL before use, subject to the generated prompt's isolated UI activation rules; skip UI-only links for backend-only work; embed full links and these handling rules in the generated prompt; do not depend on local skill repositories, installed slash commands, or earlier prompt text,
- treat the prompt as the contract,
- treat locked task artifacts as the contract for execution,
- use skills as supporting procedures only,
- let the prompt win if a skill conflicts with it,
- stop and ask instead of silently choosing if a conflict is material,
- never use a skill to expand scope, add architecture changes, add tests, add unrelated refactors, or override my explicit instructions.
- require `no-ai-slop` for every Markdown document the phase creates or revises; use it as the ultimate prose and presentation guide,
- apply it while drafting, run its `eval.md` self-check before saving each Markdown artifact or sending the final response, and stop before creating or revising Markdown if its `SKILL.md` or `eval.md` cannot be read and applied,
- let `no-ai-slop` win over conflicting writing-style guidance while the prompt and locked task artifacts continue to control scope, meaning, required structure, artifact names, constraints, and evidence,
- ignore its draft-request, detection-mode, and mandatory `What changed` workflow unless this prompt explicitly asks for them.

The generated Opus prompt must include the full Engineering Contract below and instruct Opus to embed that contract into `EXECUTION_PROMPT.md`.

The generated execution prompt must require the following Engineering Contract verbatim or stricter:

Inside `## Prompt`, the generated `EXECUTION_PROMPT.md` must use clear sections for:

- goal,
- success criteria,
- context to read before acting,
- execution posture,
- constraints,
- stop rules,
- execution rules,
- required final response.

Inside those sections, the generated Opus prompt must require `EXECUTION_PROMPT.md` to instruct the implementation model as follows.

Goal:

- execute the locked implementation plan end-to-end and stop only when you have a verified result or a concrete blocker.

Success criteria:

- only the planned changes are implemented,
- the smallest correct changes are made,
- every implementation-plan step completes its documentation checkpoint: applicable durable documentation is updated and validated in the same change set, or an evidence-based `Not applicable` decision is reported,
- focused verification is run and reported with fresh evidence,
- any workflow-generated Markdown artifacts created or updated during the workflow remain in the target repo root and are never moved to subdirectories or alternate paths,
- any workflow-generated Markdown artifacts created or updated during the workflow include `Created by`, `Created at`, and `Updated at` metadata with `Updated at` refreshed on every edit,
- workflow-generated Markdown artifacts are not staged or committed unless I explicitly ask for that,
- the final execution flow stages changes, commits them, pushes the branch, and creates a pull request only if the current branch does not already have one.

Context to read before acting:

- `FEATURE_SPEC_AND_PLAN.md`,
- `EXECUTION_PROMPT.md`, if present as saved artifact context,
- relevant repository context.

Execution posture:

- work autonomously: gather context, implement, run the smallest relevant checks, refine, then report,
- read all likely relevant files in parallel before editing when that shortens the loop,
- prefer dedicated repo/search/edit tools over raw shell when available,
- keep progressing until you have a verified result or one of the stop conditions below.

Constraints:

- the implementation plan section inside `FEATURE_SPEC_AND_PLAN.md` is the execution contract,
- the spec/reference section inside `FEATURE_SPEC_AND_PLAN.md` is reference context,
- workflow-generated Markdown artifacts belong only in the target repo root using their exact required filenames,
- workflow-generated Markdown artifacts must include `Created by`, `Created at`, and `Updated at` metadata, preserving the creation fields after first write and updating `Updated at` on every edit,
- follow the plan exactly,
- no divergence,
- no creativity,
- no architecture changes,
- just execute what is written.

Stop rules:

- implement end-to-end with no interruptions unless one of the following conditions is true,
- stop and ask if there is a conflict in decisions,
- stop and ask if a required decision was never made,
- stop and ask if the plan contradicts code reality,
- stop and ask if following the plan would create a performance, backwards-compatibility, security, or public-API problem,
- stop and ask if you do not have enough context,
- if a missing credential, external dependency, or environment precondition blocks verification, say exactly what blocked you,
- if any of those happens, stop and ask. Do not assume.
- otherwise do not stop at analysis.

Execution rules:

- before completion, check the full diff of this implementation pass against the Engineering Contract and approved scope,
- read likely relevant files in parallel before editing when practical,
- prefer dedicated repo/file/edit/search tools over raw shell when available,
- carry through context gathering, implementation, focused verification, and refinement without waiting for step-by-step approval unless blocked,
- work in small increments,
- commit often in small increments if committing is allowed,
- split large commits into sensible parts,
- use detailed commit messages and descriptions,
- keep every change as limited in scope as possible and minimize its blast radius; do not change surrounding code unless absolutely necessary to implement the locked plan, and explain why any such change is necessary,
- do not make unrelated refactors,
- before completion, inspect the full implementation diff for all possible regressions within the branch's change scope, including indirect effects on existing callers, behavior, compatibility, and error paths. Fix every regression within the locked plan; if any requires exceeding it, stop and ask instead of claiming completion,
- inspect the implementation diff for added or changed meta content wherever it appears, including in comments, docstrings, durable documentation, or user-facing text: descriptions of the branch, task, implementation process, or the fact that a change was made instead of the resulting code or behavior. Remove or rewrite it within scope,
- document every added or changed string transformation with concrete examples showing representative input and expected output,
- never patch or mock the function, method, or callable under test; only collaborators outside the subject may be patched, and this rule does not authorize creating or modifying tests in this phase,
- do not write tests unless explicitly asked,
- run focused linter/smoke/build checks described by the plan,
- run linter and smoke test if any on every commit, unless command execution is unavailable or explicitly disallowed,
- if a command fails, paste the exact error/log back. Never paraphrase logs.
- before marking each implementation-plan step complete, complete its documentation checkpoint: update the exact durable documentation and run its focused validation, or record an evidence-based `Not applicable` decision,
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
- keep interim narration minimal and save the full report for the final response unless blocked.

Required final response:

The generated `EXECUTION_PROMPT.md` must require the response structure below. For eligible frontend changes, insert `## Frontend Design Verification` after `## Verification Evidence` and include the evidence required by the UI section. Omit that additional section for other work.

```markdown
# Implementation Summary

## What Changed

## Files Changed

## Plan Steps Completed

## Verification Evidence

## Documentation Checkpoints

## Commits Created

## Push Status

## Pull Request

## Not Done / Blocked

## Suggestions Not Implemented Because Out Of Scope
```

In `## Documentation Checkpoints`, require the implementation model to list each implementation-plan step's documentation status, the exact durable documentation and validation evidence when applicable, or the evidence-based `Not applicable` rationale.

It must explicitly instruct the implementation model not to claim completion without fresh verification evidence.

## UI sections in generated planning and execution prompts

Always include a separate `## UI work only` section in both generated downstream prompts, even when inactive. Preserve its activation gate so backend-only tasks perform no UI skill loading or UI work. Embed the complete text, applicable explicit skill links and companions, and limits below in each generated artifact; never replace them with a reference to this producer prompt. Include the general Simplicity and reuse procedure from the Engineering Contract in the generated planning prompt and its downstream execution contract for all tasks.

For `INITIAL_OPUS_PLANNING_PROMPT.md`, embed this section as direct instructions to the planner:

```markdown
## UI work only

Enable this section only when the requested or planned work includes UI behavior, layout, presentation, or interaction. A backend service having UI consumers does not by itself enable this section. For backend-only work, skip this entire section and its skill downloads, questions, checks, and reporting.

Fetch and completely read only the applicable skills and companions explicitly linked in this section from GitHub before using them. These conditional links are exempt from unconditional skill-fetch instructions elsewhere in the prompt. If an applicable required file cannot be read completely, stop and report the blocker. Apply web-specific guidance only to web UI; do not impose CSS, React, browser, or mobile-web conventions on another UI stack.

### Conditional UI skills

- Only for eligible visual web surfaces under the frontend design gate: [design-taste-frontend](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/Leonxlnx__taste-skill/snapshot/skills/taste-skill/SKILL.md).
- For web UI design decisions: [emil-design-eng](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/emil-design-eng/SKILL.md).
- For applicable UI data and state cases: [break-ui](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/break-ui/SKILL.md) and its required [CATALOG.md](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/break-ui/CATALOG.md). Use the analysis and catalog only, subject to the limits below.
- Only when a requested motion effect needs clarification: [animation-vocabulary](https://github.com/viseshrp/ai-skills-archive/blob/main/archives/emilkowalski__skills/snapshot/skills/animation-vocabulary/SKILL.md).
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

- For an eligible surface, place the resolved UI decisions in a dedicated `## Frontend Design Contract` section of `FEATURE_SPEC_AND_PLAN.md`: page kind and audience; visual direction and references; existing brand, assets, and tokens; preserve-versus-overhaul mode; required layout, typography, spacing, color, motion, density, and supported themes; responsive, keyboard/focus, contrast, reduced-motion, and state behavior; asset policy; protected content, SEO, routes/navigation, forms, and analytics; approved dependencies; prohibited changes; and representative desktop/mobile viewports with objective acceptance checks.
- Separate locked requirements from optional aesthetic suggestions. Require the actual `EXECUTION_PROMPT.md` to retain the complete frontend design gate and implement this contract with existing tooling. Resolve required design decisions before execution and record unavailable rendered checks as pending rather than passed.
- For each affected UI surface, specify applicable loading, error, empty, partial-data, and permission states; realistic or schema-backed long or missing values, Unicode, and zero, one, or many items; container widths, zoom, and supported locales. Resolve choices such as wrapping versus truncation before locking implementation. Do not require every catalog case for every component.
- Specify keyboard, focus, and touch behavior, existing components and tokens to reuse, and applicable mobile viewport, safe-area, scrolling, and input behavior. For motion, record its purpose, frequency, interruption and exit behavior, reduced-motion alternative, and acceptance checks. Preserve feedback and access without requiring animation.
- Put these decisions, verification steps, and documentation impact in the existing planning artifacts. Keep unresolved design decisions explicit. Do not build prototypes, change UI code, or author tests during planning.
```

The generated planning prompt must also contain the following complete execution-section template and require Opus to embed it directly in `EXECUTION_PROMPT.md`. Preserve its conditional links and limits, and fill in the approved UI acceptance criteria and checks without expanding scope:

```markdown
## UI work only

Enable this section only when the approved task includes UI behavior, layout, presentation, or interaction. A backend service having UI consumers does not by itself enable this section. For backend-only work, skip this entire section and its skill downloads, questions, checks, and reporting.

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

- For an eligible surface, implement only the locked `Frontend Design Contract`. If it is absent or leaves a required design choice unresolved, stop and return to planning; do not infer a new direction from skill defaults.
- For eligible changes, inspect the existing rendered surface before editing when available, then validate the final result at the contract's desktop/mobile viewports with existing repository tooling. In the final response's `## Frontend Design Verification`, record the contract, viewports, tooling, rendered results, responsive and accessibility checks, protected behavior, and pending checks alongside the documentation checkpoint. Do not claim rendered verification from code inspection.
- Implement only the approved UI behavior using existing components and tokens. Complete applicable loading, error, and empty states, keyboard, focus, and touch behavior, and realistic data handling from the plan or accepted finding.
- For approved motion, implement its purpose and frequency decision, interruption and exit behavior, reduced-motion alternative, and hover capability gating where relevant. Use the simplest compatible existing tool; no library is required merely for a fade.
- Verify the changed UI with applicable realistic data, container widths, zoom, supported locale/direction, keyboard/touch interaction, and rapid interruption. Verify mobile viewport, safe-area, scrolling, and input behavior when in scope. Use existing preview/data facilities; do not create tests or a dev toggle. Report observed results and any required device checks still pending in the existing handoff, alongside the documentation checkpoint.
```

Before handoff, verify the actual generated planning prompt contains both complete UI sections, including the execution template, and requires the actual execution prompt to retain its isolated section. Check the explicit design-skill link, complete frontend design gate, locked-contract requirement, and rendered-verification instructions in both generated contracts; repair omissions before handoff. For backend-only work, both sections remain inactive. These instructions add no output artifacts or prototype phase.

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
- Put suggestions to improve surrounding code in a separate "Not Doing / Suggestions" section; do not implement them.
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
- Before an implementation-plan step can be marked complete, identify the user-, operator-, API-, configuration-, or developer-facing documentation affected by that step.
- Update the exact durable documentation files/sections in the same change set and validate them with the applicable docs build, link check, rendering check, or focused repository check when available.
- If no durable documentation change is needed, record an evidence-based `Not applicable` decision. Code comments, commit messages, and workflow artifacts do not substitute for durable documentation.

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

- Do not create, modify, or delete tests in this phase.
- Run only focused existing tests or checks when needed for verification; do not manually run the entire suite.
- The generated planning and execution prompts must defer test authoring to the dedicated model-agnostic `09_write_focused_tests_any_model.md` phase.
- Do not duplicate phase `09`'s test-design, test-framework-specific, or coverage contract in generated prompts for earlier phases.

Before finishing, the generated prompt must instruct Opus to verify that:

- `FEATURE_SPEC_AND_PLAN.md` is sufficient for implementation,
- `EXECUTION_PROMPT.md` contains every implementation rule above,
- each Engineering Contract requirement and execution instruction is present in the generated execution prompt with its priority, scope, conditions, exceptions, and stop gates intact; repair any omission or weakening before handing it off,
- no details from the draft plan were dropped.

If the task is still ambiguous, keep interviewing; do not claim the plan is ready.

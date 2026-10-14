# README demo generation

The README uses [the generated walkthrough](images/demo.gif). Its source is
[a Playwright scenario](../frontend/e2e/readme.demo.ts), driven against the
same disposable server as the browser tests. No installed agent account,
owner project, live Relay server, or owner database participates.

## Regenerate

Install the locked contributor dependencies from [CONTRIBUTING.md](../CONTRIBUTING.md),
then install FFmpeg and Chromium. FFmpeg must be available as `ffmpeg` on
`PATH`; for example, `brew install ffmpeg` on macOS or
`sudo apt-get install ffmpeg` on Ubuntu.

```bash
npm --prefix frontend exec playwright install chromium
npm --prefix frontend run demo
```

The command builds the current frontend into a temporary asset directory,
starts its own test server on an available loopback port, and captures the
walkthrough. It leaves a running app's compiled assets alone. The server
owns temporary Git, database, provider, and storage directories and removes
them when it exits. The renderer removes its temporary build after capture.

Only a successful scenario and encoding replace `docs/images/demo.gif`.
The output is a looping 1280 × 800 GIF, limited to 5 MiB. Captured frames
and Playwright failure traces remain under the ignored
`frontend/test-results/readme-demo/` directory for review. Inspect the full
loop before committing the generated image.

## Walkthrough coverage

1. Browse the starter gallery and create a workflow. Edit connected jobs in
   the synchronized visual and YAML editors.
2. Configure an agent's exact model and thinking effort. The example uses
   Codex to plan and Claude Code in the build job.
3. Enter a task and launch. The real scheduler executes jobs in an isolated
   Git worktree and holds dependent work at the owner approval.
4. Answer the approval, let command checks finish, and inspect job output.
5. Review the completed run and preview a retained artifact with a download
   action.

The agents speak the real ACP protocol but return deterministic test output.
Commands create the example plan and health report; the demo does not claim
to measure an installed agent's coding quality. Each capture waits for its
visible state or API result. Fixed frame durations control reading time;
they do not substitute for readiness checks. Loading delays are omitted.

The GIF covers the first-run authoring and execution path. Cancellation,
failed-step retry, automatic recovery, login, and settings remain covered by
their browser tests; they are omitted from this short walkthrough.

## Automatic updates

[The README demo workflow](../.github/workflows/readme-demo.yml) regenerates
the GIF after relevant frontend, backend, fixture, or dependency changes
reach `main`. It opens or updates `chore/readme-demo-update`, containing only
the GIF, for review. It does not enable automatic merge. Changes to the
capture machinery also run generation on pull requests.

Use **Actions → README demo → Run workflow** for an on-demand refresh.
Runs on other branches upload the candidate and diagnostics without opening
an update PR. Failed captures leave the checked-in GIF unchanged.

The existing `PERSONAL_ACCESS_TOKEN` secret is used when configured so the
generated PR can trigger normal CI. Otherwise the workflow uses
`GITHUB_TOKEN`; repository settings must allow Actions to create PRs, and
GitHub's token rules may require a manual CI run on that PR.

## Tool choice

The comparison below uses the tools' own documentation. Playwright with
FFmpeg fits Relay's browser interface and existing contributor setup.

| Tool | Fit for Relay |
| --- | --- |
| [Playwright](https://playwright.dev/docs/screenshots) + [FFmpeg](https://ffmpeg.org/ffmpeg-filters.html#palettegen) | Selected. Drives the real UI, asserts readiness, captures frames, and encodes a GIF with a shared palette. Playwright is already locked in the frontend dependencies. FFmpeg is the only additional local tool. |
| [VHS](https://github.com/charmbracelet/vhs) | Scripts terminal GIFs and supports CI. Useful for a CLI-focused project; Relay's authoring, approvals, and monitoring require browser interactions. It also requires FFmpeg and ttyd. |
| [asciinema + agg](https://docs.asciinema.org/manual/agg/) | Converts terminal recordings to GIF. Suitable for shell demonstrations, but does not capture Relay's browser UI. |
| [gifski](https://github.com/ImageOptim/gifski) | An alternative encoder focused on GIF color quality. It still needs a browser capture source and adds another installation. Reconsider if screenshots with gradients or photographic content outgrow FFmpeg's palette quality. |

Playwright also supports [video recording](https://playwright.dev/docs/videos).
The storyboard uses asserted screenshots with explicit durations so loading
speed does not change pacing or leave blank startup frames. Captions are
recording overlays; the underlying application layout and controls are real.

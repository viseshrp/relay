# Frontend and package builds

Relay publishes one Python source distribution and one wheel. The wheel
contains the compiled browser application, so an installed `relay up` never
needs Node.js or npm to serve it. Opt-in local JavaScript actions require
their declared installed Node 20 or 24 runtime.

## Locked build tools

The frontend uses npm and the committed `frontend/package-lock.json`. Vite
8.2.2 accepts Node `^20.19.0` or `>=22.12.0`; CI pins Node 24.21.0. Contributors
can build the browser application with:

```bash
cd frontend
npm ci
npm run build
```

The build writes `relay/static/index.html`, hashed files under
`relay/static/assets/`, and source maps. These files are generated and ignored
by Git. Change `frontend/` sources and rebuild instead of editing generated
assets.

## Hatch wheel hook

`hatch_build.py` defines `CustomBuildHook(BuildHookInterface)`. The hook does
nothing for a source-distribution target or an editable wheel (`version ==
"editable"`). Before `relay up` from a checkout, run `npm --prefix frontend ci`
and `npm --prefix frontend run build`. For a distributed wheel it resolves npm
from `PATH`, including Windows `PATHEXT` entries such as `npm.cmd`, then runs
these argument vectors with `shell=False` from `frontend/`:

```text
[resolved npm executable, "ci"]
[resolved npm executable, "run", "build:dist"]
```

The hook fails if the build does not create both `index.html` and an asset
file. It then adds the generated directory to Hatch's `force_include` mapping
as `relay/static`. The wheel target includes `relay/**`, so Django can serve
the files directly from the installed package.

## Source distributions and wheel-from-sdist

The source-distribution target includes `frontend/**`, `hatch_build.py`, the
Python package, and package metadata. In particular, it carries both
`frontend/package.json` and `frontend/package-lock.json`. It does not run npm
during source-distribution assembly. The four Markdown guides imported by
`HelpGuides.tsx` also ship as build inputs so the installed browser can display
its in-app help without fetching external documentation.
Installed frontend dependencies, browser test reports, and generated static
assets are excluded; the wheel hook rebuilds assets from the locked sources.

Building a wheel from the resulting source distribution invokes the wheel
hook in the unpacked source tree. This produces the same static layout as a
wheel built from a checkout. The top-level `certification/` directory is
excluded from both distributions.

## Build and content gates

Run the release path with:

```bash
make build
make check-dist
```

`make build` builds the source distribution and wheel. `make check-dist` runs
Twine metadata checks and `scripts/check_distribution_contents.py`. The
content check requires compiled static files in the wheel, requires the
frontend lockfile, hook, and help guides in the source distribution, rejects
installed dependencies and generated artifacts there, rejects certification
evidence, and rejects workflow or prompt templates outside the exact allow-list
for the seven [starter workflows](workflows.md#starter-workflows). Approved
sources live under `relay/workflows/starters/` and ship in both archives,
including the full AI coding workflow's helper workflows, local action,
original phase prompts, Relay instructions, MIT license, and provenance hashes.
The content gate still rejects every other YAML or template path. The blank
files created by `relay init` remain separate from these opt-in starters.

The distribution jobs install Python dependencies in editable mode, then
install the pinned Node version before building the source distribution and wheel.
The release publication job downloads the already-built artifacts and does not
rebuild them.

On pushes to `main`, CI always checks the development version, builds both
distributions, validates their contents, and retains them as the
`verified-distributions` artifact for seven days. Uploading them to TestPyPI
requires `TEST_PYPI_TOKEN` in the repository or `test-pypi` environment. If the
token is absent, CI reports the skipped upload in its log and job summary.
Build, version, and content failures still fail the job.

## Source dependency checks

The dependency scan in `make check` excludes installed Python environments,
including the `.tox/` directories created by `make test`. It scans Relay
source without treating third-party packages as project imports. The
lockfile, vulnerability and license checks still validate dependencies.

## Runtime check without Node

Install the wheel into a fresh virtual environment, remove Node from `PATH`,
and run `relay up --no-browser`. A successful readiness response from
`GET /api/auth` proves the installed Python package can serve its compiled
assets without an end-user Node runtime.

## Updating an editable frontend

`npm --prefix frontend run build` checks types and builds into a temporary
staging directory beside the served asset directory, preserving relative
source-map paths. It publishes assets first, then atomically replaces
`index.html`. Earlier hashed assets remain available for open tabs that have
not yet loaded every workspace. A failed asset copy leaves the previous entry
page in place. This updates only compiled frontend files; the running server
and durable state stay in place.

Wheel builds use `npm run build:dist`, which cleans the asset output before
building. Releases therefore contain one build, without older checkout chunks.
`npm --prefix frontend run test:build` checks publication failure and a browser
tab loading an earlier lazy chunk after publication.

Development publication keeps assets for the latest three builds so recently
opened tabs can finish loading their chunks. Each successful entry-page swap
records its assets before pruning older generations. Release builds contain no
source maps or build manifests. JavaScript, CSS, HTML, and other compressible
assets include Brotli and gzip alternatives; the static server negotiates the
encoding while retaining the original media type and cache policy.

Optional compressed companions do not trigger an asset-catalog rescan when
absent. New original asset requests still discover newly published files and
their companions. This keeps uncompressed font requests from delaying lazy
modules while preserving path containment and encoding negotiation.

For isolated development checks, set `RELAY_BUILD_ASSETS_ROOT` to a disposable
absolute directory before `npm run build` or `make test-frontend`. Set
`RELAY_TEST_ASSETS_ROOT` to the same directory so browser-test servers serve
that build. This keeps a running editable app's assets in place. Distribution
builds use their normal clean output and should run from a disposable source
copy when the owner's checkout is serving an app.

## Container images

`Dockerfile` builds a multi-stage Linux image (`linux/amd64` and
`linux/arm64`). The builder stage exports locked runtime dependencies from
`uv.lock` with SHA-256 hashes, compiles the wheel through `hatch_build.py`,
and validates the archive with `scripts/check_distribution_contents.py` before
installing into `/opt/relay/venv`. The runtime stage copies only that virtual
environment into `python:3.14-slim-trixie` alongside `git` and `procps`, runs
as non-root `relay:relay` (`1000:1000`), and excludes Node.js and npm. It has
no coding-agent CLIs, provider credentials, or desktop keyring, so agent steps
cannot run inside it.

The container `relay` command is
[`scripts/container_entrypoint.py`](../scripts/container_entrypoint.py). For
`up`, it keeps the Python server bound to the saved or requested loopback host
and port, and bridges the container interface to that address so host port
publishing (`-p 127.0.0.1:7845:7845`) works without `--network host`. The
bridge accepts connections only from the container's default gateway, where
Docker delivers published ports; other containers on the network are refused.
It runs Relay in its own session and forwards `SIGINT` and `SIGTERM` once.

`Makefile` and `scripts/docker.sh` provide shared targets for local container
workflows and CI:

```bash
make docker-build
make docker-smoke
make docker-e2e
make docker-up
make docker-push TAGS="0.1.0 latest"
```

- `make docker-build` builds `DOCKER_IMAGE` (default
  `ghcr.io/viseshrp/relay:local`) with version and Git revision labels. Without
  uv, the version label is `0.0.0.devYYYYMMDDHHMMSS`.
- `make docker-smoke` verifies the image's CLI version, OCI labels, non-root
  user, absence of Node.js and npm, `relay init`, `relay up` readiness on
  `GET /api/auth` and `GET /` (both inside the container and across a
  host-published `-p 127.0.0.1::7845` port), and clean `SIGTERM` shutdown.
  It rebuilds the default image first and pulls another `DOCKER_IMAGE` when
  it is missing.
- `make docker-e2e` drives the browser app in the image through its published
  port. It selects the image like `make docker-smoke`; on Linux it builds the
  default image as the host user, like `make docker-up`. The image user cannot
  take UID 0, so a root host, such as a CI or development container, runs the
  disposable containers as root. Another host UID that differs from the image
  user is rejected. It creates a disposable Git
  repository and data directory under `TMPDIR`, then starts `relay up` with
  login required, `make docker-up`'s host-path mounts, throwaway configuration
  and state volumes, its own Docker network, and a random
  `-p 127.0.0.1::7845` port. Playwright then runs
  [`frontend/e2e/container.spec.ts`](../frontend/e2e/container.spec.ts) with
  `playwright.container.config.ts`, which has no default address. It requires
  `npm --prefix frontend ci` and Chromium from
  `npm --prefix frontend exec playwright install chromium`.
- The browser flows cover only what the bridge and mounts can change. A new
  owner creates the password and keeps the session across a reload. The owner
  launches a workflow from the Run workflow panel and receives the run's event
  stream. The page shows the human wait without a reload, and the owner
  approves it. Host Git then finds the job commit on the run ref, resolves the
  retained run worktree, and has nothing to prune. The project's
  `canonical_path` is the host path. A returning owner signs in and cancels a
  running command, and its process leaves the container.
  `scripts/docker.sh` then checks that the installed `relay` leads its own
  session, that the bridge refuses a sibling container on the network, and
  that `docker stop` ends with `Relay stopped cleanly.` An `EXIT` trap removes
  the containers, volumes, network, and temporary files, including after a
  failure.
- `make docker-up` (aliased as `make docker-run`) rebuilds the default image,
  then starts Relay on `http://127.0.0.1:7845/`. It mounts `DOCKER_WORKTREE`
  (default: the current directory) and Relay's data directory,
  `DOCKER_DATA_HOME` (default `relay-docker` under `$XDG_DATA_HOME` or
  `~/.local/share`), at their host paths. Each repository therefore keeps its
  own project identity, and host Git can resolve the run worktrees registered
  in the repository. Named
  volumes keep Relay configuration and state. On Linux, the image user takes
  the host UID and GID (when at least 1000) so it can write the mounted
  repository.
- `make docker-push` requires explicit `TAGS` and a clean checkout,
  smoke-tests the native platform, then builds and pushes multi-architecture
  images to GHCR. It authenticates through `GH_TOKEN` or `gh auth token`.
- `make docker-push-digest` and `make docker-publish-manifest` publish
  per-architecture digests and assemble the verified multi-platform manifest.

`.github/workflows/docker.yml` builds on native `linux/amd64` and
`linux/arm64` runners. Pull requests that touch container packaging run
`make docker-build`, `make docker-smoke`, and `make docker-e2e`. Publishing
runs push each platform image untagged by digest, smoke-test that exact
digest, and run `make docker-e2e`. Because those runs write a mounted
repository, they cover a rebuild of the same revision as the runner's user
rather than the pushed digest. `make docker-publish-manifest` then tags
`ghcr.io/viseshrp/relay` after both platforms pass:

- Nightly builds at `07:17 UTC` (and `workflow_dispatch` on `main`) publish
  `:nightly` and `:nightly-YYYYMMDD-RUN-ATTEMPT`. When `main` is exactly a
  release tag, the nightly image carries that release version.
- Published GitHub releases (`release: [published]`, created after the tag test
  suite succeeds) publish `:vX.Y.Z`, `:X.Y.Z`, and `:latest`.

Publishing jobs log in to GHCR with the `GHCR_TOKEN` repository secret when it
is set, and otherwise with the workflow's `GITHUB_TOKEN`. `GITHUB_TOKEN` can
push only when the `relay` package grants this repository write access under
its "Manage Actions access" settings; a package first pushed from outside
Actions rejects it with `permission_denied`. `GHCR_TOKEN` is then a classic
personal access token with `write:packages` scope for the package owner.

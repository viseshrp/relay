# Frontend and package builds

Relay publishes one Python source distribution and one wheel. The wheel
contains the compiled browser application, so an installed `relay up` never
needs Node.js or npm.

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
[resolved npm executable, "run", "build"]
```

The hook fails if the build does not create both `index.html` and an asset
file. It then adds the generated directory to Hatch's `force_include` mapping
as `relay/static`. The wheel target includes `relay/**`, so Django can serve
the files directly from the installed package.

## Source distributions and wheel-from-sdist

The source-distribution target includes `frontend/**`, `hatch_build.py`, the
Python package, and package metadata. In particular, it carries both
`frontend/package.json` and `frontend/package-lock.json`. It does not run npm
during source-distribution assembly.

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
frontend lockfile and hook in the source distribution, rejects certification
evidence, and rejects workflow or prompt templates outside the exact allow-list
for the six [starter workflows](workflows.md#starter-workflows). Their twelve
source files live under `relay/workflows/starters/` and ship in both archives.
The content gate still rejects every other YAML or template path. The blank
files created by `relay init` remain separate from these opt-in starters.

The distribution jobs install Python dependencies in editable mode, then
install the pinned Node version before building the source distribution and wheel.
The release publication job downloads the already-built artifacts and does not
rebuild them.

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

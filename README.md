# relay

[![PyPI version](https://img.shields.io/pypi/v/relay-app.svg)](https://pypi.org/project/relay-app/)
[![Python versions](https://img.shields.io/pypi/pyversions/relay-app.svg?logo=python&logoColor=white)](https://pypi.org/project/relay-app/)
[![CI](https://github.com/viseshrp/relay/actions/workflows/main.yml/badge.svg)](https://github.com/viseshrp/relay/actions/workflows/main.yml)
[![Coverage](https://codecov.io/gh/viseshrp/relay/branch/main/graph/badge.svg)](https://codecov.io/gh/viseshrp/relay)
[![License: MIT](https://img.shields.io/github/license/viseshrp/relay)](https://github.com/viseshrp/relay/blob/main/LICENSE)
[![Format: Ruff](https://img.shields.io/badge/format-ruff-000000.svg)](https://docs.astral.sh/ruff/formatter/)
[![Lint: Ruff](https://img.shields.io/badge/lint-ruff-000000.svg)](https://docs.astral.sh/ruff/)
[![Typing: ty](https://img.shields.io/badge/typing-checked-blue.svg)](https://docs.astral.sh/ty/)

> This is a template repository for Python projects that use uv for their dependency management.

![Demo](https://raw.githubusercontent.com/viseshrp/relay/main/demo.gif)

## 🚀 Why this project exists

Explain the problem this tool solves or the goal it's intended to fulfill.

## 🧠 How this project works

Explain how the tool works.

## 📐 Requirements

* Python >= 3.10

## 🏁 Initial project setup

Cruft creates `.cruft.json` after the template finishes generating the project, so the template initializes Git without
making a commit. Create the lockfile, validate the generated project, and then make the first commit:

```bash
uv sync
uv run pre-commit install
git add .
make check
make test-local
git add .
git commit -m "Initial commit"
```

The first commit will include both Cruft's template-tracking file (`.cruft.json`) and uv's reproducibility lockfile
(`uv.lock`).

## 📦 Installation

```bash
pip install relay-app
```

## 🧪 Usage

* To view the help message, run the following command:

<!-- [[[cog
import cog
from click.testing import CliRunner

from relay.cli import main

result = CliRunner().invoke(
    main,
    ["--help"],
    prog_name="relay",
)
if result.exit_code != 0:
    raise RuntimeError(result.output) from result.exception

cog.outl("```console")
cog.outl("$ " + "relay" + " --help")
cog.out(result.output)
cog.outl("```")
]]] -->
```console
$ relay --help
Usage: relay [OPTIONS] <what_you_worked_on>

  Relay CLI.

  Example usages:

Options:
  -v, --version  Show the version and exit.
  -h, --help     Show this message and exit.
```
<!-- [[[end]]] -->

## 🛠️ Features

* Does stuff

## 🧾 Changelog

See [CHANGELOG.md](https://github.com/viseshrp/relay/blob/main/CHANGELOG.md)

## 🙏 Credits

* [Click](https://click.palletsprojects.com), for enabling delightful CLI development.
* Inspired by [Simon Willison](https://github.com/simonw)'s work.

## 📄 License

MIT © [Visesh Prasad](https://github.com/viseshrp)

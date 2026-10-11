"""Only the approved starter sources may pass the distribution template gate."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tarfile
import zipfile

import pytest

from scripts.check_distribution_contents import check_distribution


@pytest.mark.parametrize(
    "name,allowed",
    [
        ("relay/workflows/starters/ask-agent.yaml", True),
        ("relay/workflows/starters/ask-agent.md", True),
        ("relay/workflows/starters/ai-coding-workflow.yaml", True),
        ("relay/workflows/starters/ai-coding-workflow/action.yaml", True),
        ("relay/workflows/starters/ai-coding-workflow/LICENSE", True),
        ("relay/workflows/starters/ai-coding-workflow/provenance.json", True),
        ("relay/workflows/starters/ai-coding-workflow/01_initial_exploration_any_model.md", True),
        ("relay/workflows/starters/ai-coding-workflow/unknown.md", False),
        ("relay/workflows/starters/unknown.yaml", False),
        ("relay/workflows/starters/unknown.md", False),
        ("relay/templates/ask-agent.yaml", False),
        ("relay/other.yaml", False),
        ("relay/secret_prompt.md", False),
    ],
)
def test_distribution_template_allow_list_is_exact(
    tmp_path: Path, name: str, allowed: bool
) -> None:
    archive = tmp_path / "test.whl"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("relay/static/index.html", "index")
        bundle.writestr("relay/static/assets/app.js", "app")
        bundle.writestr(name, "source")
    if allowed:
        check_distribution(archive)
    else:
        with pytest.raises(RuntimeError, match="forbidden workflow or prompt templates"):
            check_distribution(archive)


@pytest.mark.parametrize(
    "extra,missing",
    [
        (None, None),
        (None, "docs/getting-started.md"),
        ("frontend/node_modules/dependency/index.js", None),
        ("frontend/test-results/result.json", None),
        ("frontend/playwright-report/index.html", None),
        ("relay/static/assets/app.js", None),
    ],
)
def test_sdist_requires_the_guides_imported_by_the_frontend(
    tmp_path: Path, extra: str | None, missing: str | None
) -> None:
    archive = tmp_path / "relay.tar.gz"
    names = {
        "frontend/package.json",
        "frontend/package-lock.json",
        "hatch_build.py",
        "docs/getting-started.md",
        "docs/coming-from-github-actions.md",
        "docs/keyboard-shortcuts.md",
    }
    if extra is not None:
        names.add(extra)
    with tarfile.open(archive, "w:gz") as bundle:
        for name in sorted(names - {missing}):
            member = tarfile.TarInfo(f"relay/{name}")
            member.size = 5
            bundle.addfile(member, BytesIO(b"input"))
    if extra is not None:
        with pytest.raises(RuntimeError, match="generated frontend"):
            check_distribution(archive)
    elif missing is None:
        check_distribution(archive)
    else:
        with pytest.raises(RuntimeError, match=missing):
            check_distribution(archive)

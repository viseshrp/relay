"""Only the approved starter sources may pass the distribution template gate."""

from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from scripts.check_distribution_contents import check_distribution


@pytest.mark.parametrize(
    "name,allowed",
    [
        ("relay/workflows/starters/ask-agent.yaml", True),
        ("relay/workflows/starters/ask-agent.md", True),
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

"""The version is written in two places, and named once more in the changelog.

pyproject.toml's [project].version is what pip installs; formwork.__version__
is what the paste-in scripts embed (the goldens carry it). Neither derives
from the other on purpose: importlib.metadata reports the version of the
*installed* distribution, which an editable install keeps stale until
reinstall, and a stale string in a golden is a confusing red. So: two
literals, one test.
"""

import pathlib
import tomllib

import formwork

ROOT = pathlib.Path(__file__).parent.parent


def test_package_version_matches_pyproject():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert formwork.__version__ == pyproject["project"]["version"]


def test_changelog_leads_with_the_current_version():
    """The current version must have the newest release heading — after an
    optional Unreleased section, which collects merged-but-unbumped work
    (M11 convention; 0.7.0 will be the first bump after the sentinel)."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [line for line in changelog.splitlines() if line.startswith("## ")]
    assert headings, "CHANGELOG.md has no release headings"
    if headings[0].startswith("## Unreleased"):
        headings = headings[1:]
    assert headings, "CHANGELOG.md has only an Unreleased heading"
    assert headings[0].startswith(f"## {formwork.__version__} ")

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
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [line for line in changelog.splitlines() if line.startswith("## ")]
    assert headings, "CHANGELOG.md has no release headings"
    assert headings[0].startswith(f"## {formwork.__version__} ")

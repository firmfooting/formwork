"""The version is written once, in src/formwork/__init__.py.

pyproject.toml declares dynamic = ["version"] and reads it from
formwork.__version__ via tool.setuptools.dynamic; release-please updates the
literal directly (the x-release-please-version annotation). A static
[project].version was tried first and rejected: uv.lock records the root
package's static version, so every release bump would have staled the lock
and failed main's `uv sync --locked` gate on the release PR's merge commit.
The changelog must lead with the same version, release-please's doing.
"""

import pathlib
import tomllib

import formwork

ROOT = pathlib.Path(__file__).parent.parent


def test_pyproject_reads_its_version_from_formwork():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in pyproject["project"], (
        "the static [project].version literal is gone on purpose; "
        "one version lives in src/formwork/__init__.py"
    )
    assert pyproject["project"]["dynamic"] == ["version"]
    assert (
        pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"]
        == "formwork.__version__"
    )


def test_changelog_leads_with_the_current_version():
    """The current version must have the newest release heading — after an
    optional Unreleased section, which collects merged-but-unbumped work.
    release-please writes the heading when it cuts a release. Headings come
    in two forms: hand-written plain (`## 0.6.0 — 2026-09-07`) and
    release-please's linked (`## [0.7.0](compare-url)`); both count. The
    first cut exposed the plain-only form as a false red on the release PR
    itself — the gate failed the release it was guarding."""
    version = formwork.__version__
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [line for line in changelog.splitlines() if line.startswith("## ")]
    assert headings, "CHANGELOG.md has no release headings"
    if headings[0].startswith("## Unreleased"):
        headings = headings[1:]
    assert headings, "CHANGELOG.md has only an Unreleased heading"
    newest = headings[0]
    assert (
        newest.startswith(f"## {version} ")
        or newest == f"## {version}"
        or newest.startswith(f"## [{version}](")
    ), f"the newest release heading is {newest!r}, expected version {version}"

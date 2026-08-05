"""The package's own metadata must not drift from itself.

`__version__` sat at 0.0.1 through two releases while pyproject.toml moved to
0.0.3 — the tag, the wheel, and the value a consumer can actually read at runtime
all disagreed. Nothing caught it because nothing compared them.
"""

import pathlib
import tomllib

import strikemetrics

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_declared_version_matches_the_importable_one():
    declared = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    assert strikemetrics.__version__ == declared, (
        f'pyproject says {declared}, strikemetrics.__version__ says '
        f'{strikemetrics.__version__} — a consumer pinning by tag gets one and '
        f'reads the other'
    )

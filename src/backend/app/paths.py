"""Filesystem locations that differ between local development and the container image.

Locally the data folder sits at the repository root; in the image it is copied next to the
application package. Resolve it once here rather than hard-coding parent counts.
"""

from __future__ import annotations

import os
from pathlib import Path

_HERE = Path(__file__).resolve()


def _candidates(folder: str) -> list[Path]:
    found: list[Path] = []
    override = os.getenv("DATA_DIR")
    if override:
        found.append(Path(override) / folder if folder != "data" else Path(override))

    # Container layout: /app/app/paths.py -> /app/data
    found.append(_HERE.parent.parent / folder)
    # Repository layout: src/backend/app/paths.py -> <root>/data
    for depth in (3, 2, 4):
        try:
            found.append(_HERE.parents[depth] / folder)
        except IndexError:
            continue
    found.append(Path.cwd() / folder)
    return found


def data_dir() -> Path:
    for candidate in _candidates("data"):
        if candidate.is_dir():
            return candidate
    return _HERE.parent.parent / "data"


def knowledge_dir() -> Path:
    return data_dir() / "knowledge"

"""Stable sequential names for experiment videos.

Video artifacts are intentionally numbered across all variants in one output
directory so that a new review can refer to ``001_...``, ``002_...``, etc.
Existing unnumbered artifacts are preserved.
"""

from __future__ import annotations

import re
from pathlib import Path


NUMBERED_VIDEO = re.compile(r"^(\d+)_.*\.(?:mp4|mov|avi)$", re.IGNORECASE)
_RESERVED_NUMBERS: dict[Path, set[int]] = {}


def next_video_path(directory: Path, stem: str, suffix: str = ".mp4") -> Path:
    """Return the next unused ``NNN_stem`` path in *directory*.

    The scan is deliberately directory-wide so comparison and candidate files
    share one sequence. Three digits are used until 999; after that the number
    continues with four or more digits rather than overwriting an artifact.
    """

    directory.mkdir(parents=True, exist_ok=True)
    used = []
    for item in directory.iterdir():
        if not item.is_file():
            continue
        match = NUMBERED_VIDEO.match(item.name)
        if match:
            used.append(int(match.group(1)))
    reserved = _RESERVED_NUMBERS.setdefault(directory.resolve(), set())
    number = max([*used, *reserved], default=0) + 1
    while True:
        path = directory / f"{number:03d}_{stem}{suffix}"
        if not path.exists() and number not in reserved:
            reserved.add(number)
            return path
        number += 1

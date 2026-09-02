"""
Resolve stored image paths to real files on disk.

`JobOutput.image_path` is written by several producers and is not consistent:
some rows hold a POSIX-relative path (`data/outputs/<job>/gen_x.jpg`), some a
Windows-relative one (`data\\outputs\\<job>\\gen_x.jpg`), and some an absolute
path from a previous machine. Every consumer (publish endpoint, scheduler,
export) needs the same answer, so the logic lives here once.
"""

from __future__ import annotations

import logging
from pathlib import Path, PureWindowsPath

from app.config import settings

logger = logging.getLogger("pre.media_paths")


def resolve_output_image(stored_path: str | Path) -> Path | None:
    """
    Return an existing absolute Path for `stored_path`, or None if the file
    cannot be found. Callers must treat None as a hard failure — publishing a
    pin whose image is missing cannot succeed.
    """
    if not stored_path:
        return None

    raw = str(stored_path).strip()
    # Normalise Windows separators so a path written on Windows still resolves
    # if the project is ever read elsewhere.
    normalised = PureWindowsPath(raw).as_posix() if "\\" in raw else raw

    candidates: list[Path] = []
    p = Path(normalised)
    if p.is_absolute():
        candidates.append(p)
    else:
        project_root = Path(".").resolve()
        candidates.append(project_root / normalised)
        # Paths stored with the `data/` prefix already included, relative to the
        # storage root. (The old inline version used `.lstrip("data/")`, which
        # strips characters rather than a prefix and turned
        # "data/outputs/..." into "utputs/...".)
        storage_root = Path(settings.storage_path)
        trimmed = normalised[len("data/"):] if normalised.startswith("data/") else normalised
        candidates.append(storage_root / trimmed)
        candidates.append(settings.outputs_path / Path(normalised).name)

    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                return cand.resolve()
        except OSError:
            continue

    logger.warning("Could not resolve output image %r (tried %s)",
                   raw, ", ".join(str(c) for c in candidates))
    return None

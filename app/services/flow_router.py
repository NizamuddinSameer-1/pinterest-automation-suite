"""
Google Flow Project Workspace Router & Load Balancer.

Distributes image generation jobs across a pool of Google Flow project workspaces
to prevent any single project canvas from becoming bloated, laggy, or hitting memory limits.

Features:
- Multi-project round-robin / random load balancing.
- Auto-loads from data/flow_projects.json, .env FLOW_PROJECT_URLS, or built-in pool.
- Automatic failover: if a project URL fails or is deleted, rotates to the next healthy project.
- Runtime extensibility: add/remove projects via API or JSON file.
"""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path
from typing import Sequence

from app.config import settings

logger = logging.getLogger("pre.flow_router")

PROJECTS_FILE = Path("./data/flow_projects.json").resolve()

# Default seed of the 10 user-provided Google Flow projects
DEFAULT_FLOW_PROJECTS = [
    "https://labs.google/fx/tools/flow/project/11a435e8-0ccb-41dd-9c9e-e8322ef0feca",
    "https://labs.google/fx/tools/flow/project/2547e2bc-d609-4199-aca0-b839cea71b62",
    "https://labs.google/fx/tools/flow/project/81e07d12-1d03-4449-9a14-18dd805c995e",
    "https://labs.google/fx/tools/flow/project/4f4c458e-7d81-4c8d-9062-11eebc4c2477",
    "https://labs.google/fx/tools/flow/project/b77512e8-1520-4bd1-b517-32a21b0e5c16",
    "https://labs.google/fx/tools/flow/project/966e85e4-e87c-40f0-be6a-db9cb1772489",
    "https://labs.google/fx/tools/flow/project/683f3d27-4dae-485c-8130-4b8ce2cd314c",
    "https://labs.google/fx/tools/flow/project/80df481a-8394-4d36-8715-53cc32dad075",
    "https://labs.google/fx/tools/flow/project/12c84a90-7182-4079-abf3-31ce2b1aa031",
    "https://labs.google/fx/tools/flow/project/3f560e82-d0de-46a0-b322-0e72555af503",
]

_ROUND_ROBIN_INDEX = 0


def _clean_url(url: str) -> str:
    """Strip whitespace and trailing slashes."""
    return url.strip().rstrip("/")


def _is_valid_flow_url(url: str) -> bool:
    """Check if string looks like a Google Flow project URL."""
    clean = _clean_url(url)
    return bool(re.search(r"labs\.google/fx/tools/flow/project/[a-zA-Z0-9_-]+", clean))


def get_project_pool() -> list[str]:
    """
    Retrieve all configured Google Flow project URLs.
    Merges data/flow_projects.json, .env variables, and defaults.
    """
    projects: list[str] = []
    seen: set[str] = set()

    def _add(cand: str):
        c = _clean_url(cand)
        if c and _is_valid_flow_url(c) and c not in seen:
            seen.add(c)
            projects.append(c)

    # 1. Read from data/flow_projects.json if exists
    if PROJECTS_FILE.exists():
        try:
            data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
            raw_list = data.get("projects", []) if isinstance(data, dict) else data
            if isinstance(raw_list, list):
                for p in raw_list:
                    if isinstance(p, str):
                        _add(p)
        except Exception as e:
            logger.warning("Could not parse %s: %s", PROJECTS_FILE, e)

    # 2. Read from .env FLOW_PROJECT_URLS (comma or newline separated)
    env_multi = getattr(settings, "flow_project_urls", None)
    if env_multi:
        if isinstance(env_multi, list):
            for u in env_multi:
                _add(u)
        elif isinstance(env_multi, str):
            for u in re.split(r"[,\n;]+", env_multi):
                _add(u)

    # 3. Read from single .env FLOW_PROJECT_URL (can be comma-separated)
    env_single = getattr(settings, "flow_project_url", "")
    if env_single:
        for u in re.split(r"[,\n;]+", env_single):
            _add(u)

    # 4. If pool is empty, initialize with default 10 projects and save
    if not projects:
        for u in DEFAULT_FLOW_PROJECTS:
            _add(u)
        save_project_pool(projects)

    return projects


def save_project_pool(projects: Sequence[str]) -> bool:
    """Save active project list to data/flow_projects.json."""
    try:
        PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        valid = [_clean_url(p) for p in projects if _is_valid_flow_url(p)]
        payload = {
            "projects": valid,
            "total": len(valid),
            "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
        PROJECTS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Saved %d Google Flow projects to %s", len(valid), PROJECTS_FILE)
        return True
    except Exception as e:
        logger.error("Failed to save projects to %s: %s", PROJECTS_FILE, e)
        return False


def get_next_project_url(strategy: str = "round_robin") -> str:
    """
    Get the next Google Flow project workspace URL from the router pool.

    Args:
        strategy: "round_robin" (default) or "random".

    Returns:
        str: Selected Google Flow project URL.
    """
    global _ROUND_ROBIN_INDEX
    pool = get_project_pool()
    if not pool:
        # Fallback to absolute default
        return DEFAULT_FLOW_PROJECTS[0]

    if strategy == "random":
        chosen = random.choice(pool)
    else:
        # Round-robin
        chosen = pool[_ROUND_ROBIN_INDEX % len(pool)]
        _ROUND_ROBIN_INDEX = (_ROUND_ROBIN_INDEX + 1) % len(pool)

    project_id = chosen.split("/")[-1]
    logger.info("🔄 [FLOW ROUTER] Selected project %s (Pool size: %d)", project_id, len(pool))
    return chosen


def get_all_project_candidates() -> list[str]:
    """
    Return the complete list of project URLs in priority/rotation order.
    Used by the automator to try multiple projects if one fails.
    """
    global _ROUND_ROBIN_INDEX
    pool = get_project_pool()
    if not pool:
        return list(DEFAULT_FLOW_PROJECTS)

    # Re-order starting from current round-robin index
    idx = _ROUND_ROBIN_INDEX % len(pool)
    _ROUND_ROBIN_INDEX = (_ROUND_ROBIN_INDEX + 1) % len(pool)
    return pool[idx:] + pool[:idx]


def add_project(url: str) -> tuple[bool, str]:
    """Add a new Google Flow project URL to the pool."""
    clean = _clean_url(url)
    if not _is_valid_flow_url(clean):
        return False, "Invalid Google Flow project URL format. Expected: https://labs.google/fx/tools/flow/project/<uuid>"

    pool = get_project_pool()
    if clean in pool:
        return True, "Project URL is already in the pool."

    pool.append(clean)
    save_project_pool(pool)
    return True, f"Successfully added project {clean.split('/')[-1]} to pool (Total: {len(pool)})."


def remove_project(url_or_uuid: str) -> tuple[bool, str]:
    """Remove a project from the pool by URL or UUID."""
    target = url_or_uuid.strip()
    pool = get_project_pool()
    filtered = [p for p in pool if target not in p]
    if len(filtered) == len(pool):
        return False, "Project not found in pool."

    save_project_pool(filtered)
    return True, f"Removed project. Remaining: {len(filtered)}."

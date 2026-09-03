"""
Google Flow Project Workspace Router & Load Balancer.

Distributes image generation jobs across a pool of Google Flow project workspaces
to prevent any single project canvas from becoming bloated, laggy, or hitting memory limits.

Features:
- Persistent rotation state on disk (data/flow_router_state.json) across Python processes.
- Multi-project round-robin (sequential) or random load balancing.
- Auto-loads from Flow Profiles List.txt, data/flow_projects.json, .env FLOW_PROJECT_URLS, or defaults.
- Usage tracking and metrics per project workspace.
- Automatic failover: if a project URL fails or is deleted, rotates to the next candidate.
- Runtime extensibility: add/remove projects and switch strategy via API or UI.
"""

from __future__ import annotations

import datetime
import json
import logging
import random
import re
from pathlib import Path
from typing import Sequence

from app.config import settings

logger = logging.getLogger("pre.flow_router")

PROJECTS_FILE = Path("./data/flow_projects.json").resolve()
STATE_FILE = Path("./data/flow_router_state.json").resolve()
WORKSPACE_PROFILES_FILE = Path("./Flow Profiles List.txt").resolve()

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


def _clean_url(url: str) -> str:
    """Strip whitespace and trailing slashes."""
    return url.strip().rstrip("/")


def _is_valid_flow_url(url: str) -> bool:
    """Check if string looks like a Google Flow project URL."""
    clean = _clean_url(url)
    return bool(re.search(r"labs\.google/fx/tools/flow/project/[a-zA-Z0-9_-]+", clean))


def _load_state() -> dict:
    """Read the persistent router state from data/flow_router_state.json."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Could not parse router state %s: %s", STATE_FILE, e)
    return {
        "strategy": getattr(settings, "flow_router_strategy", "round_robin"),
        "current_index": 0,
        "last_selected_project": "",
        "last_selected_uuid": "",
        "last_selected_at": None,
        "usage_counts": {},
        "history": [],
    }


def _save_state(state: dict) -> None:
    """Write the persistent router state atomically."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception as e:
        logger.error("Failed to save flow router state to %s: %s", STATE_FILE, e)


def get_project_pool() -> list[str]:
    """
    Retrieve all configured Google Flow project URLs.
    Merges Flow Profiles List.txt, data/flow_projects.json, .env variables, and defaults.
    """
    projects: list[str] = []
    seen: set[str] = set()

    def _add(cand: str):
        c = _clean_url(cand)
        if c and _is_valid_flow_url(c) and c not in seen:
            seen.add(c)
            projects.append(c)

    # 1. Read from root 'Flow Profiles List.txt' if exists
    if WORKSPACE_PROFILES_FILE.exists():
        try:
            for line in WORKSPACE_PROFILES_FILE.read_text(encoding="utf-8").splitlines():
                _add(line)
        except Exception as e:
            logger.warning("Could not read %s: %s", WORKSPACE_PROFILES_FILE, e)

    # 2. Read from data/flow_projects.json if exists
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

    # 3. Read from .env FLOW_PROJECT_URLS (comma or newline separated)
    env_multi = getattr(settings, "flow_project_urls", None)
    if env_multi:
        if isinstance(env_multi, list):
            for u in env_multi:
                _add(u)
        elif isinstance(env_multi, str):
            for u in re.split(r"[,\n;]+", env_multi):
                _add(u)

    # 4. Read from single .env FLOW_PROJECT_URL (can be comma-separated)
    env_single = getattr(settings, "flow_project_url", "")
    if env_single:
        for u in re.split(r"[,\n;]+", env_single):
            _add(u)

    # 5. If pool is empty, initialize with default 10 projects
    if not projects:
        for u in DEFAULT_FLOW_PROJECTS:
            _add(u)

    # Always ensure data/flow_projects.json has the active pool
    if not PROJECTS_FILE.exists():
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
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        PROJECTS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Saved %d Google Flow projects to %s", len(valid), PROJECTS_FILE)
        return True
    except Exception as e:
        logger.error("Failed to save projects to %s: %s", PROJECTS_FILE, e)
        return False


def get_all_project_candidates(strategy: str | None = None, job_id: str | None = None) -> list[str]:
    """
    Return the complete list of project URLs in rotation / priority order,
    persisting the rotation state across Python processes.

    Supported strategies:
      - 'round_robin' (default): Cycles sequentially 1..N across runs.
      - 'random': Randomly selects a workspace from the pool for each run.

    Returns:
        list[str]: Candidate URLs ordered by priority (first candidate is the selected one).
    """
    pool = get_project_pool()
    if not pool:
        return list(DEFAULT_FLOW_PROJECTS)

    state = _load_state()

    # Strategy resolution: parameter > config setting > saved state > default 'round_robin'
    active_strategy = strategy or getattr(settings, "flow_router_strategy", None) or state.get("strategy", "round_robin")
    active_strategy = str(active_strategy).lower().strip()
    if active_strategy not in ("round_robin", "random"):
        active_strategy = "round_robin"

    usage_counts = state.get("usage_counts", {})
    if not isinstance(usage_counts, dict):
        usage_counts = {}

    if active_strategy == "random":
        # Random selection: pick randomly, shuffle remainder for fallback
        chosen_idx = random.randrange(len(pool))
        chosen_url = pool[chosen_idx]
        other_candidates = [p for i, p in enumerate(pool) if i != chosen_idx]
        random.shuffle(other_candidates)
        ordered_candidates = [chosen_url] + other_candidates
    else:
        # Round-robin: persist index across runs/processes and rotate sequentially
        current_idx = int(state.get("current_index", 0))
        chosen_idx = current_idx % len(pool)
        next_idx = (chosen_idx + 1) % len(pool)
        state["current_index"] = next_idx
        chosen_url = pool[chosen_idx]
        ordered_candidates = pool[chosen_idx:] + pool[:chosen_idx]

    proj_uuid = chosen_url.split("/")[-1]
    usage_counts[proj_uuid] = usage_counts.get(proj_uuid, 0) + 1

    state["strategy"] = active_strategy
    state["last_selected_project"] = chosen_url
    state["last_selected_uuid"] = proj_uuid
    state["last_selected_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["usage_counts"] = usage_counts

    history = state.get("history", [])
    if not isinstance(history, list):
        history = []
    history.insert(0, {
        "job_id": job_id or "direct",
        "project_uuid": proj_uuid,
        "strategy": active_strategy,
        "selected_at": state["last_selected_at"],
    })
    state["history"] = history[:50]

    _save_state(state)

    logger.info(
        "🔄 [FLOW ROUTER] Mode: %s | Selected project %s (#%d/%d) | Total runs: %d",
        active_strategy, proj_uuid, chosen_idx + 1, len(pool), usage_counts[proj_uuid]
    )
    print(
        f"[FLOW ROUTER] Selected Workspace #{chosen_idx + 1}/{len(pool)} ({proj_uuid}) "
        f"using strategy='{active_strategy}' (Workspace run count: {usage_counts[proj_uuid]})"
    )

    return ordered_candidates


def get_next_project_url(strategy: str | None = None) -> str:
    """
    Get the next Google Flow project workspace URL from the router pool.
    """
    candidates = get_all_project_candidates(strategy=strategy)
    return candidates[0] if candidates else DEFAULT_FLOW_PROJECTS[0]


def record_project_verified(url: str, job_id: str | None = None) -> None:
    """Record that a project workspace opened and settled successfully."""
    proj_uuid = url.rstrip("/").split("/")[-1]
    state = _load_state()
    verified = state.get("verified_projects", {})
    if not isinstance(verified, dict):
        verified = {}
    verified[proj_uuid] = {
        "last_verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "job_id": job_id,
    }
    state["verified_projects"] = verified
    _save_state(state)


def get_router_status() -> dict:
    """Return complete status and metrics of the Flow Project Router."""
    pool = get_project_pool()
    state = _load_state()
    return {
        "projects": pool,
        "total": len(pool),
        "strategy": state.get("strategy", getattr(settings, "flow_router_strategy", "round_robin")),
        "current_index": state.get("current_index", 0),
        "last_selected_project": state.get("last_selected_project", ""),
        "last_selected_uuid": state.get("last_selected_uuid", ""),
        "last_selected_at": state.get("last_selected_at"),
        "usage_counts": state.get("usage_counts", {}),
        "history": state.get("history", [])[:15],
    }


def set_router_strategy(strategy: str) -> tuple[bool, str]:
    """Set active load balancing strategy ('round_robin' or 'random')."""
    clean = strategy.lower().strip()
    if clean not in ("round_robin", "random"):
        return False, f"Invalid strategy '{strategy}'. Must be 'round_robin' or 'random'."
    state = _load_state()
    state["strategy"] = clean
    _save_state(state)
    logger.info("🔄 [FLOW ROUTER] Strategy updated to: %s", clean)
    return True, f"Strategy updated to {clean}."


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

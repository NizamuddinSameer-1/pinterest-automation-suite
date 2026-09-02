"""
Pinterest Realism Engine — Multiple Pinterest Profiles Manager.

Manages persistent Playwright profiles for multiple distinct Pinterest accounts:
  • Profile metadata registry in `data/pinterest_profiles.json`
  • Per-profile Chromium session data in `data/pinterest_profiles/<profile_id>/`
  • Backward-compatible with the primary account in `data/pinterest_profile/` (ID: "default")
  • Per-profile board catalogues in `data/pinterest_boards_<profile_id>.json`
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("pre.pinterest_profiles")

REGISTRY_PATH = Path("./data/pinterest_profiles.json").resolve()
LEGACY_PROFILE_DIR = Path("./data/pinterest_profile").resolve()
PROFILES_BASE_DIR = Path("./data/pinterest_profiles").resolve()
DEFAULT_PROFILE_ID = "default"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_id(name: str) -> str:
    """Generate a clean slug for profile ID from name."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower()).strip("_")
    return slug[:40] or "profile"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to read JSON at %s: %s", path, e)
    return None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _check_profile_dir_auth(profile_dir: Path) -> bool:
    """Check if Chromium user data dir has session cookies or storage."""
    if not profile_dir.exists() or not profile_dir.is_dir():
        return False
    # Check for Default/Network/Cookies or Default/Cookies or general files
    default_dir = profile_dir / "Default"
    if default_dir.exists():
        cookies_net = default_dir / "Network" / "Cookies"
        cookies_root = default_dir / "Cookies"
        if cookies_net.exists() or cookies_root.exists():
            return True
    # Fallback: check if there are at least 3 files/folders created by Chrome
    try:
        items = list(profile_dir.iterdir())
        return len(items) >= 3
    except OSError:
        return False


def _get_cached_boards_count(profile_id: str) -> int:
    """Read the number of cached boards for this profile."""
    catalog_path = get_boards_catalog_path(profile_id)
    if catalog_path.exists():
        raw = _read_json(catalog_path)
        if raw and isinstance(raw.get("boards"), list):
            return len(raw["boards"])
    return 0


def _load_registry() -> dict[str, Any]:
    """Load or initialize the profiles registry."""
    raw = _read_json(REGISTRY_PATH)
    if raw and isinstance(raw.get("profiles"), list):
        return raw

    # Initialize default registry with legacy profile if exists
    registry = {
        "active_profile_id": DEFAULT_PROFILE_ID,
        "profiles": [
            {
                "id": DEFAULT_PROFILE_ID,
                "name": "Main Account",
                "folder": str(LEGACY_PROFILE_DIR.name),
                "is_default": True,
                "created_at": _now_iso(),
            }
        ],
    }
    _write_json(REGISTRY_PATH, registry)
    return registry


def list_profiles() -> list[dict[str, Any]]:
    """List all registered Pinterest profiles with active auth status & board counts."""
    registry = _load_registry()
    active_id = registry.get("active_profile_id", DEFAULT_PROFILE_ID)
    profiles_list = registry.get("profiles", [])

    results = []
    for p in profiles_list:
        pid = p["id"]
        pdir = get_profile_dir(pid)
        authenticated = _check_profile_dir_auth(pdir)
        boards_count = _get_cached_boards_count(pid)

        results.append({
            "id": pid,
            "name": p.get("name", pid),
            "folder": p.get("folder", pid),
            "is_default": bool(p.get("is_default", False)),
            "is_active": (pid == active_id),
            "authenticated": authenticated,
            "profile_dir": str(pdir),
            "cached_boards_count": boards_count,
            "created_at": p.get("created_at", _now_iso()),
        })
    return results


def get_profile(profile_id: str | None = None) -> dict[str, Any] | None:
    """Get a single profile's metadata."""
    target_id = (profile_id or DEFAULT_PROFILE_ID).strip()
    profiles = list_profiles()
    for p in profiles:
        if p["id"] == target_id:
            return p
    return None


def get_profile_dir(profile_id: str | None = None) -> Path:
    """
    Resolve the persistent Chromium profile directory on disk for a given profile ID.
    - "default" or empty -> `data/pinterest_profile` (or `data/pinterest_profiles/default`)
    - other -> `data/pinterest_profiles/<profile_id>`
    """
    pid = (profile_id or DEFAULT_PROFILE_ID).strip()
    if pid == DEFAULT_PROFILE_ID:
        return LEGACY_PROFILE_DIR

    registry = _load_registry()
    for p in registry.get("profiles", []):
        if p["id"] == pid:
            folder = p.get("folder") or pid
            if folder == LEGACY_PROFILE_DIR.name:
                return LEGACY_PROFILE_DIR
            return (PROFILES_BASE_DIR / folder).resolve()

    # If not registered yet, default to folder under PROFILES_BASE_DIR
    return (PROFILES_BASE_DIR / pid).resolve()


def get_boards_catalog_path(profile_id: str | None = None) -> Path:
    """Return the boards catalogue JSON file path for a profile."""
    pid = (profile_id or DEFAULT_PROFILE_ID).strip()
    if pid == DEFAULT_PROFILE_ID:
        return Path("./data/pinterest_boards.json").resolve()
    return Path(f"./data/pinterest_boards_{pid}.json").resolve()


def get_boards_refresh_path(profile_id: str | None = None) -> Path:
    """Return the boards refresh status JSON file path for a profile."""
    pid = (profile_id or DEFAULT_PROFILE_ID).strip()
    if pid == DEFAULT_PROFILE_ID:
        return Path("./data/pinterest_boards_refresh.json").resolve()
    return Path(f"./data/pinterest_boards_refresh_{pid}.json").resolve()


def create_profile(name: str, profile_id: str | None = None) -> dict[str, Any]:
    """Register a new Pinterest profile."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Profile name cannot be empty")

    registry = _load_registry()
    profiles = registry.get("profiles", [])

    # Determine unique ID
    base_id = profile_id.strip() if profile_id else _sanitize_id(clean_name)
    target_id = base_id
    existing_ids = {p["id"] for p in profiles}

    counter = 1
    while target_id in existing_ids:
        target_id = f"{base_id}_{counter}"
        counter += 1

    new_profile = {
        "id": target_id,
        "name": clean_name,
        "folder": target_id,
        "is_default": len(profiles) == 0,
        "created_at": _now_iso(),
    }
    profiles.append(new_profile)
    registry["profiles"] = profiles
    _write_json(REGISTRY_PATH, registry)

    # Ensure profile directory exists
    pdir = get_profile_dir(target_id)
    pdir.mkdir(parents=True, exist_ok=True)

    logger.info("Created new Pinterest profile: %s (%s) at %s", clean_name, target_id, pdir)
    return get_profile(target_id)  # type: ignore[return-value]


def delete_profile(profile_id: str) -> bool:
    """Delete a profile and its stored files from disk."""
    pid = profile_id.strip()
    if pid == DEFAULT_PROFILE_ID:
        # Don't delete the default profile entry completely, but reset folder if needed
        raise ValueError("Cannot delete the Default profile. You can re-authenticate it instead.")

    registry = _load_registry()
    profiles = registry.get("profiles", [])
    filtered = [p for p in profiles if p["id"] != pid]
    if len(filtered) == len(profiles):
        return False

    registry["profiles"] = filtered
    if registry.get("active_profile_id") == pid:
        registry["active_profile_id"] = DEFAULT_PROFILE_ID
    _write_json(REGISTRY_PATH, registry)

    # Delete profile folder on disk
    pdir = (PROFILES_BASE_DIR / pid).resolve()
    if pdir.exists() and pdir.is_dir():
        try:
            shutil.rmtree(pdir)
            logger.info("Deleted profile folder at %s", pdir)
        except Exception as e:
            logger.warning("Failed to clean up profile folder %s: %s", pdir, e)

    # Delete cached boards file if exists
    bpath = get_boards_catalog_path(pid)
    if bpath.exists():
        try:
            bpath.unlink()
        except Exception:
            pass

    return True


def set_default_profile(profile_id: str) -> bool:
    """Set a profile as the active default."""
    pid = profile_id.strip()
    registry = _load_registry()
    profiles = registry.get("profiles", [])

    found = False
    for p in profiles:
        if p["id"] == pid:
            p["is_default"] = True
            found = True
        else:
            p["is_default"] = False

    if not found:
        return False

    registry["active_profile_id"] = pid
    registry["profiles"] = profiles
    _write_json(REGISTRY_PATH, registry)
    return True

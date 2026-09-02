"""
Flow Library — the generated-image asset manager.

The engine used to treat generated images as throwaway intermediates: they were
turned into pins, the pins were posted, and the images were left orphaned on
disk with no way to find them again. This module is the answer to "organise my
Flow-generated images with their prompts".

Design rules (hard):

1. DISK IS TRUTH. The library is rebuilt by scanning ``data/outputs/**`` for
   image files, never by trusting the database. If a row and a file disagree,
   the file wins — a missing database row must not hide a real image.

2. PROMPT IS FIRST-CLASS. Every item carries the exact prompt that generated
   it. Resolution order:
      a) ``prompt.txt`` sitting next to the image (written by the Flow
         background runner at generation time — most faithful);
      b) the newest ``prompt_versions`` row for that job (database);
      c) empty — the image is kept, marked ``prompt_source="none"``.

3. USER ANNOTATIONS SURVIVE RE-SCANS. Notes, tags and ``favorite`` live in the
   persistent index ``data/flow_library/library.json``. Re-running ``scan()``
   merges fresh disk metadata into the old entry instead of clobbering it.

4. NO STYLES ABSTRACTION. The library deliberately does not re-expose Visual
   DNA or the 13-section scene machinery — it is a flat, searchable shelf of
   image -> prompt pairs, grouped by the job that produced them.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("pre.flow_library")

try:
    from PIL import Image

    _PIL = True
except Exception:  # Pillow is a dependency, but degrade gracefully.
    _PIL = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
# Non-image noise that lives inside output dirs and must never become a card.
_SKIP_NAMES = {"bg_log.txt", "status.json", "prompt.txt", "ref_image_path.txt"}
_SKIP_PREFIXES = ("step",)  # playwright debug screenshots: step1_workspace.png …


def _outputs_dir() -> Path:
    return Path(settings.storage_path) / "outputs"


def _index_path() -> Path:
    return Path(settings.storage_path) / "flow_library" / "library.json"


def _db_path() -> Path:
    url = settings.database_url
    # sqlite+aiosqlite:///./data/pre.db -> ./data/pre.db
    if url.startswith("sqlite"):
        rel = url.split("///", 1)[-1].lstrip("/")
        return Path(rel)
    return Path(settings.storage_path) / "pre.db"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Database lookups (read-only, sync sqlite3 is fine — WAL tolerates it) ──
def _load_db_maps() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Return (jobs map keyed by job id, latest prompt per job id).

    Read straight from the SQLite file. The library only ever *reads* the
    database; writes go to its own index file so a re-scan can never damage
    application state.
    """
    jobs: dict[str, dict[str, Any]] = {}
    prompts: dict[str, str] = {}
    db = _db_path()
    if not db.exists():
        return jobs, prompts
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for r in conn.execute(
            "SELECT j.id, j.current_state, j.created_at, "
            "       p.name AS product_name, p.price, p.currency, "
            "       r.trend_label, r.category AS ref_category "
            "FROM jobs j "
            "LEFT JOIN products p ON p.id = j.product_id "
            "LEFT JOIN \"references\" r ON r.id = j.reference_id"
        ):
            jobs[r["id"]] = dict(r)
        # newest prompt version per job (highest version number)
        for r in conn.execute(
            "SELECT job_id, prompt_text, version FROM prompt_versions "
            "ORDER BY version DESC"
        ):
            prompts.setdefault(r["job_id"], r["prompt_text"] or "")
        conn.close()
    except sqlite3.Error as exc:
        logger.warning("Flow library could not read database: %s", exc)
    return jobs, prompts


def _image_size(path: Path) -> tuple[int | None, int | None]:
    if not _PIL:
        return None, None
    try:
        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        return None, None


def _read_prompt_txt(image_dir: Path) -> str:
    """Look for prompt.txt beside the image, then one directory up."""
    for candidate in (image_dir / "prompt.txt", image_dir.parent / "prompt.txt"):
        try:
            if candidate.exists():
                text = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    return text
        except OSError:
            continue
    return ""


def _is_library_image(path: Path) -> bool:
    if path.suffix.lower() not in IMAGE_EXTS:
        return False
    name = path.name.lower()
    if name in _SKIP_NAMES:
        return False
    if any(name.startswith(p) for p in _SKIP_PREFIXES):
        return False
    return True


# ── Persistent index ──────────────────────────────────────────────────────
def load_index() -> dict[str, Any]:
    """Load the whole index. Never raises — a corrupt index starts empty."""
    path = _index_path()
    if not path.exists():
        return {"version": 1, "scanned_at": None, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("items"), dict):
            data["items"] = {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Flow library index unreadable (%s); starting empty", exc)
        return {"version": 1, "scanned_at": None, "items": {}}


def save_index(index: dict[str, Any]) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic on Windows


# ── Scan ──────────────────────────────────────────────────────────────────
def scan() -> dict[str, Any]:
    """Walk the outputs tree and rebuild the item list.

    Fresh disk facts (bytes, dimensions, prompt) always win. User annotations
    (notes, tags, favorite) are carried forward from the previous index entry.
    Items whose file disappeared from disk are dropped.
    """
    root = _outputs_dir()
    old = load_index()
    old_items: dict[str, dict[str, Any]] = old.get("items", {})
    jobs_map, prompt_map = _load_db_maps()

    items: dict[str, dict[str, Any]] = {}
    image_count = 0
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or not _is_library_image(path):
                continue
            image_count += 1
            rel = path.relative_to(root).as_posix()  # e.g. "<job>/flow_var_1.jpg"
            job_id = path.relative_to(root).parts[0]
            stat = path.stat()
            width, height = _image_size(path)

            prompt_file = _read_prompt_txt(path.parent)
            if prompt_file:
                prompt, prompt_source = prompt_file, "file"
            elif prompt_map.get(job_id):
                prompt, prompt_source = prompt_map[job_id], "db"
            else:
                prompt, prompt_source = "", "none"

            job = jobs_map.get(job_id, {})
            prev = old_items.get(rel, {})

            items[rel] = {
                "id": rel,
                "job_id": job_id,
                "batch": job_id[:8],
                "filename": path.name,
                "rel_path": f"outputs/{rel}",
                "url": f"/data/outputs/{rel}",
                "bytes": stat.st_size,
                "width": width,
                "height": height,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "prompt": prompt,
                "prompt_source": prompt_source,
                "product_name": job.get("product_name"),
                "price": job.get("price"),
                "currency": job.get("currency"),
                "job_state": job.get("current_state"),
                "trend_label": job.get("trend_label"),
                "ref_category": job.get("ref_category"),
                # user annotations — carry forward, default if new
                "favorite": bool(prev.get("favorite", False)),
                "tags": list(prev.get("tags", [])),
                "notes": prev.get("notes", ""),
            }

    index = {
        "version": 1,
        "scanned_at": _utcnow(),
        "items": items,
    }
    save_index(index)
    added = len(set(items) - set(old_items))
    removed = len(set(old_items) - set(items))
    logger.info(
        "Flow library scan: %d images on disk (%d indexed, +%d new, -%d gone)",
        image_count, len(items), added, removed,
    )
    return {
        "scanned_at": index["scanned_at"],
        "images_on_disk": image_count,
        "indexed": len(items),
        "added": added,
        "removed": removed,
        "with_prompt": sum(1 for i in items.values() if i["prompt"]),
        "without_prompt": sum(1 for i in items.values() if not i["prompt"]),
    }


# ── Query & mutate ────────────────────────────────────────────────────────
def _ensure_index() -> dict[str, Any]:
    """Return a ready index, scanning once on first use."""
    index = load_index()
    if not index.get("scanned_at"):
        scan()
        index = load_index()
    return index


def list_items(
    q: str | None = None,
    job_id: str | None = None,
    favorite: bool | None = None,
    has_prompt: bool | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    items = list(_ensure_index()["items"].values())
    if q:
        needle = q.strip().lower()
        items = [
            i for i in items
            if needle in (i["prompt"] or "").lower()
            or needle in (i["filename"] or "").lower()
            or needle in (i["product_name"] or "").lower()
            or needle in (i["notes"] or "").lower()
            or needle in " ".join(i["tags"]).lower()
            or needle in (i["job_id"] or "").lower()
        ]
    if job_id:
        items = [i for i in items if i["job_id"] == job_id or i["batch"] == job_id]
    if favorite is not None:
        items = [i for i in items if i["favorite"] is favorite]
    if has_prompt is not None:
        items = [i for i in items if bool(i["prompt"]) is has_prompt]
    if tag:
        items = [i for i in items if tag in i["tags"]]
    # newest first
    items.sort(key=lambda i: (i["modified_at"] or "", i["id"]), reverse=True)
    return items


def get_item(item_id: str) -> dict[str, Any] | None:
    return _ensure_index()["items"].get(item_id)


def update_item(item_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    index = _ensure_index()
    item = index["items"].get(item_id)
    if item is None:
        return None
    if "favorite" in patch:
        item["favorite"] = bool(patch["favorite"])
    if "notes" in patch:
        item["notes"] = str(patch["notes"])[:2000]
    if "tags" in patch:
        tags = patch["tags"]
        if isinstance(tags, list):
            item["tags"] = [str(t).strip() for t in tags if str(t).strip()][:20]
    save_index(index)
    return item


def delete_item(item_id: str) -> bool:
    """Remove the image file and drop it from the index."""
    index = _ensure_index()
    item = index["items"].get(item_id)
    if item is None:
        return False
    path = _outputs_dir() / item_id
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        logger.warning("Could not delete %s: %s", path, exc)
        return False
    index["items"].pop(item_id, None)
    save_index(index)
    return True


def stats() -> dict[str, Any]:
    items = list(_ensure_index()["items"].values())
    total_bytes = sum(i["bytes"] for i in items)
    jobs = {i["job_id"] for i in items}
    return {
        "images": len(items),
        "bytes": total_bytes,
        "mb": round(total_bytes / 1048576, 1),
        "jobs": len(jobs),
        "with_prompt": sum(1 for i in items if i["prompt"]),
        "without_prompt": sum(1 for i in items if not i["prompt"]),
        "favorites": sum(1 for i in items if i["favorite"]),
        "tags": sorted({t for i in items for t in i["tags"]}),
        "scanned_at": load_index().get("scanned_at"),
    }

"""
Flow Library API — browse, search, annotate and manage generated images.

Mounted at /api/library. Backed by app/services/flow_library.py.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services import flow_library

logger = logging.getLogger("pre.api.library")

router = APIRouter(prefix="/api/library", tags=["library"])


class ItemPatch(BaseModel):
    favorite: bool | None = None
    notes: str | None = None
    tags: list[str] | None = None


@router.post("/scan")
def rescan_library() -> dict[str, Any]:
    """Re-scan data/outputs and rebuild the index. Idempotent, never destroys
    user annotations."""
    return flow_library.scan()


@router.get("/stats")
def library_stats() -> dict[str, Any]:
    return flow_library.stats()


@router.get("")
def list_items(
    q: str | None = Query(None, description="search prompt / filename / product / notes"),
    job_id: str | None = Query(None, description="full job id or 8-char batch prefix"),
    favorite: bool | None = None,
    has_prompt: bool | None = None,
    tag: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items = flow_library.list_items(
        q=q, job_id=job_id, favorite=favorite, has_prompt=has_prompt, tag=tag,
    )
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "items": items[offset : offset + limit],
    }


@router.get("/{item_id:path}")
def get_item(item_id: str) -> dict[str, Any]:
    item = flow_library.get_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found in library")
    return item


@router.put("/{item_id:path}")
def update_item(item_id: str, patch: ItemPatch) -> dict[str, Any]:
    payload = patch.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Nothing to update")
    item = flow_library.update_item(item_id, payload)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found in library")
    return item


@router.delete("/{item_id:path}")
def delete_item(item_id: str) -> dict[str, Any]:
    if not flow_library.delete_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found or could not be deleted")
    return {"deleted": item_id}

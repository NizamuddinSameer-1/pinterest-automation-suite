"""
Lookbooks & Bridge Page API Router — Serves standalone HTML lookbooks and triggers generation.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Job, JobOutput, PinDraft, Product
from app.services.article_generator import generate_lookbook_html
from app.services.bridge_copilot import BridgeCopyUnavailable
from app.services.media_paths import resolve_output_image
from app.services.output_service import _product_to_dict
from app.services.vercel_publisher import VercelDeployError, deploy_article_to_vercel

router = APIRouter(tags=["lookbooks"])
logger = logging.getLogger("pre.api.lookbooks")


@router.get("/lookbook.css")
async def serve_lookbook_css():
    """Serve the shared lookbook stylesheet."""
    css_path = settings.lookbooks_path / "lookbook.css"
    if not css_path.exists():
        static_css = Path(__file__).resolve().parents[1] / "static" / "lookbook.css"
        if static_css.exists():
            css_path = static_css
    if not css_path.exists():
        raise HTTPException(status_code=404, detail="Stylesheet not found")
    return Response(content=css_path.read_text(encoding="utf-8"), media_type="text/css")


@router.get("/sitemap.xml")
async def serve_sitemap():
    """Serve the dynamic sitemap XML."""
    sitemap_path = settings.lookbooks_path / "sitemap.xml"
    if not sitemap_path.exists():
        from app.services.git_publisher import generate_catalog_index
        await generate_catalog_index()
    if not sitemap_path.exists():
        raise HTTPException(status_code=404, detail="Sitemap not found")
    return Response(content=sitemap_path.read_text(encoding="utf-8"), media_type="application/xml")


@router.get("/robots.txt")
async def serve_robots():
    """Serve the dynamic robots.txt."""
    robots_path = settings.lookbooks_path / "robots.txt"
    if not robots_path.exists():
        from app.services.git_publisher import generate_catalog_index
        await generate_catalog_index()
    if not robots_path.exists():
        raise HTTPException(status_code=404, detail="Robots.txt not found")
    return Response(content=robots_path.read_text(encoding="utf-8"), media_type="text/plain")


@router.get("/img/{filename}")
async def serve_lookbook_image(filename: str):
    """Serve a lookbook image from data/lookbooks/img/."""
    clean_name = Path(filename).name
    target = settings.lookbooks_path / "img" / clean_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    media_type = "image/webp" if clean_name.endswith(".webp") else "image/jpeg"
    return FileResponse(target, media_type=media_type)


@router.get("/lookbooks/{identifier}", response_class=HTMLResponse)
async def serve_lookbook(identifier: str):
    """
    Serve a rendered standalone lookbook HTML page by job ID or slug.
    Sanitizes identifier to prevent path traversal and performs deterministic matching.
    """
    # 1. Sanitize identifier against path traversal attacks
    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", identifier.strip())
    if not clean_id:
        raise HTTPException(status_code=400, detail="Invalid lookbook identifier.")

    lookbooks_dir = settings.lookbooks_path
    outputs_dir = settings.outputs_path
    
    # 2. Exact match check in lookbooks folder
    target = lookbooks_dir / f"{clean_id}.html"
    
    # 3. Exact match check in job outputs folder
    if not target.exists():
        target = outputs_dir / clean_id / "lookbook.html"

    # 4. Safe prefix/suffix match (e.g. 8-char job_id suffix on a slug: '{product_slug}-{job_id_8}.html')
    if not target.exists():
        exact_suffix = f"-{clean_id}.html"
        exact_prefix = f"{clean_id}-"
        for candidate in lookbooks_dir.iterdir():
            if candidate.is_file() and candidate.name.endswith(".html"):
                if candidate.name.endswith(exact_suffix) or candidate.name.startswith(exact_prefix):
                    target = candidate
                    break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Lookbook '{clean_id}' not found.")

    html_content = target.read_text(encoding="utf-8")
    return HTMLResponse(content=html_content, status_code=200)


class LookbookGenerateRequest(BaseModel):
    affiliate_url: str | None = None


@router.post("/api/jobs/{job_id}/lookbook")
async def generate_job_lookbook(
    job_id: str,
    body: LookbookGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate or regenerate a standalone universal responsive lookbook for a completed job,
    deploy to Vercel (or local preview), and update the associated pin draft destination URLs.
    """
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    product = await db.get(Product, job.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if body and body.affiliate_url and body.affiliate_url.strip():
        product.affiliate_url = body.affiliate_url.strip()
        await db.flush()

    output_dir = settings.outputs_path / job_id
    image_paths: list[str] = []

    # 1. Gather all outputs for this batch from database
    outputs_stmt = select(JobOutput).where(JobOutput.job_id == job.id)
    outputs_res = await db.execute(outputs_stmt)
    job_outputs = outputs_res.scalars().all()
    for out in job_outputs:
        resolved = resolve_output_image(out.image_path)
        if resolved and Path(resolved).exists():
            image_paths.append(str(resolved))

    # Fallback to disk scan if no DB JobOutput records or files moved
    if not image_paths:
        image_paths = sorted([str(f) for f in output_dir.glob("flow_var_*.jpg")])
    if not image_paths:
        image_paths = sorted([str(f) for f in output_dir.glob("*.jpg")] + [str(f) for f in output_dir.glob("*.png")])

    if not image_paths:
        raise HTTPException(status_code=400, detail="No variation images found on disk for this job batch.")

    product_data = _product_to_dict(product)
    scene_data = json.loads(job.scene_json) if job.scene_json else {}

    # 1. Assemble HTML & OG thumbnail
    try:
        slug, html_content, og_image_bytes = await generate_lookbook_html(
            job_id=job.id,
            product_data=product_data,
            scene_data=scene_data,
            image_paths=image_paths,
            affiliate_url=product.affiliate_url,
        )
    except BridgeCopyUnavailable as e:
        raise HTTPException(status_code=422, detail=f"Grounded copy generation failed: {e}") from e

    # 2. Deploy to Vercel Production
    try:
        deploy_url = await deploy_article_to_vercel(
            slug=slug,
            html_content=html_content,
            job_id=job.id,
            og_image_bytes=og_image_bytes,
        )
    except VercelDeployError as e:
        # The lookbook is not live anywhere. Say so instead of returning a URL
        # that would be written onto pin drafts as a destination.
        raise HTTPException(status_code=502, detail=str(e)) from e

    # 3. Update PinDraft records in Database
    updated_drafts_count = 0
    if deploy_url:
        stmt = select(PinDraft).where(PinDraft.job_id == job.id)
        result = await db.execute(stmt)
        drafts = result.scalars().all()
        for draft in drafts:
            draft.destination_url = deploy_url
            updated_drafts_count += 1
        if updated_drafts_count > 0:
            await db.commit()
            logger.info("Updated %d PinDraft destination_urls to %s for job %s", updated_drafts_count, deploy_url, job.id)

    return {
        "job_id": job.id,
        "slug": slug,
        "deploy_url": deploy_url,
        "local_preview": f"http://127.0.0.1:8000/lookbooks/{job.id}",
        "variations_count": len(image_paths),
        "pin_drafts_updated": updated_drafts_count,
    }

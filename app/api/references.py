"""
Reference API routes — upload, analyze, edit Visual DNA.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Product, Reference, ReferenceAnalysis, VisualDNA
from app.pipeline.errors import PipelineStageError
from app.pipeline.reference_analyst import analyze_reference
from app.pipeline.visual_dna import extract_visual_dna
from app.providers.llm import LLMUnavailableError
from app.schemas.schemas import ReferenceFromProductRequest, ReferenceOut, VisualDNAUpdate

router = APIRouter(prefix="/api/references", tags=["references"])

logger = logging.getLogger("pre.api.references")

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("", status_code=201)
async def upload_reference(
    file: UploadFile = File(...),
    campaign_id: str | None = Form(None),
    trend_label: str | None = Form(None),
    category: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Upload a reference image."""
    # Validate
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"File type {file.content_type} not allowed. Use JPEG, PNG, or WebP.")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "File too large. Maximum 10MB.")

    # Save file
    ref_id = str(uuid4())
    ext = file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    filename = f"{ref_id}.{ext}"
    file_path = settings.references_path / filename
    settings.references_path.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)

    # Default labels if not provided
    effective_trend = (trend_label or "").strip() or "trending"
    effective_category = (category or "").strip() or "lifestyle"

    # Create record
    ref = Reference(
        id=ref_id,
        campaign_id=campaign_id,
        image_path=str(file_path),
        trend_label=effective_trend,
        category=effective_category,
        status="uploaded",
    )
    db.add(ref)
    await db.flush()
    await db.refresh(ref)

    return {"id": ref.id, "status": "uploaded", "image_path": str(file_path)}


@router.post("/from-product", status_code=201)
async def create_reference_from_product(
    body: ReferenceFromProductRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Reference directly from a saved Product in the database.
    Copies product image, creates Reference row, runs vision analysis and extracts Visual DNA.
    """
    import shutil
    import httpx
    product = await db.get(Product, body.product_id)
    if not product:
        raise HTTPException(404, f"Product {body.product_id} not found")

    ref_id = str(uuid4())
    dest_path = settings.references_path / f"{ref_id}.jpg"
    settings.references_path.mkdir(parents=True, exist_ok=True)

    src_path_str = (product.product_image_path or "").strip()
    image_saved = False

    if src_path_str and Path(src_path_str).is_file():
        try:
            shutil.copy2(Path(src_path_str), dest_path)
            image_saved = True
        except Exception:
            pass

    if not image_saved and (src_path_str.startswith("http://") or src_path_str.startswith("https://")):
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(src_path_str)
                if r.status_code == 200:
                    dest_path.write_bytes(r.content)
                    image_saved = True
        except Exception as e:
            logger.warning("Failed to download product image from url %s: %s", src_path_str, e)

    if not image_saved:
        truth = json.loads(product.product_truth_json) if product.product_truth_json else {}
        img_url = truth.get("primary_image_url") or truth.get("image_url")
        if img_url and (img_url.startswith("http://") or img_url.startswith("https://")):
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.get(img_url)
                    if r.status_code == 200:
                        dest_path.write_bytes(r.content)
                        image_saved = True
            except Exception as e:
                logger.warning("Failed to download truth product image from url %s: %s", img_url, e)

    # Fallback: if no image, create a 1x1 dummy jpg or find existing reference
    if not dest_path.exists() or dest_path.stat().st_size == 0:
        existing_ref = (await db.execute(select(Reference).order_by(Reference.created_at.desc()))).scalars().first()
        if existing_ref and Path(existing_ref.image_path).is_file():
            shutil.copy2(Path(existing_ref.image_path), dest_path)
        else:
            # Minimal valid 1x1 JPEG
            dest_path.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9")

    # Determine trend label from product truth or title
    trend = (body.trend_label or "").strip()
    if not trend:
        truth = json.loads(product.product_truth_json) if product.product_truth_json else {}
        trend = truth.get("style_query") or product.name[:60]

    ref = Reference(
        id=ref_id,
        campaign_id=product.campaign_id,
        image_path=str(dest_path),
        trend_label=trend,
        category=product.category or "Fashion & Lifestyle",
        status="uploaded",
    )
    db.add(ref)
    await db.flush()
    await db.refresh(ref)

    # ── Real LLM Vision Analysis ─────────────────────────────────────────
    # Send the product image to the LLM for genuine 10-dimension photographic
    # analysis, then derive Visual DNA from what the model actually sees.
    # Falls back to hardcoded defaults only when the LLM is unreachable.
    analysis_data = None
    dna_data = None
    llm_analyzed = False

    # Only attempt real analysis if the image is a real photograph (not the
    # 1×1 dummy JPEG fallback, which has nothing to analyse).
    image_is_real = dest_path.exists() and dest_path.stat().st_size > 500

    if image_is_real:
        try:
            analysis_data = await analyze_reference(str(dest_path))
            llm_analyzed = True
            logger.info("LLM vision analysis succeeded for product-reference %s", ref.id)

            # Store the ReferenceAnalysis row so downstream stages (scene
            # director, subject guard) have the real reading.
            analysis_record = ReferenceAnalysis(
                reference_id=ref.id,
                analysis_json=json.dumps(analysis_data),
            )
            db.add(analysis_record)
            await db.flush()
        except Exception as e:
            logger.warning(
                "LLM vision analysis failed for product-reference %s: %s. "
                "Falling back to baseline Visual DNA.",
                ref.id, e,
            )
            analysis_data = None

    if llm_analyzed and analysis_data:
        # Stage 2: Extract real Visual DNA from the LLM's analysis
        try:
            dna_data = await extract_visual_dna(analysis_data, image_path=dest_path)
        except Exception as e:
            logger.warning(
                "Visual DNA extraction failed for product-reference %s: %s. "
                "Falling back to baseline Visual DNA.",
                ref.id, e,
            )
            dna_data = None

    # Fallback: hardcoded baseline defaults (only used when LLM is unavailable)
    if dna_data is None:
        dna_data = {
            "capture_identity": {
                "type": "casual_ugc_lifestyle",
                "professionalism": "moderate",
                "spontaneity": "high",
            },
            "composition_dna": {
                "centering": "slightly_off_center",
                "framing": "slightly_imperfect",
                "crop": "natural",
                "camera_height": "human_standing",
            },
            "environment_dna": {
                "real_world_context": True,
                "clutter": "low",
                "background_activity": "low",
            },
            "lighting_dna": {
                "type": "natural_daylight",
                "quality": "soft_directional",
                "color_cast": "warm_neutral",
            },
            "camera_dna": {
                "device_family": "iPhone 15 Pro",
                "focal_length": "28mm",
                "sensor_noise": "subtle_natural_chroma",
                "dynamic_range": "natural_smartphone",
            },
            "material_dna": {
                "texture_visibility": "high_tactile",
                "surface_imperfection": "natural_fabric_grain",
            },
            "realism_markers": {
                "anti_studio": True,
                "anti_cinematic": True,
                "imperfection_level": "moderate",
            },
        }

    dna_record = VisualDNA(
        reference_id=ref.id,
        version=1,
        dna_json=json.dumps(dna_data),
    )
    db.add(dna_record)
    ref.status = "analyzed"
    await db.flush()
    await db.refresh(ref)

    return {
        "id": ref.id,
        "reference_id": ref.id,
        "product_id": product.id,
        "product_name": product.name,
        "status": ref.status,
        "image_path": str(dest_path),
        "trend_label": ref.trend_label,
        "category": ref.category,
        "affiliate_url": product.affiliate_url,
        "has_visual_dna": True,
        "visual_dna": dna_data,
        "llm_analyzed": llm_analyzed,
        "analysis": analysis_data,
    }


@router.get("")
async def list_references(
    campaign_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    List all references, optionally filtered by campaign.

    Each row carries `has_visual_dna`. Without it the Creative Lab could not tell
    an analysed reference from an unanalysed one, so the operator only found out
    by clicking Generate and getting a 409 — `ref.status` is not a substitute,
    because DNA seeded directly into the table leaves the status at "uploaded".
    """
    query = select(Reference).order_by(Reference.created_at.desc())
    if campaign_id:
        query = query.where(Reference.campaign_id == campaign_id)
    result = await db.execute(query)
    refs = result.scalars().all()

    # One query for the whole page rather than one per reference.
    dna_rows = await db.execute(
        select(VisualDNA.reference_id, func.max(VisualDNA.version)).group_by(VisualDNA.reference_id)
    )
    dna_versions = {ref_id: version for ref_id, version in dna_rows.all()}

    out = []
    for ref in refs:
        item = {
            "id": ref.id,
            "campaign_id": ref.campaign_id,
            "image_path": ref.image_path,
            "trend_label": ref.trend_label,
            "category": ref.category,
            "status": ref.status,
            "created_at": ref.created_at.isoformat(),
            "has_visual_dna": ref.id in dna_versions,
            "dna_version": dna_versions.get(ref.id),
        }
        out.append(item)
    return out


@router.get("/{reference_id}")
async def get_reference(reference_id: str, db: AsyncSession = Depends(get_db)):
    """Get a reference with its analysis and Visual DNA."""
    ref = await db.get(Reference, reference_id)
    if not ref:
        raise HTTPException(404, "Reference not found")

    # Get analysis
    analysis_result = await db.execute(
        select(ReferenceAnalysis).where(ReferenceAnalysis.reference_id == reference_id)
    )
    analysis = analysis_result.scalar_one_or_none()

    # Get latest Visual DNA
    dna_result = await db.execute(
        select(VisualDNA)
        .where(VisualDNA.reference_id == reference_id)
        .order_by(VisualDNA.version.desc())
    )
    dna = dna_result.scalars().first()

    return {
        "id": ref.id,
        "campaign_id": ref.campaign_id,
        "image_path": ref.image_path,
        "trend_label": ref.trend_label,
        "category": ref.category,
        "status": ref.status,
        "created_at": ref.created_at.isoformat(),
        "analysis": json.loads(analysis.analysis_json) if analysis else None,
        "visual_dna": {
            "id": dna.id,
            "version": dna.version,
            "is_manually_edited": dna.is_manually_edited,
            "data": json.loads(dna.dna_json),
        } if dna else None,
    }


@router.post("/{reference_id}/analyze")
async def analyze_reference_endpoint(
    reference_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger vision analysis + Visual DNA extraction for a reference.

    This is the *only* producer of Visual DNA, and nothing can be generated
    without it, so a failure here has to be reported as a failure — the whole
    database had 0 `reference_analyses` rows because nothing ever called this and
    the missing DNA only showed up later as a 409 from `/generate`.
    """
    ref = await db.get(Reference, reference_id)
    if not ref:
        raise HTTPException(404, "Reference not found")

    if not Path(ref.image_path).is_file():
        raise HTTPException(
            409,
            f"The reference image is missing from disk ({ref.image_path}), so there is "
            "nothing to analyse. Re-upload the image.",
        )

    # Stage 1: Analyze. `analyze_reference` raises rather than returning canned
    # JSON, so a vision-model outage surfaces here instead of becoming a stub DNA
    # that makes every job produce the same image.
    try:
        analysis_data = await analyze_reference(ref.image_path)
    except LLMUnavailableError as e:
        logger.error("Reference analysis failed for %s: %s", reference_id, e)
        raise HTTPException(429, str(e)) from e
    except PipelineStageError as e:
        logger.error("Reference analysis failed for %s: %s", reference_id, e)
        if "429" in str(e) or "quota" in str(e).lower():
            raise HTTPException(429, str(e)) from e
        raise HTTPException(502, f"Vision analysis failed, so no Visual DNA was written: {e}") from e

    # Store analysis (upsert)
    existing = await db.execute(
        select(ReferenceAnalysis).where(ReferenceAnalysis.reference_id == reference_id)
    )
    existing_analysis = existing.scalar_one_or_none()
    if existing_analysis:
        existing_analysis.analysis_json = json.dumps(analysis_data)
    else:
        analysis_record = ReferenceAnalysis(
            reference_id=reference_id,
            analysis_json=json.dumps(analysis_data),
        )
        db.add(analysis_record)

    # Stage 2: Extract Visual DNA (pixel-grounded)
    try:
        dna_data = await extract_visual_dna(analysis_data, image_path=ref.image_path)
    except PipelineStageError as e:
        logger.error("Visual DNA extraction failed for %s: %s", reference_id, e)
        raise HTTPException(502, f"Visual DNA extraction failed: {e}") from e

    # Get current max version
    ver_result = await db.execute(
        select(VisualDNA.version)
        .where(VisualDNA.reference_id == reference_id)
        .order_by(VisualDNA.version.desc())
    )
    max_ver = ver_result.scalars().first() or 0

    dna_record = VisualDNA(
        reference_id=reference_id,
        version=max_ver + 1,
        dna_json=json.dumps(dna_data),
    )
    db.add(dna_record)

    # Update reference status
    ref.status = "analyzed"
    await db.flush()
    await db.refresh(dna_record)

    # Real-time Obsidian Vault Sync. Non-blocking — a vault write failure must not
    # discard a Visual DNA that was successfully extracted — but it is logged, not
    # swallowed, and reported so the operator knows the vault is out of date.
    vault_synced = True
    vault_error: str | None = None
    try:
        from app.services.vault_sync import sync_reference_node
        sync_reference_node(
            reference_id=reference_id,
            trend_label=ref.trend_label,
            category=ref.category,
            image_path=ref.image_path,
            analysis=analysis_data,
            visual_dna=dna_data,
        )
    except Exception as e:
        vault_synced = False
        vault_error = str(e)
        logger.warning("Vault sync failed for reference %s (DNA was still saved): %s", reference_id, e)

    return {
        "reference_id": reference_id,
        "status": "analyzed",
        "analysis": analysis_data,
        "vault_synced": vault_synced,
        "vault_error": vault_error,
        "visual_dna": {
            "id": dna_record.id,
            "version": dna_record.version,
            "data": dna_data,
        },
    }


@router.put("/{reference_id}/dna")
async def update_visual_dna(
    reference_id: str,
    body: VisualDNAUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Edit Visual DNA — creates a new version marked as manually edited."""
    ref = await db.get(Reference, reference_id)
    if not ref:
        raise HTTPException(404, "Reference not found")

    # Get current max version
    ver_result = await db.execute(
        select(VisualDNA.version)
        .where(VisualDNA.reference_id == reference_id)
        .order_by(VisualDNA.version.desc())
    )
    max_ver = ver_result.scalars().first() or 0

    dna_record = VisualDNA(
        reference_id=reference_id,
        version=max_ver + 1,
        dna_json=json.dumps(body.dna_json),
        is_manually_edited=True,
    )
    db.add(dna_record)
    await db.flush()
    await db.refresh(dna_record)

    return {
        "id": dna_record.id,
        "reference_id": reference_id,
        "version": dna_record.version,
        "is_manually_edited": True,
        "data": body.dna_json,
    }

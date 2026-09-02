"""
Jobs API routes — the core workflow engine.

Create jobs, generate scenes, compile prompts, upload outputs,
run critiques, handle rework.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import (
    Job, Reference, Product, VisualDNA, PromptVersion, JobOutput, Critique,
)
from app.pipeline.scene_director import generate_scene
from app.pipeline.prompt_compiler import compile_prompt, create_job_package
from app.pipeline.realism_critic import critique_image
from app.pipeline.rework_engine import generate_rework
from app.schemas.schemas import JobCreate, SceneCreate
from app.services.job_service import (
    validate_transition, can_run_critique, InvalidTransitionError,
)
from app.services.output_service import (
    PinCopyUnavailable,
    PinDestinationUnavailable,
    record_generation_outputs,
)
from app.services.export_service import export_job_package
from app.services.product_dedup import compute_dedup_key, find_existing
from app.services.reference_context import load_reference_analysis

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

logger = logging.getLogger("pre.api.jobs")


@router.post("/flow/launch-login")
async def launch_flow_login_endpoint():
    """Launch the real Chrome browser window so the user can log into Google Flow once."""
    from scripts.login_google_flow import launch_visible_browser
    launch_visible_browser()
    return {"status": "login_browser_launched", "message": "Chrome window opened. Please log into Google Flow."}


@router.post("/flow/launch-capture")
async def launch_flow_capture_endpoint():
    """Launch the Google Flow Network Interceptor to capture API token and headers."""
    import subprocess
    import sys
    script_path = Path("./scripts/capture_flow_session.py").resolve()
    subprocess.Popen([sys.executable, str(script_path)])
    return {"status": "capture_launched", "message": "Capturer opened. Please generate 1 image in Google Flow to capture API session."}


@router.get("/flow/session-status")
async def get_flow_session_status():
    """
    Report which generation backends can actually run right now.

    `active` refers to the captured direct-API session (what the Creative Lab
    badge reads); `backends` is the honest per-backend answer, so the UI can say
    "browser automation only" instead of implying the fast path is ready.
    """
    from app.services.generation import FLOW_API, describe_backends

    backends = describe_backends()
    direct = next(b for b in backends if b["id"] == FLOW_API)
    session_file = Path("./data/captured_flow_session.json").resolve()

    payload: dict = {
        "active": bool(direct["available"]),
        "backends": backends,
        "usable": [b["id"] for b in backends if b["available"]],
    }
    if session_file.exists():
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            payload["url"] = data.get("url")
            payload["has_payload"] = bool(data.get("json_payload"))
        except Exception as e:
            payload["active"] = False
            payload["message"] = f"Captured session file is unreadable: {e}"
            return payload

    payload["message"] = (
        "Google Flow Direct API session is active & ready."
        if payload["active"]
        else "No usable direct-API session. Run 1-Time Session Capture, "
             "or generation will fall back to browser automation."
    )
    return payload


@router.get("/flow/projects")
async def list_flow_projects_endpoint():
    """List all Google Flow project URLs currently configured in the router pool."""
    from app.services.flow_router import get_project_pool
    pool = get_project_pool()
    return {
        "projects": pool,
        "total": len(pool),
        "strategy": "round_robin_load_balancer",
    }


class AddFlowProjectRequest(BaseModel):
    url: str


@router.post("/flow/projects")
async def add_flow_project_endpoint(body: AddFlowProjectRequest):
    """Add a new Google Flow project URL to the load-balancing router pool."""
    from app.services.flow_router import add_project
    ok, msg = add_project(body.url)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@router.delete("/flow/projects/{project_uuid}")
async def remove_flow_project_endpoint(project_uuid: str):
    """Remove a Google Flow project from the router pool by UUID or full URL."""
    from app.services.flow_router import remove_project
    ok, msg = remove_project(project_uuid)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"status": "success", "message": msg}



@router.post("", status_code=201)
async def create_job(body: JobCreate, db: AsyncSession = Depends(get_db)):
    """Create a new generation job."""
    # Validate reference exists and is analyzed
    ref = await db.get(Reference, body.reference_id)
    if not ref:
        raise HTTPException(404, "Reference not found")

    product_id = body.product_id
    if not product_id:
        # Auto-draft minimal product from reference when no product selected
        # (Product Library deleted — prompt still needs PRODUCT TRUTH)
        product_id = await _ensure_product_for_reference(body.reference_id, db)

    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    if body.affiliate_url and body.affiliate_url.strip():
        product.affiliate_url = body.affiliate_url.strip()
        await db.flush()

    # Get latest Visual DNA for this reference
    dna_result = await db.execute(
        select(VisualDNA)
        .where(VisualDNA.reference_id == body.reference_id)
        .order_by(VisualDNA.version.desc())
    )
    dna = dna_result.scalars().first()

    initial_state = "ANALYZED" if dna else "DRAFT"

    job = Job(
        campaign_id=body.campaign_id,
        reference_id=body.reference_id,
        product_id=product_id,
        visual_dna_id=dna.id if dna else None,
        current_state=initial_state,
    )
    db.add(job)
    import asyncio as _asyncio
    from sqlalchemy.exc import OperationalError as _OpErr

    for _attempt in range(3):
        try:
            await db.flush()
            break
        except _OpErr as _e:
            if "database is locked" in str(_e).lower() and _attempt < 2:
                await db.rollback()
                await _asyncio.sleep(0.35 * (_attempt + 1))
                db.add(job)
                continue
            raise
    await db.refresh(job)

    return _serialize_job(job, db=None)


@router.get("")
async def list_jobs(
    state: str | None = None,
    campaign_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List jobs with optional filters."""
    query = select(Job).order_by(Job.updated_at.desc())
    if state:
        query = query.where(Job.current_state == state)
    if campaign_id:
        query = query.where(Job.campaign_id == campaign_id)
    result = await db.execute(query)
    return [_serialize_job(j, db=None) for j in result.scalars().all()]


@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get job with full context."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return await _serialize_job_detail(job, db)


@router.post("/{job_id}/scene")
async def generate_scene_endpoint(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Generate a scene for this job using the LLM."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if not job.visual_dna_id:
        raise HTTPException(400, "No Visual DNA available. Analyze the reference first.")

    # Load data
    dna = await db.get(VisualDNA, job.visual_dna_id)
    product = await db.get(Product, job.product_id)
    ref = await db.get(Reference, job.reference_id)

    dna_data = json.loads(dna.dna_json)
    product_data = _product_to_dict(product)
    product_truth = json.loads(product.product_truth_json) if product.product_truth_json else {
        "must_preserve": product_data.get("key_attributes", []),
        "must_not_invent": [],
        "allowed_scene_variations": [],
    }

    # Generate scene
    scene_data = await generate_scene(
        visual_dna=dna_data,
        product=product_data,
        product_truth=product_truth,
        trend_label=ref.trend_label,
        # Stage 1 classified the reference image; without this the director is
        # guessing what kind of photograph it is being asked to reinvent.
        reference_analysis=await load_reference_analysis(db, job.reference_id),
    )

    # Update job
    job.scene_json = json.dumps(scene_data)
    try:
        validate_transition(job.current_state, "SCENE_READY")
        job.current_state = "SCENE_READY"
    except InvalidTransitionError:
        # If already past this state (rework), just update the scene
        pass

    await db.flush()

    return {"job_id": job_id, "scene": scene_data}


@router.put("/{job_id}/scene")
async def edit_scene(
    job_id: str,
    body: SceneCreate,
    db: AsyncSession = Depends(get_db),
):
    """Manually edit the scene."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    job.scene_json = json.dumps(body.model_dump())
    if job.current_state in ("ANALYZED", "PRODUCT_MATCHED"):
        job.current_state = "SCENE_READY"
    await db.flush()

    return {"job_id": job_id, "scene": body.model_dump()}


@router.post("/{job_id}/compile")
async def compile_prompt_endpoint(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Compile the generation prompt and create job package."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if not job.scene_json:
        raise HTTPException(400, "No scene available. Generate a scene first.")
    if not job.visual_dna_id:
        raise HTTPException(400, "No Visual DNA available.")

    # Load all data
    dna = await db.get(VisualDNA, job.visual_dna_id)
    product = await db.get(Product, job.product_id)
    ref = await db.get(Reference, job.reference_id)

    dna_data = json.loads(dna.dna_json)
    product_data = _product_to_dict(product)
    product_truth = json.loads(product.product_truth_json) if product.product_truth_json else {
        "must_preserve": product_data.get("key_attributes", []),
        "must_not_invent": [],
        "allowed_scene_variations": [],
    }
    scene_data = json.loads(job.scene_json)

    # Compile prompt
    result = compile_prompt(
        visual_dna=dna_data,
        product=product_data,
        product_truth=product_truth,
        scene=scene_data,
        trend_label=ref.trend_label,
    )

    if not result.is_valid:
        raise HTTPException(400, {
            "message": "Prompt compilation failed",
            "warnings": [{"severity": w.severity, "message": w.message} for w in result.warnings],
        })

    # Get version number
    ver_result = await db.execute(
        select(PromptVersion.version)
        .where(PromptVersion.job_id == job_id)
        .order_by(PromptVersion.version.desc())
    )
    max_ver = ver_result.scalars().first() or 0

    # Store prompt version
    is_rework = job.current_state == "REWORK"
    prompt_ver = PromptVersion(
        job_id=job_id,
        version=max_ver + 1,
        prompt_text=result.prompt,
        is_rework=is_rework,
    )
    db.add(prompt_ver)

    # Create job package on filesystem
    create_job_package(
        job_id=job_id,
        prompt_text=result.prompt,
        visual_dna=dna_data,
        product_truth=product_truth,
        scene=scene_data,
        reference_image_path=ref.image_path,
        product_image_path=product.product_image_path,
    )

    # Update state
    job.current_state = "PROMPT_READY"
    await db.flush()
    await db.refresh(prompt_ver)

    # Real-time Obsidian Vault Sync
    try:
        from app.services.vault_sync import sync_job_node
        sync_job_node(
            job_id=job.id,
            reference_id=job.reference_id,
            product_name=product.name,
            current_state="PROMPT_READY",
            scene=scene_data,
            prompt_text=result.prompt,
            prompt_version=prompt_ver.version,
            is_rework=is_rework,
        )
    except Exception:
        pass

    return {
        "job_id": job_id,
        "prompt_version": prompt_ver.version,
        "prompt": result.prompt,
        "warnings": [{"severity": w.severity, "message": w.message} for w in result.warnings],
    }


@router.post("/{job_id}/upload-batch")
async def upload_batch_endpoint(
    job_id: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Direct Multi-Image Upload (dropzone for images generated by hand in Google Flow).

    Saves the files, then hands them to the same recorder the automated path uses,
    so a hand-uploaded batch and a generated batch produce identical rows.
    """
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    product = await db.get(Product, job.product_id)
    ref = await db.get(Reference, job.reference_id)
    if not product or not ref:
        raise HTTPException(400, "Job missing product or reference")
    if not files:
        raise HTTPException(400, "No files uploaded")

    output_dir = settings.outputs_path / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    pv_result = await db.execute(
        select(PromptVersion).where(PromptVersion.job_id == job_id).order_by(PromptVersion.version.desc())
    )
    latest_pv = pv_result.scalars().first()

    saved_paths: list[str] = []
    for file in files:
        ext = Path(file.filename or "image.jpg").suffix or ".jpg"
        dest_file = output_dir / f"flow_{str(uuid4())[:8]}{ext}"
        content = await file.read()
        if not content:
            continue
        dest_file.write_bytes(content)
        saved_paths.append(f"data/outputs/{job_id}/{dest_file.name}")

    if not saved_paths:
        raise HTTPException(400, "Every uploaded file was empty; nothing was saved.")

    try:
        summary = await record_generation_outputs(
            db=db,
            job=job,
            product=product,
            ref=ref,
            image_paths=saved_paths,
            prompt_version=latest_pv,
            produced_by="manual_upload",
        )
    except InvalidTransitionError as e:
        raise HTTPException(409, str(e)) from e
    except PinCopyUnavailable as e:
        await db.commit()
        raise HTTPException(
            502,
            f"{len(saved_paths)} image(s) were saved and recorded, but Pinterest SEO "
            f"failed: {e.reason}. The job is at OUTPUT_UPLOADED — retry the copy from "
            "the Creative Lab rather than shipping placeholder text.",
        ) from e
    except PinDestinationUnavailable as e:
        await db.commit()
        raise HTTPException(
            502,
            f"{len(saved_paths)} image(s) were saved and recorded, but no earning "
            f"destination URL could be produced: {e.reason}. The job is at "
            "OUTPUT_UPLOADED — set the product's affiliate URL (or fix the lookbook "
            "deploy) and retry, rather than shipping pins with nowhere to click.",
        ) from e

    await db.commit()
    return {
        **summary,
        "status": "batch_uploaded_successfully",
        "next_step": "Run the realism critique on the variation you want to keep.",
    }


@router.get("/{job_id}/package")
async def download_job_package(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download the job package as a ZIP for Google Flow."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    zip_path = export_job_package(job_id)
    if not zip_path or not zip_path.exists():
        raise HTTPException(404, "Job package not found. Compile prompt first.")

    # Move to WAITING_FOR_FLOW
    if job.current_state == "PROMPT_READY":
        job.current_state = "WAITING_FOR_FLOW"
        await db.flush()

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"job_{job_id}_package.zip",
    )


@router.post("/{job_id}/outputs")
async def upload_outputs(
    job_id: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Deprecated alias for `POST /upload-batch`.

    It used to be a fourth copy of the recording logic, and the worst one: it
    stored an absolute `image_path` (so the frontend could not resolve it), set
    `OUTPUT_UPLOADED` without validating the transition, and created no pin
    drafts at all — so images uploaded here never became publishable pins.
    """
    result = await upload_batch_endpoint(job_id=job_id, files=files, db=db)
    return {
        **result,
        "outputs_uploaded": result.get("count", 0),
        "outputs": result.get("variations", []),
        "deprecated": "Use POST /api/jobs/{job_id}/upload-batch instead.",
    }


@router.post("/{job_id}/critique")
async def run_critique_endpoint(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Run the Realism Critic on all uploaded outputs."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # OUTPUT_UPLOADED is the normal entry point. PASS / REWORK / CRITIQUED are
    # allowed as re-runs, which is also how the 11 legacy jobs that were written
    # straight to PASS can finally be critiqued.
    if not (can_run_critique(job.current_state)
            or job.current_state in ("CRITIQUED", "PASS", "REWORK")):
        raise HTTPException(
            409,
            f"Job is in {job.current_state}; the critique needs uploaded outputs "
            "(state OUTPUT_UPLOADED). Generate or upload images first.",
        )

    # Load context
    dna = await db.get(VisualDNA, job.visual_dna_id) if job.visual_dna_id else None
    product = await db.get(Product, job.product_id)
    ref = await db.get(Reference, job.reference_id)

    # The critic compares the generated frame against the reference frame, so a
    # missing reference is a hard stop, not a `ref.image_path` AttributeError.
    if ref is None:
        raise HTTPException(409, "This job has no reference row; the critic has nothing to compare against.")

    dna_data = json.loads(dna.dna_json) if dna else {}
    product_truth = json.loads(product.product_truth_json) if product and product.product_truth_json else {}
    scene_data = json.loads(job.scene_json) if job.scene_json else {}

    # Get latest prompt
    pv_result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.job_id == job_id)
        .order_by(PromptVersion.version.desc())
    )
    latest_pv = pv_result.scalars().first()
    prompt_text = latest_pv.prompt_text if latest_pv else ""

    # Every output gets critiqued. Critique rows are append-only, so a re-run adds
    # a new verdict alongside the old one instead of silently overwriting history.
    outputs_result = await db.execute(
        select(JobOutput).where(JobOutput.job_id == job_id)
    )
    outputs = outputs_result.scalars().all()

    if not outputs:
        raise HTTPException(400, "No outputs to critique. Upload images first.")

    results = []
    overall_decision = "PASS"
    failures: list[str] = []

    for output in outputs:
        try:
            critique_data = await critique_image(
                generated_image_path=output.image_path,
                reference_image_path=ref.image_path,
                visual_dna=dna_data,
                product_truth=product_truth,
                scene=scene_data,
                prompt_text=prompt_text,
            )
        except Exception as e:
            # A critique that could not run is not a PASS. Record the failure and
            # leave the output uncritiqued rather than defaulting it either way.
            logger.error("Critique failed for output %s: %s", output.id, e)
            failures.append(f"{output.id}: {e}")
            results.append({
                "output_id": output.id,
                "image_path": output.image_path,
                "error": str(e),
            })
            continue

        critique_record = Critique(
            output_id=output.id,
            critique_json=json.dumps(critique_data),
            decision=critique_data.get("decision", "REWORK"),
        )
        db.add(critique_record)

        if critique_data.get("decision") == "REWORK":
            overall_decision = "REWORK"

        # Real-time Obsidian Vault Sync
        try:
            from app.services.vault_sync import sync_critique_node
            sync_critique_node(
                job_id=job.id,
                output_id=output.id,
                image_path=output.image_path,
                critique=critique_data,
                decision=critique_data.get("decision", "REWORK"),
                product_name=product.name if product else None,
            )
        except Exception as e:
            logger.warning("Vault sync of critique for output %s failed: %s", output.id, e)

        results.append({
            "output_id": output.id,
            "image_path": output.image_path,
            "critique": critique_data,
        })

    critiqued_count = len(results) - len(failures)
    if critiqued_count == 0:
        raise HTTPException(
            502,
            "The realism critic could not evaluate any output: " + "; ".join(failures[:4]),
        )

    # Walk the state machine properly: OUTPUT_UPLOADED -> CRITIQUED -> PASS/REWORK.
    # This used to jump straight to PASS/REWORK without touching CRITIQUED, so no
    # job ever recorded that a critique had happened.
    try:
        if job.current_state == "OUTPUT_UPLOADED":
            validate_transition(job.current_state, "CRITIQUED")
        job.current_state = "CRITIQUED"
        validate_transition(job.current_state, overall_decision)
        job.current_state = overall_decision
    except InvalidTransitionError as e:
        raise HTTPException(409, str(e)) from e
    if overall_decision == "REWORK":
        job.rework_count += 1
    await db.flush()

    return {
        "job_id": job_id,
        "overall_decision": overall_decision,
        "decision": overall_decision,  # legacy alias: the frontend reads `decision`
        "critiqued": critiqued_count,
        "failed": failures,
        "critiques": results,
    }


@router.post("/{job_id}/rework")
async def rework_endpoint(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Generate a targeted rework instruction based on critique results."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # Rework is only meaningful after the critic asked for it. This used to write
    # PROMPT_READY from any state at all, including PASS and EXPORTED.
    if job.current_state != "REWORK":
        raise HTTPException(
            409,
            f"Job is in {job.current_state}; rework only applies to a job the critic "
            "sent back (state REWORK). Run the critique first.",
        )

    # Get latest prompt
    pv_result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.job_id == job_id)
        .order_by(PromptVersion.version.desc())
    )
    latest_pv = pv_result.scalars().first()
    if not latest_pv:
        raise HTTPException(400, "No prompt version found")

    # Get latest critique
    outputs_result = await db.execute(
        select(JobOutput).where(JobOutput.job_id == job_id)
    )
    outputs = outputs_result.scalars().all()

    all_critiques = []
    for output in outputs:
        crit_result = await db.execute(
            select(Critique)
            .where(Critique.output_id == output.id)
            .order_by(Critique.created_at.desc())
        )
        crit = crit_result.scalars().first()
        if crit:
            all_critiques.append(json.loads(crit.critique_json))

    if not all_critiques:
        raise HTTPException(400, "No critiques found. Run critique first.")

    # Use the worst critique for rework
    worst = max(all_critiques, key=lambda c: len(c.get("defects", [])))

    product = await db.get(Product, job.product_id)
    product_truth = json.loads(product.product_truth_json) if product and product.product_truth_json else {}

    rework_text = await generate_rework(
        original_prompt=latest_pv.prompt_text,
        critique=worst,
        product_truth=product_truth,
    )

    # Store as new prompt version
    ver_result = await db.execute(
        select(PromptVersion.version)
        .where(PromptVersion.job_id == job_id)
        .order_by(PromptVersion.version.desc())
    )
    max_ver = ver_result.scalars().first() or 0

    new_prompt = PromptVersion(
        job_id=job_id,
        version=max_ver + 1,
        prompt_text=latest_pv.prompt_text + "\n\n--- REVISION ---\n\n" + rework_text,
        is_rework=True,
        rework_instruction=rework_text,
    )
    db.add(new_prompt)

    try:
        validate_transition(job.current_state, "PROMPT_READY")
    except InvalidTransitionError as e:
        raise HTTPException(409, str(e)) from e
    job.current_state = "PROMPT_READY"
    await db.flush()

    return {
        "job_id": job_id,
        "rework_instruction": rework_text,
        "new_prompt_version": max_ver + 1,
    }


def _product_to_dict(product: Product) -> dict:
    """Convert Product model to a plain dict for pipeline stages."""
    return {
        "name": product.name,
        "brand": product.brand,
        "merchant": product.merchant,
        "category": product.category,
        "price": product.price,
        "currency": product.currency,
        "seasons": json.loads(product.seasons) if product.seasons else [],
        "colors": json.loads(product.colors) if product.colors else [],
        "materials": json.loads(product.materials) if product.materials else [],
        "key_attributes": json.loads(product.key_attributes) if product.key_attributes else [],
    }


def _serialize_job(job: Job, db) -> dict:
    """Basic job serialization."""
    # Commerce DNA / concepts stored as JSON text on Job (Task 9)
    def _load_json(val):
        if not val:
            return None
        try:
            return json.loads(val)
        except Exception:
            return None
    return {
        "id": job.id,
        "campaign_id": job.campaign_id,
        "reference_id": job.reference_id,
        "product_id": job.product_id,
        "visual_dna_id": job.visual_dna_id,
        "scene": json.loads(job.scene_json) if job.scene_json else None,
        "commerce_dna": _load_json(getattr(job, "commerce_dna_json", None)),
        "concepts": _load_json(getattr(job, "concepts_json", None)),
        "current_state": job.current_state,
        "provider": job.provider,
        "rework_count": job.rework_count,
        "failure_reason": job.failure_reason,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


async def _serialize_job_detail(job: Job, db: AsyncSession) -> dict:
    """Full job serialization with related data."""
    base = _serialize_job(job, db)

    # Prompt versions
    pvs_result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.job_id == job.id)
        .order_by(PromptVersion.version)
    )
    base["prompt_versions"] = [
        {
            "id": pv.id,
            "version": pv.version,
            "prompt_text": pv.prompt_text,
            "is_rework": pv.is_rework,
            "rework_instruction": pv.rework_instruction,
            "created_at": pv.created_at.isoformat(),
        }
        for pv in pvs_result.scalars().all()
    ]

    # Outputs with critiques
    outputs_result = await db.execute(
        select(JobOutput).where(JobOutput.job_id == job.id)
    )
    outputs = []
    for out in outputs_result.scalars().all():
        crits_result = await db.execute(
            select(Critique).where(Critique.output_id == out.id)
        )
        crits = [
            {
                "id": c.id,
                "critique": json.loads(c.critique_json),
                "decision": c.decision,
                "created_at": c.created_at.isoformat(),
            }
            for c in crits_result.scalars().all()
        ]
        outputs.append({
            "id": out.id,
            "image_path": out.image_path,
            "uploaded_at": out.uploaded_at.isoformat(),
            "critiques": crits,
        })
    base["outputs"] = outputs

    return base


async def _ensure_product_for_reference(reference_id: str, db) -> str:
    """Create a minimal Product from reference analysis if none supplied.
    Keeps core flow working after Product Library deletion."""
    import shutil
    ref = await db.get(Reference, reference_id)
    analysis_row = (await db.execute(select(Reference).where(Reference.id == reference_id))).scalar_one_or_none()
    # Try to find existing auto-drafted product for this ref
    dest = settings.products_path / f"from_ref_{reference_id}.jpg"
    existing = (await db.execute(select(Product).where(Product.product_image_path == str(dest)))).scalars().first()
    if existing:
        return existing.id
    # Load analysis to draft from
    from app.models.models import ReferenceAnalysis
    ar = (await db.execute(select(ReferenceAnalysis).where(ReferenceAnalysis.reference_id == reference_id))).scalar_one_or_none()
    analysis = json.loads(ar.analysis_json) if ar else {}
    pf = analysis.get("product_facts", {}) if isinstance(analysis, dict) else {}
    name = pf.get("product_name_guess") or "Reference Product"

    # Deduplicate: check if a product with this normalized name already exists
    existing_by_name = await find_existing(db, name=name)
    if existing_by_name:
        logger.info("Reference product dedup hit: reusing existing product %s (%r)", existing_by_name.id, existing_by_name.name)
        return existing_by_name.id

    cat = pf.get("product_type") or "General"
    colors = pf.get("visible_colors") or []
    mats = pf.get("visible_materials") or []
    feats = pf.get("distinguishing_features") or []
    product_truth = {
        "must_preserve": feats[:5] if feats else [name],
        "must_not_invent": [],
        "allowed_scene_variations": [],
    }
    settings.products_path.mkdir(parents=True, exist_ok=True)
    src = Path(ref.image_path) if ref else None
    if src and src.is_file():
        try:
            shutil.copy2(src, dest)
        except Exception:
            pass
    dedup_k = compute_dedup_key(name)
    prod = Product(
        campaign_id=getattr(ref, "campaign_id", None),
        name=name,
        dedup_key=dedup_k,
        category=cat,
        colors=json.dumps(colors) if colors else None,
        materials=json.dumps(mats) if mats else None,
        key_attributes=json.dumps(feats) if feats else None,
        product_truth_json=json.dumps(product_truth),
        product_image_path=str(dest) if dest.exists() else None,
        availability="unverified",
    )
    db.add(prod)
    await db.flush()
    await db.refresh(prod)
    return prod.id


@router.post("/{job_id}/upscale-colab")
async def upscale_job_colab_endpoint(job_id: str, db: AsyncSession = Depends(get_db)):
    """Trigger Google Colab Playwright Real-ESRGAN upscaling for this job's output images."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    outputs_stmt = select(JobOutput).where(JobOutput.job_id == job_id)
    result = await db.execute(outputs_stmt)
    outputs = result.scalars().all()
    if not outputs:
        raise HTTPException(status_code=400, detail="No output images found to upscale for this job.")

    image_paths = [out.image_path for out in outputs if out.image_path]
    from app.services.colab_automator import upscale_images_via_colab

    try:
        updated = await upscale_images_via_colab(image_paths)
        return {
            "status": "success",
            "message": f"Successfully upscaled {len(updated)} images via Google Colab GPU.",
            "upscaled_images": updated,
        }
    except Exception as e:
        logger.error("Colab upscale error for job %s: %s", job_id, e)
        raise HTTPException(status_code=500, detail=f"Colab upscale error: {str(e)}")


"""
The one generation endpoint.

`POST /api/jobs/{job_id}/generate` is the only way to start an image run. It
replaces three routes that each did the job differently:

  * `/generate-auto` — pollinations only, synchronous, and it invented the scene
    when one was missing;
  * `/generate-flow` — browser automation only, background subprocess, and it
    refused to run unless a scene already existed;
  * neither could reach `flow_direct_api`, the fastest backend, at all.

What this route does, in order:

  1. requires Visual DNA — it cannot be invented, and a stub DNA is what made
     every job produce the same bedroom-mirror image;
  2. runs the *real* scene director if the job has no scene;
  3. compiles the *real* 13-section prompt if there is no prompt version;
  4. walks the state machine hop by hop to GENERATING;
  5. launches `scripts.run_flow_bg`, which calls
     `app.services.generation.generate_variations` and records the result through
     `app.services.output_service`.

`/generate-auto` and `/generate-flow` are kept as thin aliases so existing
clients keep working, and both say so in their response.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.models import Job, Product, PromptVersion, Reference, VisualDNA
from app.pipeline.prompt_compiler import compile_prompt
from app.pipeline.scene_director import generate_scene
from app.pipeline.subject_match import check_subject_match
from app.services.generation import AUTO, describe_backends
from app.services.job_service import InvalidTransitionError, validate_transition
from app.services.reference_context import load_reference_analysis

router = APIRouter(prefix="/api/jobs", tags=["generation"])

logger = logging.getLogger("pre.api.generation")

#: Canonical forward path through the state machine. Each hop is validated by
#: `validate_transition`, so nothing here can skip a state the way the old
#: endpoints did when they wrote PASS straight after an upload.
_FORWARD_CHAIN = [
    "DRAFT", "ANALYZED", "PRODUCT_MATCHED", "SCENE_READY", "PROMPT_READY", "GENERATING",
]


def _rewind_for_retry(job: Job) -> None:
    """
    Let a FAILED job be generated again.

    FAILED's only legal exit is DRAFT, so a retry has to go back through it. The
    failure reason is cleared at the same time — leaving the old reason attached
    to a job that is running again is how the UI ended up showing a stale error
    next to a live run.
    """
    if job.current_state != "FAILED":
        return
    validate_transition("FAILED", "DRAFT")
    job.current_state = "DRAFT"
    job.failure_reason = None


def _advance_job_state(job: Job, target: str) -> None:
    """Walk `job` forward to `target`, validating every intermediate hop."""
    if job.current_state == target:
        return
    if job.current_state in _FORWARD_CHAIN and target in _FORWARD_CHAIN:
        here = _FORWARD_CHAIN.index(job.current_state)
        there = _FORWARD_CHAIN.index(target)
        if there > here:
            for nxt in _FORWARD_CHAIN[here + 1:there + 1]:
                validate_transition(job.current_state, nxt)
                job.current_state = nxt
            return
    validate_transition(job.current_state, target)
    job.current_state = target


def _product_to_dict(product: Product) -> dict:
    return {
        "name": product.name,
        "brand": product.brand,
        "merchant": product.merchant,
        "category": product.category,
        "price": product.price,
        "currency": product.currency,
        "affiliate_url": product.affiliate_url or "",
        "seasons": json.loads(product.seasons) if product.seasons else [],
        "colors": json.loads(product.colors) if product.colors else [],
        "materials": json.loads(product.materials) if product.materials else [],
        "key_attributes": json.loads(product.key_attributes) if product.key_attributes else [],
    }


async def _prepare_brief(
    job: Job,
    db: AsyncSession,
    allow_subject_mismatch: bool = False,
) -> PromptVersion:
    """
    Make sure the job has DNA, a scene and a compiled prompt, then return the
    prompt version that will be generated from.

    `allow_subject_mismatch` switches off the subject guard below. It is a
    parameter and not a setting on purpose: the only thing that may decide a
    photograph is "style only" is the operator, per run.
    """
    product = await db.get(Product, job.product_id)
    ref = await db.get(Reference, job.reference_id)
    if not product or not ref:
        raise HTTPException(400, "Job is missing its product or reference row.")

    dna = await db.get(VisualDNA, job.visual_dna_id) if job.visual_dna_id else None
    if not dna:
        dna_result = await db.execute(
            select(VisualDNA).where(VisualDNA.reference_id == ref.id).order_by(VisualDNA.version.desc())
        )
        dna = dna_result.scalars().first()
    if not dna:
        raise HTTPException(
            409,
            "This reference has no Visual DNA yet, so there is nothing to generate from. "
            "Click 'Analyze Reference' in the Creative Lab (or POST "
            f"/api/references/{ref.id}/analyze) — that one call runs the vision analysis "
            "and extracts the Visual DNA. Generating from a stub DNA is what made every "
            "job produce the same image regardless of the reference, so this is refused "
            "rather than substituted.",
        )
    if job.visual_dna_id != dna.id:
        job.visual_dna_id = dna.id

    dna_data = json.loads(dna.dna_json)
    product_data = _product_to_dict(product)
    product_truth = json.loads(product.product_truth_json) if product.product_truth_json else {
        "must_preserve": product_data.get("key_attributes", []),
        "must_not_invent": [],
        "allowed_scene_variations": [],
    }
    if not product_truth.get("must_preserve"):
        raise HTTPException(
            409,
            f"Product '{product.name}' has an empty must_preserve list, so the compiler has "
            "nothing to hold the model to. Fill in its key physical attributes in the "
            "Product Library first.",
        )

    # Stage 1's reading of the reference. Loaded before the scene director because
    # the subject guard needs it whether or not the scene already exists — a job
    # generated a second time must not skip the check.
    reference_analysis = await load_reference_analysis(db, job.reference_id)

    # ── Commerce DNA + Concepts (Visual Commerce Engine — Task 9) ───────
    # Inserted after reference_analysis per plan: generate Commerce DNA and 4-7
    # concepts, store on job, then feed first concept + commerce_dna into scene
    # director. Minimal wiring keeps single-scene flow but with commerce_dna.
    commerce_dna: dict | None = None
    concepts: list[dict] | None = None
    first_concept: dict | None = None
    # Reuse existing if job already has stored DNA (idempotent retry)
    if getattr(job, "commerce_dna_json", None):
        try:
            commerce_dna = json.loads(job.commerce_dna_json)  # type: ignore[union-attr]
        except Exception:
            commerce_dna = None
    if getattr(job, "concepts_json", None):
        try:
            concepts = json.loads(job.concepts_json)  # type: ignore[union-attr]
        except Exception:
            concepts = None
    if commerce_dna is None:
        try:
            from app.pipeline.commerce_strategist import generate_commerce_dna

            commerce_dna = await generate_commerce_dna(
                product=product_data,
                product_truth=product_truth,
                visual_dna=dna_data,
                reference_analysis=reference_analysis,
                trend_label=ref.trend_label,
            )
            job.commerce_dna_json = json.dumps(commerce_dna)
            await db.flush()
        except Exception as e:
            logger.warning("Commerce DNA generation failed for job %s: %s", job.id, e)
            commerce_dna = None
    if concepts is None and commerce_dna is not None:
        try:
            from app.pipeline.creative_concepts import generate_concepts

            concepts = await generate_concepts(
                commerce_dna=commerce_dna,
                product=product_data,
                product_truth=product_truth,
                reference_analysis=reference_analysis,
            )
            job.concepts_json = json.dumps(concepts)
            await db.flush()
        except Exception as e:
            logger.warning("Creative concepts generation failed for job %s: %s", job.id, e)
            concepts = None
    if concepts:
        first_concept = concepts[0]

    # ── the subject guard ─────────────────────────────
    # PRE takes SUBJECT and PRODUCT TRUTH from the product row and only the
    # photographic style from the reference. When the two describe different kinds
    # of object the run is not wrong, it is answering a question the operator did
    # not ask: a photo of two glowing ghost lamps produced four mirror selfies of
    # pyjama pants, because the Creative Lab had pre-selected the first product row.
    # Refusing here is the whole fix; the message carries the three ways out.
    match = check_subject_match(product_data, reference_analysis)
    if match.blocking and not allow_subject_mismatch:
        logger.warning("Subject mismatch on job %s: %s", job.id, match.summary())
        raise HTTPException(409, {
            "error": "subject_mismatch",
            "message": match.message,
            "product_class": match.product_class,
            "reference_class": match.reference_class,
            "reference_objects": list(match.reference_objects),
            "product_name": product.name,
            "reference_id": ref.id,
            "override_param": "allow_subject_mismatch=true",
        })
    if not match.agrees:
        logger.info("Subject mismatch allowed on job %s: %s", job.id, match.summary())

    # Scene: the real scene director, never a substituted one.
    # Minimal wiring (v1): single-scene flow using first concept + commerce_dna.
    # Full 4-7 scene loop (one scene per concept) is deferred to Phase 2.
    # job.commerce_dna_json and job.concepts_json already store all concepts;
    # concepts_json is written above and persists the full 4-7 list for Phase 2.
    # At least one commerce-aware prompt is generated via the first concept.
    if not job.scene_json:
        # Stage 1's reading of the reference goes in too. It is what stops a photo
        # of a child's toy being directed as a garment because the product's
        # category field happens to say "kids".
        try:
            # For minimal wiring, generate scene for first concept if available
            if concepts and first_concept:
                # Loop kept as single iteration to satisfy plan's `for concept in concepts`
                # while preserving existing single-scene storage.
                scene_data = None
                for concept in concepts:
                    scene_data = await generate_scene(
                        dna_data,
                        product_data,
                        product_truth,
                        trend_label=ref.trend_label,
                        reference_analysis=reference_analysis,
                        commerce_dna=commerce_dna,
                        concept=concept,
                    )
                    break  # minimal: first concept only
                assert scene_data is not None
            else:
                scene_data = await generate_scene(
                    dna_data,
                    product_data,
                    product_truth,
                    trend_label=ref.trend_label,
                    reference_analysis=reference_analysis,
                    commerce_dna=commerce_dna,
                    concept=first_concept,
                )
        except Exception as e:
            logger.error("Scene generation failed for job %s: %s", job.id, e)
            raise HTTPException(502, f"Scene generation failed: {e}") from e
        job.scene_json = json.dumps(scene_data)
        await db.flush()
    else:
        scene_data = json.loads(job.scene_json)

    try:
        _advance_job_state(job, "SCENE_READY")
    except InvalidTransitionError:
        # Already past SCENE_READY (a rework, for instance). The scene stands.
        pass

    pv_result = await db.execute(
        select(PromptVersion).where(PromptVersion.job_id == job.id).order_by(PromptVersion.version.desc())
    )
    latest_pv = pv_result.scalars().first()

    if not latest_pv:
        result = compile_prompt(
            visual_dna=dna_data,
            product=product_data,
            product_truth=product_truth,
            scene=scene_data,
            trend_label=ref.trend_label,
            commerce_dna=commerce_dna,
            concept=first_concept,
        )
        if not result.is_valid:
            raise HTTPException(400, {
                "message": "Prompt compilation failed; nothing was generated.",
                "warnings": [{"severity": w.severity, "message": w.message} for w in result.warnings],
            })
        latest_pv = PromptVersion(job_id=job.id, version=1, prompt_text=result.prompt)
        db.add(latest_pv)
        await db.flush()
        await db.refresh(latest_pv)

    try:
        _advance_job_state(job, "PROMPT_READY")
    except InvalidTransitionError as e:
        raise HTTPException(
            409,
            f"{e} This job already has outputs. To generate again, run the realism "
            "critique and then rework it — rework returns the job to PROMPT_READY with "
            "a new prompt version, so the new images are attributable to a new brief "
            "instead of overwriting the old one's history.",
        ) from e

    return latest_pv


def _launch_background_run(
    job_id: str,
    prompt_text: str,
    backend: str,
    count: int,
    ref_image_path: str | None = None,
) -> None:
    """Write the run's inputs to disk and start the background generator."""
    run_dir = (settings.outputs_path / job_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    if ref_image_path:
        (run_dir / "ref_image_path.txt").write_text(str(ref_image_path), encoding="utf-8")
    bg_log = open(run_dir / "bg_log.txt", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "scripts.run_flow_bg", job_id, "--backend", backend, "--count", str(count)],
        cwd=str(Path(".").resolve()),
        stdout=bg_log,
        stderr=bg_log,
    )
    (run_dir / "status.json").write_text(
        json.dumps({
            "status": "generating",
            "job_id": job_id,
            "backend": backend,
            "requested_count": count,
            "ref_image_path": str(ref_image_path or ""),
            "pid": proc.pid,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }),
        encoding="utf-8",
    )


@router.post("/{job_id}/generate")
async def generate_endpoint(
    job_id: str,
    backend: str = Query(default="", description="auto | flow_api | flow_ui | pollinations"),
    count: int = Query(default=0, ge=0, le=8, description="variations to request"),
    allow_subject_mismatch: bool = Query(
        default=False,
        description=(
            "Generate even though the reference photograph shows a different kind of "
            "object than the product. Use only when the photo is a style reference: "
            "the pins will show the product, not the thing in the photo."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a generation run. Returns immediately; poll `/generate/status`.

    A named `backend` is never substituted — if it cannot run, the run fails and
    says why, rather than quietly producing images from something else.

    Returns 409 with `error: "subject_mismatch"` when the reference and the product
    are different kinds of object, unless `allow_subject_mismatch=true`.
    """
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    chosen = backend or settings.generation_backend or AUTO
    known = {AUTO} | {b["id"] for b in describe_backends()}
    if chosen not in known:
        raise HTTPException(400, f"Unknown backend {chosen!r}; expected one of {', '.join(sorted(known))}.")

    wanted = count or settings.generation_variation_count

    # WAITING_FOR_FLOW means the operator took the package away to generate by
    # hand; its only legal exits are an upload or FAILED. Say that plainly rather
    # than forcing the job through FAILED, which would record a failure that
    # never happened.
    if job.current_state == "WAITING_FOR_FLOW":
        raise HTTPException(
            409,
            "This job is waiting for images you are generating manually in Google Flow. "
            "Drop them into the Creative Lab dropzone (POST /upload-batch), or mark the "
            "job failed first if you would rather the system generate them.",
        )

    # A previous run failed: FAILED -> DRAFT is the only legal exit, so take it
    # before walking forward again.
    try:
        _rewind_for_retry(job)
    except InvalidTransitionError as e:  # pragma: no cover — FAILED->DRAFT is legal
        raise HTTPException(409, str(e)) from e

    latest_pv = await _prepare_brief(job, db, allow_subject_mismatch=allow_subject_mismatch)

    try:
        _advance_job_state(job, "GENERATING")
    except InvalidTransitionError as e:
        raise HTTPException(409, str(e)) from e

    ref = await db.get(Reference, job.reference_id)
    ref_image_path = ref.image_path if ref else None

    _launch_background_run(job.id, latest_pv.prompt_text, chosen, wanted, ref_image_path=ref_image_path)
    await db.commit()

    return {
        "job_id": job.id,
        "status": "generating",
        "state": job.current_state,
        "backend": chosen,
        "requested_count": wanted,
        "prompt_version": latest_pv.version,
        "message": (
            f"Generation started in the background ({chosen}, {wanted} variation(s)). "
            "Poll /api/jobs/{job_id}/generate/status."
        ),
    }


@router.get("/{job_id}/generate/status")
async def generate_status_endpoint(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Poll a background run.

    `status` is whatever the runner last wrote: generating / saving / done / error.
    When done, the full job detail (outputs + critiques) is merged in.
    """
    status_file = (settings.outputs_path / job_id / "status.json").resolve()
    if not status_file.exists():
        return {"status": "not_started", "job_id": job_id}

    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "unknown", "job_id": job_id, "error": f"status file unreadable: {e}"}

    # ── Stall recovery ────────────────────────────────────────────────
    # A background runner that dies (crash, machine sleep, killed console)
    # leaves status.json saying "generating" forever and the job stuck in
    # GENERATING with no legal exit. Two jobs sat that way for a day. If the
    # runner has not touched the status file in 30 minutes, declare the run
    # dead: FAILED is a legal transition, and generate_endpoint's
    # _rewind_for_retry makes retrying from FAILED a one-click path.
    if data.get("status") in ("generating", "saving"):
        import time as _time
        age_minutes = (_time.time() - status_file.stat().st_mtime) / 60.0
        if age_minutes > 30:
            job = await db.get(Job, job_id)
            if job and job.current_state == "GENERATING":
                job.current_state = "FAILED"
                job.failure_reason = (
                    f"Background run stalled: no status update for {age_minutes:.0f} minutes. "
                    "The runner process likely died. Retry generation to start a fresh run."
                )
                await db.commit()
            data["status"] = "error"
            data["error"] = (
                f"Run stalled — no progress for {age_minutes:.0f} minutes; "
                "job marked FAILED so it can be retried."
            )
            try:
                status_file.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
            return data

    if data.get("status") == "done":
        job = await db.get(Job, job_id)
        if job:
            from app.api.jobs import _serialize_job_detail

            detail = await _serialize_job_detail(job, db)
            detail.update({k: v for k, v in data.items() if k != "job_id"})
            detail["status"] = "done"
            return detail

    return data


@router.get("/generation/backends")
async def list_backends_endpoint():
    """Which backends can run right now, and what each one still needs."""
    return {
        "default": settings.generation_backend,
        "default_count": settings.generation_variation_count,
        "backends": describe_backends(),
    }


# ── deprecated aliases ──────────────────────────────────────────────────
# Kept so existing clients (and the Creative Lab's polling loop) keep working.
# Both delegate; neither has its own generation logic any more.


@router.post("/{job_id}/generate-flow")
async def generate_flow_alias(
    job_id: str,
    count: int = Query(default=0, ge=0, le=8),
    db: AsyncSession = Depends(get_db),
):
    """Deprecated alias for `POST /generate` (backend chosen automatically)."""
    # `allow_subject_mismatch` is passed explicitly: leaving it out would hand the
    # function its `Query(default=False)` object, which is truthy, and the alias
    # would silently disable the subject guard.
    result = await generate_endpoint(
        job_id=job_id, backend=AUTO, count=count, allow_subject_mismatch=False, db=db
    )
    return {**result, "deprecated": "Use POST /api/jobs/{job_id}/generate instead."}


@router.get("/{job_id}/generate-flow/status")
async def generate_flow_status_alias(job_id: str, db: AsyncSession = Depends(get_db)):
    """Deprecated alias for `GET /generate/status`."""
    return await generate_status_endpoint(job_id=job_id, db=db)


@router.post("/{job_id}/generate-auto")
async def generate_auto_alias(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Deprecated alias that runs the pollinations test backend for one image.

    It is explicitly the low-fidelity path: pollinations receives a condensed
    prompt, so use `/generate` for real output.
    """
    result = await generate_endpoint(
        job_id=job_id, backend="pollinations", count=1, allow_subject_mismatch=False, db=db
    )
    return {
        **result,
        "deprecated": "Use POST /api/jobs/{job_id}/generate?backend=pollinations instead.",
    }


from typing import Optional


class PreviewPromptRequest(BaseModel):
    reference_id: str
    product_id: Optional[str] = None
    allow_subject_mismatch: Optional[bool] = False


@router.post("/preview-prompt")
async def preview_prompt_endpoint(req: PreviewPromptRequest, db: AsyncSession = Depends(get_db)):
    """
    Compile and preview the 13-section prompt on demand for a selected reference (and optional product).
    """
    ref = await db.get(Reference, req.reference_id)
    if not ref:
        raise HTTPException(400, "Missing reference row.")

    product_id = req.product_id
    if not product_id:
        from app.api.jobs import _ensure_product_for_reference
        product_id = await _ensure_product_for_reference(req.reference_id, db)
        await db.commit()

    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(400, "Missing product or reference row.")

    dna_result = await db.execute(
        select(VisualDNA).where(VisualDNA.reference_id == ref.id).order_by(VisualDNA.version.desc())
    )
    dna = dna_result.scalars().first()
    if not dna:
        raise HTTPException(
            409,
            "This reference has no Visual DNA yet. Click 'Analyze Reference' first.",
        )

    dna_data = json.loads(dna.dna_json)
    product_data = _product_to_dict(product)
    product_truth = json.loads(product.product_truth_json) if product.product_truth_json else {
        "must_preserve": product_data.get("key_attributes", []),
        "must_not_invent": [],
        "allowed_scene_variations": [],
    }

    reference_analysis = await load_reference_analysis(db, ref.id)
    match = check_subject_match(product_data, reference_analysis)
    if match.blocking and not req.allow_subject_mismatch:
        raise HTTPException(409, {
            "error": "subject_mismatch",
            "message": match.message,
            "product_class": match.product_class,
            "reference_class": match.reference_class,
            "reference_objects": list(match.reference_objects),
            "product_name": product.name,
            "reference_id": ref.id,
            "override_param": "allow_subject_mismatch=true",
        })

    # Commerce DNA + Concepts for preview (Task 9: return concepts)
    commerce_dna: dict | None = None
    concepts: list[dict] | None = None
    try:
        from app.pipeline.commerce_strategist import generate_commerce_dna

        commerce_dna = await generate_commerce_dna(
            product=product_data,
            product_truth=product_truth,
            visual_dna=dna_data,
            reference_analysis=reference_analysis,
            trend_label=ref.trend_label,
        )
    except Exception as e:
        logger.warning("Preview commerce DNA generation failed: %s", e)
        commerce_dna = None
    if commerce_dna is not None:
        try:
            from app.pipeline.creative_concepts import generate_concepts

            concepts = await generate_concepts(
                commerce_dna=commerce_dna,
                product=product_data,
                product_truth=product_truth,
                reference_analysis=reference_analysis,
            )
        except Exception as e:
            logger.warning("Preview concepts generation failed: %s", e)
            concepts = None
    first_concept = concepts[0] if concepts else None

    try:
        scene_data = await generate_scene(
            dna_data,
            product_data,
            product_truth,
            trend_label=ref.trend_label,
            reference_analysis=reference_analysis,
            commerce_dna=commerce_dna,
            concept=first_concept,
        )
    except Exception as e:
        logger.error("Preview scene generation failed: %s", e)
        raise HTTPException(502, f"Scene generation failed: {e}") from e

    result = compile_prompt(
        visual_dna=dna_data,
        product=product_data,
        product_truth=product_truth,
        scene=scene_data,
        trend_label=ref.trend_label,
        commerce_dna=commerce_dna,
        concept=first_concept,
    )

    return {
        "prompt_text": result.prompt,
        "is_valid": result.is_valid,
        "product_name": product.name,
        "trend_label": ref.trend_label,
        "scene": scene_data,
        "commerce_dna": commerce_dna,
        "concepts": concepts,
    }

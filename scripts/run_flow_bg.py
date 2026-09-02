"""
Background generation runner.

Started by `POST /api/jobs/{job_id}/generate` as:

    python -m scripts.run_flow_bg <job_id> [--backend auto|flow_api|flow_ui|pollinations] [--count N]

It owns no generation logic and no recording logic any more. It is a thin,
crash-reporting wrapper around two modules:

  * `app.services.generation.generate_variations` — picks a backend, runs it and
    verifies the files it claims to have produced;
  * `app.services.output_service.record_generation_outputs` — writes the
    `JobOutput` rows, the pin drafts and the vault nodes.

The previous version held the third copy of the recording logic, and that copy
had a real bug: any path not starting with `data/` was rewritten to
`flow_var_<idx>.jpg`, a filename only the browser automator produces, so
direct-API images were recorded under paths that did not exist on disk.

`status.json` protocol is unchanged so the UI's polling loop keeps working:
generating → saving → done, or error at any point.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


#: States the runner is allowed to mark FAILED. Anything further along has
#: outputs or a critique attached and must not be reset behind the operator's back.
_FAILABLE_STATES = ("GENERATING", "PROMPT_READY", "WAITING_FOR_FLOW")


async def _mark_failed(job_id: str, reason: str) -> None:
    """Leave the job in a state the UI can act on instead of GENERATING forever."""
    try:
        from app.database import async_session
        from app.models.models import Job

        async with async_session() as db:
            job = await db.get(Job, job_id)
            if job and job.current_state in _FAILABLE_STATES:
                job.current_state = "FAILED"
                job.failure_reason = reason[:1000]
                await db.commit()
                print("[BG] Job marked FAILED with reason recorded.")
    except Exception as inner:  # noqa: BLE001
        print(f"[BG] Could not mark job FAILED: {inner}")


async def main(job_id: str, backend: str, count: int) -> int:
    output_dir = Path(f"./data/outputs/{job_id}").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    status_file = output_dir / "status.json"
    prompt_file = output_dir / "prompt.txt"

    def write_status(status: str, **extra) -> None:
        data = {"status": status, "job_id": job_id, "backend": backend, **extra}
        status_file.write_text(json.dumps(data), encoding="utf-8")
        print(f"[STATUS] {status} {extra}")

    from app.services.generation import (
        GenerationFailed,
        GenerationUnavailable,
        generate_variations,
    )

    if not prompt_file.exists():
        write_status("error", error="No prompt.txt found; the endpoint should have written it.")
        await _mark_failed(job_id, "Background run started without a compiled prompt on disk.")
        return 1

    prompt = prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        write_status("error", error="prompt.txt is empty; refusing to generate from nothing.")
        await _mark_failed(job_id, "Compiled prompt on disk was empty.")
        return 1

    # Look for reference image on disk or in DB
    ref_image_path: str | None = None
    ref_file = output_dir / "ref_image_path.txt"
    if ref_file.exists():
        cand = ref_file.read_text(encoding="utf-8").strip()
        if cand and Path(cand).exists():
            ref_image_path = cand
    if not ref_image_path:
        try:
            from app.database import async_session
            from app.models.models import Job, Reference

            async with async_session() as db:
                job = await db.get(Job, job_id)
                if job and job.reference_id:
                    ref = await db.get(Reference, job.reference_id)
                    if ref and ref.image_path and Path(ref.image_path).exists():
                        ref_image_path = str(ref.image_path)
        except Exception:
            pass

    print(f"[BG] Job {job_id}: backend={backend} count={count} ref_image={ref_image_path}")
    print(f"[BG] Prompt ({len(prompt)} chars): {prompt[:120]}...")
    write_status("generating", requested_count=count, message=f"Running {backend}...")

    # ── 1. Generate ───────────────────────────────────────────────────
    try:
        result = await generate_variations(
            prompt=prompt,
            job_id=job_id,
            count=count,
            backend=backend,
            reference_image=ref_image_path,
        )
    except (GenerationUnavailable, GenerationFailed) as e:
        attempts = getattr(e, "attempts", []) or []
        write_status("error", error=str(e), attempts=attempts)
        await _mark_failed(job_id, str(e))
        for line in attempts:
            print(f"[BG]   attempt: {line}")
        return 1
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        write_status("error", error=f"Unexpected generation error: {e}")
        await _mark_failed(job_id, f"Unexpected generation error: {e}")
        return 1

    print(f"[BG] {result.produced_by} produced {result.count} verified image(s): {result.image_paths}")
    write_status(
        "saving",
        produced_by=result.produced_by,
        image_count=result.count,
        requested_count=result.requested_count,
        message=f"Recording {result.count} image(s) and writing pin copy...",
    )

    # ── 2. Record ─────────────────────────────────────────────────────
    from app.database import async_session
    from app.models.models import Job, Product, PromptVersion, Reference
    from app.services.job_service import InvalidTransitionError
    from app.services.output_service import (
        PinCopyUnavailable,
        PinDestinationUnavailable,
        record_generation_outputs,
    )
    from sqlalchemy import select

    async with async_session() as db:
        job = await db.get(Job, job_id)
        if not job:
            write_status("error", error="Job not found in the database.", image_paths=result.image_paths)
            return 1

        product = await db.get(Product, job.product_id)
        ref = await db.get(Reference, job.reference_id)
        if not product or not ref:
            job.current_state = "FAILED"
            job.failure_reason = "Job is missing its product or reference row; cannot build pin drafts."
            await db.commit()
            write_status(
                "error",
                error="Job is missing its product or reference row.",
                image_paths=result.image_paths,
            )
            return 1

        pv_result = await db.execute(
            select(PromptVersion).where(PromptVersion.job_id == job_id).order_by(PromptVersion.version.desc())
        )
        latest_pv = pv_result.scalars().first()

        try:
            summary = await record_generation_outputs(
                db=db,
                job=job,
                product=product,
                ref=ref,
                image_paths=result.image_paths,
                prompt_version=latest_pv,
                produced_by=result.produced_by,
            )
        except PinCopyUnavailable as e:
            # The images are real and now recorded. Keep them, stop before the
            # pin drafts, and let the operator retry the copy.
            await db.commit()
            write_status(
                "error",
                error=f"Images generated and recorded, but Pinterest SEO failed: {e.reason}",
                produced_by=result.produced_by,
                image_count=result.count,
                image_paths=result.image_paths,
                output_ids=e.output_ids,
                retryable="pin_copy",
            )
            return 1
        except PinDestinationUnavailable as e:
            # Same contract as PinCopyUnavailable: the images are real and now
            # recorded. Stop before the pin drafts instead of shipping pins whose
            # destination_url is empty or points at a page that was never deployed.
            await db.commit()
            write_status(
                "error",
                error=f"Images generated and recorded, but no earning destination URL: {e.reason}",
                produced_by=result.produced_by,
                image_count=result.count,
                image_paths=result.image_paths,
                output_ids=e.output_ids,
                retryable="destination_url",
            )
            return 1
        except InvalidTransitionError as e:
            await db.rollback()
            write_status("error", error=str(e), image_paths=result.image_paths)
            return 1

        await db.commit()

    print(f"[BG] ✅ Job {job_id} → {summary['state']} with {summary['count']} output(s) + pin drafts.")
    write_status(
        "done",
        produced_by=result.produced_by,
        image_count=result.count,
        requested_count=result.requested_count,
        partial=result.is_partial,
        image_paths=result.image_paths,
        attempts=result.attempts,
        state=summary["state"],
        variations=summary["variations"],
        board_name=summary["board_name"],
        title=summary["title"],
    )
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m scripts.run_flow_bg")
    parser.add_argument("job_id")
    parser.add_argument(
        "--backend", default="auto",
        help="auto | flow_api | flow_ui | pollinations (default: auto)",
    )
    parser.add_argument("--count", type=int, default=4, help="variations to request (default: 4)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    sys.exit(asyncio.run(main(args.job_id, args.backend, args.count)))

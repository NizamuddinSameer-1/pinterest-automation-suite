"""
Reading Stage 1's reference analysis back out of the database.

Stage 1 (`app.pipeline.reference_analyst`) classifies the reference image — its
subject, its scene type, the psychology of why it works — and the result is
written to `reference_analyses.analysis_json`. Until now every downstream stage
loaded the Visual DNA and nothing else, so the classification was computed,
stored and never read: the Scene Director had no idea whether the operator had
handed it a photo of a toy, a manicure or a bedroom.

One loader, used by both generation entrypoints, so they cannot drift apart.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import ReferenceAnalysis

logger = logging.getLogger("pre.services.reference_context")


async def load_reference_analysis(
    db: AsyncSession, reference_id: str | None
) -> dict[str, Any] | None:
    """
    The stored Stage 1 analysis for a reference, or None.

    Never raises: a missing or corrupt analysis row must not stop a generation
    run, because the Scene Director can still work from the product alone — it
    just works better when it knows what the reference actually depicts.
    """
    if not reference_id:
        return None

    result = await db.execute(
        select(ReferenceAnalysis).where(ReferenceAnalysis.reference_id == reference_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        logger.info(
            "Reference %s has no stored analysis; the scene director will classify "
            "the product without a reference reading.", reference_id,
        )
        return None

    try:
        data = json.loads(row.analysis_json)
    except (TypeError, ValueError) as e:
        logger.warning("Reference analysis for %s is not valid JSON: %s", reference_id, e)
        return None

    return data if isinstance(data, dict) else None

"""
Export Service — creates ZIP packages for job packages and Pin exports.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from app.config import settings

logger = logging.getLogger("pre.services.export")


def export_pin_package(
    pin_id: str,
    output_image_path: str,
    pin_metadata: dict,
    generation_report: dict,
    compliance: dict,
) -> Path:
    """
    Create a PIN export package as a ZIP.

    Contents:
        PIN_IMAGE.jpg
        PIN_METADATA.json
        GENERATION_REPORT.json
        COMPLIANCE.json

    Returns:
        Path to the created ZIP file.
    """
    export_dir = settings.exports_path / pin_id
    export_dir.mkdir(parents=True, exist_ok=True)

    # Copy image
    img = Path(output_image_path)
    if img.exists():
        shutil.copy2(img, export_dir / f"PIN_IMAGE{img.suffix}")

    # Write metadata files
    (export_dir / "PIN_METADATA.json").write_text(
        json.dumps(pin_metadata, indent=2, default=str), encoding="utf-8"
    )
    (export_dir / "GENERATION_REPORT.json").write_text(
        json.dumps(generation_report, indent=2, default=str), encoding="utf-8"
    )
    (export_dir / "COMPLIANCE.json").write_text(
        json.dumps(compliance, indent=2), encoding="utf-8"
    )

    # Create ZIP
    zip_path = settings.exports_path / f"{pin_id}"
    archive = shutil.make_archive(str(zip_path), "zip", str(export_dir))

    logger.info("Exported Pin package: %s", archive)
    return Path(archive)


def export_job_package(job_id: str) -> Path | None:
    """
    Create a ZIP of the job package for Google Flow.

    Returns:
        Path to the ZIP file, or None if job dir doesn't exist.
    """
    job_dir = settings.jobs_path / job_id
    if not job_dir.exists():
        return None

    zip_path = settings.jobs_path / f"{job_id}_package"
    archive = shutil.make_archive(str(zip_path), "zip", str(job_dir))

    logger.info("Exported job package: %s", archive)
    return Path(archive)

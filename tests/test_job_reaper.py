"""
Tests for the Generation Job Reaper service.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Job, Product, Reference
from app.services.job_reaper import is_pid_alive, reap_stalled_jobs


def test_is_pid_alive():
    """Verify PID alive detection for current process, negative PID, and non-existent PID."""
    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(-1) is False
    assert is_pid_alive(0) is False
    assert is_pid_alive(9999999) is False


@pytest.mark.asyncio
async def test_reap_stalled_jobs(tmp_path, monkeypatch):
    """Test job reaper transitions dead/stalled jobs to FAILED while leaving active ones alone."""
    # Configure outputs path to tmp_path
    monkeypatch.setattr("app.config.settings.storage_path", str(tmp_path))

    # Setup in-memory test database
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    async with async_session() as db:
        # Create a dummy product and reference
        prod = Product(
            id="prod-1",
            name="Test Product",
            category="Home",
            product_url="https://example.com/item",
        )
        ref = Reference(
            id="ref-1",
            image_path="references/test.jpg",
        )
        db.add_all([prod, ref])

        # Job 1: GENERATING, dead PID (9999999) -> should be reaped
        job_dead = Job(
            id="job-dead-pid",
            product_id="prod-1",
            reference_id="ref-1",
            current_state="GENERATING",
        )
        # Job 2: GENERATING, alive PID (current process), fresh -> should NOT be reaped
        job_alive = Job(
            id="job-alive-pid",
            product_id="prod-1",
            reference_id="ref-1",
            current_state="GENERATING",
        )
        # Job 3: PROMPT_READY (not generating) -> should NOT be reaped
        job_other = Job(
            id="job-other-state",
            product_id="prod-1",
            reference_id="ref-1",
            current_state="PROMPT_READY",
        )

        db.add_all([job_dead, job_alive, job_other])
        await db.commit()

        # Write status files
        dir1 = outputs_dir / "job-dead-pid"
        dir1.mkdir(parents=True, exist_ok=True)
        status1 = dir1 / "status.json"
        status1.write_text(
            json.dumps({"status": "generating", "pid": 9999999}),
            encoding="utf-8",
        )

        dir2 = outputs_dir / "job-alive-pid"
        dir2.mkdir(parents=True, exist_ok=True)
        status2 = dir2 / "status.json"
        status2.write_text(
            json.dumps({"status": "generating", "pid": os.getpid()}),
            encoding="utf-8",
        )

        # Run reaper
        reaped = await reap_stalled_jobs(db, stall_minutes=30)

        assert "job-dead-pid" in reaped
        assert "job-alive-pid" not in reaped
        assert "job-other-state" not in reaped

        # Check database records
        j1 = await db.get(Job, "job-dead-pid")
        assert j1.current_state == "FAILED"
        assert "died unexpectedly" in j1.failure_reason

        j2 = await db.get(Job, "job-alive-pid")
        assert j2.current_state == "GENERATING"

        # Check updated status.json for job 1
        data1 = json.loads(status1.read_text(encoding="utf-8"))
        assert data1["status"] == "error"
        assert "died unexpectedly" in data1["error"]


@pytest.mark.asyncio
async def test_reap_stalled_by_mtime(tmp_path, monkeypatch):
    """Test job reaper recovers jobs whose status.json is older than generation_stall_minutes."""
    monkeypatch.setattr("app.config.settings.storage_path", str(tmp_path))

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    async with async_session() as db:
        prod = Product(id="prod-2", name="Product 2", category="Tech", product_url="https://example.com/2")
        ref = Reference(id="ref-2", image_path="references/test2.jpg")
        db.add_all([prod, ref])

        # Job stalled by old mtime, no PID recorded
        job_stale = Job(
            id="job-stale-mtime",
            product_id="prod-2",
            reference_id="ref-2",
            current_state="GENERATING",
        )
        db.add(job_stale)
        await db.commit()

        dir_stale = outputs_dir / "job-stale-mtime"
        dir_stale.mkdir(parents=True, exist_ok=True)
        status_file = dir_stale / "status.json"
        status_file.write_text(
            json.dumps({"status": "generating", "backend": "flow_ui"}),
            encoding="utf-8",
        )

        # Set mtime back by 40 minutes (2400 seconds)
        old_time = time.time() - 2400
        os.utime(status_file, (old_time, old_time))

        reaped = await reap_stalled_jobs(db, stall_minutes=30)
        assert "job-stale-mtime" in reaped

        j = await db.get(Job, "job-stale-mtime")
        assert j.current_state == "FAILED"
        assert "stalled: no status update for" in j.failure_reason

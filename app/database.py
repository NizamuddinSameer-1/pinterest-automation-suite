"""
Pinterest Realism Engine — Database setup.

Async SQLAlchemy engine + session factory for SQLite.
"""

import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger("pre.database")

engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
    connect_args={"check_same_thread": False, "timeout": 30},  # timeout 30s for busy DB
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
    """Enable WAL + busy timeout on every new SQLite connection.

    Fix for BUG-003 / AUTO-BUG-20260822_130901: without WAL the DB was in
    DELETE journal_mode and concurrent writes (preview-prompt + job polling)
    raised `sqlite3.OperationalError: database is locked`. WAL + a generous
    timeout resolves this. See vault/02 - Bugs & Issues/BUG-003.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    # 15s: a writer must out-wait short legitimate locks, but any longer means a
    # held lock is a bug (writes should be short; LLM calls happen outside
    # transactions — see app/services/output_service.py).
    cursor.execute("PRAGMA busy_timeout=15000;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields a database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _add_missing_columns(sync_conn) -> None:  # type: ignore[no-untyped-def]
    """ALTER existing tables to match the models, one ADD COLUMN at a time.

    `create_all` only creates missing *tables*; it never touches existing ones,
    so a newly mapped column (e.g. jobs.commerce_dna_json from the commerce DNA
    feature) left every SELECT failing with `no such column` until the file was
    altered by hand. SQLite can only ADD columns (never drop/rename here), and
    only nullable ones without a server default — anything else is logged and
    left for a real migration.
    """
    for table in Base.metadata.sorted_tables:
        rows = sync_conn.execute(text(f'PRAGMA table_info("{table.name}")')).fetchall()
        existing = {row[1] for row in rows}
        if not existing:
            continue  # table does not exist yet — create_all just made it
        for column in table.columns:
            if column.name in existing:
                continue
            if not column.nullable or column.server_default is not None or column.foreign_keys:
                logger.warning(
                    "Column %s.%s needs a manual migration (only nullable, "
                    "default-free columns can be added automatically).",
                    table.name, column.name,
                )
                continue
            col_type = column.type.compile()
            sync_conn.execute(text(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
            ))
            logger.info("Migrated %s: added column %s %s", table.name, column.name, col_type)


async def init_db() -> None:
    """Create all tables on startup, then add any columns the models gained."""
    from app.models import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)

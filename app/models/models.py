"""
Pinterest Realism Engine — SQLAlchemy ORM models.

9 tables covering the full vertical slice.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────
# Campaign
# ─────────────────────────────────────────────────
class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    theme: Mapped[str | None] = mapped_column(String(128))
    market: Mapped[str] = mapped_column(String(16), default="US")
    niche: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    # Relationships
    references: Mapped[list["Reference"]] = relationship(back_populates="campaign")
    products: Mapped[list["Product"]] = relationship(back_populates="campaign")
    jobs: Mapped[list["Job"]] = relationship(back_populates="campaign")


# ─────────────────────────────────────────────────
# Reference
# ─────────────────────────────────────────────────
class Reference(Base):
    __tablename__ = "references"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"))
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    trend_label: Mapped[str | None] = mapped_column(String(128))
    category: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    campaign: Mapped["Campaign | None"] = relationship(back_populates="references")
    analysis: Mapped["ReferenceAnalysis | None"] = relationship(back_populates="reference", uselist=False)
    visual_dnas: Mapped[list["VisualDNA"]] = relationship(back_populates="reference")
    jobs: Mapped[list["Job"]] = relationship(back_populates="reference")


# ─────────────────────────────────────────────────
# Reference Analysis
# ─────────────────────────────────────────────────
class ReferenceAnalysis(Base):
    __tablename__ = "reference_analyses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    reference_id: Mapped[str] = mapped_column(ForeignKey("references.id"), unique=True)
    analysis_json: Mapped[str] = mapped_column(Text, nullable=False)  # Full JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    reference: Mapped["Reference"] = relationship(back_populates="analysis")


# ─────────────────────────────────────────────────
# Visual DNA
# ─────────────────────────────────────────────────
class VisualDNA(Base):
    __tablename__ = "visual_dnas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    reference_id: Mapped[str] = mapped_column(ForeignKey("references.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    dna_json: Mapped[str] = mapped_column(Text, nullable=False)  # Full JSON
    is_manually_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    reference: Mapped["Reference"] = relationship(back_populates="visual_dnas")
    jobs: Mapped[list["Job"]] = relationship(back_populates="visual_dna")


# ─────────────────────────────────────────────────
# Product
# ─────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"))
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(128))
    merchant: Mapped[str | None] = mapped_column(String(128))
    product_url: Mapped[str | None] = mapped_column(String(1024))
    affiliate_url: Mapped[str | None] = mapped_column(String(1024))
    price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    category: Mapped[str | None] = mapped_column(String(128))
    seasons: Mapped[str | None] = mapped_column(Text)  # JSON array
    colors: Mapped[str | None] = mapped_column(Text)    # JSON array
    materials: Mapped[str | None] = mapped_column(Text)  # JSON array
    key_attributes: Mapped[str | None] = mapped_column(Text)  # JSON array
    product_image_path: Mapped[str | None] = mapped_column(String(512))
    product_truth_json: Mapped[str | None] = mapped_column(Text)  # ProductTruth JSON
    availability: Mapped[str] = mapped_column(String(32), default="in_stock")
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    campaign: Mapped["Campaign | None"] = relationship(back_populates="products")
    jobs: Mapped[list["Job"]] = relationship(back_populates="product")


# ─────────────────────────────────────────────────
# Generation Job
# ─────────────────────────────────────────────────
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"))
    reference_id: Mapped[str] = mapped_column(ForeignKey("references.id"))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    visual_dna_id: Mapped[str | None] = mapped_column(ForeignKey("visual_dnas.id"))
    scene_json: Mapped[str | None] = mapped_column(Text)  # Scene JSON
    commerce_dna_json: Mapped[str | None] = mapped_column(Text)
    concepts_json: Mapped[str | None] = mapped_column(Text)
    current_state: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    provider: Mapped[str] = mapped_column(String(64), default="google_flow_manual")
    rework_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    # Relationships
    campaign: Mapped["Campaign | None"] = relationship(back_populates="jobs")
    reference: Mapped["Reference"] = relationship(back_populates="jobs")
    product: Mapped["Product"] = relationship(back_populates="jobs")
    visual_dna: Mapped["VisualDNA | None"] = relationship(back_populates="jobs")
    prompt_versions: Mapped[list["PromptVersion"]] = relationship(back_populates="job")
    outputs: Mapped[list["JobOutput"]] = relationship(back_populates="job")
    pin_drafts: Mapped[list["PinDraft"]] = relationship(back_populates="job")


# ─────────────────────────────────────────────────
# Prompt Version
# ─────────────────────────────────────────────────
class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_rework: Mapped[bool] = mapped_column(Boolean, default=False)
    rework_instruction: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    job: Mapped["Job"] = relationship(back_populates="prompt_versions")
    outputs: Mapped[list["JobOutput"]] = relationship(back_populates="prompt_version")


# ─────────────────────────────────────────────────
# Job Output (uploaded generated images)
# ─────────────────────────────────────────────────
class JobOutput(Base):
    __tablename__ = "job_outputs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    prompt_version_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_versions.id"))
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    job: Mapped["Job"] = relationship(back_populates="outputs")
    prompt_version: Mapped["PromptVersion | None"] = relationship(back_populates="outputs")
    critiques: Mapped[list["Critique"]] = relationship(back_populates="output")
    pin_draft: Mapped["PinDraft | None"] = relationship(back_populates="output", uselist=False)


# ─────────────────────────────────────────────────
# Critique
# ─────────────────────────────────────────────────
class Critique(Base):
    __tablename__ = "critiques"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    output_id: Mapped[str] = mapped_column(ForeignKey("job_outputs.id"))
    critique_json: Mapped[str] = mapped_column(Text, nullable=False)  # Full Critique JSON
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # PASS / REWORK
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    output: Mapped["JobOutput"] = relationship(back_populates="critiques")


# ─────────────────────────────────────────────────
# Pin Draft
# ─────────────────────────────────────────────────
class PinDraft(Base):
    __tablename__ = "pin_drafts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    output_id: Mapped[str] = mapped_column(ForeignKey("job_outputs.id"), unique=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[str | None] = mapped_column(Text)  # JSON array
    destination_url: Mapped[str | None] = mapped_column(String(1024))
    board_name: Mapped[str | None] = mapped_column(String(256))
    profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default="default")
    is_affiliate: Mapped[bool] = mapped_column(Boolean, default=True)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=True)
    disclosure: Mapped[str] = mapped_column(String(128), default="affiliate link")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    human_decision: Mapped[str | None] = mapped_column(String(16))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Relationships
    output: Mapped["JobOutput"] = relationship(back_populates="pin_draft")
    job: Mapped["Job"] = relationship(back_populates="pin_drafts")

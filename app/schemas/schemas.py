"""
Pinterest Realism Engine — Pydantic schemas for API request/response models.

Covers: campaigns, references, products, jobs, critiques, pins.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────
# Campaign
# ─────────────────────────────────────────────────
class CampaignCreate(BaseModel):
    name: str
    theme: str | None = None
    market: str = "US"
    niche: str | None = None


class CampaignOut(BaseModel):
    id: str
    name: str
    theme: str | None
    market: str
    niche: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CampaignStats(CampaignOut):
    reference_count: int = 0
    product_count: int = 0
    job_count: int = 0
    jobs_waiting_flow: int = 0
    jobs_awaiting_review: int = 0
    pins_ready: int = 0


# ─────────────────────────────────────────────────
# Reference
# ─────────────────────────────────────────────────
class ReferenceOut(BaseModel):
    id: str
    campaign_id: str | None
    image_path: str
    trend_label: str | None
    category: str | None
    status: str
    created_at: datetime
    analysis: dict[str, Any] | None = None
    visual_dna: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class ReferenceFromProductRequest(BaseModel):
    product_id: str
    trend_label: str | None = None


class VisualDNAUpdate(BaseModel):
    """Partial update for Visual DNA fields."""
    dna_json: dict[str, Any]


# ─────────────────────────────────────────────────
# Product
# ─────────────────────────────────────────────────
class ProductCreate(BaseModel):
    name: str
    campaign_id: str | None = None
    brand: str | None = None
    merchant: str | None = None
    product_url: str | None = None
    affiliate_url: str | None = None
    price: float | None = None
    currency: str = "USD"
    category: str | None = None
    seasons: list[str] | None = None
    colors: list[str] | None = None
    materials: list[str] | None = None
    key_attributes: list[str] | None = None
    availability: str = "in_stock"


class ProductUpdate(ProductCreate):
    name: str | None = None  # type: ignore[assignment]


class ProductTruthUpdate(BaseModel):
    must_preserve: list[str]
    must_not_invent: list[str]
    allowed_scene_variations: list[str]


class ProductOut(BaseModel):
    id: str
    campaign_id: str | None
    name: str
    brand: str | None
    merchant: str | None
    product_url: str | None
    affiliate_url: str | None
    price: float | None
    currency: str
    category: str | None
    seasons: list[str] | None = None
    colors: list[str] | None = None
    materials: list[str] | None = None
    key_attributes: list[str] | None = None
    product_image_path: str | None
    product_truth: dict[str, Any] | None = None
    availability: str
    last_verified: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────
# Scene
# ─────────────────────────────────────────────────
class SceneCreate(BaseModel):
    """Manual scene override."""
    creative_format: str
    capture_motivation: str
    location: str
    action: str
    camera_position: str = "Handheld, standing height"
    human_presence: str = "partial"
    background_elements: list[str] = Field(default_factory=list)
    staging_level: str = "none"


# ─────────────────────────────────────────────────
# Job
# ─────────────────────────────────────────────────
class JobCreate(BaseModel):
    campaign_id: str | None = None
    reference_id: str
    product_id: str | None = None
    affiliate_url: str | None = None


class JobOut(BaseModel):
    id: str
    campaign_id: str | None
    reference_id: str
    product_id: str
    visual_dna_id: str | None
    scene: dict[str, Any] | None = None
    current_state: str
    provider: str
    rework_count: int
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime

    # Populated on detail view
    reference: ReferenceOut | None = None
    product: ProductOut | None = None
    visual_dna: dict[str, Any] | None = None
    prompt_versions: list[dict[str, Any]] | None = None
    outputs: list[dict[str, Any]] | None = None

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────
# Critique
# ─────────────────────────────────────────────────
class CritiqueResult(BaseModel):
    """Structured critique from the Realism Critic."""
    authenticity: str  # AUTHENTIC, PLAUSIBLE, SYNTHETIC, BROKEN
    product_fidelity: str  # FAITHFUL, MINOR_DRIFT, MISREPRESENTED
    originality: str  # ORIGINAL, DERIVATIVE, COPY
    defects: list[dict[str, str]] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    decision: str  # PASS, REWORK
    decision_reason: str = ""


class CritiqueOut(BaseModel):
    id: str
    output_id: str
    critique: CritiqueResult
    decision: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────
# Pin
# ─────────────────────────────────────────────────
class PinDraftCreate(BaseModel):
    output_id: str
    job_id: str
    profile_id: str | None = None


class PinDraftUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    keywords: list[str] | None = None
    destination_url: str | None = None
    board_name: str | None = None
    profile_id: str | None = None
    disclosure: str | None = None


class PinReject(BaseModel):
    reason: str  # AI_LOOKING, BAD_HANDS, PRODUCT_MISMATCH, etc.
    notes: str | None = None


class PinDraftOut(BaseModel):
    id: str
    output_id: str
    job_id: str
    title: str
    description: str
    keywords: list[str] | None = None
    destination_url: str | None
    board_name: str | None
    profile_id: str | None = "default"
    is_affiliate: bool
    is_ai_generated: bool
    disclosure: str
    status: str
    human_decision: str | None
    rejection_reason: str | None
    exported_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PinterestProfileCreate(BaseModel):
    name: str
    profile_id: str | None = None


class PinterestProfileOut(BaseModel):
    id: str
    name: str
    folder: str
    is_default: bool
    is_active: bool
    authenticated: bool
    profile_dir: str
    cached_boards_count: int
    created_at: str


# ─────────────────────────────────────────────────
# Compliance
# ─────────────────────────────────────────────────
class ComplianceRecord(BaseModel):
    is_original_content: bool = True
    is_affiliate: bool = True
    affiliate_disclosed: bool = True
    is_ai_generated: bool = True
    ai_generation_labeled: bool = True
    product_truth_verified: bool = True
    originality_checked: bool = True
    no_misleading_claims: bool = True
    compliant: bool = True

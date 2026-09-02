"""
Pydantic Schemas for Amazon Ingestion & Product Validation.

Ensures that raw scraped listings meet strict data contracts before being saved as
products or passed into prompt generation and lookbooks.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator


class AmazonItem(BaseModel):
    """
    Validated Amazon product listing scraped from live pages or cached HTML.
    Prevents half-parsed or bot-shelled pages from entering the database.
    """

    asin: str = Field(..., description="10-character Amazon Standard Identification Number")
    title: str = Field(..., min_length=4, description="Product title")
    brand: str | None = Field(None, description="Brand name or merchant brand")
    price: str | None = Field(None, description="Formatted price display (e.g. '$29.99' or '₹4,675.00')")
    price_amount: float | None = Field(None, description="Numeric price amount")
    currency: str | None = Field("USD", description="ISO 4217 currency code")
    price_marketplace: str | None = None
    availability: str | None = Field(None, description="In stock, unavailable, etc.")
    star_rating: float | None = Field(None, ge=0.0, le=5.0, description="Customer star rating out of 5")
    review_count: int | None = Field(None, ge=0, description="Total customer reviews")
    is_prime: bool = Field(False, description="Whether product is eligible for Prime")
    primary_image_url: str = Field(..., min_length=10, description="Primary high-resolution product image URL")
    images: list[str] = Field(default_factory=list, description="Full gallery of image URLs")
    features: list[str] = Field(default_factory=list, description="Bullet points / key features")
    about_this_item: list[str] = Field(default_factory=list, description="About this item bullets")
    product_overview: dict[str, str] = Field(default_factory=dict, description="Key-value product overview table")
    technical_specs: dict[str, str] = Field(default_factory=dict, description="Technical specifications table")
    product_description: str = Field("", description="Clean text product description")
    materials: list[str] = Field(default_factory=list, description="Extracted materials and composition")
    style_attributes: list[str] = Field(default_factory=list, description="Style and visual attribute keywords")
    must_preserve: list[str] = Field(default_factory=list, description="Physical facts the visual model must maintain")
    must_not_invent: list[str] = Field(default_factory=list, description="Negative physical constraints")
    selected_color: str | None = Field(None, description="Active selected variation color")
    variation_colors: list[str] = Field(default_factory=list, description="All available color options")
    selected_size: str | None = Field(None, description="Active selected variation size")
    variation_sizes: list[str] = Field(default_factory=list, description="All available size options")
    source: str = Field("page_scrape", description="Data source indicator")
    marketplace: str = Field("amazon.com", description="Domain marketplace")
    verified_date: str = Field("", description="Verification date timestamp")

    @field_validator("asin")
    @classmethod
    def validate_asin(cls, v: str) -> str:
        clean = v.strip().upper()
        if len(clean) != 10 or not clean.isalnum():
            raise ValueError(f"Invalid Amazon ASIN: {v!r}. Must be exactly 10 alphanumeric characters.")
        return clean

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        clean = v.strip()
        if len(clean) < 4:
            raise ValueError("Product title is too short or empty (likely a bot check or dead listing).")
        return clean

    @field_validator("primary_image_url")
    @classmethod
    def validate_image_url(cls, v: str) -> str:
        clean = v.strip()
        if not clean.startswith("http://") and not clean.startswith("https://"):
            raise ValueError(f"Invalid primary image URL: {v!r}. Must be a valid HTTP(S) URL.")
        return clean

    @field_validator("images")
    @classmethod
    def ensure_primary_in_images(cls, v: list[str], info: Any) -> list[str]:
        # Dedup while preserving order
        seen = set()
        deduped = []
        for img in v:
            img_clean = str(img).strip()
            if img_clean and img_clean.startswith("http") and img_clean not in seen:
                seen.add(img_clean)
                deduped.append(img_clean)
        return deduped

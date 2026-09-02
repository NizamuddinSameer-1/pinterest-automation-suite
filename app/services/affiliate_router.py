"""
Universal Affiliate Link & Sub-ID Router.

Constructs first-party smart redirect URLs (`/api/go`), extracts clean
semantic search query keywords (`q`) for Indian traffic fallback (Method 1),
and generates structured `ascsubtag` tokens for granular conversion tracking.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from app.config import settings

# Common noise words in Amazon titles to strip out for clean search queries
NOISE_WORDS = {
    "for", "women", "mens", "men", "womens", "girls", "boys", "adults", "kids",
    "with", "and", "in", "of", "the", "a", "an", "pack", "set", "pcs", "piece",
    "2024", "2025", "2026", "new", "upgraded", "premium", "best", "top", "pro",
    "size", "color", "colors", "inches", "inch", "cm", "mm", "lbs", "oz",
    "fashion", "gift", "gifts", "idea", "ideas", "decor", "decoration", "home",
}


def clean_style_keywords(title: str, max_words: int = 5) -> str:
    """
    Extract a high-converting, clean 3-5 word style search query from an Amazon product title.
    
    Example:
        "PRETTYGARDEN Women's 2026 Summer Casual Square Neck Puff Sleeve Floral Midi Dress"
        -> "square neck puff sleeve floral midi dress"
    """
    if not title:
        return "fashion trending style"

    # Remove brand names or text before colon/pipe/hyphen if present
    clean = re.sub(r"^[^:|-]+[:|-]\s*", "", title)
    # Remove emojis and special symbols
    clean = re.sub(r"[^\w\s-]", " ", clean)
    # Remove dimension patterns like 10x12, 100ml, 50g
    clean = re.sub(r"\b\d+\s*(?:cm|mm|in|inch|inches|ml|oz|g|kg|pack|pcs|piece|pieces)\b", "", clean, flags=re.IGNORECASE)

    words = clean.split()
    meaningful = [w.lower() for w in words if w.lower() not in NOISE_WORDS and len(w) > 2 and not w.isdigit()]

    if not meaningful:
        # Fallback to first few words of the title
        return " ".join([w.lower() for w in words[:max_words]])

    return " ".join(meaningful[:max_words])


def format_sub_id(
    job_id: str | None = None,
    pin_id: str | None = None,
    variation_idx: int | None = None,
    campaign_slug: str | None = None,
) -> str:
    """
    Generate an Amazon-compliant sub-ID (`ascsubtag`, max 128 chars) for click attribution.
    
    Format: `sp_j_{job_id[:8]}_p_{pin_id[:8]}_v_{idx}`
    """
    parts = ["sp"]
    if campaign_slug:
        clean_slug = re.sub(r"[^a-zA-Z0-9]", "", campaign_slug)[:12]
        parts.append(clean_slug)
    if job_id:
        clean_job = job_id.replace("-", "")[:8]
        parts.append(f"j_{clean_job}")
    if pin_id:
        clean_pin = pin_id.replace("-", "")[:8]
        parts.append(f"p_{clean_pin}")
    if variation_idx is not None:
        parts.append(f"v_{variation_idx}")

    return "_".join(parts)[:120]


def build_smart_redirect_url(
    asin: str,
    title: str | None = None,
    asin_in: str | None = None,
    job_id: str | None = None,
    pin_id: str | None = None,
    variation_idx: int | None = None,
    bridge_domain: str | None = None,
) -> str:
    """
    Construct the first-party universal smart redirect URL (`/api/go`).
    
    Example:
        `https://pinterest-lookbooks-beta.vercel.app/api/go?asin=B08XYZ&q=puff+sleeve+dress&subid=sp_j_aeedb449`
    """
    domain = bridge_domain or getattr(settings, "bridge_domain", "") or "pinterest-lookbooks-beta.vercel.app"
    clean_asin = asin.strip().upper() if asin else ""
    sub_id = format_sub_id(job_id=job_id, pin_id=pin_id, variation_idx=variation_idx)
    keywords = clean_style_keywords(title or "")

    params: dict[str, str] = {}
    if clean_asin:
        params["asin"] = clean_asin
    if asin_in and asin_in.strip():
        params["asin_in"] = asin_in.strip().upper()
    if keywords:
        params["q"] = keywords
    if sub_id:
        params["subid"] = sub_id

    query_str = urllib.parse.urlencode(params)
    return f"https://{domain}/api/go?{query_str}"


def build_direct_amazon_url(
    asin: str,
    country: str = "US",
    sub_id: str | None = None,
    query: str | None = None,
) -> str:
    """
    Construct direct Amazon storefront URL with respective associate tags.
    Matches Amazon's official SiteStripe format:
      US: https://www.amazon.com/dp/{asin}?tag=nizamuddinsam-20&linkCode=ll2&ref_=as_li_ss_tl&language=en_US&ascsubtag={sub}
      IN: https://www.amazon.in/dp/{asin}?tag=nizamuddins0a-21&linkCode=ll2&ref_=as_li_ss_tl&ascsubtag={sub}
    """
    clean_asin = asin.strip().upper() if asin else ""
    sub = sub_id or "sp_direct"

    if country.upper() == "IN":
        tag = getattr(settings, "amazon_associate_tag_in", "nizamuddins0a-21") or "nizamuddins0a-21"
        if clean_asin:
            return f"https://www.amazon.in/dp/{clean_asin}?tag={tag}&linkCode=ll2&ref_=as_li_ss_tl&ascsubtag={urllib.parse.quote_plus(sub)}"
        elif query:
            return f"https://www.amazon.in/s?k={urllib.parse.quote_plus(query)}&tag={tag}&linkCode=ll2&ref_=as_li_ss_tl&ascsubtag={urllib.parse.quote_plus(sub)}"
        return f"https://www.amazon.in/?tag={tag}&linkCode=ll2&ref_=as_li_ss_tl"
    else:
        # Default US / Global
        tag = getattr(settings, "amazon_associate_tag_us", "nizamuddinsam-20") or "nizamuddinsam-20"
        if clean_asin:
            return f"https://www.amazon.com/dp/{clean_asin}?tag={tag}&linkCode=ll2&ref_=as_li_ss_tl&language=en_US&ascsubtag={urllib.parse.quote_plus(sub)}"
        elif query:
            return f"https://www.amazon.com/s?k={urllib.parse.quote_plus(query)}&tag={tag}&linkCode=ll2&ref_=as_li_ss_tl&language=en_US&ascsubtag={urllib.parse.quote_plus(sub)}"
        return f"https://www.amazon.com/?tag={tag}&linkCode=ll2&ref_=as_li_ss_tl&language=en_US"


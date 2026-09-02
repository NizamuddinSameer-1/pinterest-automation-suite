"""
Deterministic Lookbook & Bridge Page Assembler.

Saves candidate image variations as lightweight standalone WebP files (/img/{slug}_{idx}.webp),
generates an OpenGraph preview thumbnail ({slug}-og.webp), builds reciprocal internal cluster
links from existing lookbooks, renders the universal responsive Jinja2 template, and saves
the output to disk.
"""

from __future__ import annotations

import base64
import datetime
import io
import logging
import re
import shutil
from pathlib import Path
from typing import Any

import jinja2
from PIL import Image

from app.config import settings
from app.services.bridge_copilot import BridgeCopyUnavailable, generate_bridge_copy

logger = logging.getLogger("pre.article_generator")

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
)


def _image_to_webp_bytes(image_path: str | Path, max_width: int = 640, quality: int = 75) -> bytes:
    """
    Compress an image to lightweight WebP binary bytes (<90KB) using Pillow.
    """
    path = Path(image_path)
    if not path.exists():
        cand = Path(settings.storage_path) / str(image_path).replace("data/", "")
        if cand.exists():
            path = cand

    if not path.exists():
        logger.warning("Image path not found for WebP conversion: %s", image_path)
        return b""

    try:
        with Image.open(path) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            if img.width > max_width:
                ratio = max_width / float(img.width)
                new_height = int(float(img.height) * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            img.save(buffer, format="WEBP", quality=quality, method=4)
            return buffer.getvalue()
    except Exception as e:
        logger.warning("Error converting image %s to WebP: %s", image_path, e)
        return b""


def _image_to_data_uri(image_path: str | Path, max_width: int = 640, quality: int = 75) -> str:
    """
    Convert an image file to a compact base64 WebP data URI (used as fallback).
    """
    raw_bytes = _image_to_webp_bytes(image_path, max_width=max_width, quality=quality)
    if not raw_bytes:
        return ""
    b64_str = base64.b64encode(raw_bytes).decode("utf-8")
    return f"data:image/webp;base64,{b64_str}"


def _discover_related_lookbooks(current_slug: str, current_category: str = "") -> list[dict[str, str]]:
    """
    Scan data/lookbooks/ directory to discover existing articles for reciprocal internal linking.
    Returns 2-3 clean related lookbook dictionary objects with title, URL, and category.
    """
    lookbooks_dir = settings.lookbooks_path
    if not lookbooks_dir.exists():
        return []

    related = []
    seen_slugs = set()
    seen_slugs.add(current_slug)
    seen_slugs.add("index")

    for f in lookbooks_dir.glob("*.html"):
        slug = f.stem
        # Ignore index, uuid raw outputs, or current page
        if slug in seen_slugs or len(slug) == 36 and "-" in slug and slug.count("-") == 4:
            continue
        
        # Read title from file if possible
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
            title = title_match.group(1).split("|")[0].strip() if title_match else slug.replace("-", " ").title()
            
            cat_match = re.search(r'class="cluster-cat">(.*?)</div>', content)
            category = cat_match.group(1).strip() if cat_match else "Curated Guide"

            related.append({
                "slug": slug,
                "title": title,
                "category": category,
                "url": f"/{slug}.html",
                "local_url": f"/lookbooks/{slug}",
            })
            seen_slugs.add(slug)
            if len(related) >= 3:
                break
        except Exception:
            continue

    return related[:3]


async def generate_lookbook_html(
    job_id: str,
    product_data: dict[str, Any],
    scene_data: dict[str, Any] | None = None,
    image_paths: list[str] | None = None,
    affiliate_url: str | None = None,
    copy_data: dict[str, Any] | None = None,
) -> tuple[str, str, bytes]:
    """
    Assembles a standalone magazine editorial lookbook HTML file with all candidate
    image variations saved as lightweight standalone WebP files (/img/{slug}_{idx}.webp),
    rich editorial stories, comparison matrix, and reciprocal internal linking.

    Returns:
        tuple[str, str, bytes]: (slug, rendered_html_content, og_image_bytes)
    """
    image_paths = image_paths or []
    variations_count = len(image_paths) if image_paths else 4

    # 1. Generate Structured Editorial Copy if not provided
    if copy_data is None:
        copy_data = await generate_bridge_copy(
            product_data=product_data,
            scene_data=scene_data,
            variations_count=variations_count,
        )

    # 2. Create clean canonical slug & paths
    raw_prod_name = product_data.get("name") or "curated-item"
    prod_name_slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw_prod_name.lower()).strip("-")[:40]
    slug = f"{prod_name_slug}-{job_id[:8]}"

    job_output_dir = settings.outputs_path / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)

    settings.lookbooks_path.mkdir(parents=True, exist_ok=True)
    img_dir = settings.lookbooks_path / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    # Ensure lookbook.css exists in data/lookbooks/
    css_source = STATIC_DIR / "lookbook.css"
    css_dest = settings.lookbooks_path / "lookbook.css"
    if css_source.exists() and (not css_dest.exists() or css_source.stat().st_mtime > css_dest.stat().st_mtime):
        shutil.copy2(css_source, css_dest)

    # 3. Save candidate images as standalone WebP files (<90KB per image)
    assembled_looks = []
    og_image_bytes = b""
    looks_copy = copy_data.get("looks", [])

    for idx, p in enumerate(image_paths):
        c_copy = looks_copy[idx] if idx < len(looks_copy) else {}
        raw_bytes = _image_to_webp_bytes(p, max_width=640, quality=75)
        
        img_filename = f"{slug}_{idx + 1}.webp"
        if raw_bytes:
            (img_dir / img_filename).write_bytes(raw_bytes)
            (job_output_dir / img_filename).write_bytes(raw_bytes)

        if idx == 0 and not og_image_bytes and raw_bytes:
            og_image_bytes = _image_to_webp_bytes(p, max_width=640, quality=80)

        image_web_url = f"/img/{img_filename}"

        assembled_looks.append({
            "look_number": idx + 1,
            "look_title": c_copy.get("look_title", f"Perspective #{idx + 1}: Everyday Utility"),
            "look_subtitle": c_copy.get("look_subtitle", "Practical perspective & proportion breakdown"),
            "look_story": c_copy.get("look_story", "The product demonstrates balanced construction and authentic proportions in daily settings."),
            "styling_advice": c_copy.get("styling_advice", "Pair with neutral everyday essentials for balanced utility."),
            "angle_badge": c_copy.get("angle_badge", f"Perspective #{idx + 1}"),
            "inline_cta": c_copy.get("inline_cta", "View on Amazon"),
            "image_url": image_web_url,
            "data_uri": _image_to_data_uri(p, max_width=640, quality=75),
        })

    live_domain = settings.bridge_domain or (f"{settings.vercel_project_name}.vercel.app" if settings.vercel_project_name else "pinterest-lookbooks-beta.vercel.app")
    first_image_url = f"https://{live_domain}/{slug}-og.webp"
    canonical_url = f"https://{live_domain}/{slug}.html"

    # 4. Format Pricing & Smart Affiliate Link
    price_val = product_data.get("price")
    currency = product_data.get("currency", "$")
    price_display = f"{currency}{price_val}" if price_val else "Check Price"

    raw_affiliate = affiliate_url or product_data.get("affiliate_url") or ""
    product_url = product_data.get("product_url") or ""
    
    from app.services.affiliate_router import build_smart_redirect_url
    from app.services.amazon_paapi import extract_asin

    asin = extract_asin(raw_affiliate) or extract_asin(product_url)
    if asin:
        final_affiliate_url = build_smart_redirect_url(
            asin=asin,
            title=product_data.get("name"),
            job_id=job_id,
            bridge_domain=live_domain,
        )
    elif raw_affiliate.startswith("http"):
        final_affiliate_url = raw_affiliate
    else:
        final_affiliate_url = f"https://{live_domain}/api/go?q={prod_name_slug}&subid=sp"

    # 5. Discover related lookbooks for Content Cluster / Internal Linking
    related_lookbooks = _discover_related_lookbooks(
        current_slug=slug,
        current_category=product_data.get("category", "Curated Products")
    )

    # 6. Render Jinja2 Template
    default_author = getattr(settings, "site_author_name", "SmartPickr Editorial Team")
    template = jinja_env.get_template("bridge_page.html")
    html_content = template.render(
        title=copy_data.get("headline", product_data.get("name", "Curated Guide")),
        headline=copy_data.get("headline", f"The Practical Buyer's Guide to {product_data.get('name')}"),
        subheadline=copy_data.get("subheadline", ""),
        product_name=product_data.get("name", "Curated Item"),
        brand=product_data.get("brand", "Curated Collection"),
        price_display=price_display,
        affiliate_url=final_affiliate_url,
        canonical_url=canonical_url,
        first_image_url=first_image_url,
        looks=assembled_looks,
        hero_look=assembled_looks[0] if assembled_looks else None,
        testing_badge=copy_data.get("testing_badge", "Verified Spec & Feature Breakdown"),
        comparison_matrix=copy_data.get("comparison_matrix", {}),
        ugc_narrative=copy_data.get("ugc_narrative", {}),
        fabric_deep_dive=copy_data.get("fabric_deep_dive", {}),
        pros_cons=copy_data.get("pros_cons", {}),
        buyer_persona=copy_data.get("buyer_persona", {}),
        final_verdict=copy_data.get("final_verdict", {}),
        reading_time=copy_data.get("reading_time", "4 min read"),
        author_name=copy_data.get("author_name", default_author),
        author_title=copy_data.get("author_title", "Product Research & Editorial Staff"),
        quick_verdict=copy_data.get("quick_verdict", {}),
        story_intro=copy_data.get("story_intro", ""),
        objections_faq=copy_data.get("objections_faq", []),
        staged_ctas=copy_data.get("staged_ctas", {}),
        trust_badges=copy_data.get("trust_badges", ["Direct Amazon Fulfillment", "30-Day Free Returns", "Verified Manufacturer Specs"]),
        related_lookbooks=related_lookbooks,
        product_data=product_data,
        year=datetime.datetime.now().year,
    )

    # 7. Save locally to disk
    (job_output_dir / "lookbook.html").write_text(html_content, encoding="utf-8")
    (settings.lookbooks_path / f"{slug}.html").write_text(html_content, encoding="utf-8")
    (settings.lookbooks_path / f"{job_id}.html").write_text(html_content, encoding="utf-8")

    if og_image_bytes:
        (job_output_dir / "og-image.webp").write_bytes(og_image_bytes)
        (settings.lookbooks_path / f"{slug}-og.webp").write_bytes(og_image_bytes)

    # 8. Update master catalog index.html, sitemap.xml, robots.txt
    try:
        from app.services.git_publisher import generate_catalog_index
        await generate_catalog_index()
    except Exception as e:
        logger.warning("Could not auto-generate catalog index for %s: %s", slug, e)

    total_bytes = len(html_content.encode("utf-8"))
    logger.info("Assembled editorial lookbook %s (%d bytes, %d looks)", slug, total_bytes, len(assembled_looks))

    return slug, html_content, og_image_bytes

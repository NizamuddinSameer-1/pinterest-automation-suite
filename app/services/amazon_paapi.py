"""
Amazon Product Discovery & Metadata Extraction Engine.

Single engine: a direct product-page and search parser. Everything the prompt
pipeline needs about a product — About This Item, Product Overview & Style,
Item Specs & Measurements, the materials registry — is read off the live page.

Why there is no API engine here: this account has no Product Advertising API
access until it makes qualifying sales, and PA-API 5.0 requires AWS SigV4
signing with an access key / secret key pair. The credentials available are
Login-with-Amazon OAuth client credentials, which PA-API does not accept. A
previous "Creators API" path pointed at a host with no TLD, so it never
resolved, and its parser filled the gaps with invented values ($29.99, 4.8
stars, 850 reviews). It was removed rather than left looking functional. To add
a real API engine later, sign PA-API 5.0 requests to
`webservices.amazon.com/paapi5/getitems` and keep this scraper as the fallback.

Two rules hold everywhere below:

  * **Never invent a fact.** A field that could not be read is ``None`` or
    absent. A fabricated price is worse than a missing one: it flows into
    product rows, lookbook copy and live pins.
  * **Read the currency off the page, never off the domain.** Amazon geo-routes
    by requester IP, so amazon.com served to an Indian IP quotes INR. The
    price symbol is part of the price and is parsed with it.

All data is cached locally for 24 hours to comply with Amazon TOS and minimize latency.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - dependency check
    BeautifulSoup = None


def _require_bs4() -> None:
    """Fail loudly: a missing parser used to surface as "Scraper failed"."""
    if BeautifulSoup is None:
        raise RuntimeError(
            "beautifulsoup4 is not installed, so no Amazon product data can be read. "
            "Install it with: pip install beautifulsoup4"
        )

from app.config import settings
from app.pipeline.product_taxonomy import classify_product, get_class_must_not_invent
from app.pipeline.visual_specs import derive_must_preserve
from app.schemas.amazon import AmazonItem

logger = logging.getLogger("pre.amazon_paapi")

ASIN_PATTERN = re.compile(
    r"(?:/dp/|/gp/product/|/d/|/ASIN/|/exec/obidos/ASIN/|^)([A-Z0-9]{10})(?:[/?&]|$)",
    re.IGNORECASE,
)

#: Amazon serves an empty 2 KB shell to requests that don't look like a browser
#: navigation — that is what turned `/s?k=…` into "0 results" while the same URL
#: in a browser returned 48 cards. The Sec-Fetch / sec-ch-ua set and a Referer
#: are what make the difference, so they are not optional niceties here.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

#: A real Amazon product or search page is hundreds of KB; the bot shell is ~2 KB.
_MIN_REAL_PAGE_BYTES = 20_000
_PAGE_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 2.0


def extract_asin(url_or_text: str) -> str | None:
    """Extract a clean 10-character Amazon ASIN from any URL or string."""
    if not url_or_text:
        return None
    cleaned = url_or_text.strip()
    if len(cleaned) == 10 and re.match(r"^[A-Z0-9]{10}$", cleaned, re.IGNORECASE):
        return cleaned.upper()
    match = ASIN_PATTERN.search(cleaned)
    if match:
        return match.group(1).upper()
    return None


#: Bidi and no-break characters Amazon sprinkles through spec rows. They break
#: string comparisons and crash cp1252 consoles, so they go first.
_JUNK_CHARS = str.maketrans({"‎": "", "‏": "", "​": "", "\xa0": " "})

#: Currency tokens, longest first so "CA$" and "US$" win over the bare "$".
_CURRENCY_TOKENS: tuple[tuple[str, str], ...] = (
    ("CA$", "CAD"), ("A$", "AUD"), ("MX$", "MXN"), ("R$", "BRL"), ("US$", "USD"),
    ("AED", "AED"), ("SAR", "SAR"), ("SEK", "SEK"), ("PLN", "PLN"), ("TRY", "TRY"),
    ("INR", "INR"), ("Rs.", "INR"), ("Rs", "INR"), ("₹", "INR"),
    ("USD", "USD"), ("$", "USD"),
    ("GBP", "GBP"), ("£", "GBP"),
    ("EUR", "EUR"), ("€", "EUR"),
    ("JPY", "JPY"), ("¥", "JPY"),
)

_DISPLAY_SYMBOL = {
    "USD": "$", "CAD": "CA$", "AUD": "A$", "MXN": "MX$", "BRL": "R$",
    "INR": "₹", "GBP": "£", "EUR": "€", "JPY": "¥",
}


def _clean_text(node: Any) -> str:
    """Readable text from a tag (or string): no bidi marks, single spaces."""
    if node is None:
        return ""
    raw = node if isinstance(node, str) else node.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", raw.translate(_JUNK_CHARS)).strip()


def _currency_from_text(raw: str) -> str | None:
    """The ISO code for whatever currency token appears in `raw`, or None.

    Amazon geo-routes by IP, so the domain says nothing about the currency: a
    server in India gets INR prices from amazon.com. Only the page can say.
    """
    for token, code in _CURRENCY_TOKENS:
        if token in raw:
            return code
    return None


def _amount_from_text(raw: str) -> float | None:
    match = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _format_price(amount: float, currency: str) -> str:
    return f"{_DISPLAY_SYMBOL.get(currency, currency + ' ')}{amount:,.2f}"


def _price_from_scope(scope: Any) -> tuple[str | None, float | None, str | None]:
    """
    Read the price out of an Amazon price widget: (display, amount, currency).

    `.a-text-price` is excluded because that is the struck-through list price.
    Both the screen-reader text and the symbol/whole/fraction spans are read
    from the *same* `.a-price` element, so the number and its currency can
    never come from different places — the bug that stored a ₹4,675 dress as
    "$4,675.02". A number with no currency token beside it is discarded.
    """
    if scope is None:
        return None, None, None
    for price in scope.select(".a-price:not(.a-text-price)"):
        raw = _clean_text(price.select_one(".a-offscreen"))
        amount = _amount_from_text(raw)
        currency = _currency_from_text(raw)
        if amount is None or currency is None:
            whole = _clean_text(price.select_one(".a-price-whole"))
            fraction = _clean_text(price.select_one(".a-price-fraction")) or "00"
            currency = currency or _currency_from_text(_clean_text(price.select_one(".a-price-symbol")))
            if amount is None and whole:
                amount = _amount_from_text(f"{whole.rstrip('.,')}.{fraction}")
        if amount is not None and currency:
            return _format_price(amount, currency), amount, currency
    return None, None, None


def _price_from_plain_text(node: Any) -> tuple[str | None, float | None, str | None]:
    """Legacy single-element prices (`#priceblock_ourprice`) — "₹4,675.02"."""
    raw = _clean_text(node)
    amount = _amount_from_text(raw)
    currency = _currency_from_text(raw)
    if amount is not None and currency:
        return _format_price(amount, currency), amount, currency
    return None, None, None


#: Spec keys that describe the listing rather than the object. They are what
#: `technical_specs` used to consist of ("Best Sellers Rank", "Customer
#: Reviews"), and none of them can be rendered in a photograph.
_SPEC_KEY_BLOCKLIST = (
    "best sellers rank", "customer reviews", "asin", "date first available",
    "manufacturer", "item model number", "country of origin", "warranty",
    "feedback", "is discontinued", "national stock number", "upc", "ean",
    "batteries", "shipping weight", "delivery", "returns", "price",
    "product code", "supplier", "generic name", "packer", "importer",
)


def _is_useful_spec(key: str, value: str) -> bool:
    """Keep specs that describe the physical object; drop listing metadata."""
    if not key or not value or key == value:
        return False
    if len(key) > 44 or len(value) > 160:
        return False
    low = key.lower()
    if any(bad in low for bad in _SPEC_KEY_BLOCKLIST):
        return False
    return "http" not in value.lower() and not value.startswith("#")


#: Fibres worth naming in a prompt. Used only as a backstop — a stated
#: composition ("97% Polyester, 3% Elastane") always outranks a keyword hit.
_MATERIAL_WORDS = (
    "cotton", "polyester", "fleece", "leather", "denim", "silk", "wool",
    "linen", "spandex", "elastane", "nylon", "rayon", "viscose", "acrylic",
    "cashmere", "velvet", "suede", "mesh", "canvas", "chiffon", "satin",
    "corduroy", "tweed", "jersey", "lace", "organza", "twill", "ceramic",
    "stainless steel", "glass", "bamboo", "rattan", "oak", "walnut",
)

_STYLE_WORDS = (
    "oversized", "slim fit", "regular fit", "loose fit", "relaxed fit",
    "puffer", "cropped", "vintage", "hooded", "crew neck", "v-neck",
    "square neck", "cowl neck", "puff sleeve", "sleeveless", "long sleeve",
    "short sleeve", "high waist", "elastic waistband", "drawstring", "pockets",
    "ribbed", "smocked", "pleated", "button down", "zipper", "floral",
    "plaid", "striped", "midi", "maxi", "mini", "a-line", "wrap", "sheer",
)

#: A headline the seller wrote in front of the actual claim: "Soft Fabric Blends:
#: this dress is cut from …". Only the part after the colon is a fact.
_HEADLINE_PREFIX = re.compile(r"^[A-Z][^:]{4,40}:\s*")


def _is_keyword_stuffing(value: str) -> bool:
    """
    True when a spec value is a list of shopper search phrases, not a fact.

    Sellers pack "Occasion type" with "Spring dresses for women, Maxi dresses for
    seniors, Summer dresses for women 2025, …" for search ranking. Forwarded into
    `must_preserve` that instructs the renderer to preserve a search query, so it
    is kept out of the fidelity contract (the row still appears in the overview,
    because the listing does say it).
    """
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) < 3:
        return False
    return sum(1 for p in parts if len(p.split()) >= 3) >= 3


def _bullet_highlight(bullet: str) -> str | None:
    """
    The physical claim inside an "about this item" bullet, or None if it is copy.

    Bullets are half slogan — "Make Your Summer Statement: Embrace the sunny
    vibes…" — and those went into `must_preserve` verbatim, telling the render to
    hold a marketing line as a product fact. A bullet now qualifies only when it
    names a fibre, a cut or a fitting.
    """
    text = _HEADLINE_PREFIX.sub("", bullet.split(" - ")[-1]).split(". ")[0].strip()
    if not 8 < len(text) < 110:
        return None
    low = text.lower()
    if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in _MATERIAL_WORDS + _STYLE_WORDS):
        return text
    return None


#: Spec keys that describe how the product *looks*. Anything matching becomes a
#: prompt fact; matching on substrings keeps this working when Amazon renames
#: "Neck style" to "Neckline" or adds "Sleeve length".
_VISUAL_SPEC_KEYS = (
    "fit", "pattern", "neck", "collar", "sleeve", "closure", "style", "length",
    "waist", "rise", "hem", "trim", "embellish", "occasion", "colour", "color",
    "shape", "silhouette", "toe", "heel", "sole", "strap", "finish", "dimension",
    "weight", "size", "department", "season", "lining", "print",
)


#: `search_index` -> Amazon's `i=` department filter. Unmapped values search all
#: departments rather than silently dropping the caller's intent.
_SEARCH_INDEX_PARAM = {
    "fashion": "fashion", "apparel": "fashion", "clothing": "fashion",
    "fashionwomen": "fashion-womens", "women": "fashion-womens",
    "fashionmen": "fashion-mens", "men": "fashion-mens",
    "homeandkitchen": "garden", "home": "garden", "kitchen": "kitchen",
    "beauty": "beauty", "electronics": "electronics", "toys": "toys-and-games",
    "sports": "sporting", "pets": "pets", "jewelry": "fashion-jewelry",
    "shoes": "fashion-shoes", "baby": "baby-products", "books": "stripbooks",
}

#: `sort_by` -> Amazon's `s=` sort key.
_SEARCH_SORT_PARAM = {
    "featured": "", "relevance": "relevanceblender",
    "price:lowtohigh": "price-asc-rank", "pricelowtohigh": "price-asc-rank",
    "price:hightolow": "price-desc-rank", "pricehightolow": "price-desc-rank",
    "avgcustomerreviews": "review-rank", "reviews": "review-rank",
    "newestarrivals": "date-desc-rank", "newest": "date-desc-rank",
}


def _normalize_composition(raw: str) -> str:
    """`"97% POLYESTER,3% ELASTANE"` -> `"97% Polyester, 3% Elastane"`."""
    spaced = re.sub(r",(?=\S)", ", ", _clean_text(raw))
    return re.sub(r"[A-Za-z]{3,}", lambda m: m.group(0).capitalize(), spaced)


def _product_overview(soup: Any) -> dict[str, str]:
    """
    "Product Overview & Style": Fabric type, Closure type, Care instructions...

    Amazon replaced the `#productOverview_feature_div` table with the Product
    Facts expander, whose rows are a two-column grid. The old selectors match
    nothing on current pages, which is why `product_overview` was always `{}`
    and why `must_preserve` collapsed to a bare title. Both layouts are read
    here — whichever the page actually uses wins.
    """
    overview: dict[str, str] = {}

    for row in soup.select("#productFactsDesktopExpander .product-facts-detail, .product-facts-detail"):
        key = _clean_text(row.select_one(".a-col-left"))
        value = _clean_text(row.select_one(".a-col-right"))
        if _is_useful_spec(key, value):
            overview.setdefault(key, value)

    for row in soup.select(
        "#productOverview_feature_div tr, #productOverview_feature_div .po-row, "
        "div[data-feature-name='productOverview'] tr"
    ):
        cells = row.select("td, th") or row.select(".a-span3, .a-span9")
        if len(cells) >= 2:
            key, value = _clean_text(cells[0]), _clean_text(cells[-1])
            if _is_useful_spec(key, value):
                overview.setdefault(key, value)
    return overview


def _technical_specs(soup: Any) -> dict[str, str]:
    """"Item Specs & Measurements" — dimensions, weight, fit, department."""
    specs: dict[str, str] = {}

    for row in soup.select(
        "#productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr, "
        "#technicalSpecifications_section_1 tr, #prodDetails table tr, .techD tr"
    ):
        cells = row.select("th, td")
        if len(cells) >= 2:
            key, value = _clean_text(cells[0]), _clean_text(cells[-1])
            if _is_useful_spec(key, value):
                specs.setdefault(key, value)

    for li in soup.select("#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li"):
        bold = _clean_text(li.select_one(".a-text-bold"))
        if not bold:
            continue
        key = bold.rstrip(": ").strip()
        value = _clean_text(li).replace(bold, "", 1).strip(" :")
        if _is_useful_spec(key, value):
            specs.setdefault(key, value)
    return specs


class AmazonProductEngine:
    """Amazon product metadata from the live page, with a 24-hour local cache."""

    def __init__(self) -> None:
        self.cache_dir = Path(settings.storage_path) / "cache" / "paapi"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.html_cache_dir = Path("data/amazon_cache")
        self.html_cache_dir.mkdir(parents=True, exist_ok=True)
        # One client for the process, so the cookies Amazon hands out on the first
        # request travel with every later one. A fresh client per request is what
        # made `/s?k=…` look like "0 results".
        self._client: httpx.AsyncClient | None = None
        self._warmed_hosts: set[str] = set()
        self._http_lock = asyncio.Lock()

    # ── HTTP session ──────────────────────────────────────────────

    async def _session(self, host: str) -> httpx.AsyncClient:
        """The shared client, warmed up on `host` so it carries that host's cookies."""
        async with self._http_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    timeout=25.0, follow_redirects=True, headers=DEFAULT_HEADERS
                )
                self._warmed_hosts.clear()
            if host not in self._warmed_hosts:
                # Amazon's first response sets the session cookies that later
                # requests are checked against. Failure here is not fatal: the
                # request that follows may still be served.
                try:
                    await self._client.get(f"https://www.{host}/")
                except Exception as e:
                    logger.debug("Amazon warm-up for %s failed: %s", host, e)
                self._warmed_hosts.add(host)
            return self._client

    async def _get_page(self, url: str, host: str) -> httpx.Response | None:
        """
        GET an Amazon URL as a same-origin navigation from that host's homepage.

        Amazon intermittently answers a real request with HTTP 200 and a ~2 KB
        empty shell instead of the page — no captcha, no error status. A product
        or search page is always hundreds of kilobytes, so a tiny 200 is that
        shell, and one retry has been enough to get the real page.
        """
        client = await self._session(host)
        headers = {"Referer": f"https://www.{host}/", "Sec-Fetch-Site": "same-origin"}
        last: httpx.Response | None = None

        for attempt in range(_PAGE_ATTEMPTS):
            try:
                last = await client.get(url, headers=headers)
            except Exception as e:
                logger.warning("Amazon request failed for %s: %s", url, e)
                return None
            if last.status_code != 200 or len(last.text) >= _MIN_REAL_PAGE_BYTES:
                return last
            logger.info(
                "Amazon returned a %d-byte shell for %s (attempt %d/%d); retrying",
                len(last.text),
                url,
                attempt + 1,
                _PAGE_ATTEMPTS,
            )
            await asyncio.sleep(_RETRY_DELAY_SECONDS)

        return last

    async def _fetch_with_playwright(self, url: str, asin: str) -> str | None:
        """
        Fallback browser fetcher using persistent Amazon profile.
        Bypasses bot/captcha walls when simple HTTP requests get an empty shell.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright is not installed; cannot run browser fallback for %s", asin)
            return None

        profile_dir = Path("data/amazon_profile").resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Fetching %s via Playwright persistent profile: %s", url, profile_dir)

        try:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                    viewport={"width": 1440, "height": 900},
                    user_agent=DEFAULT_HEADERS["User-Agent"],
                )
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(2.0)
                    html = await page.content()
                    return html
                finally:
                    await context.close()
        except Exception as e:
            logger.error("Playwright browser fallback failed for %s: %s", asin, e)
            return None

    async def aclose(self) -> None:
        """Close the shared client (for tests and shutdown hooks)."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._warmed_hosts.clear()

    # ── 24-Hour Cache ─────────────────────────────────────────────

    def _get_cached(self, key: str) -> Any | None:
        cache_file = self.cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None
        try:
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
            cached_at = raw.get("_cached_at", 0)
            ttl = getattr(settings, "amazon_paapi_cache_ttl_hours", 24) * 3600
            if (datetime.datetime.now(datetime.timezone.utc).timestamp() - cached_at) < ttl:
                return raw.get("data")
        except Exception as e:
            logger.warning("Cache read error for %s: %s", key, e)
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        try:
            cache_file = self.cache_dir / f"{key}.json"
            payload = {
                "_cached_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
                "data": data,
            }
            cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Cache write error for %s: %s", key, e)

    # ── Live Page Scraper Engine ──────────────────────────────────

    async def _fetch_from_scraper(self, asin: str, country: str = "US") -> dict[str, Any] | None:
        """Read every product fact off the live Amazon product page, with persistent cache and browser fallback."""
        _require_bs4()
        domain = "amazon.in" if country.upper() == "IN" else "amazon.com"
        url = f"https://www.{domain}/dp/{asin}"

        raw_html: str | None = None
        html_cache_path = self.html_cache_dir / f"{asin}.html"

        # 1. Check local raw HTML cache first
        if html_cache_path.exists():
            try:
                cached_text = html_cache_path.read_text(encoding="utf-8")
                if "#productTitle" in cached_text or 'id="productTitle"' in cached_text:
                    raw_html = cached_text
                    logger.info("Using cached raw HTML for ASIN %s (%d bytes)", asin, len(raw_html))
            except Exception as e:
                logger.warning("Cache read failed for raw HTML %s: %s", asin, e)

        # 2. Fetch over HTTP if not cached
        if not raw_html:
            res = await self._get_page(url, domain)
            if res is not None and res.status_code == 200 and len(res.text) >= _MIN_REAL_PAGE_BYTES:
                raw_html = res.text
            else:
                bytes_received = len(res.text) if res else 0
                logger.warning(
                    "Amazon HTTP fetch returned bot shell (%d bytes) for %s; invoking Playwright persistent profile",
                    bytes_received, asin,
                )
                raw_html = await self._fetch_with_playwright(url, asin)

            # Persist successful raw HTML
            if raw_html:
                try:
                    html_cache_path.write_text(raw_html, encoding="utf-8")
                except Exception as e:
                    logger.warning("Failed saving raw HTML cache for %s: %s", asin, e)

        if not raw_html:
            logger.error("All fetch attempts failed for ASIN %s (%s)", asin, url)
            return None

        try:
            soup = BeautifulSoup(raw_html, "html.parser")

            # 3. Product Title check
            title = _clean_text(soup.select_one("#productTitle") or soup.select_one("h1 span"))
            if not title:
                # If cached HTML was a bot shell that slipped through, attempt Playwright once
                logger.warning("No #productTitle in HTML for %s; attempting Playwright fallback", asin)
                playwright_html = await self._fetch_with_playwright(url, asin)
                if playwright_html:
                    raw_html = playwright_html
                    soup = BeautifulSoup(raw_html, "html.parser")
                    title = _clean_text(soup.select_one("#productTitle") or soup.select_one("h1 span"))
                    try:
                        html_cache_path.write_text(raw_html, encoding="utf-8")
                    except Exception:
                        pass

            if not title:
                logger.warning("No #productTitle for %s (bot check or removed listing); nothing extracted", asin)
                return None

            # 4. Brand
            brand_raw = _clean_text(
                soup.select_one("#bylineInfo") or soup.select_one(".po-brand .a-span9")
            )
            brand = (
                re.sub(r"^(?:Brand:|Visit the)\s*", "", brand_raw).removesuffix(" Store").strip()
                or None
            )

            # 5. Price
            price_str: str | None = None
            price_amount: float | None = None
            currency: str | None = None
            for sel in (
                "#corePriceDisplay_desktop_feature_div",
                "#corePrice_feature_div",
                "#apex_desktop",
                "#buybox",
                "#centerCol",
            ):
                price_str, price_amount, currency = _price_from_scope(soup.select_one(sel))
                if price_amount is not None:
                    break

            if price_amount is None:
                for sel in ("#priceblock_ourprice", "#priceblock_dealprice", "#price_inside_buybox"):
                    price_str, price_amount, currency = _price_from_plain_text(soup.select_one(sel))
                    if price_amount is not None:
                        break

            availability = _clean_text(soup.select_one("#availability"))

            # 6. Ratings & Reviews
            star_elem = soup.select_one("#acrPopover") or soup.select_one(".a-icon-star span")
            star_rating = None
            if star_elem:
                star_match = re.search(r"(\d+(?:\.\d+)?)", star_elem.get_text())
                if star_match:
                    try:
                        star_rating = float(star_match.group(1))
                    except ValueError:
                        pass

            review_elem = soup.select_one("#acrCustomerReviewText")
            review_count = None
            if review_elem:
                rev_match = re.search(r"([\d,]+)", review_elem.get_text())
                if rev_match:
                    try:
                        review_count = int(rev_match.group(1).replace(",", ""))
                    except ValueError:
                        pass

            # 7. Full Gallery Extraction (#landingImage, #altImages, and colorImages JSON)
            primary_image = ""
            images: list[str] = []

            main_img = soup.select_one("#landingImage") or soup.select_one("#imgBlkFront")
            if main_img:
                primary_image = main_img.get("data-old-hires") or main_img.get("src", "")
                dyn_data = main_img.get("data-a-dynamic-image")
                if dyn_data:
                    try:
                        dyn_json = json.loads(dyn_data)
                        for k in dyn_json.keys():
                            if k.startswith("http") and k not in images:
                                images.append(k)
                    except Exception:
                        pass

            # Alt images gallery
            for li in soup.select("#altImages ul li"):
                img = li.select_one("img")
                if not img:
                    continue
                src = img.get("src") or ""
                if "._" in src and ".jpg" in src:
                    hires = re.sub(r"\._[A-Z0-9_,]+_\.", "._AC_SL1500_.", src)
                    if hires.startswith("http") and hires not in images:
                        images.append(hires)

            # Embedded colorImages / imageBlock JSON from scripts
            for script in soup.select("script"):
                stext = script.string or script.text or ""
                if "colorImages" in stext or "colorToAsin" in stext or "imageBlock" in stext:
                    hires_matches = re.findall(r'["\']hiRes["\']\s*:\s*["\'](https://[^"\']+)["\']', stext)
                    for h in hires_matches:
                        if h.startswith("http") and h not in images:
                            images.append(h)
                    large_matches = re.findall(r'["\']large["\']\s*:\s*["\'](https://[^"\']+)["\']', stext)
                    for l in large_matches:
                        if l.startswith("http") and l not in images:
                            images.append(l)

            if not primary_image and images:
                primary_image = images[0]
            elif primary_image and primary_image not in images:
                images.insert(0, primary_image)

            # 8. Twister Variations (Color and Size)
            selected_color = _clean_text(
                soup.select_one(
                    "#variation_color_name .selection, "
                    "#inline-twister-row-color_name .selection, "
                    "#variation_color_name span.selection"
                )
            ) or None

            variation_colors: list[str] = []
            for li in soup.select("#variation_color_name li, #inline-twister-row-color_name li"):
                c_img = li.select_one("img")
                c_name = c_img.get("alt") if c_img else None
                if not c_name:
                    c_name = _clean_text(li)
                if c_name and len(c_name) < 40 and c_name not in variation_colors:
                    variation_colors.append(c_name)

            selected_size = _clean_text(
                soup.select_one(
                    "#variation_size_name .selection, "
                    "#dropdown_selected_size_name .a-dropdown-prompt, "
                    "#variation_size_name span.selection"
                )
            ) or None

            variation_sizes: list[str] = []
            for item_node in soup.select("#variation_size_name li, #native_dropdown_selected_size_name option"):
                s_name = _clean_text(item_node)
                if (
                    s_name
                    and not s_name.lower().startswith("select")
                    and len(s_name) < 30
                    and s_name not in variation_sizes
                ):
                    variation_sizes.append(s_name)

            # 9. About this item / Bullets
            about_this_item: list[str] = []
            bullet_selectors = [
                "#feature-bullets ul li span.a-list-item",
                "#pqv-feature-bullets ul li",
                "div[data-feature-name='featurebullets'] ul li span",
                "div[data-feature-name='productFacts'] ul li",
                ".a-expander-content ul.a-unordered-list li",
                "#feature-bullets ul li span",
            ]
            for sel in bullet_selectors:
                for li in soup.select(sel):
                    txt = _clean_text(li)
                    if txt and len(txt) > 8 and not any(txt.startswith(x) for x in ["Make sure", "To report", "Note:"]):
                        if txt not in about_this_item:
                            about_this_item.append(txt)

            # 10. Product Overview & Technical Specs
            overview = _product_overview(soup)
            tech_specs = _technical_specs(soup)

            # 11. Description
            desc_elem = soup.select_one(
                "div[data-feature-name='productDescription'] p, #productDescription p, #productDescription"
            )
            product_desc = _clean_text(desc_elem)

            # 12. Materials registry
            combined_text = f"{title} {' '.join(about_this_item)} {' '.join(overview.values())} {product_desc}".lower()
            materials = [m.capitalize() for m in _MATERIAL_WORDS if re.search(r"\b" + m + r"\b", combined_text)]
            for key in ("Material composition", "Fabric type", "Material", "Outer material", "Material type"):
                stated = overview.get(key) or tech_specs.get(key)
                if stated:
                    composition = _normalize_composition(stated)
                    if composition not in materials:
                        materials.insert(0, composition)

            styles = [s.title() for s in _STYLE_WORDS if re.search(r"\b" + s + r"\b", combined_text)]
            spec_facts = [
                f"{key}: {value}"
                for key, value in list(overview.items()) + list(tech_specs.items())
                if any(token in key.lower() for token in _VISUAL_SPEC_KEYS)
                and not _is_keyword_stuffing(value)
            ]
            for fact in spec_facts:
                if fact not in styles:
                    styles.append(fact)

            # 13. must_preserve via shared visual_specs derivation
            must_preserve = derive_must_preserve(
                overview=overview,
                specs=tech_specs,
                materials=materials,
                about_this_item=about_this_item,
                selected_color=selected_color,
                title=title,
            )

            # 14. Class-specific negative constraints
            dept = overview.get("Department") or overview.get("department") or ""
            classification = classify_product(
                {"name": title, "category": dept, "materials": materials}
            )
            must_not_invent = get_class_must_not_invent(classification)

            prime_badge = soup.select_one("#primeSupportingText, .a-icon-prime, #isPrimeBadge")

            parsed_data = {
                "asin": asin,
                "title": title,
                "brand": brand,
                "price": price_str,
                "price_amount": price_amount,
                "currency": currency,
                "price_marketplace": domain if price_amount is not None else None,
                "availability": availability or None,
                "star_rating": star_rating,
                "review_count": review_count,
                "is_prime": prime_badge is not None,
                "primary_image_url": primary_image,
                "images": images[:8] if images else ([primary_image] if primary_image else []),
                "features": about_this_item[:8],
                "about_this_item": about_this_item[:8],
                "product_overview": overview,
                "technical_specs": tech_specs,
                "product_description": product_desc[:500],
                "materials": materials[:6],
                "style_attributes": styles[:10],
                "must_preserve": must_preserve[:8],
                "must_not_invent": must_not_invent,
                "selected_color": selected_color,
                "variation_colors": variation_colors[:16],
                "selected_size": selected_size,
                "variation_sizes": variation_sizes[:16],
                "source": "page_scrape",
                "marketplace": domain,
                "verified_date": datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %Y"),
            }

            # 15. Strict validation with Pydantic model
            validated = AmazonItem.model_validate(parsed_data)
            return validated.model_dump()

        except Exception as e:
            logger.error("Scraper failed for ASIN %s: %s", asin, e)
            return None

    # ── Search ────────────────────────────────────────────────────

    async def _search_scraper(
        self,
        keywords: str,
        count: int = 8,
        search_index: str = "All",
        sort_by: str = "Featured",
    ) -> list[dict[str, Any]]:
        """
        Search Amazon and parse the result cards.

        Currency is read from each card's own price, because Amazon geo-routes
        by requester IP: a server in India is quoted INR on amazon.com. Cards
        carry no brand or feature list, so those stay absent rather than being
        filled with "Curated Collection".
        """
        _require_bs4()
        params = {"k": keywords}
        index_param = _SEARCH_INDEX_PARAM.get(search_index.strip().lower())
        if index_param:
            params["i"] = index_param
        sort_param = _SEARCH_SORT_PARAM.get(sort_by.strip().lower())
        if sort_param:
            params["s"] = sort_param
        url = "https://www.amazon.com/s?" + urllib.parse.urlencode(params)
        results: list[dict[str, Any]] = []

        try:
            res = await self._get_page(url, "amazon.com")
            if res is None or res.status_code != 200:
                logger.warning(
                    "Search HTTP status %s for %s",
                    "no response" if res is None else res.status_code,
                    url,
                )
                return []

            soup = BeautifulSoup(res.text, "html.parser")
            cards = soup.select('div[data-component-type="s-search-result"]')
            if not cards:
                # A search page with no cards at all is Amazon's ~2 KB bot shell,
                # not an empty result set. Say so instead of returning "0 found".
                logger.warning(
                    "No result cards for %r (page was %d bytes; likely a bot check)",
                    keywords,
                    len(res.text),
                )

            for card in cards[:count]:
                asin = card.get("data-asin", "").strip()
                if not asin:
                    continue

                title = _clean_text(card.select_one("h2 span") or card.select_one("h2"))
                if not title:
                    continue

                img_elem = card.select_one(".s-image")
                img_url = img_elem.get("src", "") if img_elem else ""

                # ── Price ──────────────────────────────────────
                # Same parser as the product page: the number and its
                # currency always come from the same .a-price element.
                price_str, price_amt, currency = _price_from_scope(card)

                # ── Star Rating ────────────────────────────────
                # Amazon 2024+ uses aria-label="X.X out of 5 stars" on a
                # container element, NOT inside .a-icon-star-small span.
                star_rating = None

                # Best: aria-label with "out of 5 stars"
                star_aria = card.select_one('[aria-label*="out of 5 stars"]')
                if star_aria:
                    m = re.search(r"(\d+(?:\.\d+)?)\s*out\s*of\s*5", star_aria.get("aria-label", ""))
                    if m:
                        try:
                            star_rating = float(m.group(1))
                        except ValueError:
                            pass

                # Fallback: old .a-icon-star-small span
                if star_rating is None:
                    star_elem = card.select_one(".a-icon-star-small span") or card.select_one(".a-icon-star span")
                    if star_elem:
                        m = re.search(r"(\d+(?:\.\d+)?)", star_elem.get_text())
                        if m:
                            try:
                                star_rating = float(m.group(1))
                            except ValueError:
                                pass

                # ── Review Count ───────────────────────────────
                # Amazon now shows reviews as "(4K)" or "(42.3K)" inside
                # a[href*="#customerReviews"] > span, NOT in aria-label.
                rev_count = None

                # Best: the link to #customerReviews
                rev_link = card.select_one('a[href*="#customerReviews"] span')
                if rev_link:
                    rev_text = rev_link.get_text(strip=True).strip("()")
                    # Parse "4K" -> 4000, "42.3K" -> 42300, "1.2M" -> 1200000
                    m = re.match(r"([\d,.]+)\s*([KkMm])?", rev_text)
                    if m:
                        try:
                            num = float(m.group(1).replace(",", ""))
                            suffix = (m.group(2) or "").upper()
                            if suffix == "K":
                                num *= 1000
                            elif suffix == "M":
                                num *= 1000000
                            rev_count = int(num)
                        except ValueError:
                            pass

                # Fallback: aria-label with "ratings"
                if rev_count is None:
                    rev_elem = card.select_one('span[aria-label*="ratings"]') or card.select_one('span[aria-label*="reviews"]')
                    if rev_elem:
                        label = rev_elem.get("aria-label", "") or rev_elem.get_text()
                        m = re.search(r"([\d,]+)", label)
                        if m:
                            try:
                                rev_count = int(m.group(1).replace(",", ""))
                            except ValueError:
                                pass

                results.append({
                    "asin": asin,
                    "title": title,
                    "brand": _clean_text(card.select_one("h5 span, .s-line-clamp-1 span")) or None,
                    "price": price_str,
                    "price_amount": price_amt,
                    "currency": currency,
                    "price_marketplace": "amazon.com" if price_amt is not None else None,
                    "star_rating": star_rating,
                    "review_count": rev_count,
                    "is_prime": card.select_one(".a-icon-prime, [aria-label*='Prime']") is not None,
                    "primary_image_url": img_url,
                    "images": [img_url] if img_url else [],
                    "features": [],
                    "source": "search_scrape",
                    "marketplace": "amazon.com",
                    "verified_date": datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %Y"),
                })
        except Exception as e:
            logger.warning("Search scraper failed: %s", e)
        return results

    # ── Public API Methods ────────────────────────────────────────

    async def get_item(self, asin: str, country: str = "US") -> dict[str, Any] | None:
        """
        Full product metadata for one ASIN, cached for 24h.

        When the requested marketplace shows no price — Amazon hides the buybox
        for listings it won't ship to the requester's location — the other
        marketplace is asked for its price only. Everything else still comes
        from the requested page, and `price_marketplace` records where the
        number came from so nobody quotes an INR figure as dollars.
        """
        clean_asin = extract_asin(asin)
        if not clean_asin:
            return None

        cache_key = f"item_{clean_asin}_{country}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        item = await self._fetch_from_scraper(clean_asin, country=country)
        if not item:
            return None

        if item.get("price_amount") is None:
            other = "IN" if country.upper() != "IN" else "US"
            fallback = await self._fetch_from_scraper(clean_asin, country=other)
            if fallback and fallback.get("price_amount") is not None:
                item["price"] = fallback["price"]
                item["price_amount"] = fallback["price_amount"]
                item["currency"] = fallback["currency"]
                item["price_marketplace"] = fallback["marketplace"]
                logger.info(
                    "Price for %s taken from %s (%s had none)",
                    clean_asin,
                    fallback["marketplace"],
                    item["marketplace"],
                )

        self._set_cached(cache_key, item)
        return item

    async def search_items(
        self,
        keywords: str,
        search_index: str = "All",
        item_count: int = 10,
        sort_by: str = "Featured",
    ) -> list[dict[str, Any]]:
        """Search products by keyword with 24-hr caching."""
        # Department and sort belong in the key: without them a "price: low to
        # high" search silently returned the cached "featured" results.
        cache_key = "search_" + urllib.parse.quote_plus(
            f"{keywords}|{search_index}|{sort_by}|{item_count}", safe=""
        )
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        items = await self._search_scraper(
            keywords, count=item_count, search_index=search_index, sort_by=sort_by
        )
        if items:
            self._set_cached(cache_key, items)
        return items


paapi_client = AmazonProductEngine()

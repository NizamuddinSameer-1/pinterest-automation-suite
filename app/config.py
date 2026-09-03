"""
Pinterest Realism Engine — Application Configuration.

Loads settings from environment variables / .env file.
Dual-provider setup: OpenRouter (text) + Gemini (vision).
"""

from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(".env"), override=True)
except Exception:
    pass

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────
    app_env: str = "development"

    # ── Database ─────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/pre.db"

    # ── Storage ──────────────────────────────────
    storage_path: str = "./data"

    # ── OpenCode AI (Primary Provider) ───────────
    opencode_api_key: str = ""
    opencode_base_url: str = "https://opencode.ai/inference/openai/v1"
    opencode_text_model: str = "deepseek-v4-flash"
    opencode_vision_model: str = "mimo-v2.5"

    # ── Fallback Providers ───────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "deepseek/deepseek-chat-v4-0324"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    gemini_vision_model: str = "gemini-3-flash-preview"

    # ── Pinterest API (Phase 3) ──────────────────
    pinterest_client_id: str = ""
    pinterest_client_secret: str = ""
    pinterest_access_token: str = ""

    # ── Generation & publishing defaults ─────────
    # Which backend `POST /api/jobs/{id}/generate` uses when none is named.
    # "auto" = captured-session Google Flow API first, browser automation second.
    # See app/services/generation.py for the full list.
    generation_backend: str = "auto"
    generation_variation_count: int = 4
    generation_stall_minutes: int = 30
    # Google Flow project workspace the browser automator types into. Empty means
    # "discover the first project link on the Flow home page" — the previous code
    # had one operator's project UUID compiled into it.
    flow_project_url: str = ""
    flow_project_urls: str = ""
    flow_router_strategy: str = "round_robin"  # round_robin (sequential rotation) | random (load-balanced)
    # After generation, re-fetch each variation from Flow's server-side upsampler
    # (/v1/flow/upsampleImage) instead of settling for render resolution.
    # "2k" works on free accounts; "4k" is gated to paid Google AI plans (Google
    # reports the gate as a reCAPTCHA rejection); "none" keeps the old behaviour.
    # Any upsample failure falls back to the render-resolution bytes, so it can
    # never cost a variation. See app/services/flow_upscale.py.
    flow_upscale_resolution: str = "2k"
    # ── Pin Upscaler & HD Post-Processing ────────
    upscaler_target_width: int = 1080       # Full HD Pinterest Pin width (min 1080px)
    upscaler_jpeg_quality: int = 98         # 98% Studio-grade JPEG quality
    upscaler_subsampling: int = 0           # 0 = 4:4:4 zero chroma subsampling
    colab_upscaler_url: str = ""            # Optional Google Colab / Cloudflare URL for Real-ESRGAN / 4x-UltraSharp
    colab_notebook_url: str = ""            # Your Google Colab notebook shareable link (drive.google.com / colab.research.google.com)
    ugc_grain_amount: float = 2.5           # Micro-sensor grain to break AI plastic smoothness (0 to disable, 2.5 default)
    ugc_sharpen_percent: int = 140          # High-frequency micro-texture unsharp mask percent (fabric weave & skin pores)
    # Board used when the SEO stage suggests none. This was hardcoded as a literal
    # in the publisher, both generation paths and the batch upload route, so
    # changing boards meant editing four files.
    default_board_name: str = "Just Random Photography"

    # ── Pin scheduler ────────────────────────────
    # The in-process loop in app/services/scheduler.py that drains
    # data/scheduled_pins.json. Set scheduler_enabled=false while testing if you
    # do not want queued pins going live on their own.
    scheduler_enabled: bool = True
    # Publishing drives a real Chromium profile. Headless is correct for
    # unattended runs, but the pin-creation flow was only ever verified with a
    # visible window, so that stays the default until headless is confirmed.
    scheduler_headless: bool = False

    # ── Vercel Edge Publisher & Lookbook Bridge ───
    vercel_api_token: str = ""
    vercel_project_name: str = "pinterest-lookbooks"
    vercel_team_id: str = ""
    bridge_domain: str = ""
    require_lookbook_destination: bool = True  # Pins must link to the deployed blog lookbook, never raw affiliate links

    # ── Git-Backed Lookbook Publisher (GitHub + Vercel) ──
    lookbook_git_remote: str = ""  # e.g. https://github.com/<user>/pinterest-lookbooks.git or token URL
    lookbook_git_branch: str = "main"
    lookbook_git_auto_push: bool = True  # Auto-deploy to GitHub & Vercel live on lookbook generation
    lookbook_catalog_title: str = "Curated Lookbooks & Authentic Reviews"

    # ── Scene Director mode ───────────────────────
    # False (default): direct scenes from the taxonomy menu. Instant, needs no
    # LLM provider, and cannot hang the preview. The menu still has to be
    # *chosen from* — see app/pipeline/scene_director.py.
    # True: let the LLM direct. If it fails or times out the stage raises
    # (PipelineStageError) rather than substituting a scene, because a
    # substituted scene is what made every pin look the same.
    scene_director_llm: bool = False

    # ── Amazon PA-API 5.0 (Product Metadata Ingestion) ──
    # Friend's read-only PA-API keys for real-time prices, reviews, ratings, images
    amazon_paapi_access_key: str = ""
    amazon_paapi_secret_key: str = ""
    amazon_paapi_partner_tag: str = ""
    amazon_paapi_region: str = "us-east-1"
    amazon_paapi_host: str = "webservices.amazon.com"
    amazon_paapi_cache_ttl_hours: int = 24  # Amazon TOS allows caching up to 24h

    # ── Amazon Affiliate Associate Tags (100% Your Commissions) ──
    amazon_associate_tag_us: str = "nizamuddinsam-20"
    amazon_associate_tag_in: str = "nizamuddins0a-21"

    # ── Derived paths ────────────────────────────
    @property
    def references_path(self) -> Path:
        return Path(self.storage_path) / "references"

    @property
    def products_path(self) -> Path:
        return Path(self.storage_path) / "products"

    @property
    def jobs_path(self) -> Path:
        return Path(self.storage_path) / "jobs"

    @property
    def outputs_path(self) -> Path:
        return Path(self.storage_path) / "outputs"

    @property
    def exports_path(self) -> Path:
        return Path(self.storage_path) / "exports"

    @property
    def lookbooks_path(self) -> Path:
        return Path(self.storage_path) / "lookbooks"

    def ensure_storage_dirs(self) -> None:
        """Create all storage directories if they don't exist."""
        for p in [
            self.references_path,
            self.products_path,
            self.jobs_path,
            self.outputs_path,
            self.exports_path,
            self.lookbooks_path,
        ]:
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()


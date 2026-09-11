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
    # ── NVIDIA NIM (Direct Provider) ─────────────
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.2-11b-vision-instruct"

    # ── Content Lane Providers (Lane 2: blogs, pins, SEO, post copy) ──
    # Dedicated key set so long-form editorial calls never starve the
    # reference/vision/prompt lane. Empty = fall back to the primary keys
    # above, so single-key setups keep working with zero changes.
    content_nvidia_api_key: str = ""
    content_nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    content_nvidia_model: str = "meta/llama-3.2-11b-vision-instruct"

    content_opencode_api_key: str = ""
    content_opencode_base_url: str = ""
    content_opencode_text_model: str = ""
    content_opencode_vision_model: str = ""

    content_openrouter_api_key: str = ""
    content_openrouter_base_url: str = ""
    content_openrouter_model: str = ""

    content_gemini_api_key: str = ""
    content_gemini_model: str = ""
    content_gemini_vision_model: str = ""

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
    # Multi-shot mode: instead of ONE prompt submitted with count=N (which returns N
    # stochastic samples of that one prompt — four near-identical compositions), submit
    # one prompt per shot archetype and get four genuinely distinct photographs
    # (lifestyle / flat lay / macro / environment).
    #
    # Off by default because it costs N submissions instead of one, so a run takes
    # roughly N times as long and uses N times the Flow quota. Turn it on to get the
    # four distinct shots; turn it off to return to the previous single-prompt
    # behaviour with no other change. Only the browser backend (flow_ui) supports it.
    # See app/pipeline/shot_archetypes.py and docs/FLOW_4_SHOT_ARCHITECTURE.md.
    generation_multi_shot: bool = False
    # How many images to request per archetype. 1 is the purest four-shot set; 2 gives
    # a spare render per shot to survive an intermittent moderation rejection.
    generation_multi_shot_per_shot: int = 1
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
    # Every value here is read by app/services/anti_ai_processor.py. The previous
    # set produced 3.5-4.2 MB pins carrying visible sharpening halos, and
    # upscaler_target_width was declared but never read by anything.
    #
    # Target width is a *ceiling*, not a goal: images larger than this are
    # downscaled, and images smaller than this are only upscaled when the GPU
    # upscaler is unavailable. See _fit_width() in anti_ai_processor.
    upscaler_target_width: int = 1080
    # q92 at 4:2:0 is visually lossless at the sizes Pinterest actually serves.
    # q98 at 4:4:4 roughly tripled the file size for no visible gain.
    upscaler_jpeg_quality: int = 92
    upscaler_subsampling: int = 2           # 2 = 4:2:0; 0 (4:4:4) is ~3x the size
    # Fraction of the render height kept after removing the Flow sparkle. The
    # watermark sits at y 0.912-0.946 (measured over 66 raw renders), so 0.910
    # clears it with a small margin.
    watermark_keep_fraction: float = 0.910
    colab_upscaler_url: str = ""            # Colab/Cloudflare URL for the Real-ESRGAN server
    colab_notebook_url: str = ""            # Colab notebook shareable link (colab.research.google.com)
    # Cap the upscaler's 4x output before it crosses the tunnel. Uncapped, a
    # 1080px input becomes 5760px and returns as ~21 MB that is immediately
    # downscaled and discarded locally.
    colab_max_output_px: int = 2160
    ugc_grain_amount: float = 1.5           # Luminance-only sensor grain (0 to disable)
    ugc_sharpen_percent: int = 60           # Luminance-only unsharp mask percent
    ugc_sharpen_radius: float = 1.0
    # Threshold suppresses sharpening where local contrast is below it. This is
    # what keeps flat colour flat; the old value of 1 sharpened every pixel.
    ugc_sharpen_threshold: int = 3
    # Board used when the SEO stage suggests none. This was hardcoded as a literal
    # in the publisher, both generation paths and the batch upload route, so
    # changing boards meant editing four files.
    default_board_name: str = "Just Random Photography"
    auto_create_boards: bool = True  # Automatically create boards on Pinterest if missing
    # ── Trend Radar v2 scan ────────────────────────
    trend_scan_enabled: bool = True
    trend_scan_interval_hours: int = 24
    trend_weight_demand: float = 0.40
    trend_weight_money: float = 0.35
    trend_weight_winnability: float = 0.25

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
    require_lookbook_destination: bool = False  # If True, pin drafting requires a deployed lookbook. Default False: pin drafts use direct affiliate/smart redirect links.
    auto_create_lookbooks: bool = False  # If False (default), lookbooks are only created on-demand when the user clicks 'Create Batch Lookbook'.

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


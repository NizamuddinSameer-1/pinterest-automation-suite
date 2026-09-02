"""
Vercel Edge Deployer — Direct REST API publisher for static UGC lookbooks.

Uploads self-contained standalone HTML lookbooks & OG thumbnails directly to Vercel via
https://api.vercel.com/v13/deployments. Includes readiness polling and clean local fallbacks.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx

from app.config import settings
from app.services.git_publisher import commit_and_push_lookbook, generate_catalog_index

logger = logging.getLogger("pre.vercel_publisher")

VERCEL_API_BASE = "https://api.vercel.com"


class VercelDeployError(RuntimeError):
    """
    The lookbook could not be deployed to Vercel by any path.

    Raised instead of returning an unverified public URL. A URL for a page that
    was never deployed is a plausible-looking placeholder: it gets stored as the
    pin's `destination_url`, survives every downstream check, and ships to
    Pinterest pointing at a 404 — which is how this project ended up with pins
    whose destination existed only as a string nobody had ever deployed.
    """


def _gather_lookbook_payload() -> list[dict[str, Any]]:
    """
    Gather all published lookbooks, OG thumbnails, master catalog index.html,
    and Edge API functions (like api/go.js) from data/lookbooks/ so every Vercel
    REST deployment includes all pages and serverless/edge routes.
    """
    lookbooks_dir = settings.lookbooks_path
    payload_files: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for file_path in lookbooks_dir.rglob("*"):
        if not file_path.is_file():
            continue
        # Skip git metadata
        if ".git" in file_path.parts:
            continue

        rel_name = file_path.relative_to(lookbooks_dir).as_posix()
        fname = file_path.name

        # Include HTML, JS, JSON, TS Edge Functions and WebP/image assets
        if fname.endswith((".html", ".js", ".ts", ".json", ".css")):
            try:
                content = file_path.read_text(encoding="utf-8")
                payload_files.append({
                    "file": rel_name,
                    "data": content,
                    "encoding": "utf-8",
                })
                seen_names.add(rel_name)
            except Exception as e:
                logger.warning("Could not read %s for Vercel payload: %s", rel_name, e)
        elif fname.endswith((".webp", ".jpg", ".png", ".jpeg", ".svg")):
            try:
                raw = file_path.read_bytes()
                payload_files.append({
                    "file": rel_name,
                    "data": base64.b64encode(raw).decode("utf-8"),
                    "encoding": "base64",
                })
                seen_names.add(rel_name)
            except Exception as e:
                logger.warning("Could not read %s for Vercel payload: %s", rel_name, e)

    return payload_files


_CACHED_DOMAIN: str | None = None


async def resolve_vercel_live_domain() -> str:
    """
    Resolve the live production domain for the Vercel project.
    Checks settings.bridge_domain first, then queries Vercel project domains API.
    """
    global _CACHED_DOMAIN
    if settings.bridge_domain and settings.bridge_domain.strip():
        return settings.bridge_domain.strip()
    if _CACHED_DOMAIN:
        return _CACHED_DOMAIN

    token = settings.vercel_api_token.strip() if settings.vercel_api_token else ""
    project_name = settings.vercel_project_name.strip() or "pinterest-lookbooks"
    if token:
        try:
            url = f"{VERCEL_API_BASE}/v9/projects/{project_name}/domains"
            if settings.vercel_team_id:
                url += f"?teamId={settings.vercel_team_id}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                if res.status_code == 200:
                    domains = res.json().get("domains", [])
                    if domains:
                        primary = next((d["name"] for d in domains if d.get("verified")), domains[0]["name"])
                        _CACHED_DOMAIN = primary
                        return primary
        except Exception as e:
            logger.warning("Could not auto-fetch Vercel project domains: %s", e)

    return f"{project_name}.vercel.app"


async def deploy_article_to_vercel(
    slug: str,
    html_content: str,
    job_id: str,
    og_image_bytes: bytes | None = None,
) -> str:
    """
    Deploy UGC lookbooks to Vercel with zero 404s on previous campaigns.

    Dual-Pipeline Strategy:
      1. Git-Backed: Commits & pushes new lookbook + index.html to GitHub repo (Vercel Git Integration).
      2. Cumulative REST Snapshot: Packages all historical lookbooks in data/lookbooks/ so Vercel
         REST deployments never wipe past articles.

    Returns:
        str: The live production URL (e.g. `https://<alias>.vercel.app/<slug>.html`).

    Raises:
        VercelDeployError: no deploy path succeeded, so the page is not live and
            no URL is returned. Callers must fall back or fail loudly — never
            treat the missing result as a URL.
    """
    local_url = f"http://127.0.0.1:8000/lookbooks/{job_id}"

    # ── Local-First Review Mode ─────────────────────────────────
    # If auto-push is disabled, keep everything strictly local for user review
    if not getattr(settings, "lookbook_git_auto_push", False):
        logger.info(
            "Local review mode active (LOOKBOOK_GIT_AUTO_PUSH=False). Lookbook saved locally at %s",
            local_url,
        )
        return local_url

    # ── Step 1: Git-backed Auto-Push (GitHub + Vercel) ───────────
    # `pushed` is the honest signal: True means the commit reached `origin` and
    # Vercel's Git integration will build and serve the page. Every other status
    # (clean / committed_locally / push_failed / error) means it will not.
    git_pushed = False
    git_status = "unknown"
    try:
        git_res = await commit_and_push_lookbook(slug)
        git_status = git_res.get("status", "unknown")
        git_pushed = bool(git_res.get("pushed"))
        logger.info("Git lookbook publish result for %s: %s", slug, git_status)
    except Exception as e:
        git_status = f"exception: {e}"
        logger.warning("Git lookbook commit/push encountered error: %s", e)

    token = settings.vercel_api_token.strip() if settings.vercel_api_token else ""
    project_name = settings.vercel_project_name.strip() or "pinterest-lookbooks"

    live_domain = await resolve_vercel_live_domain()
    public_url = f"https://{live_domain}/{slug}.html"

    # If VERCEL_API_TOKEN is not configured, git-backed auto-deploy to GitHub + Vercel is active
    if not token:
        if git_pushed:
            logger.info(
                "VERCEL_API_TOKEN not configured in .env; lookbook deployed via Git to %s",
                public_url,
            )
            return public_url
        raise VercelDeployError(
            f"lookbook {slug!r} is not live anywhere: the git push did not reach origin "
            f"(status: {git_status}) and VERCEL_API_TOKEN is not set, so no REST deploy "
            "was attempted."
        )

    # ── Step 2: Cumulative REST Deployment Snapshot ──────────────
    # Make sure catalog index.html is generated
    try:
        await generate_catalog_index()
    except Exception:
        pass

    # Gather all lookbook files in data/lookbooks/
    files_payload = _gather_lookbook_payload()

    # Fallback safety: if directory scan was empty, include the current page explicitly
    if not any(f.get("file") == f"{slug}.html" for f in files_payload):
        files_payload.append({
            "file": f"{slug}.html",
            "data": html_content,
            "encoding": "utf-8",
        })
        if og_image_bytes:
            files_payload.append({
                "file": f"{slug}-og.webp",
                "data": base64.b64encode(og_image_bytes).decode("utf-8"),
                "encoding": "base64",
            })

    payload: dict[str, Any] = {
        "name": project_name,
        "target": "production",
        "files": files_payload,
        "projectSettings": {
            "framework": None,
        },
    }

    url = f"{VERCEL_API_BASE}/v13/deployments"
    if settings.vercel_team_id:
        url += f"?teamId={settings.vercel_team_id}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code in (200, 201):
                data = resp.json()
                deployment_id = data.get("id")

                # Poll deployment readiness to ensure global edge propagation
                ready_verified = False
                failed_state: str | None = None
                if deployment_id:
                    poll_url = f"{VERCEL_API_BASE}/v13/deployments/{deployment_id}"
                    if settings.vercel_team_id:
                        poll_url += f"?teamId={settings.vercel_team_id}"

                    for attempt in range(8):
                        await asyncio.sleep(1.5)
                        try:
                            poll_resp = await client.get(poll_url, headers=headers)
                            if poll_resp.status_code == 200:
                                pdata = poll_resp.json()
                                ready_state = pdata.get("readyState") or pdata.get("status")
                                if ready_state == "READY":
                                    logger.info("Vercel deployment %s is verified READY on attempt %d", deployment_id, attempt + 1)
                                    ready_verified = True
                                    break
                                elif ready_state in ("ERROR", "CANCELED"):
                                    logger.warning("Vercel deployment %s entered %s state", deployment_id, ready_state)
                                    failed_state = ready_state
                                    break
                        except Exception:
                            pass

                if failed_state:
                    if git_pushed:
                        logger.warning(
                            "Vercel REST deployment %s entered %s; the Git-backed deploy "
                            "already pushed this lookbook, using %s",
                            deployment_id, failed_state, public_url,
                        )
                        return public_url
                    raise VercelDeployError(
                        f"Vercel REST deployment {deployment_id} entered {failed_state} state "
                        f"and the Git-backed deploy did not reach origin (status: {git_status})"
                    )

                if ready_verified:
                    logger.info("Successfully deployed lookbook to Vercel production: %s", public_url)
                else:
                    # Accepted by Vercel (200/201) but not READY within the poll
                    # window — the deployment exists and is still building.
                    logger.warning(
                        "Vercel deployment %s was accepted but not verified READY within the "
                        "poll window; using %s (it may take a moment to propagate)",
                        deployment_id, public_url,
                    )
                return public_url

            # Non-2xx: Vercel did not accept the deployment, so the page is not live.
            err_text = resp.text[:200]
            if git_pushed:
                logger.warning(
                    "Vercel REST deployment returned HTTP %d (%s); the Git-backed deploy "
                    "already pushed this lookbook, using %s",
                    resp.status_code, err_text, public_url,
                )
                return public_url
            raise VercelDeployError(
                f"Vercel REST deployment failed with HTTP {resp.status_code}: {err_text}"
            )
    except VercelDeployError:
        raise
    except Exception as e:
        if git_pushed:
            logger.error(
                "Vercel deployment exception: %s; the Git-backed deploy already pushed "
                "this lookbook, using %s", e, public_url,
            )
            return public_url
        raise VercelDeployError(f"Vercel deployment failed: {e}") from e

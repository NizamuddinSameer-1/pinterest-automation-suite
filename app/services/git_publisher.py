"""
Git Lookbook Publisher — Manages Git-backed lookbook deployment to GitHub/Vercel.

Maintains all lookbook HTML pages in a persistent Git repository, auto-generates
a master catalog index.html, and executes lightweight async Git commits & pushes.
Vercel automatically detects pushes and updates the production site incrementally
without wiping historic lookbooks.
"""

from __future__ import annotations

import asyncio
import datetime
import html
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

import jinja2

from app.config import settings

logger = logging.getLogger("pre.git_publisher")

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
)


def _get_lookbooks_dir() -> Path:
    """Return the resolved lookbooks directory."""
    path = settings.lookbooks_path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _git_exe() -> str:
    """
    Resolve the git executable. On this machine Git is installed but not on
    PATH, so bare "git" failed silently and every auto-push was swallowed as a
    logged error. Check PATH first, then the standard install locations.
    """
    found = shutil.which("git")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\bin\git.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return "git"  # last resort; will error loudly as before


async def _run_git_cmd(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    """Execute a git CLI command asynchronously without blocking the event loop."""
    try:
        proc = await asyncio.create_subprocess_exec(
            _git_exe(),
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="ignore").strip(),
            stderr.decode("utf-8", errors="ignore").strip(),
        )
    except asyncio.TimeoutError:
        logger.warning("Git command timed out: git %s", " ".join(cmd))
        return (-1, "", "Command timed out (30s)")
    except Exception as e:
        logger.error("Git execution failed: git %s: %s", " ".join(cmd), e)
        return (-1, "", str(e))


async def init_lookbook_repo(repo_dir: Path | None = None) -> bool:
    """
    Ensure the lookbooks directory is initialized as a Git repository.
    Sets default branch to 'main' and adds a .gitignore.
    """
    repo = repo_dir or _get_lookbooks_dir()
    repo.mkdir(parents=True, exist_ok=True)

    git_dir = repo / ".git"
    if not git_dir.exists():
        code, out, err = await _run_git_cmd(["init", "-b", "main"], cwd=repo)
        if code != 0:
            # Fallback for older git versions that don't support -b in init
            code, out, err = await _run_git_cmd(["init"], cwd=repo)
            await _run_git_cmd(["branch", "-M", "main"], cwd=repo)

        logger.info("Initialized Git repository in lookbooks directory: %s", repo)

    # Ensure git user name and email are configured locally if not set globally
    code, out, _ = await _run_git_cmd(["config", "user.name"], cwd=repo)
    if not out:
        await _run_git_cmd(["config", "user.name", "Pinterest Lookbook Publisher"], cwd=repo)
        await _run_git_cmd(["config", "user.email", "publisher@pinterest-engine.local"], cwd=repo)

    # Ensure .gitignore exists in lookbooks dir
    gitignore = repo / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".DS_Store\nThumbs.db\n*.tmp\n*.bak\n", encoding="utf-8")

    # Configure remote if provided in settings
    remote_url = getattr(settings, "lookbook_git_remote", "").strip()
    if remote_url:
        code, out, _ = await _run_git_cmd(["remote", "get-url", "origin"], cwd=repo)
        if code != 0:
            await _run_git_cmd(["remote", "add", "origin", remote_url], cwd=repo)
            logger.info("Configured Git remote origin: %s", remote_url)
        elif out != remote_url:
            await _run_git_cmd(["remote", "set-url", "origin", remote_url], cwd=repo)
            logger.info("Updated Git remote origin: %s", remote_url)

    return True


def _extract_meta_from_html(html_file: Path) -> dict[str, Any] | None:
    """Parse title, description, and OG image from a generated lookbook HTML file."""
    try:
        content = html_file.read_text(encoding="utf-8", errors="ignore")
        
        title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
        title = html.unescape(title_match.group(1)).strip() if title_match else html_file.stem
        
        desc_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', content, re.IGNORECASE)
        if not desc_match:
            desc_match = re.search(r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']', content, re.IGNORECASE)
        desc = html.unescape(desc_match.group(1)).strip() if desc_match else "Curated lookbook & authentic product review."

        # Resolve the bridge domain for building absolute image URLs
        bridge_domain = getattr(settings, "bridge_domain", None) or os.environ.get("BRIDGE_DOMAIN", "")

        # Check for accompanying OG image or inline data URI
        og_image_file = html_file.with_name(f"{html_file.stem}-og.webp")
        if og_image_file.exists() and bridge_domain:
            image_url = f"https://{bridge_domain}/{html_file.stem}-og.webp"
        elif og_image_file.exists():
            image_url = f"{html_file.stem}-og.webp"
        else:
            # Check if there is an og:image in meta
            img_match = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\'](.*?)["\']', content, re.IGNORECASE)
            image_url = img_match.group(1).strip() if img_match else ""

        # Modification time for sorting
        mtime = html_file.stat().st_mtime
        date_str = datetime.datetime.fromtimestamp(mtime).strftime("%b %d, %Y")

        return {
            "slug": html_file.stem,
            "filename": html_file.name,
            "url": html_file.name,
            "title": title,
            "product_name": title.split("|")[0].split("🖤")[0].split("-")[0].strip(),
            "description": desc,
            "image_url": image_url,
            "badge": "Curator's Pick",
            "date": date_str,
            "mtime": mtime,
        }
    except Exception as e:
        logger.warning("Could not parse metadata from %s: %s", html_file.name, e)
        return None


async def generate_catalog_index(repo_dir: Path | None = None) -> str:
    """
    Build and save a master `index.html` catalog grid listing all active lookbooks.
    """
    repo = repo_dir or _get_lookbooks_dir()
    lookbooks: list[dict[str, Any]] = []

    # UUID pattern to exclude raw UUID aliases if named slug exists
    uuid_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

    for html_file in repo.glob("*.html"):
        if html_file.name == "index.html":
            continue
        # Skip raw UUID file if a slug version exists
        if uuid_pattern.match(html_file.stem):
            continue

        meta = _extract_meta_from_html(html_file)
        if meta:
            lookbooks.append(meta)

    # Sort lookbooks newest first
    lookbooks.sort(key=lambda x: x.get("mtime", 0), reverse=True)

    template = jinja_env.get_template("catalog_index.html")
    rendered_index = template.render(
        catalog_title=getattr(settings, "lookbook_catalog_title", "Curated Lookbooks & Reviews"),
        lookbooks=lookbooks,
        year=datetime.datetime.now().year,
    )

    index_path = repo / "index.html"
    index_path.write_text(rendered_index, encoding="utf-8")

    # Generate sitemap.xml & robots.txt with current catalog URLs
    bridge_domain = getattr(settings, "bridge_domain", None) or os.environ.get("BRIDGE_DOMAIN", "")
    if not bridge_domain:
        bridge_domain = (
            f"{settings.vercel_project_name}.vercel.app"
            if settings.vercel_project_name
            else "pinterest-lookbooks-beta.vercel.app"
        )

    base_url = f"https://{bridge_domain}"
    today_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    sitemap_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        '  <url>',
        f'    <loc>{base_url}/</loc>',
        f'    <lastmod>{today_iso}</lastmod>',
        '    <changefreq>daily</changefreq>',
        '    <priority>1.0</priority>',
        '  </url>',
    ]
    for lb in lookbooks:
        mtime = lb.get("mtime")
        if mtime:
            lastmod = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).strftime("%Y-%m-%d")
        else:
            lastmod = today_iso
        sitemap_lines.extend([
            '  <url>',
            f'    <loc>{base_url}/{lb["slug"]}.html</loc>',
            f'    <lastmod>{lastmod}</lastmod>',
            '    <changefreq>weekly</changefreq>',
            '    <priority>0.8</priority>',
            '  </url>',
        ])
    sitemap_lines.append('</urlset>\n')
    sitemap_xml = "\n".join(sitemap_lines)
    (repo / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")

    robots_txt = (
        "User-agent: *\n"
        "Allow: /\n\n"
        f"Sitemap: {base_url}/sitemap.xml\n"
    )
    (repo / "robots.txt").write_text(robots_txt, encoding="utf-8")

    logger.info("Generated master catalog index.html, sitemap.xml, and robots.txt with %d lookbooks", len(lookbooks))
    return rendered_index


async def commit_and_push_lookbook(
    slug: str,
    repo_dir: Path | None = None,
    commit_msg: str | None = None,
) -> dict[str, Any]:
    """
    Commit lookbook updates and push to the configured GitHub repository.
    
    Returns:
        dict[str, Any]: Status dictionary containing success, commit hash, and remote output.
    """
    repo = repo_dir or _get_lookbooks_dir()
    await init_lookbook_repo(repo)

    # 1. Regenerate master catalog index.html
    await generate_catalog_index(repo)

    # 2. Check if git status has changes
    code, status_out, _ = await _run_git_cmd(["status", "--porcelain"], cwd=repo)
    if not status_out:
        logger.info("Git repo is clean; no changes to commit for %s", slug)
        return {"status": "clean", "message": "No changes to commit", "pushed": False}

    # 3. Stage changes
    code, _, err = await _run_git_cmd(["add", "."], cwd=repo)
    if code != 0:
        logger.error("Git add failed: %s", err)
        return {"status": "error", "message": f"Git add failed: {err}", "pushed": False}

    # 4. Commit
    msg = commit_msg or f"Publish lookbook: {slug} [skip ci]"
    code, commit_out, err = await _run_git_cmd(["commit", "-m", msg], cwd=repo)
    if code != 0:
        logger.warning("Git commit notice: %s (%s)", commit_out, err)

    # 5. Push to Remote if origin exists
    branch = getattr(settings, "lookbook_git_branch", "main")
    code, remotes, _ = await _run_git_cmd(["remote"], cwd=repo)
    has_remote = "origin" in remotes.split()

    if not has_remote:
        logger.info("Git commit created locally. (No remote 'origin' configured in .env yet)")
        return {
            "status": "committed_locally",
            "message": "Committed locally; set LOOKBOOK_GIT_REMOTE in .env to enable auto-push to GitHub/Vercel.",
            "pushed": False,
        }

    logger.info("Pushing lookbook %s to remote repository (branch: %s)...", slug, branch)
    code, push_out, push_err = await _run_git_cmd(["push", "-u", "origin", branch], cwd=repo)
    
    if code == 0:
        logger.info("Successfully pushed lookbook to GitHub (%s/%s)", repo.name, branch)
        return {
            "status": "pushed",
            "message": f"Pushed {slug} to remote repository successfully.",
            "pushed": True,
        }
    else:
        logger.warning("Git push to remote failed (code %d): %s %s", code, push_out, push_err)
        return {
            "status": "push_failed",
            "message": f"Push failed: {push_err or push_out}",
            "pushed": False,
        }

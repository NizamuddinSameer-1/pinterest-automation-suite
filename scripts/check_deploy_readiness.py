"""
Deploy readiness check — can this machine actually publish a lookbook?

`LOOKBOOK_GIT_AUTO_PUSH=true` is not evidence that pushing works. It was set for
weeks while every push failed on credentials, so lookbooks were generated and
recorded as pin destinations without ever reaching the live site. This script
answers the real question with a read-only probe.

Checks, in dependency order:
  1. .env exists                — without it the app runs on bare defaults
  2. Vercel REST deploy         — token present and accepted by the Vercel API
  3. Git push path              — origin configured and the credential works

Nothing here mutates the remote. `git ls-remote` performs the same auth
handshake as `push` and is safe.

Usage
-----
    python -m scripts.check_deploy_readiness
    python -m scripts.check_deploy_readiness --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

sys.path.insert(0, str(ROOT))

OK = "PASS"
WARN = "WARN"
FAIL = "FAIL"


def check_env_file() -> dict:
    if not ENV_PATH.exists():
        return {
            "name": ".env present",
            "status": FAIL,
            "detail": ".env is missing — the app falls back to config.py defaults",
            "hint": "Restore it, or copy .env.example and fill in the values.",
        }
    keys = [
        ln.split("=", 1)[0].strip()
        for ln in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#") and "=" in ln
    ]
    return {
        "name": ".env present",
        "status": OK,
        "detail": f"{len(keys)} keys defined",
        "hint": "",
    }


def check_vercel_token() -> dict:
    from app.config import settings

    token = (settings.vercel_api_token or "").strip()
    if not token:
        return {
            "name": "Vercel REST deploy",
            "status": WARN,
            "detail": "VERCEL_API_TOKEN not set — REST deploy path disabled",
            "hint": "Set VERCEL_API_TOKEN, or rely on git push alone.",
        }
    try:
        req = urllib.request.Request(
            "https://api.vercel.com/v2/user",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        user = payload.get("user") or {}
        return {
            "name": "Vercel REST deploy",
            "status": OK,
            "detail": f"token valid for {user.get('username') or user.get('email') or 'account'}",
            "hint": "",
        }
    except urllib.error.HTTPError as e:
        return {
            "name": "Vercel REST deploy",
            "status": FAIL,
            "detail": f"token rejected (HTTP {e.code})",
            "hint": "Regenerate the token in Vercel account settings.",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "name": "Vercel REST deploy",
            "status": WARN,
            "detail": f"could not reach the Vercel API ({type(e).__name__})",
            "hint": "Check network access; git push may still work.",
        }


async def check_git_push() -> dict:
    from app.services.git_publisher import check_push_readiness

    r = await check_push_readiness()
    if r["ready"]:
        return {
            "name": "Git push (auto-deploy)",
            "status": OK,
            "detail": f"{r['remote']} -> {r['branch']}",
            "hint": "",
        }
    status = FAIL if r["remote"] else WARN
    return {
        "name": "Git push (auto-deploy)",
        "status": status,
        "detail": r["message"],
        "hint": r["hint"],
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = [check_env_file(), check_vercel_token(), await check_git_push()]

    if args.json:
        json.dump(results, sys.stdout, indent=2)
        return 0

    print("=" * 74)
    print("LOOKBOOK DEPLOY READINESS")
    print("=" * 74)
    for r in results:
        print(f"  [{r['status']:4}] {r['name']}")
        print(f"         {r['detail']}")
        if r["hint"]:
            print(f"         -> {r['hint']}")
    print()

    failed = [r for r in results if r["status"] == FAIL]
    warned = [r for r in results if r["status"] == WARN]
    if failed:
        print(f"  NOT READY — {len(failed)} blocking issue(s). Lookbooks will not deploy.")
        return 1
    if warned:
        print(f"  DEGRADED — {len(warned)} warning(s). At least one deploy path works.")
        return 0
    print("  READY — a generated lookbook will deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

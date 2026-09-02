"""
Pinterest Realism Engine — CLI System Diagnostic & Debugging Tool.

Run via:
    python -m scripts.debug

Instantly checks Database, LLM Providers, Google Flow Session, Pinterest Authentication,
Storage Directories, and Obsidian Vault sync, reporting any issues and exact fixes.
"""

import asyncio
import sys
from pathlib import Path

# Ensure ProactorEventLoop on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.error_diagnostics import run_full_system_diagnostic


def _format_status(status: str) -> str:
    if status == "PASS":
        return "\033[92m[PASS]\033[0m"
    if status == "WARN":
        return "\033[93m[WARN]\033[0m"
    return "\033[91m[FAIL]\033[0m"


async def main():
    print("\n" + "=" * 60)
    print(" 🛠️  PINTEREST REALISM ENGINE (PRE) — SYSTEM DIAGNOSTICS")
    print("=" * 60)
    print(" Running instant diagnostic across all 7 subsystems...\n")

    diag = await run_full_system_diagnostic()

    print(f" Overall System Status: {_format_status(diag['overall_status'])}  "
          f"(Completed in {diag['diagnostic_time_ms']} ms)\n")

    subsystems = diag["subsystems"]

    # 1. Database
    db = subsystems["database"]
    print(f" {db['name']:<35} {_format_status(db['status'])} ({db.get('latency_ms', 0)} ms)")
    if db.get("details"):
        counts = db["details"].get("counts", {})
        print(f"   ↳ WAL: {db['details'].get('journal_mode')}, Timeout: {db['details'].get('busy_timeout_ms')} ms")
        print(f"   ↳ DB Records: {counts.get('references', 0)} refs, {counts.get('products', 0)} products, "
              f"{counts.get('jobs', 0)} jobs, {counts.get('pin_drafts', 0)} pin drafts")
    if db.get("error"):
        print(f"   \033[91m↳ Error: {db['error']}\033[0m")
    if db.get("suggested_fix"):
        print(f"   \033[96m👉 FIX: {db['suggested_fix']}\033[0m")
    print()

    # 2. LLM Providers
    llm = subsystems["llm_provider"]
    print(f" {llm['name']:<35} {_format_status(llm['status'])} ({llm.get('latency_ms', 0)} ms)")
    if llm.get("providers"):
        p = llm["providers"]
        print(f"   ↳ Configured: Gemini={p.get('gemini')}, OpenCode={p.get('opencode')}, OpenRouter={p.get('openrouter')}")
        print(f"   ↳ Active Text Model: {p.get('text_model')}")
    if llm.get("ping_response"):
        print(f"   ↳ Test Generation Ping: {llm['ping_response']!r}")
    if llm.get("error"):
        print(f"   \033[91m↳ Error: {llm['error']}\033[0m")
    if llm.get("suggested_fix"):
        print(f"   \033[96m👉 FIX: {llm['suggested_fix']}\033[0m")
    print()

    # 3. Google Flow
    flow = subsystems["flow_automation"]
    print(f" {flow['name']:<35} {_format_status(flow['status'])}")
    print(f"   ↳ Browser Profile: {'Ready' if flow.get('has_profile') else 'Not Logged In'}")
    print(f"   ↳ Workspace URL: {flow.get('project_url')}")
    if flow.get("suggested_fix"):
        print(f"   \033[96m👉 FIX: {flow['suggested_fix']}\033[0m")
    print()

    # 4. Pinterest Publisher
    pin = subsystems["pinterest_publisher"]
    print(f" {pin['name']:<35} {_format_status(pin['status'])}")
    print(f"   ↳ Session Auth: {'Authenticated' if pin.get('authenticated') else 'Not Logged In'}")
    print(f"   ↳ Cached Boards: {pin.get('cached_boards_count', 0)} board(s) (Default: {pin.get('default_board')})")
    if pin.get("suggested_fix"):
        print(f"   \033[96m👉 FIX: {pin['suggested_fix']}\033[0m")
    print()

    # 5. Storage
    storage = subsystems["storage"]
    print(f" {storage['name']:<35} {_format_status(storage['status'])}")
    counts = storage.get("counts", {})
    print(f"   ↳ Files on disk: {counts.get('references', 0)} refs, {counts.get('jobs', 0)} jobs, "
          f"{counts.get('outputs', 0)} output folders, {counts.get('exports', 0)} exports")
    print()

    # 6. Obsidian Vault
    vault = subsystems["vault"]
    print(f" {vault['name']:<35} {_format_status(vault['status'])}")
    print(f"   ↳ Vault connected at {vault.get('vault_path')}")
    print(f"   ↳ Logged Bug Reports in Vault: {vault.get('logged_bug_count', 0)} note(s)")
    print()

    # Recent Errors
    recent = diag.get("recent_errors", [])
    if recent:
        print("=" * 60)
        print(" ⚠️  RECENT LOGGED RUNTIME ERRORS")
        print("=" * 60)
        for err in recent[:5]:
            print(f" [{err.get('id')}] \033[91m[{err.get('subsystem')}]\033[0m {err.get('error_type')}: {err.get('message')}")
            print(f"   ↳ Location: {err.get('location')}")
            if err.get('suggested_fix'):
                print(f"   \033[96m👉 FIX: {err.get('suggested_fix')}\033[0m")
            print()
    else:
        print(" ✨ No recent runtime errors logged. Everything running smoothly!\n")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

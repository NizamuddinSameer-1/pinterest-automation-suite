"""
Unified PRE Watcher — generation + publish in ONE window with live progress bars.

    python -m scripts.watch_all              # follow everything (gen + pub)
    python -m scripts.watch_all --gen        # only generation (Flow 4-var)
    python -m scripts.watch_all --pub        # only publish (browser posting)

Why this exists:
- Old start.bat only watched publish (data/publish_runs) so generation (data/outputs) stayed dark.
- New start.bat watches both separately, but you had to watch two windows to know where it stuck.
- This shows BOTH with live ASCII progress bars, so "Running scene director..." vs "Flow 37%" vs "Publishing 2/4" is obvious.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "outputs"
PUB_DIR = ROOT / "data" / "publish_runs"
POLL = 0.8

def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def _bar(pct: int, width: int = 28) -> str:
    pct = max(0, min(100, int(pct)))
    filled = int(width * pct / 100)
    return f"[{'█'*filled}{'░'*(width-filled)}] {pct:3d}%"

def _clock(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%H:%M:%S")
    except Exception:
        return iso[:8]

def _say(t=""):
    print(t, flush=True)

def _scan_gen():
    if not OUT_DIR.exists():
        return []
    outs = []
    for d in OUT_DIR.iterdir():
        if d.is_dir() and (d / "status.json").exists():
            outs.append(d)
    return sorted(outs, key=lambda d: (d / "status.json").stat().st_mtime)

def _scan_pub():
    if not PUB_DIR.exists():
        return []
    outs = []
    for d in PUB_DIR.iterdir():
        if d.is_dir() and (d / "spec.json").exists():
            outs.append(d)
    return sorted(outs, key=lambda d: (d / "spec.json").stat().st_mtime)

def _gen_status_line(s: dict) -> str:
    st = s.get("status", "unknown")
    req = s.get("requested_count", 0) or s.get("requested_count", 4)
    cur = s.get("image_count", 0)
    pct = int(100 * cur / max(req, 1)) if st in ("generating", "saving") else (100 if st == "done" else 0)
    if st == "generating":
        return f"GEN {s.get('job_id','?')[:8]} {_bar(pct)}  {cur}/{req}  backend={s.get('backend','?')}  {s.get('message','')}"
    if st == "error":
        return f"GEN {s.get('job_id','?')[:8]} {_bar(0)}  ERROR: {(s.get('error') or '')[:80]}"
    if st == "done":
        return f"GEN {s.get('job_id','?')[:8]} {_bar(100)}  DONE {cur}/{req} via {s.get('produced_by','?')}"
    return f"GEN {s.get('job_id','?')[:8]} [{st}]"

def _pub_status_line(s: dict, spec: dict | None) -> str:
    st = s.get("status", "?")
    total = s.get("total", 0)
    comp = s.get("completed", 0)
    pct = int(100 * comp / max(total, 1)) if total else 0
    kind = s.get("kind") or (spec or {}).get("kind") or "?"
    if st in ("starting", "running"):
        return f"PUB {s.get('run_id','?')[:8]} {_bar(pct)}  {comp}/{total}  {kind}  pid={s.get('pid','-')}"
    if st == "error":
        return f"PUB {s.get('run_id','?')[:8]} {_bar(pct)}  ERROR: {(s.get('error') or '')[:70]}"
    if st == "done":
        return f"PUB {s.get('run_id','?')[:8]} {_bar(100)}  DONE {comp}/{total} {kind}"
    return f"PUB {s.get('run_id','?')[:8]} [{st}]"

def main(argv):
    ap = argparse.ArgumentParser(description="Unified PRE watcher — gen + pub with progress bars")
    ap.add_argument("--gen", action="store_true", help="only generation")
    ap.add_argument("--pub", action="store_true", help="only publish")
    args = ap.parse_args(argv)

    show_gen = not args.pub
    show_pub = not args.gen

    _say("="*78)
    _say("PRE Unified Watcher — live progress for generation (Flow) + publish (browser)")
    _say(f"Gen: {OUT_DIR}   Pub: {PUB_DIR}")
    _say("Trigger Generate or Publish in the UI — bars appear here live.")
    _say("Ctrl+C to stop watching (runs keep going).")
    _say("="*78)

    # Show last 2 of each so you know what's already there
    if show_gen:
        for d in _scan_gen()[-2:]:
            s = _read_json(d / "status.json") or {}
            _say(_gen_status_line(s))
            # tail last 3 log lines
            log = d / "bg_log.txt"
            if log.exists():
                lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
                for l in lines[-3:]:
                    if l.strip():
                        _say(f"      | {l[:110]}")
    if show_pub:
        for d in _scan_pub()[-2:]:
            s = _read_json(d / "status.json") or {}
            spec = _read_json(d / "spec.json")
            _say(_pub_status_line(s, spec))

    _say("-"*78)
    _say("Watching for new runs...")

    known_gen = {d.name for d in _scan_gen()}
    known_pub = {d.name for d in _scan_pub()}
    last_gen = {d.name: _read_json(d / "status.json") for d in _scan_gen()}
    last_pub = {d.name: _read_json(d / "status.json") for d in _scan_pub()}

    gen_offsets: dict[str, int] = {}
    pub_offsets: dict[str, int] = {d.name: 0 for d in _scan_pub()}

    while True:
        # --- generation ---
        if show_gen:
            for d in _scan_gen():
                s = _read_json(d / "status.json")
                if not s:
                    continue
                # new run
                if d.name not in known_gen:
                    known_gen.add(d.name)
                    _say(f"\n▶ NEW GEN {d.name}  backend={s.get('backend')}  req={s.get('requested_count')}")
                # status change
                prev = last_gen.get(d.name)
                if s != prev:
                    _say(_gen_status_line(s))
                    last_gen[d.name] = s
                # tail bg_log.txt live
                log = d / "bg_log.txt"
                if log.exists():
                    off = gen_offsets.get(d.name, 0)
                    try:
                        with log.open("r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(off)
                            chunk = fh.read()
                            off = fh.tell()
                        gen_offsets[d.name] = off
                        for line in chunk.splitlines():
                            if line.strip():
                                # Highlight where it is stuck
                                if "Running scene director" in line or "Compiling" in line or "Generating" in line:
                                    _say(f"  ⏳ GEN {d.name[:8]} | {line.strip()[:110]}")
                                elif "Pasted reference image" in line or "Prompt delivered" in line or "Submitted via" in line or "elapsed" in line or "media named" in line:
                                    _say(f"  📎 GEN {d.name[:8]} | {line.strip()[:110]}")
                                elif "error" in line.lower() or "failed" in line.lower():
                                    _say(f"  ❌ GEN {d.name[:8]} | {line.strip()[:110]}")
                                else:
                                    _say(f"     GEN {d.name[:8]} | {line.strip()[:110]}")
                    except OSError:
                        pass

        # --- publish ---
        if show_pub:
            for d in _scan_pub():
                s = _read_json(d / "status.json") or {}
                spec = _read_json(d / "spec.json")
                if d.name not in known_pub:
                    known_pub.add(d.name)
                    _say(f"\n▶ NEW PUB {d.name}  kind={s.get('kind')}  pins={s.get('total')}")
                    last_pub[d.name] = None
                prev = last_pub.get(d.name)
                if s != prev:
                    _say(_pub_status_line(s, spec))
                    last_pub[d.name] = s
                log = d / "log.txt"
                if log.exists():
                    off = pub_offsets.get(d.name, 0)
                    try:
                        with log.open("r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(off)
                            chunk = fh.read()
                            off = fh.tell()
                        pub_offsets[d.name] = off
                        for line in chunk.splitlines():
                            if line.strip():
                                _say(f"     PUB {d.name[:8]} | {line.strip()[:110]}")
                    except OSError:
                        pass

        time.sleep(POLL)

if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        _say("\nStopped watching. Runs keep going in their own processes.")
        raise SystemExit(130)

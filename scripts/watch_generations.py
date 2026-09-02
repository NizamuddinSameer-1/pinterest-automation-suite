"""
Watch generation (Flow) runs live — the 4-variation image jobs.

    python -m scripts.watch_generations           # follow whatever starts next
    python -m scripts.watch_generations --list
    python -m scripts.watch_generations --last

Generation runs are NOT in data/publish_runs — they are in
data/outputs/<job_id>/status.json + bg_log.txt, written by
scripts/run_flow_bg.py (spawned by POST /api/jobs/{id}/generate).

This is the companion to scripts/watch_runs.py (which watches publish runs).
Leave both open: one window for publish, one for generation.
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
POLL = 1.0

def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def _runs():
    if not OUT_DIR.exists():
        return []
    outs = []
    for d in OUT_DIR.iterdir():
        if d.is_dir() and (d / "status.json").exists():
            outs.append(d)
    return sorted(outs, key=lambda d: (d / "status.json").stat().st_mtime)

def _clock(v):
    if not v:
        return "-"
    try:
        when = datetime.fromisoformat(v)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.astimezone().strftime("%H:%M:%S")
    except Exception:
        return v

def _say(t=""):
    print(t, flush=True)

def show(run: Path, tail=40):
    s = _read_json(run / "status.json") or {}
    _say("="*78)
    _say(f"GEN job {s.get('job_id') or run.name}  status={s.get('status')}  backend={s.get('backend')}  images={s.get('image_count')}/{s.get('requested_count')}")
    if s.get("error"):
        _say(f"error: {s['error']}")
    for p in (s.get("image_paths") or [])[:8]:
        _say(f"  - {p}")
    log = run / "bg_log.txt"
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        _say(f"--- bg_log.txt (last {min(tail,len(lines))} of {len(lines)}) ---")
        for l in lines[-tail:]:
            _say(l)
    _say(f"full log: {log}")
    _say(f"full status: {run / 'status.json'}")

def follow(run: Path):
    status_p, log_p = run / "status.json", run / "bg_log.txt"
    offset = 0
    last = {}
    _say("="*78)
    _say(f"GEN watching {status_p}")
    _say("-"*78)
    while True:
        cur = _read_json(status_p) or {}
        # tail log
        if log_p.exists():
            try:
                with log_p.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(offset)
                    chunk = fh.read()
                    offset = fh.tell()
                for line in chunk.splitlines():
                    if line.strip():
                        _say(f"    | {line}")
            except OSError:
                pass
        if cur and cur != last:
            _say(f"[{cur.get('status')}] {cur.get('image_count',0)}/{cur.get('requested_count',0)}")
            if cur.get("error"):
                _say(f"error: {cur['error']}")
            last = cur
        if cur.get("status") in ("done","error"):
            _say("-"*78)
            _say(f"finished as {cur.get('status')}")
            return cur
        try:
            silence = time.time() - status_p.stat().st_mtime
        except OSError:
            silence = 0
        if cur.get("status") == "generating" and silence > 10*60:
            _say(f"!! no progress for {silence/60:.0f}m — generator looks gone")
            return cur
        time.sleep(POLL)

def main(argv):
    ap = argparse.ArgumentParser(description="Watch Flow generation runs")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--last", action="store_true")
    args = ap.parse_args(argv)
    runs = _runs()
    if args.list:
        if not runs:
            _say(f"No runs under {OUT_DIR}")
            return 0
        _say(f"{'job':36} {'status':10} {'imgs':6} started")
        for r in runs[-25:]:
            s = _read_json(r / "status.json") or {}
            _say(f"{r.name:36} {str(s.get('status')):10} {s.get('image_count',0)}/{s.get('requested_count',0):<3} {_clock(s.get('started_at') or s.get('created_at'))}")
        return 0
    if args.last:
        if not runs:
            _say("No runs yet")
            return 0
        show(runs[-1])
        return 0
    known = {r.name for r in runs}
    if runs and (_read_json(runs[-1]/"status.json") or {}).get("status") == "generating":
        _say(f"job {runs[-1].name} already generating — attaching")
        follow(runs[-1]); _say()
    while True:
        for r in _runs():
            if r.name not in known:
                known.add(r.name)
                follow(r); _say()
        time.sleep(POLL)

if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        _say("\nStopped watching. Generation keeps running in its own process.")
        raise SystemExit(130)

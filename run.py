"""
Start PRE's API server.

    python run.py        →  http://127.0.0.1:8000

Two things here are deliberate and easy to break by tidying:

1. **The event-loop policy below does not reach the app.** With `reload=True`
   uvicorn runs the application in a *child* process and installs
   `WindowsSelectorEventLoopPolicy` there before importing anything of ours, so
   neither this file nor `app/main.py` can win that race. A SelectorEventLoop
   cannot spawn subprocesses, which is exactly what Playwright's driver needs —
   that is where the old "Direct browser publish failed:" 500 with an empty
   reason came from (`str(NotImplementedError())` is `''`).

   The fix is not to fight the policy: the browser now runs in its own
   interpreter via `app.services.publish_runs.start_run` →
   `python -m scripts.publish_bg <run_id>`, which gets Windows' default Proactor
   loop. `app/services/pinterest_publisher._refuse_unless_proactor` raises a
   readable error if anything tries to launch a browser in here again. The policy
   line stays because a non-reload run (or a direct import) does honour it.

2. **The reloader watches `app/` only.** Watching the whole tree meant a publish
   run writing `data/publish_runs/<id>/status.json`, or a generation writing into
   `data/outputs/`, restarted the server mid-run. `scripts/` is excluded too: the
   child process is spawned per run, so it always picks up the current file
   without a server restart.
"""

import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=["app"],
        reload_excludes=["data/*", "vault/*", "frontend/*", "*.log", "*.json"],
        loop="asyncio",
    )

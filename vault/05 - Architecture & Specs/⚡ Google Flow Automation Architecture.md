---
aliases:
  - Google Flow Automator Architecture
  - Flow Engine Spec
tags:
  - architecture
  - flow
  - automation
  - playwright
created: 2026-08-21
updated: 2026-08-29
---

# ⚡ Google Flow Automation — Deep Architecture (2026-08-29)

> [!NOTE]
> **System Goal:** Free, automated, photorealistic 9:16 Pinterest image generation through Google Flow's web UI — no paid API key, no manual clicking. One submit produces 4 variations from the compiled 13-section brief + a pasted style-reference image.

This note supersedes the 2026-08-21 version, which described DOM-diff attribution and `taskkill /F /IM chrome.exe`. Both were replaced after they caused production incidents. What follows is the **current** engine, verified line-by-line against the code and the 11 real FAILED job records.

---

## 1. Call Path (as it actually runs)

```
[ Frontend: Generate button ]
        │  POST /api/jobs/{job_id}/generate  (writes prompt.txt, returns <0.1s)
        ▼
[ scripts/run_flow_bg.py ]            detached child process; status.json protocol:
        │                             generating → saving → done | error
        ▼
[ app/services/generation.py ]        generate_variations() — the ONLY entry point
        │  picks backend, verifies bytes on disk, normalises paths
        ▼
   AUTO_ORDER = (flow_ui, flow_api)
        │
   ┌────┴─────────────────────────────┐
   ▼                                   ▼
[flow_automator.py]              [flow_direct_api.py]
 Playwright + persistent         httpx replay of captured
 profile data/flow_profile       batchGenerateImages request
 (primary, never expires)        (expires ~15 min — one-shot artefact)
        │                                   │
        └──────────► data/outputs/<job>/flow_var_N.jpg
                              │
        [output_service.record_generation_outputs]
            JobOutput rows → pin drafts → vault nodes
```

`pollinations` exists as a backend but is **never in AUTO_ORDER** — it only receives a condensed prompt, so a silent fallback would downgrade the brief. It runs only when explicitly named (`?backend=pollinations`).

---

## 2. The Three Hard-Won Rules (module docstring, flow_automator.py)

These rules exist because each was violated once in production:

1. **Never read the DOM to decide which images are yours.** The canvas is a lazy list of *every* past generation; a baseline DOM diff undercounts and credits old renders. Job `908692a5` was credited with a forklift safety poster, a text card, an espresso machine and a skincare bottle. Attribution now comes **only** from the network response to our own submit (`_GenerationWatcher` + `flow_media.harvest_media`).

2. **Never touch the page directly.** Flow client-side redirects after load; a raw `page.evaluate` in that window dies with *"Execution context was destroyed"*. All evaluates go through `_safe_eval` (4 retries on transient nav errors), all gotos through `_goto_settled`.

3. **Never send a keystroke the page can read as a command.** The prompt bar is a contenteditable where **Enter = send**. `keyboard.type` submitted a 13-section prompt in 13 pieces (one render was a picture of the word "AVOID:"). Now: `flatten_prompt()` collapses to one line with ` | ` separators, and `browser_utils.insert_text()` delivers it via `keyboard.insert_text` / CDP `Input.insertText` — zero key events. `_enter_prompt` refuses any text containing `\n`.

Supporting rule from `flow_direct_api`: the capture is a **one-shot artefact** (reCAPTCHA Enterprise token single-use, OAuth ~1h). `CAPTURE_MAX_AGE_SECONDS = 900` refuses stale replays up front instead of spending a 90s request on a guaranteed rejection.

---

## 3. Failure History → Fix Map (the 11 FAILED jobs)

Every FAILED job in `data/pre.db` maps to a fix that is already in the current code:

| Symptom (from `failure_reason`) | Jobs | Current fix |
|---|---|---|
| `Illegal header name b':authority'` (flow_api) | 8d73c5b2 | `_sanitise_headers` drops HTTP/2 pseudo-headers + client-owned headers |
| `Execution context was destroyed … navigation` | 8d73c5b2, f0ad2809 | `_safe_eval` retry loop + `_TRANSIENT_EVAL_ERRORS` |
| `'Keyboard' object has no attribute 'insertText'` | 4d7e1f25 | `browser_utils.insert_text` uses `getattr` + CDP fallback (AttributeError is not a PlaywrightError, so it slipped past `except PlaywrightError`) |
| `256 of 2040 characters present` | b722c4fb | `flatten_prompt` + read-back verification in `_enter_prompt` |
| `Could not find prompt field` (fixed coords 640,750) | 0b1c8c23, 6258cb66, 1ec24a43 | `_find_prompt_box`: 8 selectors, 25s poll, scroll-to-bottom, size check |
| `Could not open a project workspace` | fdbb8bd4 | `_open_project`: router pool → remembered URL → dashboard discovery (30s poll) → New Project click |
| Wrong button clicked (`image` add-reference) | a5b8666e | `_JS_FIND_SUBMIT` scored candidates with `NOT_SEND` icon blacklist |
| 210s stall, submit never fired | 9fd8a273, 3642c415 | `_submit_landed` two-signal confirm (request left browser OR prompt bar cleared) + `NO_REQUEST_GIVE_UP_SECONDS = 45` |
| Signed-out profile misdiagnosed | (covered) | `_open_project` distinguishes signed-out from no-project and says so |

**Conclusion: the engine is not brittle-by-neglect — it is hardened. Every historical failure class has a structural fix.** Remaining failures would be *new* classes: a Google endpoint rename that dodges both the marker list and the captured-path cross-check, or account-level throttling.

---

## 4. Attribution Mechanics (the core innovation)

`_GenerationWatcher` attaches `request` + `response` listeners, but only **acts after `.arm()`**, which happens after the prompt is verified in the box and before submit:

- `looks_like_generation_url()` — path must match a generation marker (`generate`, `imagefx`, `texttoimage`) AND NOT a listing marker (`list`, `history`, `feed`, `batchget`, `getproject`…). The listing check wins on purpose: `ListGeneratedMedia` would otherwise match "generate" and hand over the whole canvas — the original bug wearing a different hat.
- Cross-check: `captured_generation_path()` from the 1-Time Session Capture is trusted as the operator's *real* endpoint even if Google renames paths.
- `harvest_media()` collects inline base64 (`encodedimage`, `bytesbase64encoded`…; JPEG/PNG/WebP magic prefixes; ≥ `MIN_IMAGE_BYTES = 5000`) and media URLs (`getMediaUrlRedirect`, `fifeUrl`…), order-preserved.
- Downloads use `page.request` (shares the context cookie jar = authenticated full-res fetch), with an in-page `fetch(credentials:'include')` fallback — never element screenshots.
- Failure diagnostics separate **"no request left the browser"** (submit problem) from **"request sent, unrecognised answer"** (endpoint rename) — `_attribution_diagnostics`.

Timeout model: `GENERATION_TIMEOUT_SECONDS = 210`, grace of 25s after first media, give-up at 45s if no generation request left the browser.

---

## 5. Google Flow — The Product (researched 2026-08-29)

| Aspect | Fact |
|---|---|
| What it is | Google's AI creative studio (labs.google/fx/tools/flow, a.k.a. flow.google), launched 2025-05-20 at I/O as the evolution of VideoFX |
| Models | **Veo 3.1** (video), **Imagen / "Nano Banana"** (text-to-image — what this system uses), **Gemini** (prompt understanding) |
| Image features this system relies on | Text-to-image batch of 4; **ingredients** = pasted reference image for style/subject consistency (the `_paste_reference_image` flow) |
| Other product features | Scenebuilder, Camera Controls, Asset Management, Flow TV (prompt showcase) — all video-side, unused here |
| Pricing | No separate subscription. Bundled in Google AI plans: Plus $7.99 (~200 credits/mo), Pro $19.99 (~1,000 credits/mo), Ultra $100–200 (up to ~12,500 credits/mo). Credits are shared across Gemini/Veo/Flow |
| Credit cost | Video: ~20 (Fast) to ~100 (Quality) credits. Images are far cheaper per generation than video. Free tier = Veo 2, limited |
| Endpoint (observed) | `aisandbox-pa.googleapis.com/v1/projects/<id>/flowMedia:batchGenerateImages` |
| Availability | US-first, expanding; requires Google login (held in `data/flow_profile`) |

**Strategic implication:** the system rides a consumer UI with a monthly credit pool. That means (a) credits are the real budget, not time; (b) Google can rename/change the UI at any time — the network-attribution + captured-path design is the right hedge; (c) heavy volume would eventually be cheaper on the paid Veo/Imagen API, but for free-tier operation the UI path is correct.

---

## 6. Live State Snapshot (2026-08-29)

- Jobs: 19 DRAFT, 12 ANALYZED, 12 PASS, 19 OUTPUT_UPLOADED, **11 FAILED** (all pre-fix failure classes), **9 stuck GENERATING** (no reaper).
- Outputs: 115 rows in `job_outputs`.
- Project pool: 10 workspaces in `data/flow_projects.json`, round-robin via `flow_router`.
- Captured session: present but ancient (captured 2026-08-20) → flow_api backend permanently unavailable until re-capture; flow_ui carries everything.
- Persistent profile: `data/flow_profile` alive and logged in.

---

## 6b. 2K Upsampling (implemented 2026-08-29)

Flow's UI offers **Download (2K)** on every image — a server-side upsampler, not
a bigger fetch. The engine now uses it on every run:

```
batchGenerateImages response
   └─ media[i].name                                 ◄── resource name (NEW, see below)
   └─ media[i].image.generatedImage.mediaGenerationId   ◄── old id field (gone)
        └─ POST https://aisandbox-pa.googleapis.com/v1/flow/upsampleImage
           {"mediaId": "<mediaGenerationId or resource-name segment>",
            "targetResolution": "UPSAMPLE_IMAGE_RESOLUTION_2K",
            "clientContext": {"sessionId": ";<ms>", "projectId": "...", "tool": "PINHOLE"}}
                └─ response {"encodedImage": "<base64 JPEG>"}  → saved as flow_var_N.jpg
```

> **2026-08-29 evening — Flow renamed the id field.** Live responses no longer
> carry `mediaGenerationId` anywhere. Key outline from job 82956521:
> `{media: [{name, workflowId, image: {generatedImage, dimensions}}], workflows:
> [{name, metadata: {…, primaryMediaId, …}, projectId}]}`. `harvest_variations`
> now resolves the id as: inner `mediaGenerationId` → subtree search of the
> media entry → the entry's resource `name`. `flow_upscale.media_id_candidates`
> offers the upsampler the bare path segment first, then the full resource
> name. See the debugging lessons in section 6c.

- **Auth reuse (flow_ui):** `_GenerationWatcher._capture_request_auth` stashes the
  generation request's `authorization` header + `projectId` + derived API base
  (everything before `/projects/`). The upsample goes out via `page.request`, so
  the profile's cookies ride along. No reCAPTCHA token is re-sent (the captured
  one is single-use) — a 403 just falls back.
- **Auth reuse (flow_api):** the captured session's headers are replayed over
  httpx, same payload.
- **Original-image fallback:** any upsample failure (403 plan gate, timeout,
  missing id) silently uses the render-resolution bytes — an upsample can never
  cost a variation. `4K` is gated to paid Google AI plans; Google reports the
  gate as a reCAPTCHA rejection, so a persistent 403 means "plan", not "captcha".
- **Knob:** `FLOW_UPSCALE_RESOLUTION` in .env → `2k` (default), `4k`, `none`.
- **Watermark crop now scales:** the anti-AI bottom crop was fixed 120px —
  calibrated on ~1376px renders. It is now proportional (~8.7% of height, even-
  aligned for yuv420p): 1376px → 120px (unchanged), 2K → ~240px, thumbnails
  stop losing a fifth of the frame.
- New shared module: `app/services/flow_upscale.py` (no playwright/httpx imports
  at module level — callers inject an executor, same rule as `flow_media`).
- `flow_media.harvest_variations()` pairs each variation's id with its
  bytes/URL; the flat `harvest_media` is unchanged and remains the fallback.

Before: variations were 768×1376 or worse (312×556 thumbnails). After: ~2K on
the long edge whenever the upsampler answers, render resolution otherwise.

---

## 6c. Debugging lessons from the 2026-08-29 upscale rollout

Four live runs to find one renamed field. What each round cost and taught:

1. **Silent fallback hid everything.** `upscale_to_bytes` never raises and
   reported only via `logger.info` — and the BG job console captures stdout
   (`print`) only, so the reasons went nowhere. Rule: *any failure worth
   diagnosing in a background path must `print()`.* `upscale_to_bytes` now
   takes an `on_failure` hook; both backends raise with the HTTP status +
   300-char body snippet.
2. **A "count of records" log masqueraded as a "count of ids".** The old
   "4 with media ids" line counted variation records, all of which had
   `media_id=None`. Diagnostics must count the thing they claim to count:
   the line now reads "X of Y variation records carry a media id".
3. **Don't guess where a field lives — outline the payload.** Two explicit
   level-guesses (inside `generatedImage`; beside `image`) both missed
   because Google had *renamed* the field to `name`. The fix that worked:
   print `describe_shape(payload)` (keys only — payloads hold tokens and
   signed URLs) and read the truth. Subtree search + `name` fallback now
   covers every observed shape.
4. **Verify the artifact, not the log claim.** The save line's `via` tag is
   the claim; pixel dimensions of `data/outputs/<job>/flow_var_N.jpg` are
   the proof (render-res ≈768 wide, 2K ≈1400+).
5. **Confirm the fix is actually loaded.** Generation runs inside the
   uvicorn server process; the OneDrive path makes the reloader flaky. Check
   the start time of the PID listening on :8000 before concluding a code
   change was live for a run.

---

## 7. Remaining Weaknesses (not yet failing, but real)

1. **No retry/reaper.** FAILED is terminal; GENERATING has no sweep. A transient browser crash strands a job forever.
2. **No credit awareness.** The engine spends from a monthly pool it never counts. No log of credits/generation, no low-credit warning, no plan-tier config.
3. **flow_api window never refreshes.** A capture is good for 15 min and is only made by a manual script. The automator already watches the network — it could re-harvest the live generation request and rewrite the capture after every successful UI run (self-refreshing fast path).
4. **Fixed 35s reference-image wait.** `_paste_reference_image` sleeps a flat 35s regardless of when the chip actually embeds. Poll for the chip instead.
5. **Serial execution.** One job, one browser, one project at a time. The 10-project pool spreads canvas bloat but not throughput.
6. **No quality/model knob.** Flow has Fast/Quality tiers; the automator always submits at the UI default. No way to say "cheap draft" vs "final".
7. **Prompt-length cap only warned.** At 80% of the read-back it prints a warning but sends anyway; a hard cap from Flow truncates silently.
8. **Marker-list drift risk.** Attribution depends on URL markers + captured path. A rename that matches neither fails safe (no mis-attribution) but still fails the run.

---

## 8. Upgrade Roadmap (prioritised)

| # | Upgrade | Value | Effort | Touches |
|---|---|---|---|---|
| U1 | **Self-refreshing capture**: after a successful flow_ui run, persist the observed generation request (url/headers/payload shape minus per-run ids) to `captured_flow_session.json` → flow_api becomes a permanent fast path | ★★★★★ | Medium | flow_automator, flow_media |
| U2 | **Job reaper + retry queue**: sweep GENERATING > N min → FAILED; allow re-queue of FAILED with backoff | ★★★★★ | Low-Med | scheduler, jobs API |
| U3 | **Credit ledger**: count generations/day/month, persist, expose in UI; warn at plan threshold | ★★★★ | Low | generation, new table, frontend |
| U4 | **Chip-poll reference upload**: replace flat 35s with poll-for-chip (saves ~20s/job, removes a race) | ★★★ | Low | flow_automator |
| U5 | **Quality tier knob**: `?quality=fast|quality` threaded to the Flow UI model picker | ★★★ | Med | generation, flow_automator |
| U6 | **Parallel project workers**: N browser contexts across the pool with per-account rate limiting | ★★ | High (throttle risk) | flow_router, automator |
| U7 | **Endpoint-rename sentinel**: alert when request-sent-but-unrecognised-answer occurs twice in a row | ★★ | Low | watcher diagnostics |

U1 is the standout: it converts the engine's own network watcher into a credential refresher, eliminating the manual re-capture chore and making the 15-minute flow_api window effectively permanent.

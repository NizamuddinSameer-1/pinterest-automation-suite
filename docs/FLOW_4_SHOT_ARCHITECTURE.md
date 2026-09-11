# Google Flow — 4-Shot Diversity Architecture

> Research + implementation reference for turning one product into 4 **intentionally
> different** images (not 4 angles of the same scene) using Google Flow.
>
> Researched 2026-09-11 against: Google's official Flow product page & Flow update
> blogs (Nov 2025, Feb 2026), Google's official Gemini image-generation docs,
> Google's Flow tips blog, and the documented Flow image API surface.

---

## Part 1 — How Flow actually produces "4 images"

### The mechanism

Flow's image mode runs on the **Nano Banana** family. When you submit one prompt,
Flow sends **one prompt string with a `count` parameter of 1–4 (default 4)** and
returns that many candidates in a `media` array.

```
POST /images
{ "model": "nano-banana-2", "prompt": "<one prompt string>", "count": 4, "aspectRatio": "9:16" }
→ media[0..3]   ← 4 independent samples of the SAME prompt
```

**This is the root cause of your problem.** The 4 images are 4 *stochastic
neighbours* of one prompt. They are not 4 interpretations of 4 instructions. The
sampler converges on the most probable reading of your prompt, then jitters around
it — hence "4 slightly different camera angles of the same scene."

### There is no diversity control

Google's own image-generation documentation is explicit: **composition, camera
angle and lighting are controlled only through prompt text.** There is no
`variation_strength`, no `shot_type`, no `diversity` parameter. The only knobs are:

| Parameter | Values | Notes |
|---|---|---|
| `count` | 1–4 (default 4) | Candidates per request |
| `seed` | integer | Reproducibility. Same seed + same prompt ⇒ same image |
| `model` | `nano-banana-2-lite`, `nano-banana-2`, `nano-banana-pro` | See below |
| `aspectRatio` | `16:9`, `4:3`, `1:1`, `3:4`, `9:16`, `auto` | `auto` only in image-to-image, NB2/Pro |
| `reference_1..10` | media IDs | NB2/Pro max 10 |
| `character_1..7` | character IDs | Reusable identities |

**Consequence:** you cannot prompt your way into 4 distinct shots inside a single
`count=4` request. You must **submit 4 requests.** That is the whole architecture.

### Model lineup (current)

| Model | Underlying | Best for | Speed |
|---|---|---|---|
| `nano-banana-2-lite` | Gemini 3.1 Flash-Lite Image | High-volume iteration (default since Jul 2026) | Fastest |
| `nano-banana-2` | Gemini 3.1 Flash Image | Balanced, most dynamic interpretations | Fast |
| `nano-banana-pro` | Gemini 3 Pro Image | **Highest fidelity + most literal instruction-following** | Slowest (up to ~2 min) |

> ⚠️ **Imagen was removed from Flow in July 2026.** The `imagen-4` ID now aliases to
> `nano-banana-2-lite`. Any code or doc still referring to Imagen/Veo 2 is stale.

**For product photography, use `nano-banana-pro`.** It is the only model that
reliably renders fine detail (stitching, hardware, label text) and follows
instructions literally. Use `-lite` only for cheap first-pass exploration.

### Other facts that matter for your pipeline

- **`@`-mentions** — Flow lets you reference library assets inline with `@`, plus
  Collections and an asset grid. This is the Flow-native way to pin the product
  reference without re-uploading.
- **Reference limits** — up to 10 references on NB2/Pro; up to 14 object refs on
  Flash Lite via the Gemini API (6 objects + 5 characters + 3 styles on Pro).
- **Upscale** — `POST /images/upscale` with `resolution` `2k` (default) or `4k`.
  **4K requires a paid Google account.** Imagen/legacy IDs cannot be upscaled.
- **SynthID** — every generated image carries a Google SynthID watermark.
- **Moderation** — requests can be silently rejected (empty results). Each model
  moderates slightly differently; retry, reword, or switch model.
- **Free tier** — image generation in Flow is free; paid is needed for video and 4K.

---

## Part 2 — The architecture: 3 blocks, 4 requests

The professional pattern (validated across commercial AI-photography workflows) is
**not a better prompt — it is a better workflow.** Separate the prompt into
invariant and variable blocks, then issue one request per shot.

```
┌──────────────────────────────────────────────────────────────┐
│ BLOCK A — PRODUCT PASSPORT            (byte-identical ×4)    │
│   shape · material · colour · hardware · label · silhouette   │
├──────────────────────────────────────────────────────────────┤
│ BLOCK B — WORLD / VIRTUAL SET         (locked family ×4)     │
│   lighting rig · palette · lens & film character · mood       │
├──────────────────────────────────────────────────────────────┤
│ BLOCK C — SHOT DIRECTIVE              (UNIQUE per shot)      │
│   shot 1 lifestyle │ 2 flat-lay │ 3 macro │ 4 environment     │
└──────────────────────────────────────────────────────────────┘
        A + B + C₁  →  request 1  (count=1, seed₁)
        A + B + C₂  →  request 2  (count=1, seed₂)
        A + B + C₃  →  request 3  (count=1, seed₃)
        A + B + C₄  →  request 4  (count=1, seed₄)
```

**Why blocks A and B must be byte-identical:** the model has no memory between
requests. Any rewording — even `studio lighting` → `professional lighting` — shifts
the output and the four shots stop reading as one shoot. Copy-paste them literally.

**Why Block C must be one shot, not four:** if you enumerate four shots inside one
prompt, the sampler still produces four *neighbours of the merged description*. It
does not partition them. One shot per request is the only reliable mechanism.

---

## Part 3 — The four shot archetypes

These four cover the standard ecommerce/marketplace slot set and map 1:1 onto
Pinterest's needs (lifestyle → save-driven, macro → detail-driven, context →
inspiration-driven, flat-lay → clean repin).

### Shot 1 — LIFESTYLE / ON-MODEL

Purpose: the viewer imagines themselves using it. Drives saves.

```
SHOT TYPE: candid lifestyle photograph, product in genuine use.
SUBJECT ACTION: <in-use verb> — the product being worn / held / used naturally.
CAMERA: medium shot, handheld at chest height, 35–50mm equivalent, slight
  over-the-shoulder or three-quarter angle. Shallow depth of field.
LIGHTING: <warm window light from the side | golden hour | soft diffused daylight>.
COMPOSITION: subject occupies right third; lived-in environment softly out of focus.
MOOD: unposed, warm, aspirational-but-real.
```

### Shot 2 — EDITORIAL / FLAT-LAY

Purpose: the clean hero. Shows silhouette and true colour. Drives repins.

```
SHOT TYPE: editorial flat-lay, no human presence.
ARRANGEMENT: product laid flat, <diagonal placement | asymmetric grid>, styled with
  <2–3 complementary props>.
CAMERA: direct overhead 90°, perfectly level, 50mm equivalent, deep focus.
LIGHTING: soft diffused overhead key, gentle fill, soft even shadows.
SURFACE: <textured surface that contrasts the product material>.
MOOD: calm, considered, catalogue-grade.
```

### Shot 3 — MACRO / DETAIL

Purpose: proves quality. Answers "is this well made?" Kills the AI-plastic read.

```
SHOT TYPE: extreme close-up detail photograph.
FOCUS TARGET: <stitching / weave / hardware / label / texture / mechanism>.
CAMERA: 100mm macro equivalent, 1:1 magnification, razor-thin depth of field
  with creamy falloff, focus on the single most tactile feature.
LIGHTING: raking side light at 45° to reveal surface relief and fibre structure.
MOOD: tactile, honest, luxury-grade.
```

### Shot 4 — CONTEXT / ENVIRONMENT

Purpose: shows where it lives. Sells the lifestyle, not the object.

```
SHOT TYPE: environmental still-life, product in its real-world setting.
SETTING: <the room/place the product belongs to, described concretely>.
CAMERA: eye-level or slightly elevated 3/4 angle, 35mm equivalent, medium depth
  of field so the setting stays readable.
LIGHTING: ambient light of that place, plus one directional accent.
STAGING: 3–5 believable props, some partially cropped by frame edge, natural
  asymmetry — nothing centred or symmetrical.
MOOD: lived-in, aspirational, editorial interior.
```

### Optional shots 5–8 (for full campaign coverage)

| # | Archetype | Sells |
|---|---|---|
| 5 | Scale / in-hand | Size honesty |
| 6 | Packaging / unboxing | Gifting + perceived value |
| 7 | Group / collection | Bundle or variant upsell |
| 8 | Motion / in-action | Energy, dynamic ads |

---

## Part 4 — Niche-agnostic design

The four archetypes are universal. Only **four slots** change per niche. Everything
else in the template is fixed — that is what makes it scale.

| Niche | In-use verb (Shot 1) | Detail target (Shot 3) | Surface (Shot 2) | Setting (Shot 4) |
|---|---|---|---|---|
| Apparel | worn, mid-movement | stitch, weave, hem, hardware | linen / raw wood | changing room, bedroom, street |
| Accessories | carried, worn on wrist | clasp, grain, edge-paint | marble / slate | café table, car interior |
| Home goods | in use in the room | glaze, joinery, weave | oak / concrete | styled living room, kitchen |
| Electronics | held / plugged in / on desk | port, mesh, chamfer, LED | matte desk / slate | workspace, bedside, commute |
| Beauty | applied / held to face | dropper, texture, cap thread | glass / stone | vanity, bathroom shelf |
| Food | poured / plated / served | crumb, drip, label | stone slab / board | rustic table, café |

### Material-specific lighting rules (put these in Block B)

| Material | Lighting | Prompt phrase |
|---|---|---|
| Glass / transparent | Soft backlight | "soft backlight from behind, glowing through the liquid" |
| Metal / chrome | Large soft source, no hotspots | "large softbox upper-left, no harsh specular hotspots" |
| Matte surfaces | Directional side light | "side light from the left at 45°" |
| Fabric / leather | Raking side light | "directional side light raking across, revealing texture" |
| White products | Soft even light | "soft even lighting with subtle shadow definition" |
| Food | Side or backlight, warm | "warm side lighting" |

---

## Part 5 — Submission protocol (Flow-specific)

1. **Set the reference first.** Paste/select the product image as an Ingredient (or
   `@`-mention the library asset). Reference-anchored generation is dramatically
   more product-faithful than text-only. Use 1 main view + 1 detail view if you have
   both; 3 references is the sweet spot, more can conflict.
2. **Model:** `nano-banana-pro` for final output, `nano-banana-2-lite` for exploring.
3. **One request per shot.** `count = 1`.
4. **Distinct seed per shot** (e.g. 101, 202, 303, 404). Record it — a re-run with
   the same prompt + seed reproduces the exact image.
5. **Aspect ratio per shot purpose**, not one ratio for all:
   - Lifestyle / context → `4:5` or `9:16` (Pinterest-native)
   - Flat-lay / macro → `1:1`
   - Environment wide → `16:9` or `3:4`
6. **Wait between submissions.** `POST /images` is synchronous and takes 20–60s;
   Pro can hit ~2 min under load. Serialise, don't fire all four at once.
7. **Upscale** the keepers via `/images/upscale` at `2k` (or `4k` on a paid plan).
8. **Budget for rejections.** Moderation returns empty results intermittently —
   retry once, then reword. Roughly 15–20% of generations get discarded in
   production workflows; plan for it.

### Fallback trick — the contact-sheet prompt

If you need one request instead of four, ask for a **multi-panel layout in a single
image** and crop it yourself:

```
A 2x2 editorial contact sheet of <product>, four panels on one canvas:
top-left a lifestyle shot of it in use; top-right an overhead flat-lay;
bottom-left a macro of <detail>; bottom-right it styled in <setting>.
Consistent lighting and colour across all four panels, thin white gutters.
```

**Trade-offs:** cheaper and faster, panels share one coherent look, but each panel
gets ~¼ the resolution, the model frequently bleeds elements between panels, and
gutters are not reliably straight. Treat as a fast concepting tool, **not** as the
production path. This is also what Flow's **Grid Architect** tool is built around.

---

## Part 6 — Wiring this into the existing pipeline

**Status: implemented.** This part describes what was actually built, which differs
from the first sketch in one important way — see "What changed from the sketch".

### Before

```
scene_director.variation_for(class, seed)  →  ONE axis set
        ↓
prompt_compiler.compile_prompt()           →  ONE prompt (6 axes listed inside it)
        ↓
flow_automator types ONE prompt            →  count=4 → flow_var_1..4.jpg
```

Structurally guaranteed to give four near-identical images: `count=4` is four
stochastic samples of one string.

### After

```
scene_director.variation_for(class, seed)  →  ONE axis set  (the job's "world")
        ↓
prompt_compiler.compile_shot_set()         →  FOUR prompts, one per archetype
        ↓
flow_automator.generate_flow_shots_automated()
        ↓
4 × (enter prompt → baseline canvas → arm watcher → submit → wait → harvest)
        ↓
shot_1_lifestyle_1.jpg … shot_4_environment_1.jpg
```

### The pieces

| File | What it does |
| --- | --- |
| `app/pipeline/shot_archetypes.py` | The four archetypes (camera, framing, lighting, composition, mood, aspect ratio, whether a human appears), the per-class slot table (`_NICHE`, 23 classes + `generic` fallback), and the Block C directive builder. |
| `prompt_compiler.compile_prompt(..., shot_archetype=...)` | Emits that archetype's camera/framing/crop/human-presence/lighting and its Block C, and **replaces** the six-axis block. `shot_archetype=None` keeps the original behaviour exactly. |
| `prompt_compiler.compile_shot_set(...)` | Returns all four `CompileResult`s. Inputs are never mutated. |
| `flow_automator.generate_flow_shots_automated(...)` | One browser session, one serial submission per shot, a fresh `_GenerationWatcher` per shot. |
| `flow_automator.ShotRequest` / `ShotResult` | The in/out types for the multi-shot runner. |
| `generation.generate_shot_set(...)` | Coordinator: verifies the produced files, tolerates partial success, reports a `produced_by` of `flow_ui (multi-shot)`. |
| `generation.compile_shot_requests(job_id)` | DB → shot prompts, using the same rows and product mapping as the compile endpoint. |
| `scripts/run_flow_bg.py` | Opt-in branch behind `GENERATION_MULTI_SHOT`. |

### Enabling it

```
GENERATION_MULTI_SHOT=true          # in .env — off by default
GENERATION_MULTI_SHOT_PER_SHOT=1    # images per archetype (2 gives a spare render)
```

Multi-shot mode costs **four submissions instead of one**, so a run takes roughly
four times as long and uses four times the Flow quota. That is why it is off by
default: turning the flag off restores the previous single-prompt behaviour with no
other change. Only the browser backend (`flow_ui`) can do it — `flow_api` replays a
single captured request and `pollinations` takes a single prompt, and neither has a
multi-submit runner. Requesting multi-shot with those backends logs a warning and
falls back rather than silently returning four samples of one prompt.

### What changed from the sketch

The original plan was to call `variation_for()` once per archetype and keep the
six-axis block. That is **not** what was built, for two reasons:

1. The six-axis block names *one* camera angle and *one* lighting setup. Keeping it
   alongside an archetype directive makes the two fight — a flat lay cannot be
   "handheld at chest level". The directive **replaces** the block.
2. The archetypes already carry the between-shot difference, and they carry it better
   than a seeded axis draw does: a macro shot needs raking 45° side light because it
   is a macro shot, not because a hash said so.

So the division of labour is:

* **`variation_for` (six axes)** → the job's *world*: colour grade and aesthetic,
  which are restated inside every shot block so the set reads as one photoshoot.
* **The archetype** → the *shot*: camera, framing, crop, human presence, lighting
  direction, Block C.

`prompt_modules` still reads `scene["framing"]` and `scene["human_presence"]`, so
the archetype writes those into a **copy** of the scene. That is what makes the hand
modules appear on the lifestyle shot and vanish from the macro shot.

### A related bug this exposed

`_humanize()` maps the bare enum token `medium` → `moderate` (correct for
`material_dna.texture_visibility`). It was also being applied to `framing`, so every
prompt in the system said **"moderate framing"** instead of "medium framing".
Framing now has its own pass (`_humanize_framing`) with the real vocabulary
(`macro | tight | medium | wide`).

### Why not just enumerate four shots in the one prompt?

Because `count=4` samples one prompt independently. Each sample reads the whole
merged description and converges on the most probable single reading — it does not
assign one instruction per sample. You get four neighbours of the average, which is
precisely the symptom being reported.

### Verification

`scripts/audit_prompt_system.py` gained a fourth check for this. It recompiles a real
job and asserts the four prompts are distinct, share a byte-identical product
passport, that human presence appears only on the lifestyle shot, that the six-axis
block is gone from shot prompts, and that single-prompt mode still emits it.

`scratch/verify_shot_set.py` additionally proves the single-prompt path is
**byte-identical** to a pre-archetype baseline built from git HEAD plus the earlier
bugfix patch, across six real jobs.

### Known gap — aspect ratio is prompt text only

`shot_archetypes` assigns 4:5 / 1:1 / 1:1 / 9:16, and each prompt states its ratio in
a `FRAME:` line. But **the automator never sets Flow's `aspectRatio` parameter** — it
types a prompt and clicks submit, and nothing in the codebase touches `aspectRatio`.
So the ratios are a prompt instruction, not an API guarantee. Setting the real
parameter needs UI automation of Flow's aspect-ratio control, which has not been
built or verified against the live UI.


### Why not just enumerate four shots in the one prompt?

Because `count=4` samples one prompt independently. Each sample reads the whole
merged description and converges on the most probable single reading — it does not
assign one instruction per sample. You get four neighbours of the average, which is
precisely the symptom being reported.

---

## Sources

- Google Flow — official product page (models: Nano Banana, Veo 3.1, Gemini Omni) — `flow.google`
- Google, *5 tips for using Flow* (Jun 2025) — `blog.google/innovation-and-ai/products/flow-video-tips/`
- Google, *Flow gets new ways to refine and edit videos* (Nov 2025) — Nano Banana Pro controls: depth of focus, lighting, colour grading; edit pose/angle without re-rolling
- Google, *Flow updates* (Feb 2026) — image-first redesign, Nano Banana core, `@`-mentions, Collections, free image generation
- Google, *Nano Banana image generation* docs — official prompt templates, 14-reference limits, no `n`/`seed` params documented, SynthID
- useapi.net, *Google Flow images* — documented `count` 1–4 (default 4), `seed`, `aspectRatio`, `reference_1..10`, `/images/upscale` 2k/4k
- useapi.net, *Nano Banana model comparison* — Imagen removed Jul 2026; model positioning and speed
- Commercial workflow write-ups (Kolbo Creative Director, MyUP "virtual set" method, Graswald "Views") — invariant-block + per-shot-prompt pattern

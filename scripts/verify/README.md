# Offline verification checks

Nine scripts that check the parts of PRE that used to lie about their own results.
They import nothing from PyPI (they stub `app.config` and use AST analysis), so they
run on a bare Python 3.11+ with no dependencies installed and no network.

```bash
python scripts/verify/verify_compiler.py         # prompt compiler: sanitizer scope + trend anchor
python scripts/verify/verify_states.py           # job state machine + vault-sync neutrality
python scripts/verify/verify_static.py           # imports, settings.*, fabricated-success patterns
python scripts/verify/verify_subject_match.py    # reference and product must describe the same thing
```

Each prints `FAILURES: none` when clean; `verify_static.py` also exits non-zero on failure,
so it can go straight into a pre-commit hook or CI step.

What they guard against, concretely:

- `verify_compiler.py` — the compiler must not strip its own negative constraints
  (`anti-cinematic`, `cinematic lighting`) while still scrubbing banned keywords that
  arrive in *data*, and `trend_label` must actually reach the prompt.
- `verify_states.py` — the happy path and the rework loop must both be walkable, the old
  `OUTPUT_UPLOADED -> PASS` shortcut must stay illegal, every state must be reachable,
  `FAILED` must be reachable from every non-terminal state, and vault notes must not
  default to a hardcoded seasonal campaign.
- `verify_static.py` — every `from app.x import y` resolves, every `settings.<attr>`
  exists on `Settings`, and no fabricated-success pattern has crept back in: on the Python
  side `pin_live_`, `(using fallback)`, writing `PASS` without a critique,
  `lstrip("data/")`, a synthesised `/pin/published-<ts>/` URL; on the frontend side
  "Published to Pinterest live!", "Pin is now active", the invented board
  "Seasonal Trends & Aesthetic Finds", and hardcoded Halloween defaults. Comment lines are
  skipped, since the fixes deliberately document what they replaced.
- `verify_subject_match.py` — a reference photograph and a product that are different
  kinds of object must not be combined silently. Uses the real ghost-lamp analysis: it
  must classify as `home_decor`, every seeded product must block against it, near
  neighbours (costume vs apparel) must be reported but allowed, and nothing undecidable
  (no analysis, GENERIC, low confidence) may block. Also checks the drafter turns that
  photograph into a product whose PRESERVE list describes the lamps and invents no price,
  merchant or affiliate URL, and that the wiring holds: the guard runs before the scene
  director, the override is per-run, and the Creative Lab no longer pre-selects a product.

These do **not** replace a real run. Booting FastAPI, touching the database, and driving
Playwright all need the actual dependencies:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

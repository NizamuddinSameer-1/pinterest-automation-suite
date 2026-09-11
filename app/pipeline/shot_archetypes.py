"""
Shot Archetypes — the four distinct photographs one product should produce.

WHY THIS EXISTS
───────────────
Google Flow's image generation takes ONE prompt string and a `count` parameter
(1–4, default 4). Those four outputs are four *stochastic samples of the same
prompt* — the sampler converges on the most probable reading of the string and
then jitters around it. That is why one submission produced "four slightly
different camera angles of the same scene": it is structurally what count=4 does,
not a prompt-writing failure.

There is no diversity control in Flow. Google's own image-generation docs confirm
composition, camera angle and lighting are settable only through prompt text.
So **N genuinely distinct shots requires N separate submissions**, each with its
own prompt and `count=1`.

This module supplies the four prompts. They follow the three-block model that
commercial AI-photography workflows converge on:

    BLOCK A  product passport      — locked, byte-identical across all four shots
    BLOCK B1 world / film character— locked (colour grade, palette, aesthetic)
    BLOCK B2 lighting per shot     — varies, because each shot type needs its own light
    BLOCK C  shot directive        — unique per shot

A + B1 stay byte-identical so the four images read as one photoshoot rather than
four unrelated experiments. C is what makes them serve four different jobs.

The four archetypes map onto the standard marketplace/ecommerce slot set and onto
Pinterest's save drivers: lifestyle (saves), flat-lay (repins), macro (quality
proof), environment (inspiration).

NICHE-AGNOSTIC BY CONSTRUCTION
──────────────────────────────
The archetypes are universal. Only five slots change per product class — the
in-use verb, the detail target, the flat-lay surface, the setting, and the props.
Those live in `_NICHE`, keyed by `product_taxonomy.CLASSES` key, with a `generic`
fallback so an unrecognised class still gets a sensible set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ─────────────────────────────────────────────────────────────────────
# The four archetypes
# ─────────────────────────────────────────────────────────────────────

#: Submission order. Lifestyle leads because it is the highest-saving shot.
SHOT_ORDER: tuple[str, ...] = ("lifestyle", "flat_lay", "macro", "environment")


@dataclass(frozen=True)
class ShotArchetype:
    """One deliberately different photograph."""

    key: str
    label: str
    purpose: str          # what this shot is FOR — drives the marketing slot
    aspect_ratio: str     # Pinterest-native where it matters
    camera: str           # camera body / lens / position
    framing: str          # macro | tight | medium | wide
    camera_height: str    # where the camera sits, for the compiler's camera block
    camera_pos: str       # how it is held or supported
    lighting: str         # this shot type's own light — deliberately not shared
    composition: str
    mood: str
    wants_human: bool     # whether a person should appear


ARCHETYPES: dict[str, ShotArchetype] = {
    "lifestyle": ShotArchetype(
        key="lifestyle",
        label="Lifestyle / in use",
        purpose="show the product in genuine use so the viewer pictures themselves with it",
        aspect_ratio="4:5",
        camera=(
            "medium shot, handheld at chest height, 35–50mm equivalent, "
            "slight three-quarter angle, shallow depth of field"
        ),
        framing="medium",
        camera_height="at chest height",
        camera_pos="handheld",
        lighting="warm directional window light from the side, soft natural falloff",
        composition=(
            "subject occupies the right third; the environment falls softly out of "
            "focus behind them; natural unposed posture, nothing centred or symmetrical"
        ),
        mood="unposed, warm, aspirational but real — a photo a real person would share",
        wants_human=True,
    ),
    "flat_lay": ShotArchetype(
        key="flat_lay",
        label="Editorial / flat lay",
        purpose="clean hero shot — silhouette and true colour, no human presence",
        aspect_ratio="1:1",
        camera=(
            "direct overhead 90°, perfectly level, 50mm equivalent, deep focus, "
            "no perspective distortion"
        ),
        framing="wide",
        camera_height="directly overhead",
        camera_pos="held perfectly level on a support",
        lighting="soft diffused overhead key with gentle fill and soft even shadows",
        composition=(
            "product laid flat on a diagonal axis with deliberate negative space; "
            "two or three complementary props placed asymmetrically"
        ),
        mood="calm, considered, catalogue-grade",
        wants_human=False,
    ),
    "macro": ShotArchetype(
        key="macro",
        label="Macro / detail",
        purpose="prove the quality and craft — the detail that kills the AI-plastic read",
        aspect_ratio="1:1",
        camera=(
            "100mm macro equivalent, 1:1 magnification, razor-thin depth of field "
            "with creamy optical falloff"
        ),
        framing="macro",
        camera_height="at macro working distance",
        camera_pos="braced steady",
        lighting="raking side light at 45° to reveal surface relief and fibre structure",
        composition=(
            "frame filled by the single most tactile feature; focus plane on that "
            "detail alone; everything else dissolves into natural bokeh"
        ),
        mood="tactile, honest, luxury-grade",
        wants_human=False,
    ),
    "environment": ShotArchetype(
        key="environment",
        label="Context / environment",
        purpose="show where the product lives — sells the lifestyle, not the object",
        aspect_ratio="9:16",
        camera=(
            "eye-level or slightly elevated three-quarter angle, 35mm equivalent, "
            "medium depth of field so the setting stays readable"
        ),
        framing="medium",
        camera_height="at eye level or slightly above",
        camera_pos="handheld",
        lighting="the ambient light of that place plus one directional accent",
        composition=(
            "product placed off-centre in a wider frame; three to five believable props, "
            "some partially cropped by the frame edge; natural lived-in asymmetry"
        ),
        mood="lived-in, aspirational, editorial interior",
        wants_human=False,
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Per-class slots — the only thing that changes between niches
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NicheSlots:
    """The five values that make the archetypes niche-specific."""

    in_use: str       # the in-use verb / moment, for the lifestyle shot
    detail: str       # the macro focus target
    surface: str      # the flat-lay surface
    setting: str      # the environment shot's location
    props: str        # 2–3 props for the flat lay and environment shots


_NICHE: dict[str, NicheSlots] = {
    "apparel": NicheSlots(
        in_use="worn naturally, mid-movement, the fabric moving with the body",
        detail="the fabric weave, the stitch line, and the hem finish",
        surface="washed linen",
        setting="a sunlit bedroom with a chair in the corner and a mirror on the wall",
        props="a folded knit and a pair of sunglasses",
    ),
    "footwear": NicheSlots(
        in_use="on the feet, one foot slightly forward, weight settled naturally",
        detail="the sole tread, the stitch line, and the leather grain",
        surface="pale worn concrete",
        setting="an entryway with a doormat and a coat hanging on a hook",
        props="a canvas tote and a set of keys",
    ),
    "bags": NicheSlots(
        in_use="carried on the shoulder, the bag settling into its natural shape",
        detail="the hardware, the stitch line, and the grain of the leather",
        surface="a wooden bench top",
        setting="a hallway with a coat on a hook and a mirror beyond",
        props="a folded scarf and a set of keys",
    ),
    "jewelry": NicheSlots(
        in_use="worn on the body, catching the light as the wearer moves",
        detail="the metal finish, the clasp, and the stone setting",
        surface="raw silk",
        setting="a dressing table with a small dish and a candle",
        props="a trinket dish and a slim candle",
    ),
    "makeup": NicheSlots(
        in_use="applied on the face mid-routine, the product held in hand",
        detail="the pigment texture, the bullet or pan surface, and the cap thread",
        surface="a marble vanity top",
        setting="a bathroom vanity with a mirror and a small tray",
        props="a makeup brush and a compact mirror",
    ),
    "skincare": NicheSlots(
        in_use="being applied, a smear of product visible on the skin",
        detail="the serum texture, the dropper tip, and the label printing",
        surface="a stone shelf",
        setting="a bathroom shelf beside a folded towel and a sprig of greenery",
        props="a folded towel and a small plant",
    ),
    "hair": NicheSlots(
        in_use="worked through damp hair",
        detail="the product texture, the pump mechanism, and the label",
        surface="a tiled ledge",
        setting="a bathroom counter with a hairbrush and a folded towel",
        props="a hairbrush and a hair clip",
    ),
    "fragrance": NicheSlots(
        in_use="sprayed at the wrist, the bottle held in hand",
        detail="the glass thickness, the cap facets, and the level of the liquid",
        surface="a marble slab",
        setting="a bedroom dresser with a folded scarf and dried flowers",
        props="dried flowers and a folded silk scarf",
    ),
    "nail_art": NicheSlots(
        in_use="freshly applied on natural nails, hands resting casually",
        detail="the nail bed translucency, the cuticle line, and the gloss on the free edge",
        surface="soft matte fabric",
        setting="a bright vanity with polish bottles and a hand mirror",
        props="a polish bottle and a small dish of remover pads",
    ),
    "costume": NicheSlots(
        in_use="worn, mid-adjust, the wearer settling it into place",
        detail="the fabric sheen, the trim, and the fastening",
        surface="a quilted bedspread",
        setting="a bedroom with the packaging and accessories laid out alongside",
        props="the separate accessories and a garment bag",
    ),
    "toys": NicheSlots(
        in_use="mid-play, pieces scattered naturally around it",
        detail="the moulded edge, the paint finish, and the moving part",
        surface="a pale wood floor",
        setting="a playroom rug with companion toys nearby",
        props="a couple of companion pieces and a storage basket",
    ),
    "baby": NicheSlots(
        in_use="in use, held or worn by the baby",
        detail="the fabric softness, the fastening, and the safety stitching",
        surface="a soft cotton blanket",
        setting="a nursery with a cot and a folded blanket",
        props="a folded muslin and a small soft toy",
    ),
    "pets": NicheSlots(
        in_use="worn by the animal, or in use at floor level",
        detail="the webbing, the buckle, and the fabric weave",
        surface="a woven rug",
        setting="a hallway with a lead on a hook and a food bowl on the floor",
        props="a food bowl and a chew toy",
    ),
    "home_decor": NicheSlots(
        in_use="placed and lived-with in the room it belongs to",
        detail="the surface glaze, the joinery, and the material grain",
        surface="a wooden console top",
        setting="a styled living room with the edge of a sofa and a plant",
        props="a stack of books and a small vase",
    ),
    "bedding": NicheSlots(
        in_use="made up on the bed, softly rumpled",
        detail="the weave, the hem, and the surface texture of the fabric",
        surface="the bed itself",
        setting="a bedroom with a bedside table and a lamp",
        props="a bedside lamp and a folded throw",
    ),
    "kitchen": NicheSlots(
        in_use="mid-use with food in it",
        detail="the glaze, the rim, and the honest wear on the base",
        surface="a stone countertop",
        setting="a kitchen counter with a chopping board and a tea towel",
        props="a chopping board and a tea towel",
    ),
    "food": NicheSlots(
        in_use="poured, plated or served",
        detail="the crumb, the drip, and the packaging label",
        surface="a stone slab",
        setting="a rustic table with a linen napkin and a knife",
        props="a linen napkin and a small knife",
    ),
    "tech": NicheSlots(
        in_use="in use with the screen on, or plugged in and charging",
        detail="the port, the mesh, the chamfer, and the indicator light",
        surface="a matte desk",
        setting="a workspace with the edge of a keyboard and a coffee cup",
        props="a keyboard edge and a coffee cup",
    ),
    "stationery": NicheSlots(
        in_use="mid-use with writing visible on the page",
        detail="the paper tooth, the ink line, and the binding",
        surface="a warm wood desk",
        setting="a desk with a lamp and a stack of paper",
        props="a stack of paper and a small lamp",
    ),
    "fitness": NicheSlots(
        in_use="mid-workout, in motion, the product under real load",
        detail="the grip texture, the seam, and the stretch of the fabric",
        surface="a rubber gym mat",
        setting="a home gym corner with a water bottle and a towel",
        props="a water bottle and a rolled towel",
    ),
    "garden": NicheSlots(
        in_use="in use in the garden, soil on the hands",
        detail="the surface texture, the joinery, and the honest weathering",
        surface="a weathered wooden bench",
        setting="a garden border with soil and potted plants",
        props="a terracotta pot and a pair of gloves",
    ),
    "storage": NicheSlots(
        in_use="filled with the things it is meant to hold",
        detail="the weave, the seam, and the label tag",
        surface="a pale wood floor",
        setting="a shelved corner with folded items around it",
        props="folded items and a small basket",
    ),
    "generic": NicheSlots(
        in_use="in genuine use, handled the way it would really be handled",
        detail="the surface texture, the finish, and the material grain",
        surface="a textured surface that contrasts the product material",
        setting="a lived-in room with believable everyday objects around it",
        props="two or three complementary everyday objects",
    ),
}


def niche_slots(class_key: str | None) -> NicheSlots:
    """Slots for a product class, falling back to the generic set."""
    return _NICHE.get(str(class_key or "").strip().lower(), _NICHE["generic"])


# ─────────────────────────────────────────────────────────────────────
# Naming the product mid-sentence
# ─────────────────────────────────────────────────────────────────────

_DETERMINERS: tuple[str, ...] = (
    "a ",
    "an ",
    "the ",
    "this ",
    "these ",
    "those ",
    "my ",
    "your ",
    "our ",
    "his ",
    "her ",
    "its ",
)


def name_phrase(product: dict[str, Any]) -> str:
    """
    The product named the way a person would say it inside a sentence.

    `subject_line()` in product_taxonomy produces a standalone line ending in a
    full stop. Block C needs the product *mid-sentence*, so this adds a determiner
    only when the name hasn't already got one — "linen midi dress" becomes "the
    linen midi dress", while "The Linen Dress" is left alone.
    """
    name = str(product.get("name") or "the product").strip().rstrip(".")
    if not name:
        name = "the product"
    if any(name.lower().startswith(d) for d in _DETERMINERS):
        return name
    return f"the {name}"


# ─────────────────────────────────────────────────────────────────────
# Human presence
# ─────────────────────────────────────────────────────────────────────


def human_for(klass: Any, wants_human: bool) -> str:
    """
    Pick a human_presence value this class allows.

    Lifestyle wants a person; flat-lay, macro and environment do not (a person in
    a macro detail shot only competes for attention).

    The taxonomy lists its values "most typical first", so we defer to that
    ordering rather than inventing our own: for a lifestyle shot we take the
    class's own top non-`none` choice (apparel -> `full`, tech -> `partial_hand_arm`,
    home_decor -> `partial_hand_arm`). We never emit a value outside the allow-list,
    so an impossible combination can't reach the prompt.
    """
    allowed = tuple(getattr(klass, "human_presence", ()) or ("none",))

    if wants_human:
        for pref in allowed:
            if pref != "none":
                return pref
        return "none"

    # Non-human shots: `none` whenever the class permits it.
    if "none" in allowed:
        return "none"
    return allowed[-1]


# ─────────────────────────────────────────────────────────────────────
# Block C — the shot directive
# ─────────────────────────────────────────────────────────────────────


def shot_directive(
    archetype_key: str,
    klass: Any,
    product: dict[str, Any],
    locked_world: dict[str, str] | None = None,
) -> str:
    """
    Build the unique per-shot block for one archetype.

    `locked_world` carries the values that must stay identical across all four
    shots (colour grade, aesthetic, palette) so the set reads as one shoot. They
    are restated inside every shot block on purpose: each submission is a separate
    request and the model has no memory of the others.
    """
    arch = ARCHETYPES.get(archetype_key)
    if arch is None:
        raise KeyError(f"unknown shot archetype {archetype_key!r}; expected one of {SHOT_ORDER}")

    slots = niche_slots(getattr(klass, "key", None))
    name = name_phrase(product)
    world = locked_world or {}

    lines = [
        f"SHOT TYPE — {arch.label}.",
        f"THIS SHOT'S JOB: {arch.purpose}.",
        "A single photograph. Not a collage, grid, contact sheet, diptych or split panel.",
    ]

    # Subject / moment
    if archetype_key == "lifestyle":
        lines.append(f"SUBJECT: {name} {slots.in_use}.")
    elif archetype_key == "flat_lay":
        lines.append(
            f"SUBJECT: {name} laid flat and styled, nothing worn, no person in frame."
        )
    elif archetype_key == "macro":
        lines.append(f"SUBJECT: an extreme close-up of {name}, showing {slots.detail}.")
    else:
        lines.append(
            f"SUBJECT: {name} placed in its real setting, at rest, not being held."
        )

    # Camera
    lines.append(f"CAMERA: {arch.camera}.")

    # Lighting — deliberately per-shot, because each shot type needs its own light
    lines.append(f"LIGHTING: {arch.lighting}.")

    # Surface / setting — which slot applies depends on the shot.
    # A macro frame gets a *backdrop*, not a surface: naming a surface in a 1:1
    # magnification frame invites the model to render that material prominently
    # and compete with the detail we are trying to prove.
    if archetype_key == "flat_lay":
        lines.append(f"SURFACE: {slots.surface}.")
    elif archetype_key == "macro":
        lines.append(
            f"BACKDROP: {slots.surface}, held far behind the focus plane and "
            "rendered only as soft out-of-focus tone — no competing texture."
        )
    else:
        lines.append(f"SETTING: {slots.setting}.")

    # Props only where they help; a macro frame should stay uncluttered
    if archetype_key in ("flat_lay", "environment"):
        lines.append(f"STYLING PROPS: {slots.props}, placed asymmetrically, some cropped by the frame edge.")

    lines.append(f"COMPOSITION: {arch.composition}.")
    lines.append(f"MOOD: {arch.mood}.")

    # Locked world — restated so all four submissions share one look
    if world:
        world_bits = [f"{k} — {v}" for k, v in world.items() if v]
        if world_bits:
            lines.append(
                "CONSISTENCY (must match the other shots in this set exactly): "
                + "; ".join(world_bits)
                + "."
            )

    return "\n".join(lines)


def locked_world_from_scene(scene: dict[str, Any]) -> dict[str, str]:
    """
    The values that must stay identical across all four shots.

    Colour grade, aesthetic and palette are shared; camera angle, lighting setup
    and environment are NOT, because each archetype legitimately needs its own.
    """
    return {
        "colour grading": str(scene.get("color_grading") or "").strip(),
        "visual aesthetic": str(scene.get("style_aesthetic") or "").strip(),
    }


def aspect_ratio_for(archetype_key: str) -> str:
    arch = ARCHETYPES.get(archetype_key)
    return arch.aspect_ratio if arch else "4:5"


#: Human-readable crop phrasing per aspect ratio. The compiler writes
#: "with a {crop} crop", so this must not be the raw ratio — "with a 1:1 crop"
#: reads badly and a stale "2:3 Pinterest crop" would contradict a square request.
_CROP_PHRASES: dict[str, str] = {
    "1:1": "square",
    "4:5": "4:5 vertical",
    "9:16": "9:16 vertical",
    "2:3": "2:3 vertical",
    "16:9": "16:9 horizontal",
    "3:2": "3:2 horizontal",
}


def crop_phrase(aspect_ratio: str) -> str:
    """Readable crop name for an aspect ratio, so prompt text matches the request."""
    return _CROP_PHRASES.get(str(aspect_ratio).strip(), f"{aspect_ratio} framed")


def shot_plan(klass: Any, scene: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    The ordered four-shot plan for a class, with niche slots resolved.

    Returns a list of dicts — one per shot — carrying everything a caller needs to
    compile a prompt and to submit it: key, label, purpose, aspect ratio, framing,
    human presence, and the rendered directive text.
    """
    scene = scene or {}
    world = locked_world_from_scene(scene)
    plan: list[dict[str, Any]] = []
    for key in SHOT_ORDER:
        arch = ARCHETYPES[key]
        plan.append(
            {
                "key": arch.key,
                "label": arch.label,
                "purpose": arch.purpose,
                "aspect_ratio": arch.aspect_ratio,
                "framing": arch.framing,
                "human_presence": human_for(klass, arch.wants_human),
                "directive": shot_directive(key, klass, {}, world),
            }
        )
    return plan


def label_for(archetype_key: str) -> str:
    arch = ARCHETYPES.get(archetype_key)
    return arch.label if arch else archetype_key


def describe_archetypes() -> str:
    """Human-readable summary, for diagnostics and the audit script."""
    return "\n".join(
        f"  {k:12} {ARCHETYPES[k].label:24} {ARCHETYPES[k].aspect_ratio:6} {ARCHETYPES[k].purpose}"
        for k in SHOT_ORDER
    )

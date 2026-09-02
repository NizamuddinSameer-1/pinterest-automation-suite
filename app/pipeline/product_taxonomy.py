"""
What kind of thing is this product, and therefore what photograph is believable?

Every pin this system produced was shaped like a clothing pin: a person, a mirror
or a retail rail, standing height, moderate clutter. Nothing hardcoded "apparel" —
the bias was emergent, and that made it invisible:

  * `scene_director` offered the LLM one fixed list of ten creative formats, six of
    which are apparel/retail idioms (`wear_test`, `product_rack`, `mirror_pov`,
    `shopping_cart`, `discovery`, `bedroom_home`), with five motivation examples of
    which four were clothing or footwear;
  * `prompt_compiler` then wrote whatever came back into a fixed skeleton whose
    fallbacks are apparel fallbacks — `Camera height: human standing`,
    `Crop: natural`, `Clutter: moderate` — and appended one unconditional AVOID
    list that bans `plastic textures` (most of a toy), `perfect symmetry` and
    `sterile backgrounds` (the native idiom of skincare and nail art);
  * and `visual_dna` discarded the one piece of structured evidence the system
    already had: `subject.primary_category` and `scene.type`, computed by
    `reference_analyst` and then read by nobody.

So a press-on nail set was directed like a dress. This module is the missing
answer: a product class carries the formats, framing, camera height, surfaces,
product states, motivation examples and AVOID deltas that are *believable for that
kind of object*, and the two stages downstream read them instead of guessing.

Pure data and string matching — no LLM call, no I/O, no `app.config` import — so
the scene director, the compiler and the verifier can all use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Every creative format the system knows, with the one-line description the LLM
#: sees. A class exposes a *subset*; the point is that `mirror_pov` is never
#: offered for a saucepan and `plate_up` is never offered for jeans.
CREATIVE_FORMATS: dict[str, str] = {
    # person-centred
    "wear_test": "Person wearing the product, photographed by themselves or a friend",
    "mirror_pov": "Held-phone mirror shot from the wearer's own point of view",
    "in_use": "Product mid-use by a person, caught in the middle of the action",
    "hands_holding": "Hands holding or presenting the product, face out of frame",
    "kid_playing": "A child playing with the product, unposed",
    "pet_wearing": "A pet wearing or using the product",
    # object-centred
    "macro_detail": "Very close detail of texture, finish or pattern filling the frame",
    "closeup": "Close view of the product with a little of its surroundings",
    "flat_lay": "Product arranged on a surface and shot from directly above",
    "styled_surface": "Product resting where it lives — vanity, desk, shelf, counter",
    "collection": "Several related items grouped together",
    "before_after": "Two states of the same thing side by side, or the result of using it",
    "plate_up": "Food or drink served and about to be eaten",
    # retail and arrival
    "discovery": "Shopper finds the product in a store, phone out",
    "product_rack": "Product on a retail rail, peg or shelf display",
    "shopping_cart": "Product in a cart, basket or trolley",
    "unboxing": "Product just arrived — packaging still open, box in frame",
    "gift_moment": "Product wrapped, gifted or being handed over",
    "unexpected_find": "Novelty-driven — the product somewhere you would not expect it",
    # environment-led
    "bedroom_home": "Product in an ordinary lived-in room",
    "desk_setup": "Product as part of a working desk or workspace",
    "outdoor_use": "Product outdoors, in weather and daylight",
}

#: The negative constraints as separable clauses. They used to be one frozen
#: sentence appended to every prompt, which is why a toy was told to avoid
#: `plastic textures` and a skincare bottle was told to avoid `perfect symmetry`
#: and `sterile backgrounds` — the exact look a real skincare flat-lay has.
BASE_AVOID: tuple[str, ...] = (
    "studio product photography",
    "catalog styling",
    "cinematic lighting",
    "extreme HDR",
    "artificial bokeh",
    "excessive sharpness",
    "plastic textures",
    "sterile backgrounds",
    "perfect symmetry",
    "CGI appearance",
    "impossible geometry",
    "malformed anatomy",
    "invented product features",
)

#: No class may lift these. A class that wants "invented product features" allowed
#: is a class that wants to lie about the product, which defeats the whole
#: Product Truth stage.
UNLIFTABLE_AVOID: frozenset[str] = frozenset({
    "CGI appearance", "impossible geometry", "malformed anatomy",
    "invented product features",
})


@dataclass(frozen=True)
class ProductClass:
    """
    One kind of object, and the photograph that is believable for it.

    `formats` is a whitelist, not a ranking: the Scene Director still chooses, but
    it can only choose something that makes sense for this object. `avoid_lift` is
    the important field — it is how a category escapes a negative constraint that
    is right for clothing and wrong for it.
    """

    key: str
    noun: str                                   # how to name it in the SUBJECT line
    formats: tuple[str, ...]
    human_presence: tuple[str, ...]             # allowed values, most typical first
    framing: str                                # macro | tight | medium | wide
    scale_note: str                             # how big the thing is, in words
    camera_height: str
    crop: str
    clutter: str
    surfaces: tuple[str, ...] = ()              # believable things to put it on
    locations: tuple[str, ...] = ()
    product_states: tuple[str, ...] = ()        # worn / held / plugged in / opened …
    motivations: tuple[str, ...] = ()           # class-matched capture_motivation examples
    avoid_extra: tuple[str, ...] = ()           # negatives this class needs and others don't
    avoid_lift: tuple[str, ...] = ()            # base negatives that are wrong for this class
    notes: tuple[str, ...] = ()                 # rules worth telling the director outright
    keywords: tuple[str, ...] = field(default_factory=tuple, repr=False)

    def avoid_clauses(self) -> tuple[str, ...]:
        """The negative constraints that actually apply to this class."""
        lifted = {c.lower() for c in self.avoid_lift} - {
            c.lower() for c in UNLIFTABLE_AVOID
        }
        kept = tuple(c for c in BASE_AVOID if c.lower() not in lifted)
        return kept + tuple(c for c in self.avoid_extra if c not in kept)

    def format_menu(self) -> str:
        """The eligible formats, rendered for the Scene Director's system prompt."""
        return "\n".join(
            f"  {name} — {CREATIVE_FORMATS[name]}"
            for name in self.formats
            if name in CREATIVE_FORMATS
        )


#: Insertion order is match priority: the first class whose keywords hit wins, so
#: the specific ones (nail art, costume) come before the broad ones (beauty,
#: apparel) that would otherwise swallow them.
CLASSES: dict[str, ProductClass] = {}


def _add(pc: ProductClass) -> ProductClass:
    CLASSES[pc.key] = pc
    return pc


NAIL_ART = _add(ProductClass(
    key="nail_art",
    noun="set of press-on nails",
    formats=("macro_detail", "closeup", "hands_holding", "before_after",
             "flat_lay", "unboxing", "collection"),
    human_presence=("partial_hand_arm", "none"),
    framing="macro",
    scale_note="a few centimetres across — the hand should fill most of the frame",
    camera_height="hands held up at chest height, camera close",
    crop="tight",
    clutter="low",
    surfaces=("bare hand against a plain sleeve", "desk beside the nail kit",
              "car steering wheel", "open book", "coffee cup being held"),
    locations=("at a desk by a window", "on a bed", "in a car in daylight",
               "at a bathroom counter"),
    product_states=("freshly applied on the nails", "still in the tray",
                    "one nail held up between finger and thumb"),
    motivations=(
        "Person just finished applying the set and wants to show how the shape sits",
        "Someone is comparing two colours from the pack against their skin tone",
        "Wearer noticed the nails still look perfect after a week and photographed them",
    ),
    avoid_extra=("hands with the wrong number of fingers",
                 "nails melted into the fingertip", "salon price list"),
    # A nail photo is *supposed* to be a clean, close, symmetric surface. Banning
    # that is what made every nail pin look like a clothing pin.
    avoid_lift=("perfect symmetry", "sterile backgrounds", "excessive sharpness",
                "plastic textures"),
    notes=("Nails cannot be hung on a rack or worn on a body — the hand IS the scene.",
           "Fingers, cuticles and nail edges must read as real skin."),
    keywords=("nail", "nails", "press-on", "press on", "manicure", "pedicure",
              "nail art", "gel nail", "acrylic nail", "nail wrap"),
))

MAKEUP = _add(ProductClass(
    key="makeup",
    noun="makeup product",
    formats=("hands_holding", "styled_surface", "flat_lay", "macro_detail",
             "before_after", "in_use", "collection", "discovery", "unboxing"),
    human_presence=("partial_hand_arm", "partial_body", "none"),
    framing="tight",
    scale_note="palm-sized — the product should fill a third to a half of the frame",
    camera_height="looking down at a counter, or held at arm's length",
    crop="tight",
    clutter="low",
    surfaces=("bathroom counter", "vanity top", "windowsill", "open makeup bag",
              "back of the hand as a swatch"),
    locations=("at a bathroom mirror", "at a bedroom vanity", "by a window in daylight"),
    product_states=("cap off beside the tube", "swatched on the back of the hand",
                    "held up next to the face", "half-used, label a little scuffed"),
    motivations=(
        "Person swatched three shades on their hand and wants to show the difference",
        "Someone finished their makeup and photographed the products they actually used",
        "Buyer wants to show how small the compact really is next to their hand",
    ),
    avoid_extra=("invented shade names on the packaging", "unreadable smeared text"),
    avoid_lift=("perfect symmetry", "sterile backgrounds"),
    notes=("Swatches and counter-top shots are the native idiom — a person is optional.",),
    keywords=("lipstick", "lip gloss", "mascara", "eyeliner", "eyeshadow", "foundation",
              "concealer", "blush", "highlighter", "makeup", "cosmetic", "palette",
              "brow", "primer", "setting spray", "bronzer"),
))

SKINCARE = _add(ProductClass(
    key="skincare",
    noun="skincare product",
    formats=("styled_surface", "flat_lay", "hands_holding", "macro_detail",
             "in_use", "collection", "unboxing", "discovery", "before_after"),
    human_presence=("none", "partial_hand_arm", "partial_body"),
    framing="tight",
    scale_note="bottle-sized — usually one or two objects, not a room",
    camera_height="overhead over a counter, or straight on at counter height",
    crop="tight",
    clutter="low",
    surfaces=("bathroom shelf", "tiled counter", "linen towel", "wooden tray",
              "windowsill with morning light", "edge of a bathtub"),
    locations=("in a small bathroom", "on a bedside table", "by a window"),
    product_states=("pump half-used", "dropper lifted out", "a smear of cream on the hand",
                    "sitting next to the box it came in"),
    motivations=(
        "Person reached the end of the bottle and wants to say it was worth repurchasing",
        "Someone photographed their actual morning shelf, not a styled set",
        "Buyer is showing the texture of the cream on the back of their hand",
    ),
    avoid_extra=("invented ingredient claims on the label", "medical or clinical staging"),
    # Clean, symmetric, uncluttered surfaces are exactly right here.
    avoid_lift=("perfect symmetry", "sterile backgrounds", "catalog styling"),
    notes=("A quiet, clean surface shot is believable for skincare and needs no person.",),
    keywords=("serum", "moisturizer", "moisturiser", "cleanser", "toner", "sunscreen",
              "spf", "skincare", "face mask", "retinol", "hyaluronic", "lotion",
              "body wash", "balm", "osea", "facial oil", "body oil", "body cream",
              "eye cream", "face oil", "exfoliant", "essence", "body butter",
              "moisturizing", "moisturising", "cream", "hand cream"),
))

HAIR = _add(ProductClass(
    key="hair",
    noun="hair product",
    formats=("in_use", "before_after", "styled_surface", "hands_holding",
             "mirror_pov", "flat_lay", "collection", "unboxing"),
    human_presence=("partial_body", "partial_hand_arm", "none"),
    framing="tight",
    scale_note="held in one hand, or a head of hair filling the frame",
    camera_height="held at head height, or looking down at a counter",
    crop="tight",
    clutter="low",
    surfaces=("bathroom counter", "dressing table", "shower ledge"),
    locations=("in a bathroom", "at a mirror", "by a window"),
    product_states=("in use in damp hair", "on the counter beside a hairbrush",
                    "clipped into styled hair"),
    motivations=(
        "Person air-dried their hair for the first time with it and liked the result",
        "Someone photographed the clip actually holding their hair up, not on a table",
        "Buyer wants to show how little product it takes",
    ),
    avoid_extra=("salon advertisement styling", "hair melting into the scalp"),
    avoid_lift=("perfect symmetry", "sterile backgrounds"),
    keywords=("shampoo", "conditioner", "hair oil", "hair mask", "hair clip", "claw clip",
              "scrunchie", "hair dryer", "curling", "straightener", "hairbrush",
              "heatless curl", "scalp"),
))

FRAGRANCE = _add(ProductClass(
    key="fragrance",
    noun="fragrance",
    formats=("styled_surface", "flat_lay", "hands_holding", "macro_detail",
             "gift_moment", "collection", "unboxing", "discovery"),
    human_presence=("none", "partial_hand_arm"),
    framing="tight",
    scale_note="one bottle, close — the glass and the light on it are the subject",
    camera_height="straight on at counter height, or a slight look-down",
    crop="tight",
    clutter="low",
    surfaces=("dresser top", "windowsill", "marble counter", "stack of books"),
    locations=("on a dresser", "by a window in late light", "on a bedside table"),
    product_states=("cap off beside the bottle", "half full, catching the light",
                    "still in the opened box"),
    motivations=(
        "Person set the bottle in the window because the light through it looked good",
        "Someone is showing which of their bottles is nearly finished",
        "Gift arrived and the box is still half-wrapped beside it",
    ),
    avoid_extra=("perfume advertisement art direction", "invented notes printed on glass"),
    avoid_lift=("perfect symmetry", "sterile backgrounds", "catalog styling"),
    keywords=("perfume", "fragrance", "eau de", "cologne", "body mist", "roll-on scent"),
))

JEWELRY = _add(ProductClass(
    key="jewelry",
    noun="piece of jewellery",
    formats=("macro_detail", "closeup", "wear_test", "hands_holding", "flat_lay",
             "styled_surface", "collection", "gift_moment", "unboxing"),
    human_presence=("partial_body", "partial_hand_arm", "none"),
    framing="macro",
    scale_note="centimetres — skin, chain links and clasp texture should be visible",
    camera_height="close to the neck, wrist or ear; or looking down at a surface",
    crop="tight",
    clutter="low",
    surfaces=("bare collarbone", "wrist against a sleeve", "jewellery dish",
              "linen cloth", "open ring box"),
    locations=("at a mirror in daylight", "at a dressing table", "held up to a window"),
    product_states=("worn and slightly off-centre", "layered with a piece they already own",
                    "still on the card it came on"),
    motivations=(
        "Person layered it with a necklace they already owned and liked the mix",
        "Someone photographed the clasp because reviews said it was flimsy and it isn't",
        "Wearer caught the light on the stone at their desk",
    ),
    avoid_extra=("jewellery fused to the skin", "invented hallmarks or engraving"),
    avoid_lift=("perfect symmetry", "excessive sharpness", "sterile backgrounds"),
    notes=("Scale is the whole point: show it against a body part or a familiar object.",),
    keywords=("necklace", "bracelet", "earring", "ring", "pendant", "anklet", "charm",
              "jewelry", "jewellery", "chain", "signet", "hoops", "brooch"),
))

FOOTWEAR = _add(ProductClass(
    key="footwear",
    noun="pair of shoes",
    formats=("wear_test", "closeup", "outdoor_use", "discovery", "product_rack",
             "unboxing", "flat_lay", "collection", "styled_surface"),
    human_presence=("partial_body", "full", "none"),
    framing="medium",
    scale_note="feet and a strip of the ground — the floor is part of the shot",
    camera_height="looking down at the wearer's own feet, or crouched at shoe height",
    crop="natural",
    clutter="moderate",
    surfaces=("pavement", "kerb", "gym floor", "hallway rug", "car footwell",
              "shoebox with tissue paper"),
    locations=("on a street", "in a hallway by the door", "in a shoe shop aisle",
               "on a park path"),
    product_states=("on the feet, one foot slightly forward", "muddy after a walk",
                    "just out of the box with the tissue still in"),
    motivations=(
        "Runner photographed the shoes right after a first wet-weather run",
        "Someone looked down at their own feet to show how the colour reads outdoors",
        "Shopper found their size on the shelf after weeks of looking",
    ),
    avoid_extra=("feet with the wrong number of toes", "shoes floating above the ground"),
    keywords=("shoe", "shoes", "sneaker", "trainer", "boot", "boots", "sandal", "heel",
              "heels", "loafer", "slipper", "footwear", "flip flop", "clog"),
))

BAGS = _add(ProductClass(
    key="bags",
    noun="bag",
    formats=("wear_test", "hands_holding", "styled_surface", "discovery", "flat_lay",
             "product_rack", "closeup", "unboxing", "outdoor_use"),
    human_presence=("partial_body", "full", "none"),
    framing="medium",
    scale_note="body-sized reference matters — show it on a shoulder or beside a chair",
    camera_height="held at chest height, or looking down at the bag on a seat",
    crop="natural",
    clutter="moderate",
    surfaces=("café chair", "car passenger seat", "hallway hook", "bed",
              "shop floor beside a mirror"),
    locations=("in a café", "on a train", "in a hallway", "in a shop"),
    product_states=("packed and slightly bulging", "open with everyday things inside",
                    "hanging off a chair back"),
    motivations=(
        "Person emptied their day bag onto the bed to show what actually fits",
        "Someone photographed it on their shoulder because the listing had no scale shot",
        "Commuter noticed the strap had not dug in after a week",
    ),
    avoid_extra=("straps merging into the shoulder", "invented brand logos"),
    keywords=("bag", "tote", "backpack", "purse", "handbag", "crossbody", "clutch",
              "duffel", "wallet", "pouch", "satchel", "luggage", "suitcase"),
))

COSTUME = _add(ProductClass(
    key="costume",
    noun="costume",
    formats=("wear_test", "mirror_pov", "hands_holding", "unboxing", "flat_lay",
             "discovery", "product_rack", "collection", "gift_moment"),
    human_presence=("full", "partial_body", "none"),
    framing="medium",
    scale_note="most of a body, or the garment laid out with its pieces visible",
    camera_height="human standing, or held up at arm's length",
    crop="natural",
    clutter="moderate",
    surfaces=("bed with the packaging beside it", "bedroom door hook",
              "shop rail", "hanger on a wardrobe door"),
    locations=("in a bedroom", "at a full-length mirror", "in a party shop aisle",
               "in a hallway before going out"),
    product_states=("worn, mid-adjust", "still on the hanger with the tag on",
                    "laid out on the bed with the accessories separate"),
    motivations=(
        "Person is checking the fit in the mirror the night before the party",
        "Someone laid every piece out on the bed to see what the set actually includes",
        "Shopper spotted the last one in their size on the rail",
    ),
    avoid_extra=("professional cosplay staging", "theatrical stage lighting",
                 "invented accessories that are not in the set"),
    notes=("Costume pins are seasonal — let the trend context show in the setting, "
           "not as text or a caption.",),
    keywords=("costume", "cosplay", "halloween outfit", "fancy dress", "maid outfit",
              "wig set", "party outfit"),
))

APPAREL = _add(ProductClass(
    key="apparel",
    noun="clothing item",
    formats=("wear_test", "mirror_pov", "discovery", "product_rack", "flat_lay",
             "closeup", "bedroom_home", "unboxing", "collection", "shopping_cart"),
    human_presence=("full", "partial_body", "none"),
    framing="medium",
    scale_note="most of a body, or the garment laid flat with a sleeve turned back",
    camera_height="human standing",
    crop="natural",
    clutter="moderate",
    surfaces=("bed", "wardrobe rail", "shop rail", "back of a chair", "changing-room hook"),
    locations=("in a bedroom", "at a full-length mirror", "in a changing room",
               "in a shop aisle", "outdoors on a walk"),
    product_states=("worn, mid-movement", "on the hanger with the tag still on",
                    "laid flat on the bed", "sleeve cuff turned to show the seam"),
    motivations=(
        "Friend asked what the linen dress actually looks like in daylight",
        "Shopper found an unexpected colour of this jacket on the clearance rail",
        "Person is deciding between two sizes and photographed both on the bed",
    ),
    avoid_extra=("fashion editorial posing", "fabric fused to the skin",
                 "invented prints or slogans"),
    keywords=("dress", "shirt", "t-shirt", "tee", "top", "blouse", "jeans", "denim",
              "trouser", "pants", "skirt", "jacket", "coat", "hoodie", "sweater",
              "knit", "cardigan", "pajama", "pyjama", "loungewear", "sleepwear",
              "leggings", "shorts", "romper", "jumpsuit", "swimsuit", "bikini",
              "sock", "socks", "underwear", "bra", "apparel", "clothing", "outfit"),
))

TOYS = _add(ProductClass(
    key="toys",
    noun="toy",
    formats=("kid_playing", "in_use", "flat_lay", "collection", "unboxing",
             "gift_moment", "macro_detail", "bedroom_home", "discovery", "unexpected_find"),
    human_presence=("partial_hand_arm", "full", "none"),
    framing="medium",
    scale_note="held in a child's hands, or spread out on a floor or table",
    camera_height="crouched at child height, or looking down at the floor",
    crop="natural",
    clutter="moderate",
    surfaces=("living-room rug", "play mat", "kitchen table", "bedroom floor",
              "opened box with the moulded tray showing"),
    locations=("in a living room", "on a bedroom floor", "at a kitchen table",
               "in a garden"),
    product_states=("mid-play, pieces scattered", "half assembled",
                    "just unboxed with packaging still around it"),
    motivations=(
        "Parent photographed the set mid-play because their child had not stopped for an hour",
        "Someone laid out every piece to show how many are in the box",
        "Grandparent wants to show what it looks like next to a child's hands for scale",
    ),
    avoid_extra=("children's faces in sharp focus", "unsafe small parts near a baby's mouth",
                 "invented licensed characters"),
    # A toy is made of plastic. Banning "plastic textures" told the model to lie.
    avoid_lift=("plastic textures", "perfect symmetry"),
    notes=("Plastic, moulded seams and printed decals are correct here, not defects.",),
    keywords=("toy", "toys", "plush", "stuffed animal", "doll", "figurine", "lego",
              "building block", "puzzle", "board game", "playset", "action figure",
              "rc car", "squishmallow", "fidget"),
))

BABY = _add(ProductClass(
    key="baby",
    noun="baby product",
    formats=("in_use", "hands_holding", "flat_lay", "bedroom_home", "unboxing",
             "collection", "gift_moment", "closeup"),
    human_presence=("partial_hand_arm", "partial_body", "none"),
    framing="medium",
    scale_note="show it against an adult hand or a cot — parents buy on size",
    camera_height="looking down into a cot or changing table",
    crop="natural",
    clutter="low",
    surfaces=("changing mat", "cot mattress", "nursery shelf", "pram seat"),
    locations=("in a nursery", "in a living room", "in the back of a car"),
    product_states=("in use", "folded ready in the bag", "laid out with the spare parts"),
    motivations=(
        "Parent packed the bag at 6am and photographed what actually fits",
        "Someone is showing how small it folds next to a water bottle",
        "New parent wants to show the fabric against a cot for scale",
    ),
    avoid_extra=("babies' faces in sharp focus", "unsafe sleep positions",
                 "loose bedding around a sleeping baby"),
    avoid_lift=("plastic textures",),
    keywords=("baby", "infant", "newborn", "nursery", "pram", "stroller", "cot",
              "pacifier", "bottle warmer", "swaddle", "nappy", "diaper", "high chair"),
))

PETS = _add(ProductClass(
    key="pets",
    noun="pet product",
    formats=("pet_wearing", "in_use", "hands_holding", "flat_lay", "collection",
             "unboxing", "outdoor_use", "bedroom_home", "closeup"),
    human_presence=("none", "partial_hand_arm"),
    framing="medium",
    scale_note="the animal is the scale reference — show it wearing or using the thing",
    camera_height="crouched at the animal's height",
    crop="natural",
    clutter="moderate",
    surfaces=("living-room floor", "garden path", "pet bed", "kitchen tiles"),
    locations=("in a living room", "in a garden", "on a walk", "at a vet's waiting room"),
    product_states=("worn by the animal", "chewed a little", "filled with food",
                    "still in the packet"),
    motivations=(
        "Owner photographed the harness on the dog because sizing charts never help",
        "Someone's cat claimed the bed within a minute of it arriving",
        "Owner is showing the toy survived a week of chewing",
    ),
    avoid_extra=("distressed animals", "collars digging into fur",
                 "animals with malformed limbs"),
    avoid_lift=("plastic textures",),
    keywords=("dog", "cat", "pet", "puppy", "kitten", "leash", "harness", "collar",
              "litter", "pet bed", "chew toy", "aquarium", "hamster", "bird cage"),
))

HOME_DECOR = _add(ProductClass(
    key="home_decor",
    noun="home decor piece",
    formats=("styled_surface", "bedroom_home", "closeup", "collection", "unboxing",
             "flat_lay", "discovery", "gift_moment", "unexpected_find"),
    human_presence=("none", "partial_hand_arm"),
    framing="medium",
    scale_note="show the piece in the room it belongs to, with a wall or corner visible",
    camera_height="sitting height, looking slightly up or level at the shelf",
    crop="natural",
    clutter="moderate",
    surfaces=("shelf", "side table", "mantelpiece", "windowsill", "bedside table",
              "hallway console"),
    locations=("in a living room", "in a bedroom corner", "in a hallway",
               "in a small rented flat"),
    product_states=("placed and lived-with", "just unpacked with paper beside it",
                    "lit in the evening"),
    motivations=(
        "Someone rearranged a shelf and liked how the new lamp looked",
        "Person finally filled the empty corner and photographed it at dusk",
        "Buyer wants to show the real colour against a white wall",
    ),
    avoid_extra=("interiors magazine styling", "showroom emptiness",
                 "invented wall art content"),
    avoid_lift=("catalog styling",),
    keywords=("lamp", "vase", "candle", "cushion", "pillow", "throw", "rug", "mirror",
              "frame", "poster", "print", "decor", "plant pot", "planter", "shelf",
              "curtain", "clock", "ornament", "diffuser"),
))

BEDDING = _add(ProductClass(
    key="bedding",
    noun="bedding set",
    formats=("bedroom_home", "closeup", "macro_detail", "flat_lay", "in_use",
             "unboxing", "collection", "styled_surface"),
    human_presence=("none", "partial_hand_arm", "partial_body"),
    framing="wide",
    scale_note="a bed fills the frame — texture at the near edge, room behind",
    camera_height="standing beside the bed looking down across it",
    crop="natural",
    clutter="low",
    surfaces=("made bed", "unmade bed", "sofa", "linen cupboard shelf"),
    locations=("in a bedroom in morning light", "in a small bedroom", "on a sofa"),
    product_states=("slightly rumpled after sleeping in it", "freshly made",
                    "folded with the packaging band still on"),
    motivations=(
        "Person photographed the bed unmade because that is how the linen really creases",
        "Someone washed it three times and wants to show it did not pill",
        "Buyer is showing the true colour next to their existing sheets",
    ),
    avoid_extra=("hotel showroom perfection", "invented embroidery"),
    avoid_lift=("perfect symmetry",),
    keywords=("duvet", "comforter", "bedding", "bed sheet", "sheets", "pillowcase",
              "blanket", "quilt", "mattress", "bedspread", "throw blanket"),
))

KITCHEN = _add(ProductClass(
    key="kitchen",
    noun="kitchen item",
    formats=("in_use", "styled_surface", "flat_lay", "closeup", "collection",
             "unboxing", "discovery", "macro_detail", "plate_up"),
    human_presence=("partial_hand_arm", "none"),
    framing="medium",
    scale_note="counter-height view; hands in frame make the size read",
    camera_height="looking down at the counter or hob",
    crop="natural",
    clutter="moderate",
    surfaces=("kitchen counter", "hob", "wooden board", "draining board", "open cupboard"),
    locations=("in a small kitchen", "at a counter in daylight", "at a dining table"),
    product_states=("mid-use with food in it", "washed and drying",
                    "used, with honest marks on the base"),
    motivations=(
        "Someone photographed the pan mid-cook because the coating actually released",
        "Person is showing how it fits in a small cupboard",
        "Buyer wants to show the size next to a standard mug",
    ),
    avoid_extra=("food advertising gloss", "steam added artificially",
                 "invented capacity markings"),
    avoid_lift=("perfect symmetry", "sterile backgrounds", "plastic textures"),
    keywords=("pan", "pot", "skillet", "knife", "cutting board", "mug", "cup", "glass",
              "plate", "bowl", "kettle", "blender", "airfryer", "air fryer", "utensil",
              "kitchen", "cookware", "tumbler", "water bottle", "food container",
              "coffee maker", "espresso", "dutch oven", "saucepan", "casserole", "wok", "toaster"),
))

FOOD = _add(ProductClass(
    key="food",
    noun="food or drink product",
    formats=("plate_up", "in_use", "flat_lay", "styled_surface", "hands_holding",
             "closeup", "macro_detail", "collection", "discovery", "unboxing"),
    human_presence=("partial_hand_arm", "none"),
    framing="tight",
    scale_note="the food fills the frame; the packet is usually just behind it",
    camera_height="looking down at a table, or level with a glass",
    crop="tight",
    clutter="low",
    surfaces=("dining table", "kitchen counter", "café table", "desk beside a laptop"),
    locations=("at a kitchen table", "in a café", "at a desk", "on a picnic blanket"),
    product_states=("opened and half eaten", "poured into a glass",
                    "still sealed beside the prepared portion"),
    motivations=(
        "Person opened the packet at their desk and photographed it before finishing it",
        "Someone is showing how much is actually in a serving",
        "Buyer photographed the drink poured out because the bottle colour lies",
    ),
    avoid_extra=("food advertising retouching", "inedible props",
                 "invented nutrition claims on the label"),
    avoid_lift=("perfect symmetry", "excessive sharpness"),
    keywords=("snack", "coffee", "tea", "chocolate", "protein", "supplement", "vitamin",
              "drink", "juice", "sauce", "spice", "food", "candy", "cookie", "granola",
              "matcha", "syrup"),
))

TECH = _add(ProductClass(
    key="tech",
    noun="gadget",
    formats=("desk_setup", "in_use", "hands_holding", "flat_lay", "unboxing",
             "closeup", "macro_detail", "collection", "styled_surface"),
    human_presence=("partial_hand_arm", "none"),
    framing="tight",
    scale_note="hand or desk for scale; cables and ports should be visible and real",
    camera_height="looking down at a desk",
    crop="tight",
    clutter="moderate",
    surfaces=("desk", "bedside table", "car dashboard mount", "sofa arm",
              "opened box with the moulded insert showing"),
    locations=("at a desk", "in a bedroom", "on a train", "in a car"),
    product_states=("plugged in and charging", "in use with the screen on",
                    "just unboxed with the film half peeled off"),
    motivations=(
        "Person photographed their desk after finally hiding the cable",
        "Someone is showing the charger's real size next to their phone",
        "Buyer peeled the screen film off and photographed the first power-on",
    ),
    avoid_extra=("invented user interface content", "brand logos that do not exist",
                 "impossible cable routing"),
    avoid_lift=("plastic textures", "perfect symmetry", "sterile backgrounds"),
    keywords=("charger", "cable", "headphone", "earbud", "speaker", "phone case",
              "laptop stand", "keyboard", "mouse", "monitor", "camera", "smart watch",
              "tracker", "power bank", "led strip", "gadget", "electronic"),
))

STATIONERY = _add(ProductClass(
    key="stationery",
    noun="stationery or craft item",
    formats=("desk_setup", "flat_lay", "in_use", "hands_holding", "macro_detail",
             "collection", "unboxing", "styled_surface", "before_after"),
    human_presence=("partial_hand_arm", "none"),
    framing="tight",
    scale_note="a desk surface, shot close — the page and the pen tip are the subject",
    camera_height="looking straight down at the desk",
    crop="tight",
    clutter="low",
    surfaces=("open notebook", "desk", "craft table", "cutting mat", "windowsill"),
    locations=("at a desk", "at a kitchen table", "in a craft corner"),
    product_states=("mid-use with writing on the page", "swatched on a sample sheet",
                    "arranged the way they are actually stored"),
    motivations=(
        "Person tested every pen in the pack on one page and photographed the result",
        "Someone is showing whether the marker bleeds through the paper",
        "Buyer set up their desk for the term and liked how it looked",
    ),
    avoid_extra=("invented printed text or logos", "unreadable pretend handwriting"),
    avoid_lift=("perfect symmetry", "sterile backgrounds", "catalog styling",
                "excessive sharpness"),
    keywords=("pen", "pencil", "marker", "notebook", "journal", "planner", "sticker",
              "washi", "stationery", "craft", "yarn", "knitting", "paint", "brush set",
              "sketchbook", "scrapbook", "desk pad"),
))

FITNESS = _add(ProductClass(
    key="fitness",
    noun="fitness product",
    formats=("in_use", "wear_test", "outdoor_use", "flat_lay", "styled_surface",
             "closeup", "collection", "unboxing", "before_after"),
    human_presence=("partial_body", "full", "none"),
    framing="medium",
    scale_note="a room corner or a stretch of path; body for scale where it is worn",
    camera_height="floor level for mats and weights, standing for worn items",
    crop="natural",
    clutter="low",
    surfaces=("living-room floor", "gym floor", "yoga mat", "park path", "car boot"),
    locations=("in a living room", "at a gym", "in a park", "in a garage"),
    product_states=("mid-workout, slightly used", "rolled up by the door",
                    "sweaty after a session"),
    motivations=(
        "Person photographed the mat after a session because it had not slid once",
        "Someone is showing the dumbbells stored in a flat with no space",
        "Runner wanted to show the band still had tension after a month",
    ),
    avoid_extra=("gym advertisement posing", "impossible body proportions"),
    avoid_lift=("plastic textures",),
    keywords=("yoga", "mat", "dumbbell", "kettlebell", "resistance band", "fitness",
              "gym", "workout", "treadmill", "foam roller", "jump rope", "activewear",
              "sports bra", "water jug"),
))

GARDEN = _add(ProductClass(
    key="garden",
    noun="garden or outdoor item",
    formats=("outdoor_use", "in_use", "styled_surface", "closeup", "collection",
             "unboxing", "discovery", "before_after", "macro_detail"),
    human_presence=("partial_hand_arm", "none", "partial_body"),
    framing="medium",
    scale_note="daylight and ground texture matter — show soil, paving or grass",
    camera_height="crouched at plant height, or looking down at the soil",
    crop="natural",
    clutter="moderate",
    surfaces=("soil", "patio paving", "balcony rail", "greenhouse bench", "potting table"),
    locations=("in a small garden", "on a balcony", "in a greenhouse", "on a doorstep"),
    product_states=("in use with soil on it", "planted up", "weathered after a season"),
    motivations=(
        "Person potted the whole tray in one evening and photographed the result",
        "Someone is showing the tool after a season outdoors — it has not rusted",
        "Balcony gardener wants to show how much fits in a metre of rail",
    ),
    avoid_extra=("garden centre display staging", "plants in impossible bloom together"),
    avoid_lift=("plastic textures",),
    keywords=("garden", "plant", "seed", "soil", "compost", "watering can", "pruner",
              "trowel", "outdoor", "patio", "bbq", "grill", "hose", "greenhouse",
              "bird feeder", "fairy light"),
))

STORAGE = _add(ProductClass(
    key="storage",
    noun="storage or organising product",
    formats=("before_after", "in_use", "styled_surface", "flat_lay", "bedroom_home",
             "closeup", "collection", "unboxing", "desk_setup"),
    human_presence=("partial_hand_arm", "none"),
    framing="medium",
    scale_note="show the drawer, cupboard or shelf it goes in — fit is the whole appeal",
    camera_height="looking down into the drawer, or level with the shelf",
    crop="natural",
    clutter="moderate",
    surfaces=("open drawer", "wardrobe shelf", "under-sink cupboard", "bathroom cabinet",
              "car boot"),
    locations=("in a small flat", "in a bathroom", "in a kitchen cupboard",
               "in a bedroom wardrobe"),
    product_states=("filled with the things it is meant to hold", "stacked two high",
                    "still flat-packed beside the assembled one"),
    motivations=(
        "Person finally organised the drawer and photographed it before it got messy again",
        "Someone is showing that three of them fit exactly across a standard shelf",
        "Buyer wants to show how much it actually holds",
    ),
    avoid_extra=("organising-influencer perfection", "empty showroom staging"),
    avoid_lift=("plastic textures", "perfect symmetry", "sterile backgrounds"),
    keywords=("organizer", "organiser", "storage", "basket", "bin", "drawer divider",
              "hanger", "hook", "rack", "shelf insert", "caddy", "box set",
              "vacuum bag", "label maker"),
))

GENERIC = _add(ProductClass(
    key="generic",
    noun="product",
    formats=("hands_holding", "in_use", "styled_surface", "flat_lay", "closeup",
             "unboxing", "discovery", "collection", "bedroom_home", "unexpected_find"),
    human_presence=("partial_hand_arm", "none", "partial_body"),
    framing="medium",
    scale_note="include something ordinary for scale — a hand, a mug, a doorway",
    camera_height="natural eye level for the object's size",
    crop="natural",
    clutter="low",
    surfaces=("table", "counter", "desk", "floor", "shelf"),
    locations=("in an ordinary home", "in a shop", "outdoors in daylight"),
    product_states=("in use", "just unpacked", "put away where it lives"),
    motivations=(
        "Person is showing what the product actually looks like out of the packaging",
        "Someone photographed it in use because no listing photo shows that",
        "Buyer wants to show the real size against something familiar",
    ),
    notes=("The product class could not be identified, so decide the scene from the "
           "product's own name, attributes and materials — do not fall back to a "
           "clothing or mirror scene.",),
    keywords=(),
))


# ── classification ──────────────────────────────────────────────────────

#: Free-text `category` values the UI and the product library actually use, mapped
#: onto a class. This is a hint, not a decision: the product *name* outweighs it,
#: because the database's press-on nail set is filed under `beauty` and a scene
#: directed for "beauty" is not a scene directed for nails.
CATEGORY_HINTS: dict[str, str] = {
    "fashion": "apparel", "clothing": "apparel", "apparel": "apparel",
    "sleepwear": "apparel", "loungewear": "apparel", "swimwear": "apparel",
    "outerwear": "apparel", "dresses": "apparel", "tops": "apparel",
    "footwear": "footwear", "shoes": "footwear", "sneakers": "footwear",
    "jewelry": "jewelry", "jewellery": "jewelry",
    "bags": "bags", "handbags": "bags", "luggage": "bags",
    "costumes": "costume", "costume": "costume", "halloween": "costume",
    "beauty": "makeup", "cosmetics": "makeup", "makeup": "makeup",
    "skincare": "skincare", "haircare": "hair", "hair": "hair",
    "fragrance": "fragrance", "perfume": "fragrance",
    "nails": "nail_art", "nail": "nail_art", "nail_art": "nail_art",
    "toys": "toys", "games": "toys", "kids": "toys",
    "baby": "baby", "nursery": "baby",
    "pets": "pets", "pet": "pets",
    "home": "home_decor", "decor": "home_decor", "furniture": "home_decor",
    "lighting": "home_decor",
    "bedding": "bedding", "linens": "bedding",
    "kitchen": "kitchen", "cookware": "kitchen", "drinkware": "kitchen",
    "food": "food", "grocery": "food", "supplements": "food", "beverages": "food",
    "tech": "tech", "electronics": "tech", "gadgets": "tech", "audio": "tech",
    "stationery": "stationery", "craft": "stationery", "crafts": "stationery",
    "office": "stationery",
    "fitness": "fitness", "sports": "fitness", "activewear": "fitness",
    "garden": "garden", "outdoors": "garden", "patio": "garden",
    "storage": "storage", "organization": "storage", "organisation": "storage",
    # Vision-side vocabulary. `reference_analyst` writes `subject.primary_category`
    # in its own words — "home_decor", "seasonal_decor", "kitchenware" — and those
    # strings are now classified too, because `app.pipeline.subject_match` puts the
    # *picture* through this same function to check it shows the same kind of thing
    # as the product. Without these aliases the ghost-lamp photo that started all
    # this resolved to no category hint at all.
    "home_decor": "home_decor", "seasonal_decor": "home_decor",
    "decoration": "home_decor", "decorations": "home_decor",
    "candle": "home_decor", "candles": "home_decor", "lamp": "home_decor",
    "lamps": "home_decor", "wall_art": "home_decor", "ornaments": "home_decor",
    "kitchenware": "kitchen", "tableware": "kitchen", "bakeware": "kitchen",
    "bath": "bedding", "home_textiles": "bedding", "towels": "bedding",
    "plush": "toys", "plushies": "toys", "toys_games": "toys", "board_games": "toys",
    "pet_supplies": "pets", "pet_accessories": "pets",
    "nail_care": "nail_art", "press_on_nails": "nail_art",
    "haircare": "hair", "hair_accessories": "hair",
    "sportswear": "fitness", "gym": "fitness",
    "gardening": "garden", "plants": "garden",
    "shoes_boots": "footwear", "boots": "footwear", "sandals": "footwear",
    "handbag": "bags", "backpack": "bags", "purse": "bags",
    "pyjamas": "apparel", "pajamas": "apparel", "nightwear": "apparel",
}


@dataclass(frozen=True)
class Classification:
    """Which class a product landed in, and on what evidence."""

    product_class: ProductClass
    matched_on: tuple[str, ...]
    confidence: str  # high | medium | low

    @property
    def key(self) -> str:
        return self.product_class.key

    def describe(self) -> str:
        evidence = ", ".join(self.matched_on) if self.matched_on else "no signal"
        return f"{self.product_class.key} ({self.confidence} confidence — {evidence})"


def _hits(keyword: str, text: str) -> bool:
    """
    Whole-word (or whole-phrase) match, tolerating a trailing plural.

    Substring matching is not good enough here: `pot` would fire on "spotted",
    `tee` on "canteen" and `top` on "laptop", which is how a laptop stand ends up
    directed as a blouse.
    """
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}s?(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _weight(keyword: str, base: int) -> int:
    """Multi-word keywords are more specific, so `plant pot` beats `pot`."""
    return base * (1 + keyword.count(" ") + keyword.count("-"))


def classify_product(
    product: dict[str, Any],
    reference_analysis: dict[str, Any] | None = None,
) -> Classification:
    """
    Decide which `ProductClass` a product belongs to.

    Evidence, in descending weight: the product name, the reference image's own
    `subject` classification from Stage 1, the free-text category, then materials
    and key attributes. Stage 1's opinion is used because it is the only signal
    derived from the actual picture — and until now it was computed, stored in
    `reference_analyses.analysis_json`, and read by nothing.

    Never raises and never returns None: an unrecognised product gets `GENERIC`,
    whose brief tells the director to reason from the product itself rather than
    fall back to a clothing scene.
    """
    name = str(product.get("name") or "").lower()
    category = str(product.get("category") or "").lower().strip()
    extras = " ".join(
        str(v).lower() for key in ("materials", "key_attributes", "colors", "seasons")
        for v in (product.get(key) or [])
        if isinstance(product.get(key), list)
    )

    subject_text = ""
    if isinstance(reference_analysis, dict):
        subject = reference_analysis.get("subject")
        if isinstance(subject, dict):
            parts = [
                str(subject.get("primary_category") or ""),
                str(subject.get("secondary_category") or ""),
            ]
            objects = subject.get("objects")
            if isinstance(objects, list):
                parts += [str(o) for o in objects]
            subject_text = " ".join(parts).lower()

    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}

    def _note(key: str, points: int, why: str) -> None:
        scores[key] = scores.get(key, 0) + points
        evidence.setdefault(key, []).append(why)

    # An exact category alias is a strong hint but not a verdict.
    hinted = CATEGORY_HINTS.get(category.replace(" ", "_")) or CATEGORY_HINTS.get(category)
    if hinted:
        _note(hinted, 4, f"category {category!r}")

    for key, pc in CLASSES.items():
        for kw in pc.keywords:
            if name and _hits(kw, name):
                _note(key, _weight(kw, 4), f"name contains {kw!r}")
            if subject_text and _hits(kw, subject_text):
                _note(key, _weight(kw, 3), f"reference subject mentions {kw!r}")
            if category and _hits(kw, category):
                _note(key, _weight(kw, 2), f"category mentions {kw!r}")
            if extras and _hits(kw, extras):
                _note(key, _weight(kw, 1), f"attributes mention {kw!r}")

    if not scores:
        return Classification(GENERIC, (), "low")

    order = list(CLASSES)
    best = max(scores.items(), key=lambda kv: (kv[1], -order.index(kv[0])))
    runner_up = max((v for k, v in scores.items() if k != best[0]), default=0)

    if best[1] >= 8 and best[1] - runner_up >= 3:
        confidence = "high"
    elif best[1] >= 4:
        confidence = "medium"
    else:
        confidence = "low"

    return Classification(CLASSES[best[0]], tuple(evidence[best[0]][:4]), confidence)


# ── what the two downstream stages read ─────────────────────────────────


def resolve_class(key: str | None) -> ProductClass:
    """A class by key, falling back to GENERIC rather than raising."""
    return CLASSES.get(str(key or "").strip().lower(), GENERIC)


def _article(noun: str) -> str:
    return "an" if noun[:1].lower() in "aeiou" else "a"


def subject_line(product: dict[str, Any], klass: ProductClass) -> str:
    """
    The SUBJECT line, naming the product like a person would.

    The compiler used to write `f"{name} — a {category}."`, which produced
    "Two-Piece Ruffled French Maid Halloween Costume Set — a costumes." The class
    noun is grammatical, and it is dropped entirely when the name already says it.
    """
    name = str(product.get("name") or "product").strip()
    lowered = name.lower()
    significant = [w for w in re.split(r"[\s/]+", klass.noun) if len(w) > 3]
    if any(_hits(word, lowered) for word in significant):
        return f"{name}."
    return f"{name} — {_article(klass.noun)} {klass.noun}."


def avoid_text(klass: ProductClass) -> str:
    """
    The AVOID section for this class.

    One frozen list told a toy to avoid `plastic textures` and a skincare bottle to
    avoid `perfect symmetry` and `sterile backgrounds` — the exact look those
    products really have. Lifting a clause is a per-class decision; the four
    clauses in `UNLIFTABLE_AVOID` are not negotiable.
    """
    clauses = klass.avoid_clauses()
    body = ", ".join(clauses)
    return f"AVOID:\n{body[:1].upper()}{body[1:]}."


def format_is_plausible(scene_format: str, klass: ProductClass) -> tuple[bool, str]:
    """
    Whether `scene_format` is believable for this class.

    Replaces the compiler's one hardcoded check — `product_rack` against the
    categories `nails`/`nail_art`/`jewelry` — which could never fire, because the
    only nail product in the library is filed under `beauty`.
    """
    if not scene_format:
        return False, "the scene has no creative_format"
    if scene_format in klass.formats:
        return True, ""
    if scene_format not in CREATIVE_FORMATS:
        return False, (
            f"creative_format {scene_format!r} is not one the system knows; "
            f"expected one of: {', '.join(klass.formats)}"
        )
    return False, (
        f"creative_format {scene_format!r} is not believable for a "
        f"{klass.noun} — expected one of: {', '.join(klass.formats)}"
    )


def director_brief(
    klass: ProductClass,
    classification: Classification | None = None,
) -> str:
    """
    The class-specific block the Scene Director is given.

    This is the fix for the original complaint. The director used to see one fixed
    menu of ten formats — six of them clothing or retail idioms — and five
    motivation examples, four of which were clothing. Whatever the product was, the
    likeliest scene was a person, a mirror or a rail. Now the menu, the physical
    reality and the examples all come from the product's own class, so a toy is
    directed as a toy.
    """
    lines: list[str] = []
    header = f"PRODUCT CLASS: {klass.key} — {klass.noun}"
    if classification is not None:
        header += f"\n  (matched with {classification.confidence} confidence: " + (
            "; ".join(classification.matched_on) or "no explicit signal"
        ) + ")"
    lines.append(header)

    lines.append(
        "CREATIVE FORMAT OPTIONS — choose exactly one, and only from this list. "
        "Anything else is not believable for this kind of product:\n"
        + klass.format_menu()
    )

    physical = [
        f"  Scale: {klass.scale_note}",
        f"  Framing: {klass.framing}",
        f"  Camera height: {klass.camera_height}",
        f"  Human presence must be one of: {', '.join(klass.human_presence)}",
    ]
    if klass.surfaces:
        physical.append(f"  Believable surfaces: {'; '.join(klass.surfaces)}")
    if klass.locations:
        physical.append(f"  Believable locations: {'; '.join(klass.locations)}")
    if klass.product_states:
        physical.append(f"  Believable product states: {'; '.join(klass.product_states)}")
    lines.append("PHYSICAL REALITY OF THIS PRODUCT:\n" + "\n".join(physical))

    if klass.notes:
        lines.append("CLASS RULES:\n" + "\n".join(f"  - {n}" for n in klass.notes))

    if klass.motivations:
        lines.append(
            "capture_motivation examples for THIS kind of product — match their "
            "specificity, do not copy them:\n"
            + "\n".join(f"  - \"{m}\"" for m in klass.motivations)
        )

    return "\n\n".join(lines)


# ── Class-Specific Product Truth Negative Constraints ───────────────────

CLASS_MUST_NOT_INVENT: dict[str, tuple[str, ...]] = {
    "kitchen": (
        "Do not invent extra handles, non-existent lids, pouring spouts, or fictional logos",
        "Do not alter the cookware or kitchenware material, finish, or geometric profile",
        "Do not change the stated enamel color, stainless steel grade, or non-stick surface",
    ),
    "tech": (
        "Do not invent extra ports, buttons, LED lights, dials, or fictional logos",
        "Do not alter the device enclosure material, metallic colorway, or form factor",
        "Do not add fictional screens, antennas, or speculative accessories",
    ),
    "skincare": (
        "Do not alter the bottle shape, pump mechanism, dropper, or cap closure",
        "Do not invent fictional brand names, logos, or pseudo-scientific claims on packaging",
        "Do not change the stated product texture, translucency, or fluid viscosity",
    ),
    "makeup": (
        "Do not alter the compact shape, pan layout, applicator wand, or casing finish",
        "Do not invent fictional branding or alter the stated shade colorway",
        "Do not depict unrealistic cakey CGI finishes; preserve authentic pigment texture",
    ),
    "fragrance": (
        "Do not alter the perfume flacon geometry, atomizer collar, cap, or glass tint",
        "Do not invent extra embellishments, ribbons, or fictional typography on the bottle",
    ),
    "jewelry": (
        "Do not alter the gemstone cut, prong setting, metal karat/finish, or clasp type",
        "Do not invent extra stones, charms, engravings, or speculative chains",
    ),
    "footwear": (
        "Do not alter the sole thickness, tread pattern, eyelet count, or heel height",
        "Do not invent extra straps, buckles, non-existent logos, or change colorway blocks",
    ),
    "bags": (
        "Do not alter the strap drop length, hardware finish, buckle type, or pocket count",
        "Do not invent non-existent zippers, monogram prints, or fictional logos",
    ),
    "apparel": (
        "Do not alter garment neckline, sleeve length, hemline, or pocket placement",
        "Do not invent extra zippers, hoods, belts, straps, or non-existent hardware",
        "Do not change the stated textile composition, knit gauge, or authentic pattern",
    ),
    "costume": (
        "Do not invent extra accessories, frills, or fictional branding",
        "Do not alter the costume silhouette, trim, or stated material components",
    ),
    "home_decor": (
        "Do not alter the object dimensions, material finish, ceramic glaze, or surface pattern",
        "Do not invent extra legs, pedestals, or fictional decorative motifs",
    ),
    "bedding": (
        "Do not alter the weave texture, thread count appearance, hem finish, or pattern scale",
        "Do not invent extra ruffles, embroidery, or buttons not on the product",
    ),
    "toys": (
        "Do not alter the character anatomy, articulation points, molded seams, or safety features",
        "Do not invent non-existent paint apps, decals, or speculative accessories",
    ),
    "fitness": (
        "Do not alter the grip knurling, resistance markings, strap buckles, or structural seams",
        "Do not invent extra digital displays, sensors, or non-existent branding",
    ),
    "food": (
        "Do not alter the food portion, garnish, natural baked crust, or authentic color",
        "Do not depict synthetic plastic-sheen artificial food styling",
    ),
}

GENERIC_MUST_NOT_INVENT: tuple[str, ...] = (
    "Do not add logos, graphics, or branding not on the original product",
    "Do not invent extra parts, accessories, or fictional physical features",
    "Do not alter the product's authentic colorway, silhouette, or material composition",
)


def get_class_must_not_invent(klass: ProductClass | Classification | str | None) -> list[str]:
    """
    Get tailored must_not_invent constraints for this specific product class.
    Prevents apparel constraints ("neckline, sleeve length") from being applied to kitchenware/tech.
    """
    if hasattr(klass, "key"):
        key = klass.key
    elif hasattr(klass, "product_class"):
        key = klass.product_class.key
    else:
        key = str(klass or "").strip().lower()
    key = str(key).strip().lower()
    constraints = CLASS_MUST_NOT_INVENT.get(key)
    if constraints:
        return list(constraints)
    return list(GENERIC_MUST_NOT_INVENT)




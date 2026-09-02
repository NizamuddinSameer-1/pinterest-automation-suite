"""
Does the reference photograph actually show the product this job is selling?

The failure this module exists to prevent, in the operator's words: *"i providd
this refrence product those two ghost type lamp or ehat evrr that ws and see what
flow give me genrted image why pants"*.

Nothing was broken. The reference was a photo of two illuminated ghost figurines
on a mantelpiece and Stage 1 read it correctly — `primary_category: home_decor`,
objects `illuminated ghost figures`, `ceramic vase with branches`, `candlestick
with lit candle`. The job's *product*, though, was `prod_001` "Pumpkin Fleece
Pajama Pants": a seeded demo row that the Creative Lab had silently pre-selected
with `setSelectedProdId(prods[0].id)` and that the operator never chose.

PRE takes the SUBJECT and the PRODUCT TRUTH from the product record and only the
photographic style from the reference, so the two inputs described different
objects and the pipeline faithfully rendered the one it is told is the subject.
Every line of the prompt the operator objected to — `SUBJECT: a clothing item`,
`PRESERVE: black base colour, orange pumpkin print, soft fleece` — is an accurate
reading of that row.

So the seam is here: a reference and a product that describe different kinds of
object must never be combined *silently*. This module puts the picture through the
same taxonomy the product goes through and reports whether the two agree. It never
decides on its own to substitute one for the other — that is the class of bug it
was written to end.

Pure string matching over the Stage 1 analysis: no LLM, no I/O, no `app.config`
import, so the API, the pipeline and the offline verifier can all use it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.pipeline.product_taxonomy import GENERIC, Classification, classify_product

#: Classes whose photographs are near enough that preferring one over the other is
#: a judgement call rather than an obvious mistake — a costume *is* worn like
#: apparel, a serum *is* shot like a moisturiser. A disagreement inside a family is
#: reported and allowed through; a disagreement across families (a lamp against a
#: pair of pyjamas) is refused until the operator says otherwise.
FAMILIES: dict[str, tuple[str, ...]] = {
    "worn": ("apparel", "costume", "footwear", "bags", "jewelry"),
    "beauty": ("makeup", "skincare", "hair", "fragrance", "nail_art"),
    "home": ("home_decor", "bedding", "kitchen", "storage", "garden"),
    "play": ("toys", "baby", "pets"),
    "gear": ("tech", "stationery", "fitness"),
    "consumable": ("food",),
}

#: Confidences that count as an opinion. `low` means the taxonomy is guessing, and
#: a guess must not block a run.
CONFIDENT = ("high", "medium")


def family_of(class_key: str) -> str | None:
    """The family a product class belongs to, or None if it has no near neighbours."""
    for family, members in FAMILIES.items():
        if class_key in members:
            return family
    return None


def _subject(analysis: Any) -> dict[str, Any]:
    if isinstance(analysis, dict):
        subject = analysis.get("subject")
        if isinstance(subject, dict):
            return subject
    return {}


def reference_objects(analysis: Any) -> tuple[str, ...]:
    """What Stage 1 says is visible in the reference photograph."""
    objects = _subject(analysis).get("objects")
    if not isinstance(objects, list):
        return ()
    return tuple(str(o).strip() for o in objects if str(o).strip())


def reference_categories(analysis: Any) -> tuple[str, str]:
    """Stage 1's own `(primary, secondary)` category words for the photograph."""
    subject = _subject(analysis)
    return (
        str(subject.get("primary_category") or "").strip(),
        str(subject.get("secondary_category") or "").strip(),
    )


def reference_textures(analysis: Any) -> tuple[str, ...]:
    """The textures Stage 1 could see. Also the fallback material list for a draft."""
    materials = analysis.get("materials") if isinstance(analysis, dict) else None
    if isinstance(materials, dict):
        textures = materials.get("primary_textures")
        if isinstance(textures, list):
            return tuple(str(t).strip() for t in textures if str(t).strip())
    return ()


def reference_as_product(analysis: Any) -> dict[str, Any]:
    """
    The photograph, described in the shape `classify_product` reads.

    Deliberately built from what the *vision model* saw and nothing else: the
    operator-typed `category` on the reference row is not consulted here, because
    the row that started this was a photo of two ghost lamps filed by hand under
    `costumes`. The picture is the evidence.
    """
    objects = reference_objects(analysis)
    primary, secondary = reference_categories(analysis)
    return {
        "name": ", ".join(objects[:6]),
        "category": primary.lower().replace(" ", "_"),
        "key_attributes": [secondary] if secondary else [],
        "materials": list(reference_textures(analysis))[:4],
    }


def classify_reference(analysis: Any) -> Classification | None:
    """
    Which product class the reference photograph itself looks like.

    None when there is no analysis to read — an unanalysed reference cannot be
    generated from anyway (`/generate` returns 409 for the missing Visual DNA), so
    there is nothing to compare.
    """
    if not isinstance(analysis, dict) or not analysis:
        return None
    return classify_product(reference_as_product(analysis), analysis)


@dataclass(frozen=True)
class SubjectMatch:
    """Whether the picture and the product describe the same kind of object."""

    product_class: str
    reference_class: str
    reference_objects: tuple[str, ...]
    product_confidence: str
    reference_confidence: str
    agrees: bool          # same class
    blocking: bool        # different families, both classifications confident
    message: str

    def summary(self) -> str:
        seen = ", ".join(self.reference_objects[:4]) or "nothing nameable"
        return (
            f"reference looks like {self.reference_class} "
            f"({self.reference_confidence}; {seen}) / "
            f"product classifies as {self.product_class} ({self.product_confidence})"
        )


#: How to get out of a block, stated in the message itself. A refusal that does not
#: say what to do next is how the earlier 409 ("no Visual DNA") wasted an afternoon.
#: The button is quoted by its exact label — the first version said "Use this
#: reference as the product" while the Creative Lab's button read "Use this photo as
#: the product", so the instruction named a control that did not exist.
_WAYS_OUT = (
    "Fix it in one of three ways: (1) pick the product this photograph actually "
    "shows in panel 2; (2) press \"Use this photo as the product\" in panel 2 to "
    "draft a product from the photograph itself; or (3) if the photo is only a "
    "style reference and the product is right, choose OK / \"generate anyway\" — "
    "that sends allow_subject_mismatch=true and the reference is used for lighting, "
    "framing and mood only."
)


def check_subject_match(
    product: dict[str, Any],
    reference_analysis: Any,
) -> SubjectMatch:
    """
    Compare the photograph's own class against the product's.

    The product is classified from the product record *alone*. Passing the
    reference analysis in as well (which `classify_product` accepts, and which the
    Scene Director does on purpose) would let the picture drag the product's class
    toward itself and hide precisely the disagreement being looked for.
    """
    prod = classify_product(product)
    ref = classify_reference(reference_analysis)
    name = str(product.get("name") or "this product")

    if ref is None:
        return SubjectMatch(
            product_class=prod.key,
            reference_class="unknown",
            reference_objects=(),
            product_confidence=prod.confidence,
            reference_confidence="none",
            agrees=True,
            blocking=False,
            message="The reference has no Stage 1 analysis, so its subject cannot be "
                    "compared with the product. Nothing is blocked on that basis.",
        )

    objects = reference_objects(reference_analysis)
    agrees = ref.key == prod.key
    ref_family, prod_family = family_of(ref.key), family_of(prod.key)
    undecidable = (
        ref.product_class is GENERIC
        or prod.product_class is GENERIC
        or ref.confidence not in CONFIDENT
        or prod.confidence not in CONFIDENT
    )
    blocking = (
        not agrees
        and not undecidable
        and (ref_family is None or prod_family is None or ref_family != prod_family)
    )

    seen = ", ".join(objects[:5]) or "no nameable objects"
    if agrees:
        message = (
            f"The reference and '{name}' are both {prod.key}. Subject and style agree."
        )
    elif blocking:
        message = (
            "The reference photograph and the selected product are not the same kind "
            f"of thing. Stage 1 read the photograph as {ref.key} (it saw: {seen}), "
            f"but '{name}' classifies as {prod.key}. PRE takes the SUBJECT and the "
            "PRODUCT TRUTH from the product and only the photographic style from the "
            "reference, so generating now would produce pins of the product and not "
            "of the thing in your photo — that is exactly how a photo of two ghost "
            f"lamps became four mirror selfies of pyjama pants. {_WAYS_OUT}"
        )
    else:
        message = (
            f"The reference looks like {ref.key} (it saw: {seen}) while '{name}' "
            f"classifies as {prod.key}. Those are close enough to shoot the same way, "
            "so this is allowed — but if the photograph is the product, draft the "
            "product from it rather than borrowing a similar row."
        )

    return SubjectMatch(
        product_class=prod.key,
        reference_class=ref.key,
        reference_objects=objects,
        product_confidence=prod.confidence,
        reference_confidence=ref.confidence,
        agrees=agrees,
        blocking=blocking,
        message=message,
    )



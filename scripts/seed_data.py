"""
Seed initial benchmark campaign and product catalog data into SQLite.
"""

import asyncio
import json
from datetime import datetime, timezone

from app.database import async_session, init_db
from app.models.models import Campaign, Product, Reference, VisualDNA
from app.services.vault_sync import sync_product_node, sync_reference_node


async def seed():
    await init_db()
    async with async_session() as db:
        # Check if campaign already exists
        camp = Campaign(
            id="camp_halloween_2026",
            name="Fall Halloween 2026",
            theme="Halloween",
            market="US",
            niche="fashion_and_trends",
            status="active",
        )
        db.add(camp)

        # 1. Product: Pumpkin Fleece Pajama Pants
        prod1 = Product(
            id="prod_001",
            campaign_id=camp.id,
            name="Pumpkin Fleece Pajama Pants",
            brand="CozySeason",
            merchant="Target",
            product_url="https://target.example.com/pumpkin-pjs",
            affiliate_url="https://affiliate.example.com/pumpkin-pjs",
            price=19.99,
            currency="USD",
            category="sleepwear",
            seasons=json.dumps(["fall", "halloween"]),
            colors=json.dumps(["black", "orange"]),
            materials=json.dumps(["fleece"]),
            key_attributes=json.dumps(["pumpkin pattern", "relaxed fit", "elastic waist"]),
            product_truth_json=json.dumps({
                "must_preserve": [
                    "black base color",
                    "orange pumpkin/jack-o-lantern print",
                    "soft fleece fabric texture",
                    "relaxed fit pant silhouette"
                ],
                "must_not_invent": [
                    "hood",
                    "metal zipper pockets",
                    "brand logo embroidery",
                    "different pattern or colors"
                ],
                "allowed_scene_variations": [
                    "hanging on clothing rack in store",
                    "held casually by shopper",
                    "folded on bedside table",
                    "worn naturally in cozy home"
                ]
            }),
            availability="in_stock",
        )
        db.add(prod1)

        # 2. Product: Ghost & Bat Fuzzy Crew Socks
        prod2 = Product(
            id="prod_002",
            campaign_id=camp.id,
            name="Halloween Ghost Fuzzy Crew Socks",
            brand="SpookyFeet",
            merchant="Amazon",
            product_url="https://amazon.example.com/ghost-socks",
            affiliate_url="https://amzn.to/ghost-socks",
            price=9.99,
            currency="USD",
            category="accessories",
            seasons=json.dumps(["fall", "halloween"]),
            colors=json.dumps(["lavender", "white", "black"]),
            materials=json.dumps(["microfiber knit"]),
            key_attributes=json.dumps(["fuzzy high-pile texture", "ghost cartoon print"]),
            product_truth_json=json.dumps({
                "must_preserve": [
                    "lavender pastel base color",
                    "white cartoon ghost print",
                    "high-pile fluffy microfiber texture",
                    "ribbed crew cuff"
                ],
                "must_not_invent": [
                    "lace trim",
                    "silk sheen",
                    "mismatched heel color"
                ],
                "allowed_scene_variations": [
                    "worn on feet resting on bedroom rug",
                    "held in shopping basket",
                    "laid flat on wooden floor"
                ]
            }),
            availability="in_stock",
        )
        db.add(prod2)

        # 3. Product: Cat-Eye Velvet Press-On Nails
        prod3 = Product(
            id="prod_003",
            campaign_id=camp.id,
            name="Cat-Eye Velvet Press-On Nails",
            brand="GlamClaws",
            merchant="Etsy",
            product_url="https://etsy.example.com/cat-eye-nails",
            affiliate_url="https://affiliate.example.com/cat-eye-nails",
            price=14.50,
            currency="USD",
            category="beauty",
            seasons=json.dumps(["fall", "halloween"]),
            colors=json.dumps(["emerald green", "magnetic black"]),
            materials=json.dumps(["gel polish"]),
            key_attributes=json.dumps(["almond shape", "velvet magnetic shift", "glossy topcoat"]),
            product_truth_json=json.dumps({
                "must_preserve": [
                    "medium almond shape",
                    "magnetic emerald-to-black velvet shifting shimmer",
                    "high-gloss gel reflection"
                ],
                "must_not_invent": [
                    "stiletto long shape",
                    "matte topcoat",
                    "3D rhinestones"
                ],
                "allowed_scene_variations": [
                    "human hand resting on desk showing completed manicure",
                    "holding warm autumn coffee mug",
                    "natural hand pose against fabric"
                ]
            }),
            availability="in_stock",
        )
        db.add(prod3)

        # Sample Reference
        ref1 = Reference(
            id="ref_001",
            campaign_id=camp.id,
            image_path="data/references/ref_001.jpg",
            trend_label="Halloween",
            category="sleepwear",
            status="analyzed",
        )
        db.add(ref1)

        dna1 = VisualDNA(
            reference_id=ref1.id,
            version=1,
            dna_json=json.dumps({
                "capture_identity": {
                    "type": "casual_ugc_smartphone",
                    "professionalism": "very_low",
                    "spontaneity": "high"
                },
                "composition_dna": {
                    "centering": "slightly_off_center",
                    "framing": "imperfect",
                    "crop": "natural",
                    "camera_height": "human_standing"
                },
                "environment_dna": {
                    "real_world_context": True,
                    "clutter": "moderate_to_high",
                    "background_activity": "moderate"
                },
                "lighting_dna": {
                    "source": "retail_fluorescent",
                    "contrast": "low",
                    "warmth": "neutral_to_cool"
                },
                "camera_dna": {
                    "smartphone_behavior": True,
                    "sharpness": "moderate",
                    "noise": "subtle",
                    "hdr": "restrained"
                },
                "material_dna": {
                    "texture_visibility": "high",
                    "surface_imperfection": "moderate"
                },
                "realism_markers": {
                    "imperfection_level": "moderate",
                    "anti_studio": True,
                    "anti_cinematic": True
                }
            }),
        )
        db.add(dna1)

        await db.commit()
        print("Initial benchmark data seeded successfully!")


if __name__ == "__main__":
    asyncio.run(seed())

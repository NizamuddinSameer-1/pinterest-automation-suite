---
aliases:
  - Product Truth
  - Truth Standards
tags:
  - product_truth
  - compliance
  - fidelity
created: 2026-08-20
updated: 2026-08-20
---

# 📐 Product Truth Standards

Product Truth is the system's enforcement mechanism that guarantees the generated Pinterest image remains **100% faithful to the actual physical affiliate product** being promoted.

---

## 🚫 The #1 Affiliate Marketing Failure Mode
Most AI affiliate campaigns fail because the generator invents a fantasy version of the product:
- Inventing pockets, hoods, or zippers that don't exist
- Changing the pattern scale or color hue
- Altering the material (e.g. rendering cheap polyester as heavy luxury cashmere)
- Adding nonexistent luxury branding or embellishments

When a Pinterest user clicks the affiliate link and sees a different product on Amazon/Target, they bounce immediately without purchasing.

---

## 🛡️ The Product Truth Schema

Every product registered in the PRE system contains a strict `ProductTruth` constraint record:

```json
{
  "must_preserve": [
    "Jet black fleece fabric base",
    "Bright orange carved pumpkin pattern repeat",
    "Elastic waistband with matching black drawstrings",
    "Relaxed-fit pajama pant silhouette"
  ],
  "must_not_invent": [
    "Hooded top or matching sweatshirt",
    "Side pockets with metal zippers",
    "Brand logo embroidery",
    "Different Halloween characters (ghosts, bats)"
  ],
  "allowed_scene_variations": [
    "Hanging naturally from a plastic retail hanger",
    "Held casually in hand by an in-store shopper",
    "Folded neatly on a wooden bedside table",
    "Worn in a cozy home environment"
  ]
}
```

---

## 🔗 Related Notes
- [[🛍️ Product Catalog & Truth Registry]]
- [[🎨 Prompt Engineering Playbook]]
- [[🔍 Realism Critic Defect Taxonomy]]

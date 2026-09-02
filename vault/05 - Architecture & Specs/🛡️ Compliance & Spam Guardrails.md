---
aliases:
  - Compliance
  - Spam Guardrails
  - Pinterest Policy
tags:
  - compliance
  - policy
  - affiliate
created: 2026-08-20
updated: 2026-08-20
---

# 🛡️ Compliance & Spam Guardrails

Pinterest Community Guidelines and FTC affiliate disclosure compliance requirements embedded into the PRE system.

---

## 📜 Key Pinterest Affiliate Policies

1. **Originality & Unique Value:** Affiliate pins cannot be direct copies or generic duplicate spam. Each pin must have original photography and distinct value.
2. **Transparent Commercial Relationship:** Clear disclosure (`#affiliate`, `affiliate link`, or `paid link`) must accompany the pin description.
3. **Generative AI Transparency:** Pins created with generative AI tools must store `is_ai_generated: true` in metadata and comply with community standard content policies.
4. **No Spam or Engagement Farming:** Prohibits automated mass-posting (>50 pins/hr), artificial click pods, or misleading destination redirects.

---

## 📋 The Automated Pin Compliance Check Record

Every exported pin ZIP bundle includes a `COMPLIANCE.json` file structured as:

```json
{
  "is_original_content": true,
  "is_affiliate": true,
  "affiliate_disclosed": true,
  "disclosure_text": "affiliate link",
  "is_ai_generated": true,
  "ai_generation_labeled": true,
  "product_truth_verified": true,
  "originality_checked": true,
  "no_misleading_claims": true,
  "compliant": true
}
```

---

## 🔗 Related Notes
- [[📋 Redesigned PRD v2]]
- [[📐 Product Truth Standards]]
- [[🗺️ System Map & Architecture MOC]]

---
aliases:
  - Defect Taxonomy
  - Realism Critic
tags:
  - realism_critic
  - defects
  - quality_gate
created: 2026-08-20
updated: 2026-08-20
---

# 🔍 Realism Critic Defect Taxonomy

The Realism Critic (`app/pipeline/realism_critic.py`) evaluates generated visuals across 3 categorical dimensions and identifies defects tagged with explicit severity levels.

---

## 🚦 The 3 Categorical Evaluation Questions

```
                   ┌──────────────────────────────────────────────┐
                   │          REALISM CRITIC EVALUATION           │
                   └──────────────────────┬───────────────────────┘
                                          │
         ┌────────────────────────────────┼────────────────────────────────┐
         ▼                                ▼                                ▼
┌─────────────────┐              ┌─────────────────┐              ┌─────────────────┐
│ 1. AUTHENTICITY │              │ 2. PRODUCT TRUTH│              │ 3. ORIGINALITY  │
│  • AUTHENTIC    │              │  • FAITHFUL     │              │  • ORIGINAL     │
│  • PLAUSIBLE    │              │  • MINOR_DRIFT  │              │  • DERIVATIVE   │
│  • SYNTHETIC    │              │  • MISREPRESENT │              │  • COPY         │
│  • BROKEN       │              └─────────────────┘              └─────────────────┘
└─────────────────┘
```

---

## 🛑 Defect Severity Classification

| Severity Level | Definition | Impact on Decision | Common Examples |
| :--- | :--- | :---: | :--- |
| **⛔ BLOCKER** | Obvious physical/anatomical impossibility or product distortion | **Auto-REWORK** (Cannot Pass) | 6 fingers on hand, melted knuckles, floating garment in midair, distorted logo, broken hanger |
| **⚠️ MAJOR** | Synthetic visual tells or structural oddities | **Strong REWORK** recommendation | Repetitive pattern duplication on rack, impossible background perspective, plastic skin sheen |
| **ℹ️ MINOR** | Subtle ambient flaws that often pass as UGC quirks | **Can Pass** with warning | Slight blur on background price tag, minor edge grain inconsistency |

---

## 🔄 The Targeted Rework Engine Formula

When a generation receives a `REWORK` verdict, the system generates a **targeted revision prompt** instead of starting from scratch:

```text
PRESERVE: Product base color, silhouette, rack environment, overall lighting.
FIX: The shopper's hand has distorted knuckles and the background shelves repeat identically.
AVOID: Changing the product fleece material, shifting to studio background, or over-smoothing skin.
```

---

## 🔗 Related Notes
- [[🎨 Prompt Engineering Playbook]]
- [[🧬 Visual DNA Knowledge Base]]
- [[🐛 Bug Tracker MOC]]

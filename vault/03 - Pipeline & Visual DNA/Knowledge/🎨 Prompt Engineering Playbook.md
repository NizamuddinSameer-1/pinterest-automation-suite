---
aliases:
  - Prompt Playbook
  - Prompt Structure
tags:
  - prompt_engineering
  - compiler
  - flow
created: 2026-08-20
updated: 2026-08-20
---

# 🎨 Prompt Engineering Playbook

The exact compiler formula, section architecture, banned phrases, and negative constraints for generating Google Flow prompts.

---

## 🧱 The 13-Section Prompt Structure

Every compiled prompt produced by `app/pipeline/prompt_compiler.py` follows this strict sequential hierarchy:

```text
1.  PHOTOGRAPHIC INTENT   ──► The believable human motivation ("Why this photo exists")
2.  SUBJECT               ──► Product name + natural category designation
3.  PRODUCT TRUTH         ──► PRESERVE exact features; DO NOT INVENT false details
4.  SCENE                 ──► Location context, human action, ambient background
5.  HUMAN INTERACTION     ──► Human presence (hands, outfit check) & camera holding
6.  CAMERA                ──► Smartphone sensor specs, subtle noise, restrained HDR
7.  COMPOSITION           ──► Imperfect framing, slight off-center, human height
8.  LIGHTING              ──► Overhead retail fluorescent / ambient indoor daylight
9.  MATERIALS             ──► Real fiber weave, texture imperfections, skin pores
10. ENVIRONMENT           ──► Store aisles, clothes racks, price tags, natural clutter
11. REALISM               ──► Anti-studio directives, natural scaling & perspective
12. ORIGINALITY           ──► Explicit instruction to construct a brand new angle
13. AVOID                 ──► Negative constraints (studio, 3D CGI, plastic skin, etc.)
```

---

## 🚫 The Auto-Stripped Banned Words Filter

The prompt compiler strictly forbids and strips the following buzzwords:

| Banned Keyword | Why It Fails on Pinterest |
| :--- | :--- |
| `8K`, `Masterpiece` | Causes over-sharpened plastic CGI rendering |
| `Cinematic Lighting` | Adds fake movie grading and dramatic spotlight shadows |
| `Hyper Realistic` | Triggers high-contrast synthetic edge halos |
| `Award Winning Photography` | Causes sterile commercial catalog staging |
| `Unreal Engine`, `Octane Render` | Forces 3D video game aesthetic |

---

## 📋 Standard Negative Constraint Block

```text
AVOID:
Studio product photography, catalog styling, cinematic lighting, extreme HDR,
artificial bokeh, excessive sharpness, plastic textures, sterile backgrounds,
perfect symmetry, CGI appearance, impossible object geometry, malformed anatomy,
floating objects, or invented product features.
```

---

## 🔗 Related Notes
- [[🧬 Visual DNA Knowledge Base]]
- [[🔍 Realism Critic Defect Taxonomy]]
- [[🧪 Experiment & DNA MOC]]

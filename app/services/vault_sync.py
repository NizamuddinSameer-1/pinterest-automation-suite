"""
Pinterest Realism Engine — Obsidian Vault Real-Time Synchronization Service.

Automatically mirrors all live database models, pipeline stages, critiques,
prompts, and runtime exceptions directly into the Obsidian /vault markdown graph.

Every entity is linked bidirectionally using [[WikiLinks]], frontmatter tags,
and status metadata so Obsidian Graph View and Dashboards update instantly.
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("pre.vault_sync")

VAULT_PATH = Path("./vault")


#: Vault taxonomy. Auto-generated notes are filed into the sub-folder that
#: matches their type; the flat top-level folders were one level deep for every
#: kind of node, which put 115 pin drafts in the same folder as the campaign
#: notes you actually navigate by.
FOLDER_MOCS = VAULT_PATH / "00 - Dashboard & MOCs"
FOLDER_DEV_LOGS = VAULT_PATH / "01 - Dev Logs & History"
FOLDER_BUGS = VAULT_PATH / "02 - Bugs & Issues"
FOLDER_BUGS_ACTIVE = FOLDER_BUGS / "Active"
FOLDER_BUGS_AUTO = FOLDER_BUGS / "_Archive - Auto Bugs"
FOLDER_DNA = VAULT_PATH / "03 - Pipeline & Visual DNA"
FOLDER_DNA_KNOWLEDGE = FOLDER_DNA / "Knowledge"
FOLDER_DNA_REFS = FOLDER_DNA / "References"
FOLDER_COMMERCE = VAULT_PATH / "04 - Campaigns & Products"
FOLDER_CAMPAIGNS = FOLDER_COMMERCE / "Campaigns"
FOLDER_PRODUCTS = FOLDER_COMMERCE / "Products"
FOLDER_PINS = FOLDER_COMMERCE / "Pins"
FOLDER_SPECS = VAULT_PATH / "05 - Architecture & Specs"
FOLDER_IDEAS = VAULT_PATH / "06 - Ideas & Future Backlog"
FOLDER_TEMPLATES = VAULT_PATH / "07 - Templates"
FOLDER_NODES = VAULT_PATH / "08 - Live Generation Nodes"
FOLDER_JOBS = FOLDER_NODES / "Jobs"
FOLDER_CRITIQUES = FOLDER_NODES / "Critiques"
FOLDER_ARCHIVE = VAULT_PATH / "09 - Archive"


def _ensure_vault_dirs() -> None:
    """Ensure all required vault folders exist."""
    folders = [
        FOLDER_MOCS,
        FOLDER_DEV_LOGS,
        FOLDER_BUGS,
        FOLDER_BUGS_ACTIVE,
        FOLDER_BUGS_AUTO,
        FOLDER_DNA,
        FOLDER_DNA_KNOWLEDGE,
        FOLDER_DNA_REFS,
        FOLDER_COMMERCE,
        FOLDER_CAMPAIGNS,
        FOLDER_PRODUCTS,
        FOLDER_PINS,
        FOLDER_SPECS,
        FOLDER_IDEAS,
        FOLDER_TEMPLATES,
        FOLDER_NODES,
        FOLDER_JOBS,
        FOLDER_CRITIQUES,
        FOLDER_ARCHIVE,
    ]
    for f in folders:
        f.mkdir(parents=True, exist_ok=True)


# YAML frontmatter tags must NOT carry a leading "#". Obsidian reads a
# frontmatter entry of "#state/pass" as a tag literally named "#state/pass",
# which lands in the tag pane as its own broken tag instead of nesting under
# "state". The "#" belongs to inline body tags only.
def _slugify(text: str) -> str:
    """Sanitize title for filename."""
    return re.sub(r'[\\/*?:"<>|]', "", text).strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _campaign_link(campaign_name: str | None = None, trend_label: str | None = None) -> str:
    """
    Wikilink to the campaign note for this job.

    Every sync function used to fall back to a literal
    `[[🎃 Campaign - Fall Halloween 2026]]`, so any job without a campaign was
    filed under the one seasonal test campaign — and because the emoji prefix
    did not match the note the campaign sync itself writes, the vault ended up
    with two separate notes for the same campaign
    (`Campaign - Fall Halloween 2026.md` and `🎃 Campaign - Fall Halloween 2026.md`).
    No emoji, no hardcoded season: campaign, else trend, else Unassigned.
    """
    if campaign_name:
        return f"[[Campaign - {_slugify(campaign_name)}]]"
    if trend_label:
        return f"[[Campaign - {_slugify(trend_label)}]]"
    return "[[Campaign - Unassigned]]"


# ─────────────────────────────────────────────────
# 1. Real-Time Reference & Visual DNA Sync
# ─────────────────────────────────────────────────
def sync_reference_node(
    reference_id: str,
    trend_label: str | None,
    category: str | None,
    image_path: str,
    analysis: dict[str, Any] | None,
    visual_dna: dict[str, Any] | None,
    campaign_name: str | None = None,
) -> Path:
    """Creates or updates a real-time Reference node in the Obsidian Vault."""
    _ensure_vault_dirs()
    filename = f"Ref - {reference_id}.md"
    file_path = FOLDER_DNA_REFS / filename

    campaign_link = _campaign_link(campaign_name, trend_label)
    trend_tag = f"trend/{trend_label.lower()}" if trend_label else "trend/general"
    category_tag = f"category/{category.lower()}" if category else "category/unassigned"

    content = f"""---
node_type: reference
reference_id: "{reference_id}"
trend: "{trend_label or 'N/A'}"
category: "{category or 'N/A'}"
created: "{_now_iso()}"
tags:
  - reference/live
  - {trend_tag}
  - {category_tag}
---

# 📸 Reference Node: {reference_id}

- **Campaign:** {campaign_link}
- **Trend Topic:** {trend_label or 'Unassigned'}
- **Category:** {category or 'General'}
- **Source Image:** `{image_path}`
- **Last Sync:** `{_now_iso()}`

---

## 🔍 Stage 1: Multimodal Vision Analysis
"""
    if analysis:
        content += f"""
```json
{json.dumps(analysis, indent=2)}
```
"""
    else:
        content += "\n*Pending vision analysis via Gemini AI Studio...*\n"

    content += """
---

## 🧬 Stage 2: Extracted Stable Visual DNA
"""
    if visual_dna:
        content += f"""
```json
{json.dumps(visual_dna, indent=2)}
```
"""
    else:
        content += "\n*Pending Visual DNA extraction...*\n"

    content += f"""
---

## 🔗 Graph Relationships & Backlinks
- [[🗺️ System Map & Architecture MOC]]
- [[🧬 Visual DNA Knowledge Base]]
- {campaign_link}
"""

    file_path.write_text(content, encoding="utf-8")
    logger.info("Obsidian Vault synced Reference Node: %s", file_path)
    return file_path


# ─────────────────────────────────────────────────
# 2. Real-Time Product & Product Truth Sync
# ─────────────────────────────────────────────────
def sync_product_node(
    product_id: str,
    name: str,
    category: str | None,
    brand: str | None,
    merchant: str | None,
    price: float | None,
    affiliate_url: str | None,
    product_truth: dict[str, Any] | None,
    campaign_name: str | None = None,
) -> Path:
    """Creates or updates a real-time Product & Truth node in the Obsidian Vault."""
    _ensure_vault_dirs()
    safe_name = _slugify(name)
    filename = f"Product - {safe_name}.md"
    file_path = FOLDER_PRODUCTS / filename

    campaign_link = _campaign_link(campaign_name)
    cat_tag = f"category/{category.lower()}" if category else "category/general"

    must_preserve = product_truth.get("must_preserve", []) if product_truth else []
    must_not_invent = product_truth.get("must_not_invent", []) if product_truth else []
    variations = product_truth.get("allowed_scene_variations", []) if product_truth else []

    preserve_list = "\n".join([f"- [x] {item}" for item in must_preserve]) or "*None registered yet.*"
    not_invent_list = "\n".join([f"- 🚫 {item}" for item in must_not_invent]) or "*None registered yet.*"
    variations_list = "\n".join([f"- 🎬 {item}" for item in variations]) or "*None registered yet.*"

    content = f"""---
node_type: product
product_id: "{product_id}"
name: "{name}"
category: "{category or 'general'}"
merchant: "{merchant or 'N/A'}"
price: {price or 0.00}
affiliate_link: "{affiliate_url or ''}"
created: "{_now_iso()}"
tags:
  - product/active
  - {cat_tag}
---

# 🛍️ Product Node: {name}

- **Product ID:** `{product_id}`
- **Brand / Merchant:** {brand or 'N/A'} / {merchant or 'N/A'}
- **Category:** {category or 'General'}
- **Retail Price:** `${price or 0.00} USD`
- **Affiliate Destination:** [{affiliate_url or 'No Link'}]({affiliate_url or '#'})
- **Campaign Association:** {campaign_link}
- **Last Sync:** `{_now_iso()}`

---

## 🛡️ Product Truth Constraints

### 🔒 Must Preserve
{preserve_list}

### 🚫 Must NOT Invent (Anti-Hallucination)
{not_invent_list}

### 🎬 Allowed Scene Variations
{variations_list}

---

## 🔗 Graph Relationships & Backlinks
- [[📐 Product Truth Standards]]
- [[🛍️ Product Catalog & Truth Registry]]
- {campaign_link}
"""

    file_path.write_text(content, encoding="utf-8")
    logger.info("Obsidian Vault synced Product Node: %s", file_path)
    return file_path


# ─────────────────────────────────────────────────
# 3. Real-Time Generation Job & Prompt Sync
# ─────────────────────────────────────────────────
def sync_job_node(
    job_id: str,
    reference_id: str,
    product_name: str,
    current_state: str,
    scene: dict[str, Any] | None,
    prompt_text: str | None,
    prompt_version: int = 1,
    is_rework: bool = False,
    rework_instruction: str | None = None,
    campaign_name: str | None = None,
) -> Path:
    """Creates or updates a real-time Generation Job Node linking all pipeline steps."""
    _ensure_vault_dirs()
    filename = f"Job - {job_id}.md"
    file_path = FOLDER_JOBS / filename

    ref_link = f"[[Ref - {reference_id}]]"
    prod_link = f"[[Product - {_slugify(product_name)}]]"
    campaign_link = _campaign_link(campaign_name)
    state_tag = f"state/{current_state.lower()}"

    content = f"""---
node_type: generation_job
job_id: "{job_id}"
reference_id: "{reference_id}"
product_name: "{product_name}"
state: "{current_state}"
prompt_version: {prompt_version}
is_rework: {str(is_rework).lower()}
updated: "{_now_iso()}"
tags:
  - job/live
  - {state_tag}
---

# ⚙️ Generation Job Node: {job_id}

- **Current Lifecycle State:** `{current_state}`
- **Reference Style:** {ref_link}
- **Product Subject:** {prod_link}
- **Campaign:** {campaign_link}
- **Prompt Version:** `v{prompt_version}` {'*(Targeted Rework Revision)*' if is_rework else ''}
- **Last Sync:** `{_now_iso()}`

---

## 🎬 Stage 3: Scene Director Scenario
"""
    if scene:
        content += f"""
- **Format:** `{scene.get('creative_format', 'N/A')}`
- **Motivation:** *"{scene.get('capture_motivation', 'N/A')}"*
- **Location:** {scene.get('location', 'N/A')}
- **Human Action:** {scene.get('action', 'N/A')}
- **Camera Position:** {scene.get('camera_position', 'N/A')}
- **Background Elements:** {', '.join(scene.get('background_elements', []))}
"""
    else:
        content += "\n*Pending scene generation...*\n"

    content += """
---

## ✍️ Stage 4: Compiled Google Flow Prompt
"""
    if prompt_text:
        content += f"""
```text
{prompt_text}
```
"""
    else:
        content += "\n*Pending prompt compilation...*\n"

    if is_rework and rework_instruction:
        content += f"""
---

## 🔧 Targeted Rework Directive
```text
{rework_instruction}
```
"""

    content += f"""
---

## 🔗 Graph Relationships & Backlinks
- {ref_link}
- {prod_link}
- {campaign_link}
- [[🎨 Prompt Engineering Playbook]]
- [[🗺️ System Map & Architecture MOC]]
"""

    file_path.write_text(content, encoding="utf-8")
    logger.info("Obsidian Vault synced Job Node: %s", file_path)
    return file_path


# ─────────────────────────────────────────────────
# 4. Real-Time Critique & Quality Gate Sync
# ─────────────────────────────────────────────────
def sync_critique_node(
    job_id: str,
    output_id: str,
    image_path: str,
    critique: dict[str, Any],
    decision: str,
    product_name: str | None = None,
) -> Path:
    """Creates a real-time Critique Node in the Obsidian Vault."""
    _ensure_vault_dirs()
    filename = f"Critique - {output_id}.md"
    file_path = FOLDER_CRITIQUES / filename

    decision_tag = "decision/pass" if decision == "PASS" else "decision/rework"
    job_link = f"[[Job - {job_id}]]"
    prod_link = f"[[Product - {_slugify(product_name)}]]" if product_name else ""

    authenticity = critique.get("authenticity", "N/A")
    fidelity = critique.get("product_fidelity", "N/A")
    originality = critique.get("originality", "N/A")
    defects = critique.get("defects", [])
    strengths = critique.get("strengths", [])
    reason = critique.get("decision_reason", "")

    defects_md = ""
    for d in defects:
        sev = d.get("severity", "MINOR")
        badge = "⛔ BLOCKER" if sev == "BLOCKER" else ("⚠️ MAJOR" if sev == "MAJOR" else "ℹ️ MINOR")
        defects_md += f"- **{badge}** (`{d.get('location', 'general')}`): {d.get('description', '')}\n"
    if not defects:
        defects_md = "*No defects detected.*"

    strengths_md = "\n".join([f"- ✅ {s}" for s in strengths]) or "*None listed.*"

    content = f"""---
node_type: critique
output_id: "{output_id}"
job_id: "{job_id}"
decision: "{decision}"
authenticity: "{authenticity}"
product_fidelity: "{fidelity}"
originality: "{originality}"
created: "{_now_iso()}"
tags:
  - critique/live
  - {decision_tag}
---

# 🔎 Realism Critique Node: {output_id}

- **Generation Job:** {job_link} {('(' + prod_link + ')') if prod_link else ''}
- **Evaluated Image:** `{image_path}`
- **Final Decision:** **{decision}**
- **Decision Rationale:** *{reason}*
- **Evaluation Timestamp:** `{_now_iso()}`

---

## 📊 Core Question Ratings

| Dimension | Rating | Description |
| :--- | :---: | :--- |
| **Authenticity** | `{authenticity}` | Plausibility as real-world smartphone photo |
| **Product Truth Fidelity** | `{fidelity}` | Match to actual physical product features |
| **Visual Originality** | `{originality}` | Distinction from original reference framing |

---

## 🛑 Detected Defects
{defects_md}

---

## 🌟 Visual Strengths
{strengths_md}

---

## 🔗 Graph Relationships & Backlinks
- {job_link}
- [[🔍 Realism Critic Defect Taxonomy]]
- [[🧪 Experiment & DNA MOC]]
"""

    file_path.write_text(content, encoding="utf-8")
    logger.info("Obsidian Vault synced Critique Node: %s", file_path)
    return file_path


# ─────────────────────────────────────────────────
# 5. Real-Time Pin Draft & Compliance Sync
# ─────────────────────────────────────────────────
def sync_pin_node(
    pin_id: str,
    job_id: str,
    title: str,
    description: str,
    keywords: list[str] | None,
    destination_url: str | None,
    board_name: str | None,
    status: str,
    product_name: str | None = None,
    live_url: str | None = None,
    scheduled_time: str | None = None,
    campaign_name: str | None = None,
) -> Path:
    """Creates or updates an approved/exported/published Pin Draft node in the vault."""
    _ensure_vault_dirs()
    safe_title = _slugify(title[:40])
    filename = f"Pin - {safe_title} ({pin_id[:8]}).md"
    file_path = FOLDER_PINS / filename

    job_link = f"[[Job - {job_id}]]"
    prod_link = f"[[Product - {_slugify(product_name)}]]" if product_name else ""
    campaign_link = _campaign_link(campaign_name)
    status_tag = f"pin/{status.lower()}"

    kw_list = ", ".join([f"`{k}`" for k in (keywords or [])])

    live_link_row = f"- **Live Pinterest URL:** [{live_url}]({live_url})\n" if live_url else ""
    sched_row = f"- **Scheduled For:** `{scheduled_time}`\n" if scheduled_time else ""

    content = f"""---
node_type: pin_draft
pin_id: "{pin_id}"
job_id: "{job_id}"
title: "{title}"
status: "{status}"
live_url: "{live_url or ''}"
scheduled_time: "{scheduled_time or ''}"
created: "{_now_iso()}"
tags:
  - pin/live
  - {status_tag}
  - affiliate
---

# 📌 Pinterest Pin Node: {title}

- **Status:** `{status.upper()}`
- **Target Board:** `{board_name or 'General'}`
- **Destination URL:** [{destination_url or '#'}]({destination_url or '#'})
{live_link_row}{sched_row}- **Origin Job:** {job_link} {('(' + prod_link + ')') if prod_link else ''}
- **Last Sync:** `{_now_iso()}`

---

## 📝 Pin Copy & Metadata

### Title
> **{title}**

### Description
> {description}

### Search Keywords & Hashtags
{kw_list or '*None*'}

---

## 🛡️ Compliance & Disclosure Checklist
*Nothing below is auto-verified. These were pre-ticked `[x]` by the exporter,
which made every pin note claim a product-catalog match and an originality
check that no code performs. Tick them yourself when you have actually checked.*

- [ ] **Original Content Check:** camera perspective & scene composition differ from the reference
- [ ] **Commercial Disclosure:** affiliate link disclosed in the description
- [ ] **Product Truth Verified:** image matches the physical product (no invented features)
- **AI Content Tagging:** `is_ai_generated: true` is written into the export metadata automatically

---

## 🔗 Graph Relationships & Backlinks
- {job_link}
- [[🛡️ Compliance & Spam Guardrails]]
- {campaign_link}
- [[⚡ n8n Workflow & Pinterest Automation Architecture]]
"""

    file_path.write_text(content, encoding="utf-8")
    logger.info("Obsidian Vault synced Pin Node: %s", file_path)
    return file_path


# ─────────────────────────────────────────────────
# 6. Real-Time Automatic Bug & Exception Logger
# ─────────────────────────────────────────────────
def log_runtime_bug(
    title: str,
    subsystem: str,
    severity: str,
    error: Exception | str,
    context: dict[str, Any] | None = None,
) -> Path:
    """
    Automatically creates an active Bug Issue in `vault/02 - Bugs & Issues/`
    whenever any API handler or pipeline stage encounters an unhandled exception.
    """
    _ensure_vault_dirs()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_title = _slugify(title[:50])
    filename = f"AUTO-BUG-{timestamp} - {safe_title}.md"
    file_path = FOLDER_BUGS_AUTO / filename

    tb_str = traceback.format_exc() if isinstance(error, Exception) else str(error)
    context_str = json.dumps(context or {}, indent=2)

    content = f"""---
id: "AUTO-BUG-{timestamp}"
title: "{title}"
severity: "{severity.lower()}"
status: "open"
subsystem: "{subsystem.lower()}"
created: "{_now_iso()}"
tags:
  - bug/open
  - severity/{severity.lower()}
  - subsystem/{subsystem.lower()}
---

# 🐛 Automated Bug Log: {title}

- **Subsystem:** `{subsystem}`
- **Severity Level:** `{severity.upper()}`
- **Logged At:** `{_now_iso()}`
- **Status:** `🔴 OPEN`

---

## 📋 Exception Stack Trace
```python
{tb_str}
```

---

## 🔍 Request / Execution Context
```json
{context_str}
```

---

## 🩹 Triage Action Plan
- [ ] Inspect root cause in `app/{subsystem}/`
- [ ] Implement retry, exception catch, or payload validation safeguard
- [ ] Verify fix and update status to `#bug/resolved`

---

## 🔗 Related Notes
- [[🐛 Bug Tracker MOC]]
- [[Issues Tracker Index]]
"""

    file_path.write_text(content, encoding="utf-8")
    logger.error("Obsidian Vault auto-logged Bug Issue: %s", file_path)
    return file_path


# ─────────────────────────────────────────────────
# 7. Commerce DNA Vault Sync (Task 10)
# ─────────────────────────────────────────────────
def sync_commerce_node(job_id: str, commerce_dna: dict) -> Path:
    """Write Commerce DNA JSON for a job into the vault.

    Tries `vault/05 - Architecture & Specs/Commerce DNA - {job_id}.md` first
    (the canonical architecture folder) and falls back to `vault/Commerce DNA - {job_id}.md`
    if needed. Returns the Path written. Mirrors `sync_job_node` lifecycle.
    """
    _ensure_vault_dirs()
    # Preferred location per plan
    preferred = VAULT_PATH / "05 - Architecture & Specs" / f"Commerce DNA - {job_id}.md"
    fallback = VAULT_PATH / f"Commerce DNA - {job_id}.md"
    # Use preferred if its parent exists (always after _ensure_vault_dirs), else fallback
    file_path = preferred if preferred.parent.exists() else fallback
    # Ensure parent exists
    file_path.parent.mkdir(parents=True, exist_ok=True)

    content = f"""---
node_type: commerce_dna
job_id: "{job_id}"
created: "{_now_iso()}"
tags:
  - commerce/dna
---

# Commerce DNA - {job_id}

- **Job:** [[Job - {job_id}]]
- **Synced:** `{_now_iso()}`

---

## Commerce DNA Payload

```json
{json.dumps(commerce_dna, indent=2)}
```

---

## Graph Relationships & Backlinks
- [[Job - {job_id}]]
- [[System Map & Architecture MOC]]
- [[Visual DNA Knowledge Base]]
"""

    file_path.write_text(content, encoding="utf-8")
    # Also ensure legacy root location exists for backward compat if preferred was used
    # (optional mirror — only if caller expects vault/Commerce DNA - {job_id}.md)
    # We do not duplicate by default; existence of preferred satisfies spec's "or".
    logger.info("Obsidian Vault synced Commerce DNA Node: %s", file_path)
    return file_path

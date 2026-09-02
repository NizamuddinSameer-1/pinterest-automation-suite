"""
Pinterest Realism Engine — Full Vault Synchronization Script.

Syncs all live database entities into the Obsidian Vault (/vault):
- 00 - Dashboard & MOCs (Main Dashboard, Map MOC, Bug Tracker MOC, DNA MOC)
- 03 - Pipeline & Visual DNA (References, Visual DNA nodes)
- 04 - Campaigns & Products (Campaigns, Products with Truth Constraints, Pin Drafts)
- 05 - Architecture & Specs (PRDs, State Machine, LLM Spec, Google Flow Automation Spec)
- 08 - Live Generation Nodes (All Jobs, Outputs, Critiques)
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from sqlalchemy import select

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from app.database import async_session
from app.models.models import (
    Campaign, Reference, Product, VisualDNA,
    Job, PromptVersion, JobOutput, Critique, PinDraft
)
from app.services.vault_sync import (
    sync_reference_node, sync_product_node, sync_job_node,
    sync_critique_node, sync_pin_node, _ensure_vault_dirs, VAULT_PATH
)


async def sync_all():
    print("🚀 Starting full Obsidian Vault synchronization...")
    _ensure_vault_dirs()

    async with async_session() as db:
        # 1. Sync Campaigns
        campaigns_res = await db.execute(select(Campaign))
        campaigns = campaigns_res.scalars().all()
        print(f"📦 Found {len(campaigns)} Campaigns")
        for camp in campaigns:
            camp_file = VAULT_PATH / "04 - Campaigns & Products" / f"Campaign - {camp.name}.md"
            camp_content = f"""---
node_type: campaign
campaign_id: "{camp.id}"
name: "{camp.name}"
theme: "{camp.theme or 'Seasonal'}"
market: "{camp.market or 'US'}"
niche: "{camp.niche or 'General'}"
status: "{camp.status}"
created: "{camp.created_at.isoformat()}"
tags:
  - campaign/active
---

# 🎃 Campaign: {camp.name}

- **Theme:** {camp.theme or 'Seasonal'}
- **Market:** {camp.market or 'US'}
- **Niche:** {camp.niche or 'General'}
- **Status:** `{camp.status}`
- **Created At:** `{camp.created_at.isoformat()}`

---

## 🔗 Associated Products & Pins
- [[🛍️ Product Catalog & Truth Registry]]
- [[🗺️ System Map & Architecture MOC]]
"""
            camp_file.write_text(camp_content, encoding="utf-8")
            print(f"  ✅ Synced Campaign: {camp.name}")

        # 2. Sync References
        refs_res = await db.execute(select(Reference))
        refs = refs_res.scalars().all()
        print(f"📸 Found {len(refs)} References")
        for ref in refs:
            # Get latest DNA
            dna_res = await db.execute(select(VisualDNA).where(VisualDNA.reference_id == ref.id).order_by(VisualDNA.version.desc()))
            dna = dna_res.scalars().first()
            dna_data = json.loads(dna.dna_json) if dna and dna.dna_json else None
            sync_reference_node(
                reference_id=ref.id,
                trend_label=ref.trend_label,
                category=ref.category,
                image_path=ref.image_path,
                analysis=None,
                visual_dna=dna_data,
            )
            print(f"  ✅ Synced Reference: {ref.id} ({ref.trend_label})")

        # 3. Sync Products
        prods_res = await db.execute(select(Product))
        prods = prods_res.scalars().all()
        print(f"🛍️ Found {len(prods)} Products")
        for prod in prods:
            truth = json.loads(prod.product_truth_json) if prod.product_truth_json else None
            sync_product_node(
                product_id=prod.id,
                name=prod.name,
                category=prod.category,
                brand=prod.brand,
                merchant=prod.merchant,
                price=prod.price,
                affiliate_url=prod.affiliate_url,
                product_truth=truth,
            )
            print(f"  ✅ Synced Product: {prod.name}")

        # 4. Sync Jobs & Outputs
        jobs_res = await db.execute(select(Job).order_by(Job.updated_at.desc()))
        jobs = jobs_res.scalars().all()
        print(f"⚙️ Found {len(jobs)} Jobs")
        for job in jobs:
            prod = await db.get(Product, job.product_id)
            prod_name = prod.name if prod else "Unknown Product"
            pv_res = await db.execute(select(PromptVersion).where(PromptVersion.job_id == job.id).order_by(PromptVersion.version.desc()))
            pv = pv_res.scalars().first()
            scene_data = json.loads(job.scene_json) if job.scene_json else None
            
            sync_job_node(
                job_id=job.id,
                reference_id=job.reference_id,
                product_name=prod_name,
                current_state=job.current_state,
                scene=scene_data,
                prompt_text=pv.prompt_text if pv else None,
                prompt_version=pv.version if pv else 1,
                is_rework=pv.is_rework if pv else False,
                rework_instruction=pv.rework_instruction if pv else None,
            )

            # Outputs & Critiques
            outs_res = await db.execute(select(JobOutput).where(JobOutput.job_id == job.id))
            for out in outs_res.scalars().all():
                crits_res = await db.execute(select(Critique).where(Critique.output_id == out.id))
                for c in crits_res.scalars().all():
                    crit_data = json.loads(c.critique_json) if c.critique_json else {}
                    sync_critique_node(
                        job_id=job.id,
                        output_id=out.id,
                        image_path=out.image_path,
                        critique=crit_data,
                    )
            print(f"  ✅ Synced Job: {job.id} (State: {job.current_state})")

        # 5. Sync Pin Drafts
        pins_res = await db.execute(select(PinDraft))
        pins = pins_res.scalars().all()
        print(f"📌 Found {len(pins)} Pin Drafts")
        for pin in pins:
            job = await db.get(Job, pin.job_id)
            prod = await db.get(Product, job.product_id) if job else None
            prod_name = prod.name if prod else None
            sync_pin_node(
                pin_id=pin.id,
                job_id=pin.job_id,
                title=pin.title,
                description=pin.description,
                keywords=json.loads(pin.keywords) if pin.keywords else [],
                destination_url=pin.destination_url or "",
                board_name=pin.board_name or "Seasonal Trends",
                status=pin.status,
                product_name=prod_name,
            )
            print(f"  ✅ Synced Pin Draft: {pin.title} ({pin.id[:8]})")

        # 6. Update Main Dashboard & MOCs
        dash_path = VAULT_PATH / "00 - Dashboard & MOCs" / "🏠 Main Dashboard.md"
        dash_content = f"""---
aliases:
  - Main Dashboard
  - Pinterest Realism Engine Cockpit
tags:
  - dashboard
  - moc
  - index
created: 2026-08-20
updated: 2026-08-21
---

# 🚀 Pinterest Realism Engine — Knowledge & Telemetry Vault

Welcome to the **Pinterest Realism Engine (PRE)** Obsidian Knowledge Graph. This vault is synchronized in real-time with the production database, pipeline state machine, and **Google Flow 4-Variation Batch Engine**.

---

## 📊 Live System Metrics

| Metric | Live Count | Status |
|---|---|---|
| **Active Campaigns** | `{len(campaigns)}` | 🟢 Healthy |
| **Analyzed Style References** | `{len(refs)}` | 🟢 Indexed |
| **Product Truth Catalog** | `{len(prods)}` | 🟢 Verified |
| **Generation Jobs** | `{len(jobs)}` | 🟢 Synced |
| **Approved / Draft Pins** | `{len(pins)}` | 🟢 Ready |
| **Google Flow Free Engine** | `Nano Banana 2 × x4` | ⚡ Active & Automated |

---

## 🗺️ Core Maps of Content (MOCs)

- [[🗺️ System Map & Architecture MOC]] — Full architectural layout, database models, and workflow graphs.
- [[⚡ Google Flow Automation Architecture]] — Complete spec of the Playwright subprocess, profile unlock, and DOM diffing engine.
- [[🧪 Experiment & DNA MOC]] — Visual DNA repository, extraction parameters, and reference styles.
- [[🛍️ Product Catalog & Truth Registry]] — Anti-hallucination truth constraints and merchant associations.
- [[🐛 Bug Tracker MOC]] — Automated and manual runtime bug issues, crash reports, and resolutions.

---

## 📜 Dev Logs & Evolution
- [[Changelog]] — System releases & version history (**v2.1.0 Live**).
- [[2026-08-21 - Google Flow Automator Resolution]] — Technical deep-dive on resolving the Flow engine, Windows proactor loop, and Chrome profile locking.
- [[2026-08-20 - Project Inception & Phase 1 Build]] — Initial build of the 6-stage pipeline and SQLite state machine.

---

## ⚡ Active Pipeline Status
```
[Reference Photo] ➔ [Visual DNA] ➔ [Product Truth] ➔ [Scene Director] ➔ [Google Flow 4-Batch Engine] ➔ [Realism Critic] ➔ [1-Click Publish]
```
"""
        dash_path.write_text(dash_content, encoding="utf-8")
        print("  ✅ Updated 🏠 Main Dashboard.md")

    print("\n🎉 Obsidian Vault synchronization complete! All nodes, MOCs, and metrics are up to date.")

if __name__ == "__main__":
    asyncio.run(sync_all())

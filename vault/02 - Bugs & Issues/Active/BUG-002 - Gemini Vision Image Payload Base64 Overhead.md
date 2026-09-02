---
id: BUG-002
title: Large Image Payloads Causing Gemini Base64 Overhead & Latency
severity: medium
status: open
subsystem: pipeline
created: 2026-08-20
updated: 2026-08-20
assigned: Pipeline Team
tags:
  - bug/open
  - severity/medium
  - subsystem/pipeline
---

# 🐛 BUG-002: Large Image Payloads Causing Gemini Base64 Overhead & Latency

## 📋 Summary
High-resolution Pinterest screenshots (e.g. 4K PNGs > 5MB) converted to Base64 inline strings in Gemini `generateContent` API requests inflate JSON payload sizes by ~33%, leading to slower uploads, network timeouts, or elevated latency in Stage 1 (Analyst) and Stage 6 (Critic).

---

## 🔍 Root Cause Analysis
- Base64 encoding increases byte size by $\approx 1.33 \times$.
- Transmitting a 6MB raw image means sending an ~8MB HTTP JSON body over client connections.
- Gemini processing latency scales with raw input payload dimensions when no client-side compression is applied.

---

## 💥 Impact
- Latency on Stage 1 analysis spikes from 2-3s up to 12-15s on larger uploads.
- Potential connection drops on slower broadband connections.

---

## 🩹 Proposed Solution
- [ ] **Client/Server Image Preprocessing:** Automatically resize images to maximum dimensions of $1080 \times 1920$ and compress to WebP/JPEG (quality 85) before base64 encoding for vision analysis.
- [ ] Preserve original high-res asset in filesystem for final Google Flow job package reference.

---

## 🔗 Related Notes
- [[🧬 Visual DNA Knowledge Base]]
- [[🔍 Realism Critic Defect Taxonomy]]
- [[🐛 Bug Tracker MOC]]

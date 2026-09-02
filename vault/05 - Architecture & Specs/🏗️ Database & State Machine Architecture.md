---
aliases:
  - Database Spec
  - State Machine
tags:
  - database
  - state_machine
  - schema
created: 2026-08-20
updated: 2026-08-20
---

# 🏗️ Database & State Machine Architecture

Comprehensive technical specification for the 9-table SQLite data layer and the generation job lifecycle state machine.

---

## 🗄️ Database Entity Relationship Diagram

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│  Campaigns   │──────<│  References  │──────<│    Jobs      │
└──────┬───────┘       └──────┬───────┘       └──────┬───────┘
       │                      │                      │
       │                      ▼                      ▼
       │               ┌──────────────┐       ┌──────────────┐
       │               │ Reference    │       │PromptVersions│
       │               │ Analyses     │       └──────┬───────┘
       │               └──────────────┘              │
       │                      │                      ▼
       │                      ▼               ┌──────────────┐
       │               ┌──────────────┐       │  JobOutputs  │
       │               │ VisualDNAs   │       └──────┬───────┘
       │               └──────────────┘              │
       ▼                                             ▼
┌──────────────┐                              ┌──────────────┐
│   Products   │─────────────────────────────>│  Critiques   │
└──────────────┘                              └──────┬───────┘
                                                     │
                                                     ▼
                                              ┌──────────────┐
                                              │  PinDrafts   │
                                              └──────────────┘
```

---

## 🔄 Generation Job State Machine Lifecycle

```
[DRAFT]
   │
   ▼
[ANALYZED]
   │
   ▼
[PRODUCT_MATCHED]
   │
   ▼
[SCENE_READY]
   │
   ▼
[PROMPT_READY]
   │
   ▼
[WAITING_FOR_FLOW] ───► Operator downloads ZIP, runs Google Flow, uploads outputs
   │
   ▼
[OUTPUT_UPLOADED]
   │
   ▼
[CRITIQUED]
   │
   ├───► PASS ───► [PIN_DRAFT] ───► [APPROVED] ───► [EXPORTED]
   │
   └───► REWORK ───► [PROMPT_READY (v+1)] ───► [WAITING_FOR_FLOW]
```

### Transition Enforcement Rules:
1. `validate_transition(current, next)` raises `InvalidTransitionError` if state skip is attempted.
2. A job in `REWORK` can cycle back to `PROMPT_READY` with an incremented version number.
3. Any fatal step moves state to `FAILED` with an error message stored in `failure_reason`.

---

## 🔗 Related Notes
- [[📋 Redesigned PRD v2]]
- [[🗺️ System Map & Architecture MOC]]
- [[🐛 Bug Tracker MOC]]

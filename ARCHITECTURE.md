# AURA Architecture

> **Version:** v1.0.0 | **Last Updated:** 2026-05-25

AURA is a dual-mode AI narrative engine. This document describes the technical architecture of both modes.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Dual-Mode Architecture](#2-dual-mode-architecture)
3. [Mode A: Prompt Compiler (LangGraph)](#3-mode-a-prompt-compiler-langgraph)
4. [Mode B: World Platform (Director + NPC Agent)](#4-mode-b-world-platform-director--npc-agent)
5. [Meta-Model](#5-meta-model)
6. [Cartridge System](#6-cartridge-system)
7. [Shared Infrastructure](#7-shared-infrastructure)
8. [Project Structure](#8-project-structure)
9. [Version History](#9-version-history)

---

## 1. System Overview

AURA operates as middleware between RP frontends (TAVO) and LLM backends. It solves 15+ systematic pain points in long-form roleplay by:

- **Decomposing** chaotic TAVO System Prompts into structured components
- **Compiling** them into model-optimized block prompts
- **Retrieving** context via 3-layer memory + causal graph traversal (planned)
- **Guarding** output quality with automated checks
- **Failing over** to backup models on timeout

---

## 2. Dual-Mode Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              TAVO / Player                               │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                         │
              ▼                                         ▼
┌─────────────────────────────┐           ┌─────────────────────────────┐
│   Mode A: /chat/completions │           │   Mode B: /world/completions │
│   (Prompt Compiler)         │           │   (World Platform)          │
├─────────────────────────────┤           ├─────────────────────────────┤
│ LangGraph 14-node state     │           │ Director                     │
│ machine                     │           │ ├─ Field snapshot            │
│ ├─ PromptDecomposer         │           │ ├─ Mention resolution        │
│ ├─ ContextAssemble          │           │ ├─ NPC scheduling            │
│ ├─ LLMGenerate              │           │ ├─ Rule checking             │
│ ├─ FormatGuard              │           │ └─ Arbitration               │
│ └─ MemoryExtract            │           │                              │
│                             │           │ NPC Agent (×N)              │
│ 3-layer memory (FAISS)      │           │ ├─ Independent System Prompt │
│ SQLite dialogue storage     │           │ ├─ Identity + Habitus        │
│ IntentTagger                │           │ └─ LLM call (reuses Mode A)  │
└─────────────────────────────┘           └─────────────────────────────┘
              │                                         │
              └────────────────────┬────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         LLM Backend (DeepSeek/Kimi/Gemini)               │
│                         Primary → Fallback failover (3s ttfb timeout)    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Mode A: Prompt Compiler (LangGraph)

### 3.1 State Machine

```
[InputReceive] → [PromptDecomposer] → [EntityExtract] → [EmotionAnalyze]
                                                          │
                                                          ▼
[StateManager] ← [StyleInjection] ← [ModelDialectCompiler] ← [MemoryRetrieve]
       │
       ▼
[ContextAssemble] → [LLMGenerate] → [ParallelQualityCheck]
       │                                      │
       │                          [retry loop, max 2]
       │                                      │
       └──────────────────┬───────────────────┘
                          ▼
                   [OutputReturn] → [MemoryExtract]
```

### 3.2 Key Nodes

| Node | File | Status | Description |
|------|------|--------|-------------|
| InputReceive | `input_receive.py` | ✅ | Request parsing + intent pre-call |
| PromptDecomposer | `prompt_decomposer.py` | ✅ | 3-tier parsing (`=====` / HTML / fallback) |
| MemoryRetrieve | `memory_nodes.py` | ✅ | FAISS RAG (semantic + structured + time) |
| ContextAssemble | `context_assemble.py` | ✅ | 9-block System Prompt assembly |
| LLMGenerate | `llm_quality_output.py` | ✅ | Non-streaming call with primary→fallback failover |
| FormatGuard | `llm_quality_output.py` | ✅ | Overreach + style pollution + length checks |
| OutputReturn | `llm_quality_output.py` | ✅ | Response packaging + SSE simulation |
| MemoryExtract | `memory_nodes.py` | ✅ | Dialogue sync + summarization trigger |
| RetryStrategy | `retry_strategy.py` | ✅ | Failure analysis + strategy patches |
| EntityExtract | `entity_extract.py` | 🔲 Stub | Entity recognition (reserved) |
| EmotionAnalyze | `emotion_analyze.py` | 🔲 Stub | Emotion analysis (reserved) |
| StateManager | `state_style_compiler.py` | 🔲 Stub | Dynamic state injection (reserved) |
| StyleInjection | `state_style_compiler.py` | 🔲 Stub | Style control (reserved) |
| ModelDialectCompiler | `state_style_compiler.py` | 🔲 Stub | Per-model format optimization (reserved) |

### 3.3 9-Block Prompt Structure

```
[MAIN_PROMPT]       ← User custom prompt header
[PROTOCOL]          ← Communication mark conventions
[CONSTRAINTS]       ← Role boundaries + negative instructions
[CHARACTER_CARD]    ← Character definition (from TAVO)
[USER_PROFILE]      ← User profile (from TAVO)
[CURRENT_STATE]     ← Entity current state (reserved)
[RECENT_MEMORY]     ← Recent 10 memory summaries
[LONG_TERM_MEMORY]  ← RAG Top-5 / TAVO fallback
[WORLD_CONTEXT]     ← World book (conditional)
[OUTPUT_SPEC]       ← Output format + COT self-check
```

**Recency Effect**: `WORKING_MEMORY` (last 5 rounds) + `USER_INTENT_TAG` are appended to the last user message to maximize compliance.

---

## 4. Mode B: World Platform (Director + NPC Agent)

### 4.1 Single Round Flow

```
Player Input
    │
    ▼
Director.resolve_mention() ──→ Alias matching (multilingual)
    │
    ▼
Director.get_field_snapshot() ──→ WorldField (location, time, ambient, rules)
    │
    ▼
Director.check_rule_violation() ──→ WorldRule validation
    │
    ▼
Director.schedule_npcs() ──→ Who should react this round?
    │
    ▼
For each scheduled NPC:
    Director.get_npc_field_slice() ──→ Memory-filtered field view
    NPCAgent.build_system_prompt() ──→ Identity + Habitus + Known events
    NPCAgent.generate_response() ──→ LLM call (reuses _call_single_llm)
    │
    ▼
Director.arbitrate_outputs() ──→ Conflict detection + dramatic sorting
    │
    ▼
World.apply_patch(EventPatch) ──→ Atomic state commit
    │
    ▼
Stream response to player
```

### 4.2 Director

| Capability | Status | Description |
|------------|--------|-------------|
| Field snapshot | ✅ | Renders ambient from WorldField + global state |
| Mention resolution | ✅ | Alias matching across all languages, fallback to semantic |
| Rule checking | 🟡 Mock | Keyword-based rule violation detection |
| NPC scheduling | 🟡 Mock | Returns all present NPCs (to be refined by Habitus matching) |
| Field slice | ✅ | Memory-permission-filtered view per NPC |
| Arbitration | 🟡 Mock | Simple concatenation (to be enhanced by conflict detection) |

### 4.3 NPC Agent

- **Perspective**: Character-only. Knows only `memory.known_events`.
- **System Prompt**: Built from `Identity + Habitus + State + known_events + relationships`
- **LLM Call**: Independent, reuses Mode A's `_call_single_llm` with failover
- **State Update**: `update_emotion()` / `add_known_event()` triggered by EventPatch

---

## 5. Meta-Model

### 5.1 Entity (三层结构)

| Layer | Class | Mutable? | Key Fields |
|-------|-------|----------|------------|
| **Existence** | `Identity` | ❌ | `entity_id`, `name`, `race`, `core_motivation`, `speech_fingerprint`, `aliases` |
| **Practice** | `Habitus` | ❌ | `Tendency[]`, `default_behavior`, `stress_response` |
| **Emergence** | `State` | ✅ | `location_id`, `EmotionalState`, `relationships`, `memory` |

### 5.2 EventPatch (State Diff + Causal Links)

- `state_diffs`: Attribute changes per entity (dot-path support, e.g. `emotion.current_label`)
- `emotional_impacts`: Narrative emotional deltas per entity
- `caused_by` / `causes` / `activates` / `closes`: Causal chain links
- `public_to` / `secret_to` / `hidden_from`: Visibility permissions

### 5.3 World (Container)

- `locations`: Spatial graph with `connected_to` travel times
- `entities`: All characters
- `events`: Causal event graph
- `rules`: Hard constraints with scope and exceptions
- `open_loops`: Unresolved event IDs (driving narrative tension)

---

## 6. Cartridge System

```
example_world.aura/
├── meta.yaml          # Title, author, version, dependencies
├── world.yaml         # Rules + initial state + open_loops
├── entities/          # Character YAML files
│   └── weiss_schnee.yaml
├── locations/         # Spatial structure
│   └── beacon_academy_gate.yaml
├── events/            # Seed events
│   └── opening.yaml
└── assets/            # Optional resources
```

**Loader**: `CartridgeLoader` parses YAML → Pydantic models with multilingual name resolution.
**Validator**: `CartridgeValidator` checks internal consistency (location connectivity, event causality, relationship references).

---

## 7. Shared Infrastructure

### 7.1 Memory (Mode A + Mode B)

| Layer | Implementation | Status |
|-------|---------------|--------|
| Vector search | FAISS (IndexFlatL2) + bge-small-zh-v1.5 | ✅ Active |
| Structured storage | SQLite (dialogue, session, dynamic_state) | ✅ Active |
| Causal graph | Kuzu / NetworkX (reserved) | ❌ Not yet |

### 7.2 LLM Configuration

```python
# Scene-isolated configuration
get_llm_config(provider="deepseek", scene="main")
# → temperature=0.7, max_tokens=4096, timeout=60, ttfb_timeout=3

get_llm_config(provider="kimi", scene="intent")
# → temperature=0.3, max_tokens=1024, timeout=15
```

### 7.3 Failover

- Primary model has `ttfb_timeout` (default 3s)
- On `asyncio.TimeoutError`, auto-switches to `fallback_provider`
- Fallback uses full timeout, no ttfb limit
- Records `actual_backend`, `fallback_triggered`, `fallback_reason` in state

---

## 8. Project Structure

```
AURA/
├── app/
│   ├── main.py                 # FastAPI entry + lifespan
│   ├── api/
│   │   ├── router.py           # Pydantic models + routing
│   │   ├── completions.py      # /chat/completions + /world/completions
│   │   └── streaming.py        # SSE simulation
│   ├── core/
│   │   ├── config.py           # Scene-isolated LLM config
│   │   ├── intent_tagger.py    # Intent parser
│   │   └── prompt_decomposer.py# Prompt decomposer
│   ├── graph/                  # Mode A: LangGraph orchestration
│   │   ├── state.py
│   │   ├── workflow.py
│   │   └── nodes/              # 14 node implementations
│   ├── memory/                 # Shared memory layer
│   │   ├── manager.py
│   │   ├── faiss_store.py
│   │   ├── sqlite_store.py
│   │   ├── embedding.py
│   │   ├── summarizer.py
│   │   └── models.py
│   ├── models/                 # Mode B: Meta-models
│   │   ├── entity.py
│   │   ├── event.py
│   │   └── world.py
│   ├── cartridge/              # Mode B: Cartridge system
│   │   ├── loader.py
│   │   └── validator.py
│   ├── world/                  # Mode B: World runtime
│   │   └── runtime.py
│   ├── director/               # Mode B: Director
│   │   └── director.py
│   ├── npc/                    # Mode B: NPC Agent
│   │   └── agent.py
│   ├── causal/                 # Reserved: Causal engine stub
│   └── engine/                 # Reserved: Event/Pacing/Perturbation stubs
│
├── cartridges/                 # Example world cartridges
│   └── rwby_beacon/
│       ├── meta.yaml
│       ├── world.yaml
│       ├── entities/
│       ├── locations/
│       └── events/
│
├── docs/
│   ├── vscode-guide.md
│   └── vscode-guide.zh.md
│
├── README.md                   # English
├── README.zh.md                # 中文
├── ROADMAP.md                  # English
├── ROADMAP.zh.md               # 中文
├── ARCHITECTURE.md             # This file
├── ARCHITECTURE.zh.md          # 本文件中文版本
└── requirements.txt
```

---

## 9. Version History

| Version | Date | Major Changes |
|---------|------|---------------|
| v0.5.0 | 2026-05-03 | Basic forwarding + Prompt decomposition |
| v0.6.0 | 2026-05-04 | SQLite + FAISS memory + RAG |
| v0.7.0 | 2026-05-10 | 3-layer memory + IntentTagger + intent-aware RAG v2 |
| v0.8.0 | 2026-05-11 | LangGraph 14-node state machine |
| v0.8.3 | 2026-05-17 | Module reorganization + file splitting |
| **v1.0.0** | **2026-05-25** | **Route B: Meta-models, cartridge system, Director, NPC Agent, LLM failover** |

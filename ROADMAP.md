# AURA — Vision & Roadmap

> **AURA is a text adventure platform, not a chat tool.**
> The host is a game console; the cartridge is a game world.
> The director directs actors; rules constrain emergence.
> Players experience freedom within determinism, and logic within freedom.

---

## 1. Project Vision

AURA is an LLM-powered text adventure platform — a **"livable text world"** where players enter, interact with AI-driven NPCs, push the plot forward, and the world itself keeps running according to physical rules and character personalities.

### Core Form: Host + Cartridge

- **Host (AURA Runtime)**: A semi-open-source narrative engine. Content-agnostic. Handles world simulation, causal computation, consistency checks, LLM routing, and cartridge management.
- **Cartridge (.aura)**: Creator-made world/character/script data packages. YAML-based, Pydantic-validated.
- **Player brings their own API key**: The platform does not bear model inference costs.

### Dual-Mode Architecture

| Mode | Endpoint | Architecture | Purpose |
|------|----------|--------------|---------|
| **A — Prompt Compiler** | `POST /v1/chat/completions` | LangGraph 14-node state machine | TAVO-compatible RP optimization |
| **B — World Platform** | `POST /v1/world/completions` | Director + NPC Agent | Multi-character text adventure |

Mode A is the foundation. Mode B is the evolution. Both share the same LLM calling infrastructure; Mode B injects structured world data into Mode A's Prompt compiler as a new data source.

---

## 2. Core Philosophy

### The Triad Loop

```
Entity (人) — driven by Habitus in an objective Field
    ↓
Event (事件) — state diffs that feed back into people and the world
    ↓
World (世界) — physical rules and spatial structure provide new conditions
    ↓
Back to Entity — memory updates, emotional shifts, relationship evolution
```

### Design Principles

1. **Text is root** — Narrative logic is the sole carrier. Images/music are presentation-layer enhancements. Do not touch them until the text layer is 100% stable.
2. **State-driven** — Entities activate by presence (`WorldField.present_entities`), not keyword matching. No trigger keywords needed.
3. **Causality first** — Events are state-diff patches + causal links, not logs.
4. **Event-driven** — Reject time-driven tick systems. The world advances only when events happen.
5. **Narrative emotions** — Emotions and relationships are expressed in natural language, not numerical scores.
6. **Determinism before probability** — The rule layer (world editor) must be 100% deterministic; the generation layer (LLM) produces probabilistic output within rules.
7. **Anti-template** — Consistency guards boundaries (no OOC, no teleportation), not tracks (no prescribed sentence structures).
8. **No root, no perturbation** — Dramatic surprises come only from field mutations with physical causes, not random injection.

---

## 3. Meta-Model

### 3.1 Entity (Character)

Three-layer structure:

| Layer | Class | Immutable? | Description |
|-------|-------|-----------|-------------|
| **Existence** | `Identity` | ✅ | DNA: `entity_id`, `name`, `race`, `core_motivation`, `speech_fingerprint`, `aliases` |
| **Practice** | `Habitus` | ✅ | Conditional behavior mappings: `Tendency[]` + `default_behavior` + `stress_response` |
| **Emergence** | `State` | ❌ | Temporary: `location_id`, `EmotionalState`, `relationships`, `memory` |

**Key insight**: `Habitus` is not a personality trait — it is a set of condition-behavior mappings. "When at the gate with Ruby → protect her despite cold words." This is what drives emergent events.

### 3.2 Event (World Patch)

An event is **not a log**. It is:
- A set of `StateChange` diffs
- A set of `EmotionalImpact` narratives
- Causal links (`caused_by` / `causes` / `activates` / `closes`)
- Visibility permissions (`public_to` / `secret_to` / `hidden_from`)

Events are applied atomically via `World.apply_patch(event)`.

### 3.3 World (Container)

- `Location` — spatial graph with travel times and properties
- `WorldRule` — hard constraints with scope and exception events
- `WorldField` — snapshot of objective conditions at a given moment
- `World` — the runtime container; all mutations go through `EventPatch`

---

## 4. Runtime Architecture: Director + Actors

### Director (God View)

- Renders the ambient field (weather, sound, light)
- Checks rules: does this action violate a `WorldRule`?
- Schedules NPCs: who should react this round?
- Broadcasts results to NPCs — filtered by memory permissions
- Arbitrates outputs: detects conflicts, sorts by dramatic weight, inserts narration

### NPC Agent (Character View)

- Knows only what's in `memory.known_events`
- Has its own `Identity + Habitus + State` injected into an independent System Prompt
- Calls LLM independently (reuses Mode A's `_call_single_llm`)
- Cannot read other characters' memories

### Single Round Flow

```
Player Input
    ↓
Director resolves mentions (Alias matching)
    ↓
Director updates WorldField, checks rules
    ↓
Director schedules NPCs (who is present, who should react)
    ↓
Director prepares per-NPC field slices (memory-filtered)
    ↓
Each NPC Agent calls LLM independently
    ↓
Director arbitrates outputs → assembles final response
    ↓
Atomic EventPatch commit
    ↓
Stream response to player
```

---

## 5. Key Engines

### Implemented ✅

| Engine | Status | Description |
|--------|--------|-------------|
| **PromptDecomposer** | ✅ | 3-tier parsing (`=====` / HTML comments / format fallback) |
| **ContextAssemble** | ✅ | 9-block Prompt assembly with model-specific constraints |
| **LLMGenerate** | ✅ | Non-streaming call with primary→fallback failover (3s ttfb timeout) |
| **FormatGuard** | ✅ | Overreach detection + style pollution filter + length check |
| **IntentTagger** | ✅ | Lightweight LLM pre-call for implicit instruction extraction |
| **FAISS RAG** | ✅ | Semantic + structured-field + time-weighted composite scoring |
| **MemoryManager** | ✅ | SQLite + FAISS facade with summarization every 5 rounds |
| **CartridgeLoader** | ✅ | YAML → Pydantic parser with multi-language name resolution |
| **WorldRuntime** | ✅ | World state manager with checkpoint save/load |
| **Director** | 🟡 Skeleton | Field snapshot, mention resolution, NPC scheduling (mock), arbitration (mock) |
| **NPCAgent** | 🟡 Skeleton | Independent System Prompt + LLM call per character |

### Planned 📋

| Engine | Priority | Description |
|--------|----------|-------------|
| **CausalRAG** | High | Graph DB (Kuzu/NetworkX) traversal: upstream 2 layers + downstream 1 layer |
| **EventEngine** | High | `Habitus × Field + Perturbation` → EventDraft generation |
| **PacingEngine** | Medium | Four-state pacing (起承转合) based on open_loop count and chain depth |
| **PerturbationEngine** | Medium | Detects long-suppressed causal chains and releases accumulated potential |
| **EventScheduler** | Medium | Offline NPC autonomous emergence; offline summary on player return |
| **Deep FormatGuard** | Medium | WorldRule violation check, spatial consistency (no teleportation), Habitus boundary check |
| **ModelDialectCompiler** | Low | Per-model prompt format optimization (DeepSeek/Gemini/Kimi/Qwen) |
| **Multi-Agent Concurrency** | Low | Parallel NPC LLM calls with conflict detection |

---

## 6. Cartridge System (.aura)

```
example_world.aura/
├── meta.yaml          # Title, author, version, dependencies
├── world.yaml         # Global rules + initial state + open loops
├── entities/          # Character definitions (Identity + Habitus + State)
├── locations/         # Spatial structure + connectivity
├── events/            # Seed events (causal chain starters)
└── assets/            # Optional resource indices
```

**Cartridge = Database**: Deserialized into Pydantic models at runtime.
**Cartridge = Save**: World state diffs written back to `save/` on exit.
**Cartridge = Product**: Creators package and upload to a marketplace.

### Multi-Language Support

- `aliases: {en: [...], zh: [...], ja: [...]}` — cross-language coreference resolution
- `name`, `core_motivation`, `speech_fingerprint` support per-language values
- Runtime loads the player's language; falls back to English if missing

---

## 7. Storage Architecture

| Layer | Data | Tool | Status |
|-------|------|------|--------|
| **Causal (graph)** | Event nodes + causal edges | Kuzu / NetworkX | ❌ Not yet integrated |
| **Real-time (cache)** | NPC current states | SQLite / JSON | ✅ SQLite tables exist |
| **Semantic (vector)** | `narrative_text` embeddings | FAISS (IndexFlatL2) | ✅ Active |

---

## 8. Development Roadmap

### Phase 0 — Foundation (v1.0.x → v1.0.0) ✅ Completed

- [x] LangGraph 14-node state machine
- [x] Prompt decomposition + 9-block assembly
- [x] 3-layer memory (Working/Recent/Long-term)
- [x] Intent-aware RAG with structured field matching
- [x] Multi-backend LLM with failover
- [x] Meta-models (Entity/Event/World) as Pydantic classes
- [x] Cartridge loader + validator
- [x] Director skeleton + NPC Agent skeleton
- [x] Example cartridge: `rwby_beacon` (Weiss & Ruby)

### Phase 1 — Graph & Causality (v1.1.x → v1.2.x)

- [ ] Integrate Kuzu or NetworkX for causal graph storage
- [ ] Replace FAISS pure-vector search with CausalRAG (graph traversal + vector fallback)
- [ ] EventEngine: generate EventDraft from `Habitus × Field`
- [ ] Atomic EventPatch application with conflict detection
- [ ] Deep FormatGuard: WorldRule + spatial consistency checks

### Phase 2 — Emergence & Pacing (v1.2.x → v1.3.x)

- [ ] PacingEngine: four-state narrative rhythm control
- [ ] PerturbationEngine: detect and release suppressed causal potential
- [ ] EventScheduler: offline NPC autonomous behavior
- [ ] Multi-Agent concurrency: parallel LLM calls for all active NPCs

### Phase 3 — Polish & Ecosystem (v1.4.x)

- [ ] ModelDialectCompiler: per-model prompt optimization
- [ ] Branching timelines: save checkpoints at key decision points
- [ ] Cartridge marketplace foundation
- [ ] Visual world editor (AURA Pro)

### Phase 4 — Scale

- [ ] Multiplayer: multiple players in the same world instance
- [ ] Cloud sync: world state persistence across devices
- [ ] Creator economy: paid cartridges, revenue sharing

---

## 9. Design Iron Laws

1. **Text is root**
2. **Ruby first, then abstract** — Build concrete, then generalize
3. **State-driven** — No keyword matching
4. **Causality first** — Events drive the world, not ticks
5. **Event-driven** — No time-driven tick system
6. **No root, no perturbation**
7. **Narrative emotions** — No numerical scoring
8. **Anti-template** — Guard boundaries, not tracks
9. **Firmware before cartridges** — The host must be solid before the content shines

---

## 10. The Origin

> *"Even if the world forgets the character's oath, AURA will remember it for them."*

The first cartridge, `rwby_beacon`, places Weiss Schnee and Ruby Rose at the gates of Beacon Academy on enrollment day — a homage to where it all began.

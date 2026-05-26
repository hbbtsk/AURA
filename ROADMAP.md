# AURA Roadmap

> **This is a technical evolution plan, not a product release schedule.**  
> We are building an event-driven narrative engine. The roadmap shows how the architecture deepens from "single-character prompt optimization" to "multi-agent persistent world simulation."

---

## Phase 0: Architecture Validation (Current)

**Status**: 🚧 In Progress  
**Goal**: Prove that "event bus + state machine" solves problems that pure Prompt engineering cannot.

| Module | Deliverable | State |
|--------|-------------|-------|
| Event Bus Data Model | EventPatch schema, causality fields, visibility rules | ✅ Validated |
| 8-Layer Character Model | Physique/Voice/Roots/Network/Core/Tension/Trajectory/Hooks definition | ✅ Validated |
| Prompt Compiler Skeleton | LangGraph 15-node workflow, TAVO API compatibility | 🚧 Runnable |
| 3-Layer Memory | WORKING + RECENT + LONG_TERM RAG | 🚧 Basic |

**Milestone for Phase 0 Complete**:  
A single-character RP session through AURA shows measurable consistency improvement over raw ST (same card, same model, 20+ turns) in a controlled test.

---

## Phase 1: Quality Guard Layer (v1.0.x)

**Status**: 📋 Next  
**Goal**: Make Mode A (Prompt Compiler) production-usable for solo RP.

| Feature | Technical Approach | Why It Matters |
|---------|-------------------|----------------|
| Overreach Detection | Regex + JSON Schema post-filter, no LLM retry | Prevents model from writing user lines |
| Style Pollution Filter | Voice-layer fingerprint matching against baseline | Catches model drift back to training-data prose |
| Length Guard | Hard min/max tokens + template fallback | Stops model from rambling or giving one-word replies |
| Intent Tagger v2 | Lightweight classifier (local 7B or embedding) | Replaces heuristic intent parsing with structured tags |
| ST Card Importer | PNG metadata parser → 8-layer JSON population | Bridges existing ST ecosystem to AURA state model |

**Milestone**: User can import a ST card, run a 30-turn session, and observe fewer OOC incidents than native ST with the same backend model.

---

## Phase 2: World Platform Foundation (v1.1.x)

**Status**: 📋 Architecture validated, code pending  
**Goal**: Move from "one character + user" to "multiple characters + world rules."

| Component | Responsibility |
|-----------|--------------|
| Director | Field snapshot rendering, mention resolution, NPC scheduling, conflict arbitration |
| NPC Agent | Per-character System Prompt + isolated LLM call, memory-filtered field slice |
| World State Manager | Atomic EventPatch application, checkpoint save/load, physical rule enforcement |
| Cartridge Loader | YAML → Pydantic parser, consistency validation, multi-language alias support |

**Key Technical Challenge**:  
Concurrent NPC LLM calls (2-3 characters responding to the same event) without exponential token cost. Solution: shared context retrieval + per-agent prompt slicing.

**Milestone**: A 3-character scene (player + 2 NPCs) runs for 10 turns without crosstalk, with NPCs referencing each other's prior statements correctly.

---

## Phase 3: Causal Engine (v1.2.x)

**Status**: 📋 Planned  
**Goal**: Make long-arc narrative coherent across sessions.

| Feature | Approach |
|---------|----------|
| Causal Graph Storage | Kuzu graph database for `triggered_by` / `causes` links |
| CausalRAG | Retrieve not just "similar events" but "causally related events" |
| Root Cause Tracking | Every event knows its ultimate origin; prevents plot regression |
| Session Checkpoint | Save world state + event graph; resume exactly where left off |

**Milestone**: A mystery plotline spanning 5 sessions (50+ turns total) maintains clue consistency; red herrings don't accidentally become true, true clues don't disappear.

---

## Phase 4: Event Emergence (v1.3.x)

**Status**: 📋 Planned  
**Goal**: The world generates events without direct player input.

| Engine | Function |
|--------|----------|
| EventEngine | NPCs schedule off-screen actions based on goals and state |
| PacingEngine | Monitors narrative tension; injects lulls or escalations |
| PerturbationEngine | Random world events (weather, news, accidents) that force character reactions |

**Milestone**: Player logs in after 24h real time; 2-3 "off-screen events" have occurred, changing NPC emotional states and available conversation topics.

---

## Phase 5: Multi-Agent Concurrency (v1.4.x)

**Status**: 📋 Planned  
**Goal**: Scale to 5+ simultaneous NPCs with meaningful group dynamics.

| Problem | Solution |
|---------|----------|
| Exponential LLM cost | Batch context retrieval; shared field snapshot; selective NPC activation |
| Conflict detection | When two NPCs propose contradictory world_deltas, Director arbitrates by priority + timestamp |
| Offline simulation | NPCs continue "living" in background threads, generating events while player is away |

**Milestone**: A tavern scene with 5 NPCs + player; NPCs have sidebar conversations, eavesdrop, interrupt, or ignore player based on attention filters.

---

## How to Contribute

**Phase 0-1** (Immediate needs):
- Quality guard implementation (Python, regex, JSON Schema)
- ST card importer (PNG metadata parsing, YAML generation)
- Benchmark suite: define "OOC score" and measure AURA vs baseline

**Phase 2+** (Architecture-heavy):
- Director scheduling algorithm design
- Kuzu graph schema for causal storage
- Event emergence rule system

See open Issues for tagged tasks: `good first issue`, `help wanted`, `architecture discussion`.

---

## Design Principles Driving the Roadmap

1. **State before text**: Physical/psychological state changes are computed by rules; LLM only handles cognitive layer.
2. **Causality before similarity**: RAG retrieves by causal chain first, embedding similarity second.
3. **No LLM retry**: Output guards filter or truncate, never ask LLM to regenerate.
4. **Player brings keys**: We don't host models; we host architecture.
5. **Text is root**: All narrative logic is inspectable, diffable, and version-controllable.

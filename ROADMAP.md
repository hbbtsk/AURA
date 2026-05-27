# AURA Roadmap

> This is a **technical evolution plan**, not a product release schedule.  
> We are building an event-driven narrative engine grounded in narratology.  
> The roadmap shows how the architecture deepens from "single-character prompt optimization" to "multi-agent persistent world simulation."

---

## Phase 0: Architecture Validation (Current)

**Status**: In Progress  
**Goal**: Prove that "deterministic state layer + dual-output architecture" solves problems that pure prompt engineering cannot.

| Module | Deliverable | State |
|--------|-------------|-------|
| Event Patch Data Model | EventPatch schema, causality fields, visibility rules, negative event definition | Validated |
| 8-Layer Character Model | Physique/Voice/Roots/Network/Core/Tension/Trajectory/Hooks definition | Validated |
| Dual-Output Architecture | `narrative` + `structured` single-call output schema | Defined |
| Prompt Compiler Skeleton | LangGraph 15-node workflow, TAVO API compatibility | v0.8 Runnable |
| 3-Layer Memory | WORKING + RECENT + LONG_TERM RAG | Basic |
| Narrative Theory Foundation | Bremond sequences, Todorov equilibrium, Trabasso causal test | Defined |

**Milestone for Phase 0 Complete**:  
A single-character RP session through AURA shows measurable consistency improvement over raw ST (same card, same model, 20+ turns) in a controlled test.

---

## Phase 1: Quality Guard Layer (v1.0.x)

**Status**: Next  
**Goal**: Make Mode A (Prompt Compiler) production-usable for solo RP.

**Key Architectural Decision**: Quality guards are **post-output and non-blocking**. The dual-output architecture produces both narrative and structured data in a single LLM call. Guards inspect the output after the fact; they never block the SSE stream. Issues are recorded into state and corrected in the next round's prompt — not by retrying the current LLM call.

| Feature | Technical Approach | Why It Matters |
|---------|-------------------|----------------|
| Overreach Detection | Lightweight regex on `narrative.content` during SSE streaming (<1ms) | Prevents model from writing user lines; only zero-tolerance check on hot path |
| Style Pollution Filter | Voice-layer fingerprint matching against baseline (async) | Catches model drift back to training-data prose; feeds state for next-round correction |
| Length Guard | Hard min/max tokens + template fallback (async) | Stops model from rambling or giving one-word replies |
| Intent Tagger v2 | Extracted from `structured.intent_tags` in dual-output | LLM self-annotates intent; replaces heuristic intent parsing |
| ST Card Importer | PNG metadata parser → 8-layer JSON population | Bridges existing ST ecosystem to AURA state model |
| Non-Blocking Quality Pipeline | All guards except overreach run async via Event Bus | Eliminates feedback-loop latency that causes user-perceived "freezing" |

**Milestone**: User can import a ST card, run a 30-turn session, and observe fewer OOC incidents than native ST with the same backend model. Session does not "freeze" at any point due to quality checking.

---

## Phase 2: World Platform Foundation (v1.1.x)

**Status**: Architecture validated, code pending  
**Goal**: Move from "one character + user" to "multiple characters + world rules."

| Component | Responsibility |
|-----------|--------------|
| Director | Field snapshot rendering, mention resolution, NPC scheduling, conflict arbitration, sequence progression |
| NPC Agent | Per-character System Prompt + single LLM call → dual-output, memory-filtered field slice |
| World State Manager | Atomic EventPatch application, checkpoint save/load, physical rule enforcement, `world_delta` validation |
| Cartridge Loader | YAML → Pydantic parser, consistency validation, multi-language alias support |
| Sequence Layer | PresetSequence (galgame) + DynamicSequence (open world) management |

**Key Technical Challenge**:  
Concurrent NPC LLM calls (2-3 characters responding to the same event) without exponential token cost. Solution: shared context retrieval + per-agent prompt slicing + dual-output structured data for Director arbitration.

**Key Architectural Decision — Visibility**:  
Each NPC maintains an independent visibility map of every event. The same EventPatch carries different `character_delta` and `visibility` per NPC. "What Pyrrha knows" and "What Weiss knows" are computed independently by the Director.

**Milestone**: A 3-character scene (player + 2 NPCs) runs for 10 turns without crosstalk, with NPCs referencing each other's prior statements correctly. Preset sequences can progress based on state conditions.

---

## Phase 3: Causal Engine (v1.2.x)

**Status**: Defined  
**Goal**: Make long-arc narrative coherent across sessions.

| Feature | Approach |
|---------|----------|
| Causal Graph Storage | Kuzu graph database for `triggered_by` / `causes` links |
| Causal Test (Trabasso) | "If not A then not B" — automated causal link validation |
| Sequence Structure | Bremond's elementary sequences + composite connections (enchainment/enclave/two-sided) |
| CausalRAG | Retrieve not just "similar events" but "causally related events" — causal chain first, embedding similarity second |
| Root Cause Tracking | Every event knows its ultimate origin; prevents plot regression |
| Session Checkpoint | Save world state + event graph + sequence progress; resume exactly where left off |

**Milestone**: A mystery plotline spanning 5 sessions (50+ turns total) maintains clue consistency; red herrings don't accidentally become true, true clues don't disappear. Flashback sequences (enclave) correctly integrate with main timeline.

---

## Phase 4: Event Emergence (v1.3.x)

**Status**: Planned  
**Goal**: The world generates events without direct player input.

| Engine | Function |
|--------|----------|
| EventEngine | NPCs schedule off-screen actions based on goals and state; DynamicSequence generation |
| PacingEngine | Monitors narrative tension via sequence structure; injects lulls or escalations |
| PerturbationEngine | Random world events (weather, news, accidents) that force character reactions; validated by World State Manager before application |

**Milestone**: Player logs in after 24h real time; 2-3 "off-screen events" have occurred, changing NPC emotional states and available conversation topics. Events are causally linked to prior player actions (Trabasso test passes).

---

## Phase 5: Multi-Agent Concurrency (v1.4.x)

**Status**: Planned  
**Goal**: Scale to 5+ simultaneous NPCs with meaningful group dynamics.

| Problem | Solution |
|---------|----------|
| Exponential LLM cost | Batch context retrieval; shared field snapshot; selective NPC activation; dual-output reduces per-NPC overhead |
| Conflict detection | When two NPCs propose contradictory `world_delta`, Director arbitrates by priority + timestamp + narrative function |
| Offline simulation | NPCs continue "living" in background threads via EventEngine, generating events while player is away |
| Two-sided sequences | Same event carries different meaning per character; Director computes independent impacts |

**Milestone**: A tavern scene with 5 NPCs + player; NPCs have sidebar conversations, eavesdrop, interrupt, or ignore player based on attention filters. Visibility rules ensure each NPC only knows what they should know.

---

## Narrative Theory Integration Timeline

Narratology is not a "feature" to be added later. It is the **foundation** that evolves with each phase:

| Phase | Narrative Theory Integration |
|-------|------------------------------|
| v0.9.x | Event negative definition (Agent + Action + Impact); non-event filtering |
| v1.0.x | Intent tagging as narrative function labeling; voice-layer as Barthes's "voice" |
| v1.1.x | Sequence layer: elementary sequences (Bremond); preset vs dynamic |
| v1.2.x | Full causal graph: Trabasso test, composite connections, CausalRAG |
| v1.3.x | Emergent narrative: Todorov equilibrium model for world-state pacing |
| v1.4.x | Multi-agent: two-sided sequences, per-character visibility as narrative focalization |

---

## How to Contribute

**Phase 0-1** (Immediate needs):
- Quality guard implementation (Python, regex, JSON Schema)
- ST card importer (PNG metadata parsing, 8-layer YAML generation)
- Benchmark suite: define "OOC score" and measure AURA vs baseline

**Phase 2+** (Architecture-heavy):
- Director scheduling algorithm design
- Kuzu graph schema for causal storage
- Event emergence rule system
- Narrative theory → code mapping validation

See open Issues for tagged tasks: `good first issue`, `help wanted`, `architecture discussion`.

---

## Design Principles Driving the Roadmap

1. **State before text**: Physical/psychological state changes are computed by rules; LLM only handles the cognitive/expressive layer.
2. **Causality before similarity**: RAG retrieves by causal chain first, embedding similarity second.
3. **No LLM retry**: Output guards filter or truncate, never ask LLM to regenerate. Issues are corrected in the next round's prompt via state.
4. **Player brings keys**: We don't host models; we host architecture.
5. **Text is root**: All narrative logic is inspectable, diffable, and version-controllable.
6. **Narrative theory drives engineering**: Every technical decision is traceable to a narratological concept.

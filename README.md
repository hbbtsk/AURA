# AURA

> **An event-driven narrative engine with deterministic character state machines.**
> Built by a roleplayer, for roleplayers.

<p align="center">
  <a href="README.zh.md">中文版</a>
</p>

---

## What AURA Is

AURA inserts a **deterministic state layer** between the frontend and the LLM.

Existing tools (SillyTavern, Character.AI) bet everything on the LLM's context window and prompt engineering. After 20 turns: OOC, character bleeding, state regression, style pollution. These aren't prompt problems. They're **architecture problems**.

AURA solves this with three core primitives:

| Primitive | What It Does |
|-----------|-------------|
| **8-Layer Character Model** | Physique / Voice / Roots / Network / Core / Tension / Trajectory / Hooks — a character is not a card, a character is a living system |
| **EventPatch** | An event is not a log. It is a state patch: *someone (agent) did something (action) that caused something (impact)* |
| **Causal Graph** | Events are linked by narrative causality, not just temporal order. Inspired by narrative theory (Bremond, Todorov, Trabasso) |

**One LLM call produces two outputs:**

```json
{
  "narrative": {
    "content": "The character's dialogue for the player",
    "meta_action": "Stage direction: finger tapping, gaze shifting"
  },
  "structured": {
    "intent_tags": ["evasion", "redirect"],
    "world_delta": [{"field": "interrogation_room.focus", "value": "turned_to_chen_biao"}],
    "visibility": "public"
  }
}
```

The player sees `narrative.content`. The system consumes `structured` directly — zero additional LLM calls. This is **not** function calling. The LLM is not commanding the system. The LLM is producing content and self-annotating.

---

## Why AURA

### The Problem: OOC Is an Architecture Problem, Not a Model Problem

Context windows are now 2M tokens. Models are now GPT-5-class. **OOC still happens.** Why?

Because OOC is not caused by "forgetting." It is caused by the **absence of a deterministic state layer**. An LLM has no concept of "state." It has context. Context is not state.

| Issue | Root Cause | Why Bigger Context Doesn't Fix It |
|-------|-----------|-----------------------------------|
| OOC | No persistent character state | 2M tokens of inconsistent text is still inconsistent |
| Character bleeding | No isolation between NPCs | All NPCs share one context soup |
| Style pollution | No voice-layer enforcement | LLM drifts to training-data prose over time |
| State regression | No world_delta validation | LLM claims a state change that contradicts physics/rules |

### The "5G Highway" Analogy

LLMs are the highway infrastructure. The industry has spent years widening the highway (bigger models, longer context). But the **cars** (applications) are still leaking oil.

Roleplay is one of the few verified "cars" on this highway — 45M MAU on Character.AI alone. But the RP "car" leaks everywhere: OOC after 20 turns, memory loss, character drift. **AURA is the repair shop.** We don't build highways. We fix the car.

---

## Narrative Theory Foundation

AURA's architecture is grounded in **narratology**, not just engineering:

| Narrative Theory | AURA Implementation |
|-----------------|---------------------|
| **Bremond's Narrative Sequence** | Sequence Layer: `opening → actualization → result` |
| **Todorov's Equilibrium Model** | World State Manager tracks balance/disruption |
| **Trabasso's Causal Criterion** | `If not A then not B` — the test for causal links |
| **Kernel vs. Satellite (Barthes)** | EventQualifier distinguishes plot-driving events from flavor text |
| **Greimas's Actantial Model** | Subject-Object-Process structure in EventPatch |

> *"The minimal complete plot consists in the passage from one equilibrium to another."*
> — Tzvetan Todorov

---

## Current Status

| Module | Status | Notes |
|--------|--------|-------|
| **8-Layer Character Model** | Validated | Definition locked, schema defined |
| **Event Bus Design** | Validated | EventPatch schema, causality fields, visibility rules |
| **Dual-Output Architecture** | Defined | `narrative` + `structured` single-call output |
| **Mode A: Prompt Compiler** | v0.8 Runnable | 15-node LangGraph workflow, TAVO-compatible endpoint |
| **Mode B: World Platform** | Architecture validated | Director + NPC Agent design locked |
| **Sequence Layer** | Defined | PresetSequence (galgame) + DynamicSequence (open world) |
| **Causal Graph Engine** | Defined | Kuzu schema, Trabasso causal test, enchainment/enclave/two-sided |
| **Quality Guard Layer** | Planned | Overreach detection, style filter, length guard (post-output, non-blocking) |
| **ST Card Importer** | Planned | PNG metadata → 8-layer JSON |

**Target Timeline:**
- Mode A stable (non-blocking quality guards + causal graph v0.1): 2026 Q3
- Mode B prototype (3-NPC scene): 2026 Q4

---

## Architecture: Character · Event · World · Sequence

### Character — Not a Card, a Living System

Import a SillyTavern card and AURA populates the 8 layers. Empty fields stay empty — LLM hallucination is blocked. Events fill gaps dynamically.

| Layer | Description | Narrative Function |
|-------|-------------|-------------------|
| **Physique** | Skeleton, marks, wear, traces, aura | Physical presence in scenes |
| **Voice** | Pace, tics, register, emotional baseline, silence habits, subtext patterns | Style consistency guard |
| **Roots** | Soil, rupture, livelihood, social mask, real standing | Deep motivation |
| **Network** | Public ties, secret ties, debts, alliances, information position | Social state |
| **Core** | Surface desire, deep hunger, fear, wound, moral boundary, values | Decision driver |
| **Tension** | Internal contradictions, external friction, time pressure, identity crack | Behavioral variance |
| **Trajectory** | Life stage, recent turning point, current burdens, ticking bombs | Arc direction |
| **Hooks** | Entry style, catalyst events, chemistry with others, narrative function | Scene activation |

### Event — A State Patch, Not a Log

```yaml
Event:
  header:
    id: evt_042
    type: utterance | action | state_change | narration
    causality:
      triggered_by: evt_038    # direct trigger
      root_cause: evt_001      # root cause tracking
    visibility: public | private | faction_only
  payload:
    source: char_001
    targets: [char_002]
    content: "Where were you last night?"
    intent_tags: [inquiry, pressure]
    world_delta:
      proposed_changes:
        - {field: "char_002.psychological.stress", delta: +0.1}
    perspective: first_person | third_person_limited
  narrative_function: opening | actualization | result
  sequence_id: seq_007
```

**What is NOT an event (negative definition):**
- No action taken (pure thought, pure emotion, pure description)
- No state change caused (idle chat)
- No participating agent (environmental description without narrative agent)
- No expectation-result gap (repetition, mechanical response)

> *An event = Agent + Action + Impact. If any leg is missing, it is a `non_event` — stored in vector memory for semantic retrieval, but not entered into the Causal Graph.*

### World — Not Scene Description, an Arbiter

- **Physical state**: Locations, items, environmental rules (code-enforced, no LLM)
- **Rule engine**: Validates every `world_delta`; rejects physically/socially impossible requests
- **Causal graph**: `triggered_by` / `causes` links for long-arc narrative tracking

### Sequence — The Glue Between Events

Events are not isolated atoms. They are organized into **sequences**:

| Sequence Type | Use Case | AURA Mode |
|--------------|----------|-----------|
| **PresetSequence** | Hand-authored branching narrative (galgame structure) | Mode A + Cartridges |
| **DynamicSequence** | Emergent narrative from character states and world rules | Mode B |

**Basic sequence structure** (Bremond):
```
Opening (possibility arises) → Actualization (action taken) → Result (success/failure)
```

**Composite connections**:
- **Enchainment**: Result of Sequence A = Opening of Sequence B
- **Enclave**: A sub-sequence embedded within another (flashbacks, side quests)
- **Two-sided**: Same event carries different meaning for different characters

---

## Dual-Mode Design

### Mode A: Prompt Compiler (TAVO / ST Compatible)

```
TAVO → AURA → Prompt Decomposition → 3-Layer Memory → Quality Guard (post-output) → LLM Dual-Output → Return
```

- 9-Block Prompt assembly (constraints + character slice + world slice + event context + sequence context)
- 3-layer memory: WORKING (5 turns) + RECENT (summaries) + LONG_TERM (CausalRAG + Vector RAG)
- **Quality guards are post-output and non-blocking**: overreach detection (lightweight regex), style filter (async), length truncation (async)
- **Dual-output**: one LLM call produces both `narrative` and `structured`
- **Zero LLM retries**: output guards filter or truncate, never ask LLM to regenerate

**Endpoint**: `POST /v1/chat/completions`

### Mode B: World Platform (Multi-Agent Narrative)

```
Player Input → Director (field snapshot + mention resolution + NPC scheduling + sequence tracking)
  → NPC Agent (independent System Prompt + single LLM call per character → dual-output)
  → Director Arbitration → Merged Output
```

- Each NPC owns an independent state machine; exchanges information via Event Bus
- Director handles physical arbitration, conflict resolution, focus scheduling, sequence progression
- Visibility rules: each NPC sees only what they should see
- Supports cartridge loading (`.aura` format) for complete world imports

**Endpoint**: `POST /v1/world/completions`

---

## Cartridge System (.aura)

Self-contained world data packages:

```
rwby_beacon.aura/
├── meta.yaml          # Title, author, version
├── world.yaml         # Global rules + initial state
├── sequences/         # Preset narrative sequences
│   ├── vol1_defense.yaml
│   └── vol2_stalemate.yaml
├── entities/          # Character cards (Identity + Habitus + State)
│   ├── weiss_schnee.yaml
│   └── ruby_rose.yaml
├── locations/         # Spatial structure + connectivity
├── events/            # Seed events (causal chains)
└── assets/            # Optional resource index
```

The Director automatically activates entities present in the field — no keyword matching required. Sequences progress based on state conditions, not script triggers.

---

## Design Principles

1. **Text is root**: Narrative logic is the sole carrier; images/audio are presentation layers
2. **State before text**: Physical/psychological state changes are computed by rules; LLM only handles the cognitive/expressive layer
3. **Causality before similarity**: RAG retrieves by causal chain first, embedding similarity second
4. **No LLM retry**: Output guards filter or truncate, never ask LLM to regenerate
5. **Player brings keys**: We don't host models; we host architecture
6. **Narrative theory drives engineering**: Event definitions, sequence structures, and causal tests are grounded in narratology (Bremond, Todorov, Barthes, Greimas, Trabasso)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Gateway | FastAPI + Pydantic v2 + Uvicorn |
| LLM Client | httpx (direct) |
| Orchestration (Mode A) | LangGraph + LangChain Core |
| Vector Memory | FAISS + sentence-transformers |
| Causal Graph | Kuzu (embedded graph DB) |
| Structured Storage | SQLite |
| Meta-Models | Pydantic v2 |
| Cartridge Format | YAML |

---

## Quick Start

```bash
git clone https://github.com/hbbtsk/AURA.git
cd AURA
pip install -r requirements.txt

# Configure API Key
echo "DEEPSEEK_API_KEY=sk-your-key" > .env

# Start Mode A (Prompt Compiler)
python -m app.main
# Then connect TAVO to: http://localhost:8000/v1/chat/completions
```

> **Note**: The current version is a skeleton. It runs, but the effect may not be better than native ST yet. We are validating architecture, not shipping a product.

---

## Roadmap

See [ROADMAP.md](./ROADMAP.md) for detailed technical evolution plan.

| Phase | Focus | Status |
|-------|-------|--------|
| **v0.9.x** | Prompt Compiler: Dual-output architecture, non-blocking quality guards, ST compatible | Skeleton runnable |
| **v1.0.x** | Quality Guard: Overreach detection, style filter, length control | In development |
| **v1.1.x** | World Platform: Meta-models, cartridge system, Director, NPC Agent | Architecture validated, code pending |
| **v1.2.x** | Causal Engine: Kuzu graph DB, causal chain traversal, CausalRAG | Defined |
| **v1.3.x** | Event Emergence: EventEngine, PacingEngine, PerturbationEngine | Planned |
| **v1.4.x** | Multi-Agent Concurrency: Parallel NPC LLM calls, conflict detection | Planned |

---

## How to Participate

**You don't need to write code to help.**

- **Share pain points**: What is the most frustrating OOC scene you've experienced in ST/CAI? We need real test cases.
- **Review architecture**: Does the 8-layer character model miss anything critical for your RP style?
- **Share scenarios**: If you have a TTRPG experience where "multiple characters must not crosstalk," tell us the details.
- **Design critique**: We are especially looking for feedback on the EventPatch visibility rules, the Sequence Layer, and the World Agent arbitration logic.

**For developers:**
- See [ROADMAP.md](./ROADMAP.md) for current tasks
- See [docs/](./docs/) for architecture documents
- PRs welcome, especially for:
  - Mode A quality guard layer (overreach detection, style filter)
  - ST card importer (PNG metadata parser → 8-layer JSON)
  - YAML cartridge format validator

---

## License

MIT

---

## Acknowledgements

Built for the RWBY universe and beyond.  
The first cartridge, `rwby_beacon`, features Song Greywind and Pyrrha Nikos — a narrative built from 500 cycles of轮回 and 210,000 words of同人 fiction.  
AURA's cartridge system is open to any fictional universe or TTRPG module. PRs welcome.

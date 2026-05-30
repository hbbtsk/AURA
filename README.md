# AURA

> **A Deterministic Character State Machine Powered Event Narrative Engine.**
> Built by a roleplayer, for roleplayers.

<p align="center">
  <a href="README.zh.md">中文</a>
</p>

---

## What AURA Is

AURA inserts a **deterministic state layer** between the LLM and the frontend.

Existing tools (SillyTavern, Character.AI) bet everything on the LLM's context window and prompt engineering. After 20 turns: OOC, character blending, state regression, style contamination. These are not prompt problems. They are **architecture problems**.

AURA solves this with three core primitives:

| Primitive | Function |
|-----------|----------|
| **8-Layer Character Model** | Physique / Voice / Roots / Network / Core / Tension / Trajectory / Hooks — a character is not a card, a character is a living system |
| **EventPatch** | Events are not logs; they are state patches: *someone (subject) did something (action), causing some effect (consequence)* |
| **Causal Graph** | Events linked by narrative causality, not just chronological order. Inspired by narratology (Bremond, Todorov, Trabasso) |

**One LLM call, two outputs:**

```json
{
  "narrative": {
    "content": "Character dialogue for the player",
    "meta_action": "Stage direction: fingers drumming on table, gaze shifting"
  },
  "structured": {
    "intent_tags": ["evasion", "redirect"],
    "world_delta": [{"field": "interrogation_room.current_focus", "value": "Chen Biao"}],
    "visibility": "public"
  }
}
```

The player sees `narrative.content`. The system consumes `structured` directly — zero additional LLM calls. This is **not** Function Calling. The LLM is not commanding the system. The LLM is self-annotating while producing content.

---

## Why AURA

### The Problem: OOC Is an Architecture Problem, Not a Model Problem

Context windows are already 2M tokens. Models are already GPT-5 level. **OOC still happens.** Why?

Because OOC is not caused by "forgetting." It is caused by **the absence of a deterministic state layer**. LLMs have no concept of "state." They have context. Context is not state.

| Problem | Root Cause | Why a bigger context window won't fix it |
|---------|-----------|------------------------------------------|
| OOC | No persistent character state | 2M tokens of inconsistent text is still inconsistent |
| Character blending | No isolation between NPCs | All NPCs share the same context soup |
| Style contamination | No voice layer enforcement | LLM drifts back to training data style over time |
| State regression | No world_delta validation | LLM-claimed state changes contradict physics/rules |

### The "5G Highway" Analogy

LLMs are highway infrastructure. The industry spent years widening the road (bigger models, longer context). But the **cars** (applications) on the road are still leaking oil.

Roleplay is one of the few proven "cars" on this highway — Character.AI alone has 45 million monthly active users. But this RP "car" leaks everywhere: OOC after 20 turns, memory loss, character drift. **AURA is the repair shop.** We don't build the road. We fix the car.

---

## Narratology Foundation

AURA's architecture is grounded in **narratology**, not just engineering practice:

| Narratological Theory | AURA Implementation |
|----------------------|---------------------|
| **Bremond's Narrative Sequence** | Sequence layer: `Situation Formation → Action Taken → Goal Achieved` |
| **Todorov's Equilibrium Model** | World state manager tracks equilibrium / disequilibrium |
| **Trabasso's Causal Criteria** | "If not A, then not B" — the test for causal link validity |
| **Core vs. Satellite Events (Barthes)** | EventQualifier distinguishes plot-driving events from atmospheric text |
| **Greimas's Actantial Model** | Subject-object-process structure in EventPatch |

> *"The minimal complete plot is the transition from one equilibrium state to another."*
> — Tzvetan Todorov

---

## Current Status

| Module | Status | Notes |
|--------|--------|-------|
| **8-Layer Character Model** | Validated | Definitions locked, schema finalized |
| **Event Bus Design** | Validated | EventPatch schema, causal fields, visibility rules |
| **Dual-Output Architecture** | Defined | `narrative` + `structured` single-call output |
| **Mode A: Prompt Compiler** | v1.1 runnable | Multi-turn chat persistence, context restoration, raw prompt observability |
| **Mode B: World Platform** | Architecture validated | Director + NPC Agent design locked |
| **Sequence Layer** | Defined | PresetSequence (Galgame) + DynamicSequence (open world) |
| **Knowledge Graph Engine** | Defined | Neo4j relation network + causal graph (multi-hop reasoning, indirect association) |
| **Quality Guard Layer** | Planned | Usurpation detection, style filter, length guard (post-output, non-blocking) |
| **ST Card Importer** | Planned | PNG metadata → 8-layer JSON |

**Target Timeline:**
- V1.0 RP Engine (observability + Director + dual-output): 2026 Q3
- V1.1 Knowledge Graph (Neo4j relation reasoning network): 2026 Q4
- V1.2 Novel Mode (outline Agent + foreshadowing tracker): 2027 Q1

---

## Architecture: Character · Event · World · Sequence

### Character — Not a Card, But a Living System

Import a SillyTavern card, AURA auto-fills 8 layers. Empty fields remain empty — LLM hallucination is blocked. Events dynamically fill blanks.

| Layer | Description | Narrative Function |
|-------|-------------|-------------------|
| **Physique** | Build, scars, clothing, traces, aura | Physical presence in scenes |
| **Voice** | Speech rate, verbal tics, register, emotional baseline, silence habits, subtext patterns | Style consistency enforcement |
| **Roots** | Origin soil, fractures, livelihood, social mask, true standing | Deep motivation |
| **Network** | Public relations, secret relations, debts, alliances, information position | Social state |
| **Core** | Surface desires, deep hunger, fears, traumas, moral boundaries, values | Decision-driving force |
| **Tension** | Inner contradictions, external friction, time pressure, identity cracks | Behavioral variation |
| **Trajectory** | Life stage, recent turning points, current burdens, ticking bombs | Arc direction |
| **Hooks** | Entry style, catalytic events, chemistry with others, narrative function | Scene activation |

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
- Actions that did not actually occur (pure thoughts, pure emotions, pure descriptions)
- Actions that caused no state change (idle chatter)
- Actions without a participating subject (environmental descriptions without narrative agency)
- Actions with no expectation-result divergence (repeated confirmations, mechanical responses)

> *Event = Subject + Action + Effect. If any of the three legs is missing, it is a `non_event` — stored in vector memory for semantic retrieval, but does not enter the causal graph.*

### World — Not Scene Description, but Arbiter

- **Physical state**: Locations, items, environmental rules (code-enforced, no LLM involvement)
- **Rules engine**: Validates every `world_delta`; rejects physically/socially impossible state changes
- **Causal graph**: `triggered_by` / `causes` links for long-arc narrative tracking

### Sequence — The Glue Between Events

Events are not isolated atoms. They are organized into **sequences**:

| Sequence Type | Use Case | AURA Mode |
|--------------|----------|-----------|
| **PresetSequence** | Hand-written branching narrative (Galgame structure) | Mode A + Cartridge |
| **DynamicSequence** | Emergent narrative auto-generated from character state and world rules | Mode B |

**Basic sequence structure** (Bremond):
```
Situation Formation (possibility arises) → Action Taken (execution) → Goal Achieved (success/failure)
```

**Compound connection types:**
- **Concatenation**: Sequence A's result = Sequence B's situation formation
- **Nesting**: A sub-sequence embedded within another (flashbacks, side quests)
- **Two-sided**: The same event has different meanings for different characters

---

## Dual-Mode Design

### Mode A: Prompt Compiler (TAVO / ST Compatible)

```
TAVO → AURA → Prompt decomposition → 3-layer memory → Quality guards (post-output) → LLM dual-output → Return
```

- 9-block prompt assembly (constraints + character slice + world slice + event context + sequence context)
- 3-layer memory: WORKING (5 turns) + RECENT (summary) + LONG_TERM (CausalRAG + vector RAG)
- **Quality guards are post-output and non-blocking**: usurpation detection (lightweight regex), style filtering (async), length truncation (async)
- **Dual-output**: One LLM call produces both `narrative` and `structured`
- **Zero LLM retries**: Output guards filter or truncate; never ask the LLM to regenerate

**Endpoint:** `POST /v1/chat/completions`

### Mode B: World Platform (Multi-Agent Narrative)

```
Player input → Director (field snapshot + mention resolution + NPC scheduling + sequence advancement)
  → NPC Agent (independent System Prompt + per-character single LLM call → dual-output)
  → Director arbitration → Merged output
```

- Each NPC has an independent state machine; exchanges information via event bus
- Director handles physical arbitration, conflict resolution, focus scheduling, sequence advancement
- Visibility rules: Each NPC only sees what it should see
- Supports Cartridge loading (`.aura` format) to import complete worlds

**Endpoint:** `POST /v1/world/completions`

---

## Cartridge System (.aura)

Self-contained world data packages:

```
rwby_beacon.aura/
├── meta.yaml          # title, author, version
├── world.yaml         # global rules + initial state
├── sequences/         # preset narrative sequences
│   ├── vol1_defense.yaml
│   └── vol2_stalemate.yaml
├── entities/          # character cards (identity + habits + state)
│   ├── weiss_schnee.yaml
│   └── ruby_rose.yaml
├── locations/         # spatial structure + connectivity
├── events/            # seed events (causal chains)
└── assets/            # optional resource index
```

The Director automatically activates entities present in the field — no keyword matching required. Sequences advance based on state conditions, not script triggers.

---

## Design Principles

1. **Text as root**: Narrative logic is the sole carrier; images/audio are only presentation layers
2. **State before text**: Physical/psychological state changes are computed by rules; LLM only handles cognition/expression layers
3. **Causality before similarity**: RAG retrieves by causal chain first, embedding similarity second
4. **No LLM retries**: Output guards filter or truncate; never request LLM regeneration
5. **Bring your own key**: We don't host models; we host architecture
6. **Narratology-driven engineering**: Event definitions, sequence structures, and causal tests are all grounded in narratological theory (Bremond, Todorov, Barthes, Greimas, Trabasso)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Gateway | FastAPI + Pydantic v2 + Uvicorn |
| LLM Client | httpx (direct) |
| Orchestration (Mode A) | LangGraph + LangChain Core |
| Vector Memory | FAISS + sentence-transformers |
| Knowledge Graph | Neo4j (relation reasoning + causal network) |
| Structured Storage | SQLite |
| Meta Model | Pydantic v2 |
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
# Then connect TAVO to: http://localhost:8080/v1/chat/completions
```

> **Note**: The current version is a skeleton. It runs, but results may not yet surpass native ST. We are validating architecture, not delivering product.

---

## Roadmap

See [ROADMAP.zh.md](./ROADMAP.zh.md) for details.

| Stage | Focus | Status |
|-------|-------|--------|
| **v0.9.x** | Prompt compiler skeleton: dual-output architecture, LangGraph workflow | Skeleton runnable |
| **v1.0.x** | RP engine core: 8-layer state machine, observability dashboard, Director Agent, dual-output constraint | In development |
| **v1.1.x** | Knowledge graph: Neo4j relation reasoning network, causal network, indirect association queries | Architecture validated, code pending |
| **v1.2.x** | Novel mode: outline Agent, narrative Agent, foreshadowing tracker, author style mimicry | Defined |
| **v1.3.x** | Multi-Agent concurrency: parallel NPC LLM calls, physical elimination of attention dilution | Planned |
| **v1.4.x** | Event emergence: EventEngine, PacingEngine, PerturbationEngine | Planned |

---

## How to Contribute

**You don't need to write code to help.**

- **Share pain points**: What's the most frustrating OOC scenario you've experienced in ST/CAI? We need real test cases.
- **Review architecture**: Is there anything critical missing from the 8-layer model for your RP style?
- **Share scenarios**: Have you ever been in a TTRPG situation where "multiple characters must never blend"? Tell us the details.
- **Design critique**: We especially need feedback on EventPatch visibility rules, sequence layers, and world agent arbitration logic.

**Developers:**
- See [ROADMAP.zh.md](./ROADMAP.zh.md) for current tasks
- See [docs/](./docs/) for architecture documentation
- PRs welcome, especially for:
  - Mode A quality guard layer (usurpation detection, style filtering)
  - ST card importer (PNG metadata parsing → 8-layer JSON)
  - YAML Cartridge format validator

---

## License

Apache-2.0

AURA is licensed under the Apache License, Version 2.0. You are free to use, modify, and distribute this software, including for commercial purposes. See [LICENSE](./LICENSE) for the full license text.

---

## Acknowledgments

Built for the RWBY universe and the broader world of narrative.

The first Cartridge, `rwby_beacon`, featuring Blake Belladonna and Pyrrha Nikos — distilled from 500 time loops and 210,000 words of fan fiction.

AURA's Cartridge system is open to any fictional universe or TTRPG module. PRs welcome.

<p align="center">
  <a href="README.zh.md">🇨🇳 中文</a>
</p>

<h1 align="center">AURA 🚧</h1>

<p align="center">
  <strong>⚠️ This is not a ready-to-use product. It is an architecture validation project.</strong><br><br>
  We are building an <strong>event-driven narrative engine with character state machines</strong>.<br>
  Architecture validated. Implementation in progress.<br>
  ST-compatible frontend, private deployment, bring-your-own-key.
</p>

---

## Why This Project

SillyTavern and TAVO are excellent frontends, but they bet everything on the LLM's context window. After 20 rounds: OOC, character bleeding, state regression, style pollution. These aren't Prompt problems—they're **architecture problems**. No state layer means no consistency.

**The hypothesis we are validating**: If we insert a deterministic layer of "event bus + state machine" between the frontend and the LLM, can characters truly possess memory, trauma, and growth arcs?

If you have ever experienced a beloved RP character suddenly forgetting your shared history, or two NPCs in a group chat sounding like the same person, you understand the pain we are trying to solve.

---

## Current Status

| Module | Status | Notes |
|--------|--------|-------|
| **Event Bus Design** | ✅ Validated | Data model, causality chain, visibility mechanism defined |
| **8-Layer Character Model** | ✅ Validated | Physique / Voice / Roots / Network / Core / Tension / Trajectory / Hooks |
| **Mode A: Prompt Compiler** | 🚧 Skeleton runnable | Can connect to TAVO; basic 3-layer memory; quality guards WIP |
| **Mode B: World Platform** | 📋 Design stage | Director + NPC Agent architecture documented, code pending |
| **ST Card Importer** | 📋 Pending | PNG/JSON parsing, 8-layer auto-population |
| **Causal Engine** | 📋 Pending | Kuzu graph DB, long-arc narrative tracking |
| **Local VLM Integration** | 📋 Pending | Qwen2.5-VL / MiniCPM-V for image-to-physique |

**Estimated Availability**
- Mode A stable: 2026 Q3
- Mode B prototype: 2026 Q4

---

## What We Are Validating

### Target Architecture: Character · Event · World

AURA's narrative logic rests on three structured entities—not chat logs, but **state diffs + causal chains + rule arbitration**.

#### Character (Entity) — Not a card, a living system

Import a SillyTavern card and AURA parses it into **8 layers**:

- **Physique**: Skeleton, marks, wear, traces, aura
- **Voice**: Pace, tics, register, emotional baseline, silence habits, subtext patterns
- **Roots**: Soil, rupture, livelihood, social mask, real standing
- **Network**: Public ties, secret ties, debts, alliances, information position
- **Core**: Surface desire, deep hunger, fear, wound, moral boundary, values
- **Tension**: Internal contradictions, external friction, time pressure, identity crack
- **Trajectory**: Life stage, recent turning point, current burdens, ticking bombs
- **Hooks**: Entry style, catalyst events, chemistry with others, information nodes, narrative function

**Empty fields stay empty**. LLM hallucination is blocked; later events or user edits fill gaps dynamically.

#### Event (EventPatch) — Not a log, a state patch

```yaml
Event:
  header:
    id: evt_042
    type: utterance | action | state_change
    causality:
      triggered_by: evt_038   # direct trigger
      root_cause: evt_001     # root cause tracking
    visibility: public | private | faction_only
  payload:
    source: char_001
    targets: [char_002]
    content: "Where were you last night?"
    intent_tags: [inquiry, pressure]
    world_delta:
      proposed_changes:
        - {field: "char_002.psychological.stress", delta: +0.1}
  routing:
    required_agents: [character, world]
```

#### World — Not scene description, an arbiter

- **Physical state**: Locations, items, environmental rules (code-enforced, no LLM)
- **Rule engine**: Validates every `world_delta`; rejects physically/socially impossible requests
- **Causal graph**: `triggered_by` and `causes` links for long-arc narrative tracking

---

## Dual-Mode Design

### Mode A: Prompt Compiler (TAVO / ST Compatible)

```
TAVO → AURA → Prompt Decomposition → 3-Layer Memory → Quality Guard → LLM → Return
```

- 9-Block Prompt assembly (constraints + character slice + world slice + event context)
- 3-layer memory: WORKING (5 turns) + RECENT (summaries) + LONG_TERM (RAG Top-5)
- Lightweight filtering: overreach detection, style guard, length truncation (**no LLM retry**)

**Endpoint**: `POST /v1/chat/completions`

### Mode B: World Platform (Multi-Agent Narrative)

```
Player Input → Director (field snapshot + mention resolution + NPC scheduling)
  → NPC Agent (independent System Prompt + single LLM call per character)
  → Director Arbitration → Merged Output
```

- Each NPC owns an independent state machine; exchanges information via Event Bus
- Director handles physical arbitration, conflict resolution, focus scheduling
- Supports cartridge loading (`.aura` format) for complete world imports

**Endpoint**: `POST /v1/world/completions`

---

## How to Participate

**You don't need to write code to help.**

- **Share pain points**: What is the most disgusting OOC scene you've experienced in ST/CAI? We need real test cases.
- **Review architecture**: Does the 8-layer character model miss anything critical for your RP style?
- **Share scenarios**: If you have a TTRPG experience where "multiple characters must not crosstalk," tell us the details.
- **Design critique**: We are especially looking for feedback on the Event Bus visibility rules and the World Agent arbitration logic.

**For developers:**
- See [ROADMAP.md](./ROADMAP.md) for current tasks
- See [docs/](./docs/) for architecture documents
- PRs welcome, especially for:
  - Mode A quality guard layer (overreach detection, style filter)
  - ST card importer (PNG metadata parser → 8-layer JSON)
  - YAML cartridge format validator

---

## Quick Experience (Current Skeleton)

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

**⚠️ Note**: The current version is a skeleton. It runs, but the effect may not be better than native ST yet. We are validating architecture, not shipping a product.

---

## Cartridge System (.aura) — Design Preview

Self-contained world data packages (format locked, loader pending):

```
rwby_beacon.aura/
├── meta.yaml          # Title, author, version
├── world.yaml         # Global rules + initial state
├── entities/          # Character cards (Identity + Habitus + State)
│   ├── weiss_schnee.yaml
│   └── ruby_rose.yaml
├── locations/         # Spatial structure + connectivity
├── events/            # Seed events (causal chains)
└── assets/            # Optional resource index
```

The Director will automatically activate entities present in the field—no keyword matching required.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Gateway | FastAPI + Pydantic v2 + Uvicorn |
| LLM Client | httpx (direct) |
| Orchestration (Mode A) | LangGraph + LangChain Core |
| Vector Memory | FAISS + sentence-transformers |
| Structured Storage | SQLite |
| Meta-Models | Pydantic v2 |
| Cartridge Format | YAML |

---

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| **v0.9.x** | Prompt Compiler: Single-character depth optimization, ST compatible | 🚧 Skeleton runnable |
| **v1.0.x** | Quality Guard: Overreach detection, style filter, length control | 📋 In development |
| **v1.1.x** | World Platform: Meta-models, cartridge system, Director, NPC Agent | 📋 Architecture validated, code pending |
| **v1.2.x** | Causal Engine: Kuzu graph DB, causal chain traversal, CausalRAG | 📋 Planned |
| **v1.3.x** | Event Emergence: EventEngine, PacingEngine, PerturbationEngine | 📋 Planned |
| **v1.4.x** | Multi-Agent Concurrency: Parallel NPC LLM calls, conflict detection | 📋 Planned |

---

## Design Philosophy

1. **Text is root**: Narrative logic is the sole carrier; images/audio are presentation layers
2. **State-driven**: Entities activate by presence, not keyword matching
3. **Causality first**: Events are state diffs + causal links, not logs
4. **Anti-template**: Consistency guards boundaries, not sentence structures
5. **Player brings API keys**: The platform does not bear model inference costs; data never leaves the user's domain

---

## License

MIT

---

## Acknowledgements

Built for the RWBY universe and beyond.  
The first cartridge, `rwby_beacon`, features Weiss Schnee and Ruby Rose at Beacon Academy's entrance—a homage to where it all began.  
AURA's cartridge system is open to any fictional universe or TTRPG module. PRs welcome.

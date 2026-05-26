# AURA

> **Open-source, privately deployable AI narrative engine**  
> Event Bus × Character State Machine × 8-Layer Character Definition  
> Give your SillyTavern cards memory, trauma, and growth arcs

---

## Not Another API Proxy

SillyTavern and TAVO are excellent frontends, but they bet everything on the LLM's context window. After 20 rounds: OOC, character bleeding, state regression, style pollution. These aren't Prompt problems—they're **architecture problems**. No state layer means no consistency.

AURA inserts a **deterministic narrative layer** between your frontend and the LLM:

| Pain Point | Legacy Fix (Prompt Hacks) | AURA (State Machine) |
|------------|--------------------------|---------------------|
| Character amnesia after 20 turns | Summary compression | **Event Bus persistence + RAG retrieval** |
| Multi-character crosstalk | Single-prompt group chat, one brain split | **Independent NPC Agents, state exchange via events** |
| State regression (pregnant→not→pregnant) | LLM probability drift | **World Agent arbitration, immutable snapshots** |
| Style pollution / lock-in | Model training artifacts | **8-layer definition locks speech fingerprint** |
| Inner monologue leakage | LLM reads all context | **Visibility fields: private events don't broadcast** |
| Player lines overwritten by LLM | Prompt begging "don't write for user" | **JSON Schema output + rule engine guard** |
| Output too long / too short | Temperature tuning | **Structured output + hard length caps, no retry** |

**In one sentence**: ST is a "mask warehouse"; AURA is "bones and nervous system."

---

## Core Architecture: Character · Event · World

AURA's narrative logic rests on three structured entities—not chat logs, but **state diffs + causal chains + rule arbitration**.

### Character (Entity) — Not a card, a living system

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

### Event (EventPatch) — Not a log, a state patch

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

### World — Not scene description, an arbiter

- **Physical state**: Locations, items, environmental rules (code-enforced, no LLM)
- **Rule engine**: Validates every `world_delta`; rejects physically/socially impossible requests
- **Causal graph**: `triggered_by` and `causes` links for long-arc narrative tracking

---

## Dual-Mode Operation

AURA exposes an OpenAI-compatible API for zero-retrofit frontend integration.

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

## SillyTavern Ecosystem Compatible

AURA doesn't replace ST—it gives ST's existing assets capabilities ST will never have:

- **ST card import**: PNG/JSON direct parsing, auto-populating 8-layer definitions
- **Lorebook conversion**: Lorebook entries → world rules + narrative anchors
- **Image parsing**: Local VLM (Qwen2.5-VL / MiniCPM-V) or cloud API (user-provided key) extracts physique descriptions
- **Bidirectional compatibility**: Aura-completed dark threads, tensions, and trajectories export to extended formats

**Key difference**: ST cards are "static masks"; imported into AURA they become "evolving organisms"—state persists across sessions, personality drifts after trauma.

---

## Quick Start

### Requirements

- Python 3.10+
- 8GB+ RAM (recommended)
- LLM API Key (DeepSeek / Kimi / Gemini, user-provided)

### Install

```bash
git clone https://github.com/hbbtsk/AURA.git
cd AURA
pip install -r requirements.txt
```

### Configure

Create `.env`:

```env
# At least one LLM backend
DEEPSEEK_API_KEY=sk-your-deepseek-key
KIMI_API_KEY=sk-your-kimi-key

# Optional: timeout and fallback
LLM_MAIN_TTFB_TIMEOUT=3
LLM_MAIN_FALLBACK_PROVIDER=kimi
```

### Run

```bash
python -m app.main
# Service runs at http://localhost:8000
```

### Connect TAVO (Mode A)

| Setting | Value |
|---------|-------|
| API URL | `http://localhost:8000/v1/chat/completions` |
| API Key | Any value (AURA does not validate; TAVO requires it) |
| Model | `deepseek-v4-flash` / `kimi-k2.6` / `gemini-2.0-flash` |

### Run a World (Mode B)

```bash
curl -X POST http://localhost:8000/v1/world/completions   -H "Content-Type: application/json"   -d '{
    "message": "Hello, Weiss.",
    "cartridge": "rwby_beacon",
    "model": "deepseek-v4-flash"
  }'
```

---

## Cartridge System (.aura)

Self-contained world data packages:

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

The Director automatically activates entities present in the field—no keyword matching required.

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
| **v1.0.x** | Prompt Compiler: LangGraph state machine, 3-layer memory, quality guards | ✅ Stable |
| **v1.1.x** | World Platform: Meta-models, cartridge system, Director, NPC Agent | 🚧 Skeleton |
| **v1.2.x** | Causal Engine: Kuzu graph DB, causal chain traversal, CausalRAG | 📋 Planned |
| **v1.3.x** | Event Emergence: EventEngine, PacingEngine, PerturbationEngine | 📋 Planned |
| **v1.4.x** | Multi-Agent Concurrency: Parallel NPC LLM calls, conflict detection, offline simulation | 📋 Planned |

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

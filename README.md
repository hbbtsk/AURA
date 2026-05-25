# AURA

**Agentic Unified Roleplay Assistant**

AURA is a dual-mode AI narrative engine that bridges front-end RP platforms (like TAVO) with LLM backends. It operates as both a **Prompt Compiler** (optimizing roleplay interactions) and a **Text Adventure Platform** (running immersive worlds with Director + NPC Agent architecture).

---

## What is AURA?

AURA sits between your RP frontend and the LLM backend, solving 15+ systematic pain points in long-form roleplay sessions. Unlike simple API proxies, AURA:

- **Decomposes** chaotic TAVO System Prompts into structured 9-block prompts
- **Retrieves** context via 3-layer memory (Working + Recent + Long-term RAG)
- **Guards** output quality with automated checks (overreach, style pollution, length)
- **Falls back** to backup models when the primary LLM times out
- **Runs worlds** via Director/NPC Agent architecture for true text adventure gameplay

---

## Dual-Mode Architecture

AURA operates in two distinct modes, accessible via different API endpoints:

### Mode A: TAVO Compatible (Prompt Compiler)

The original LangGraph state machine with 15 nodes:

```
TAVO → InputReceive → PromptDecomposer → [6 parallel prep nodes]
  → ContextAssemble → LLMGenerate → ParallelQualityCheck
  → [retry loop] → OutputReturn → MemoryExtract → TAVO
```

**Endpoint:** `POST /v1/chat/completions`

Best for: Direct TAVO integration, single-character roleplay, prompt optimization.

### Mode B: World Platform (Text Adventure Engine)

The new Director + NPC Agent architecture:

```
Player Input → Director (field snapshot + mention resolution + NPC scheduling)
  → NPC Agent (independent System Prompt + LLM call per character)
  → Director Arbitration → Player Response
```

**Endpoint:** `POST /v1/world/completions`

Best for: Multi-character narrative worlds, persistent state, emergent storytelling.

---

## Quick Start

### Requirements

- Python 3.10+
- 8GB+ RAM (recommended)
- LLM API Keys (DeepSeek, Kimi, or Gemini)

### Installation

```bash
git clone https://github.com/hbbtsk/AURA.git
cd AURA
pip install -r requirements.txt
```

### Configuration

Create a `.env` file:

```bash
# Required: at least one LLM backend
DEEPSEEK_API_KEY=sk-your-deepseek-key
KIMI_API_KEY=sk-your-kimi-key

# Optional: fallback configuration
LLM_MAIN_TTFB_TIMEOUT=3          # First-token timeout (seconds)
LLM_MAIN_FALLBACK_PROVIDER=kimi  # Backup model on timeout
```

### Run

```bash
python -m app.main
```

Service runs at `http://localhost:8000`.

### Connect TAVO (Mode A)

In TAVO's custom API settings:

| Setting | Value |
|---------|-------|
| API URL | `http://localhost:8000/v1/chat/completions` |
| API Key | Any value (AURA does not validate, but TAVO requires it) |
| Model | `deepseek-v4-flash` / `kimi-k2.6` / `gemini-2.0-flash` |

### Play a World (Mode B)

```bash
curl -X POST http://localhost:8000/v1/world/completions \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello, Weiss.",
    "cartridge": "rwby_beacon",
    "model": "deepseek-v4-flash"
  }'
```

---

## Cartridge System (.aura)

AURA's world platform uses **cartridges** — self-contained world data packages:

```
rwby_beacon.aura/
├── meta.yaml          # Title, author, version
├── world.yaml         # Global rules + initial state
├── entities/          # Character cards (Identity + Habitus + State)
│   ├── weiss_schnee.yaml
│   └── ruby_rose.yaml
├── locations/         # Spatial structure + connectivity
│   ├── beacon_academy_gate.yaml
│   └── dormitory.yaml
├── events/            # Seed events (causal chains)
│   └── opening.yaml
└── assets/            # Optional resource indices
```

Characters are defined via the **Meta-Model**:

- **Identity** — Who they are (name, race, motivation, speech fingerprint)
- **Habitus** — Conditional behavior mappings ("when X, tend to Y")
- **State** — Ephemeral condition (location, emotion, relationships, memory)

The Director automatically activates entities present in the field — no keyword matching needed.

---

## Core Features

| Feature | Description | Mode |
|---------|-------------|------|
| **Prompt Decomposition** | 3-tier parsing (marked/HTML/fallback) of chaotic TAVO prompts | A |
| **9-Block Prompt Assembly** | Structured SYSTEM prompt with constraints, character card, memory layers | A |
| **3-Layer Memory** | WORKING (5 rounds) + RECENT (10 summaries) + LONG_TERM (RAG Top-5) | A |
| **Intent-Aware RAG v2** | 6-dimensional structured search with field-level embedding + composite scoring | A |
| **LLM Fallback** | Auto-switch to backup model on first-token timeout (default 3s) | A/B |
| **Quality Guard** | Overreach detection + style pollution filter + length control | A |
| **Director Orchestration** | Field rendering, mention resolution, rule checking, NPC scheduling | B |
| **NPC Agent** | Independent System Prompt + LLM call per character, memory-filtered field slice | B |
| **Cartridge Loader** | YAML-to-Pydantic parser with multi-language alias support | B |
| **World State Manager** | Atomic EventPatch application, checkpoint save/load | B |

---

## Meta-Model

AURA's world platform is built on three interconnected meta-models:

### Entity (Character)
```python
class Entity(BaseModel):
    identity: Identity       # DNA — immutable
    habitus: Habitus         # Conditional behavior patterns
    location_id: str         # Current position
    emotion: EmotionalState  # Narrative emotional condition
    relationships: dict      # Per-target relation narratives
    memory: Memory           # Known events + secrets
```

### Event (World Patch)
```python
class EventPatch(BaseModel):
    event_id: str
    state_diffs: list        # Attribute changes per entity
    emotional_impacts: list  # Narrative emotional deltas
    caused_by: list          # Parent event IDs
    causes: list             # Child event IDs
    narrative_text: str      # Natural language for LLM consumption
```

### World (Container)
```python
class World(BaseModel):
    locations: dict          # Spatial graph with travel times
    entities: dict           # All characters
    events: dict             # Causal event graph
    rules: list              # Hard world constraints
    open_loops: list         # Unresolved event IDs
```

---

## Project Structure

```
AURA/
├── app/
│   ├── main.py                 # FastAPI entry point
│   │
│   ├── api/                    # API layer
│   │   ├── router.py           # Pydantic models + routing
│   │   ├── streaming.py        # SSE streaming simulation
│   │   └── completions.py      # /chat/completions + /world/completions
│   │
│   ├── core/                   # Core business logic
│   │   ├── config.py           # Centralized config (scene-isolated)
│   │   ├── intent_tagger.py    # Intent parser
│   │   └── prompt_decomposer.py# Prompt decomposer
│   │
│   ├── graph/                  # LangGraph orchestration (Mode A)
│   │   ├── state.py            # AgentState definition
│   │   ├── workflow.py         # StateGraph builder
│   │   └── nodes/              # 14 node implementations
│   │
│   ├── memory/                 # Memory management
│   │   ├── manager.py          # Memory Facade
│   │   ├── faiss_store.py      # FAISS vector search
│   │   ├── sqlite_store.py     # SQLite structured storage
│   │   └── summarizer.py       # Dialogue summarization
│   │
│   ├── models/                 # Meta-models (Mode B)
│   │   ├── entity.py           # Entity, Identity, Habitus, etc.
│   │   ├── event.py            # EventPatch, StateChange, etc.
│   │   └── world.py            # World, Location, WorldRule, etc.
│   │
│   ├── cartridge/              # Cartridge system (Mode B)
│   │   ├── loader.py           # YAML → Pydantic parser
│   │   └── validator.py        # Consistency checker
│   │
│   ├── world/                  # World runtime (Mode B)
│   │   └── runtime.py          # WorldRuntime + checkpointing
│   │
│   ├── director/               # Director (Mode B)
│   │   └── director.py         # Field snapshot, scheduling, arbitration
│   │
│   ├── npc/                    # NPC Agent (Mode B)
│   │   └── agent.py            # Per-character LLM calls
│   │
│   ├── causal/                 # Causal engine (stub)
│   └── engine/                 # Event/Pacing/Perturbation engines (stub)
│
├── cartridges/                 # Example world cartridges
│   └── rwby_beacon/
│       ├── meta.yaml
│       ├── world.yaml
│       ├── entities/
│       ├── locations/
│       └── events/
│
├── AURA-1.0-架构总纲.md       # Architecture manifesto (Chinese)
└── requirements.txt
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API Gateway | FastAPI + Pydantic v2 + Uvicorn |
| LLM Client | httpx (direct API calls) |
| Orchestration (Mode A) | LangGraph + LangChain Core |
| Vector Memory | FAISS (IndexFlatL2) + sentence-transformers (bge-small-zh-v1.5) |
| Structured Storage | SQLite |
| Meta-Models | Pydantic v2 |
| Cartridge Format | YAML |

---

## Development Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| **v0.8.x** | Prompt Compiler — LangGraph state machine, 3-layer memory, quality guards | ✅ Stable |
| **v0.9.x** | World Platform — Meta-models, cartridge system, Director, NPC Agent | 🚧 Skeleton |
| **v0.10.x** | Causal Engine — Kuzu graph DB, causal chain traversal, CausalRAG | 📋 Planned |
| **v0.11.x** | Event Emergence — EventEngine, PacingEngine, PerturbationEngine | 📋 Planned |
| **v0.12.x** | Multi-Agent — Concurrent NPC LLM calls, conflict detection, offline simulation | 📋 Planned |

---

## Design Philosophy

1. **Text is root** — Narrative logic is the sole carrier. Images/music are presentation layers.
2. **State-driven** — Entities activate by presence, not keyword matching.
3. **Causality first** — Events are state diffs + causal links, not logs.
4. **Anti-template** — Consistency guards boundaries, not sentence structures.
5. **Player brings API keys** — The platform does not bear model inference costs.

---

## License

MIT

---

## Acknowledgements

Built for the RWBY universe and beyond. The first cartridge (`rwby_beacon`) features Weiss Schnee and Ruby Rose at Beacon Academy's entrance — a homage to where it all began.

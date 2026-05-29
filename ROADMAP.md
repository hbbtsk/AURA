# AURA Roadmap

> **Current Phase**: V1.0 RP Engine Core Development
> **Last Updated**: 2026-05-29

---

## Version Overview

| Version | Focus | Target Date | Status |
|---------|-------|-------------|--------|
| V0.9.x | Prompt compiler skeleton | Completed | Skeleton runnable |
| **V1.0.x** | **RP Engine Core** | **2026 Q3** | **In development** |
| V1.1.x | Knowledge Graph (Neo4j) | 2026 Q4 | Architecture validated |
| V1.2.x | Novel Mode | 2027 Q1 | Defined |
| V1.3.x | Multi-Agent Concurrency | 2027 Q2 | Planned |
| V1.4.x | Event Emergence Engine | 2027 H2 | Long-term |

---

## V1.0.x — RP Engine Core (Current)

**Goal**: A working RP engine where characters stay in-character for 50+ turns, fully observable via dashboard

### V1.0.0 Must-Have

- [ ] **8-Layer State Machine**
  - [ ] Character card import (SillyTavern PNG format)
  - [ ] 8-layer schema definition + Pydantic models
  - [ ] Numeric-to-adjective mapping (trust 0.62 → "basic trust")
  - [ ] Inter-layer dependency rules (trust change triggers emotion change)

- [ ] **Dual-Output Constraint**
  - [ ] System Prompt enforces narrative + structured format
  - [ ] structured layer world_delta parsing + execution
  - [ ] Completeness check (missing structured → warning flag)

- [ ] **Director Agent (Simplified)**
  - [ ] Intent recognition (fast model call)
  - [ ] Character scheduling (who should speak)
  - [ ] Director instruction generation

- [ ] **Observability Dashboard**
  - [ ] Real-time panel (triad: Character + Event + World)
  - [ ] Engine panel (LLM call chain: Memory→Compress→Intent→Prompt)
  - [ ] Character switcher + relation matrix display
  - [ ] Historical turn replay

- [ ] **Infrastructure**
  - [ ] FastAPI route layer
  - [ ] SQLite schema (characters, events, world state, turns)
  - [ ] @snapshot decorator (intermediate process capture)

### V1.0.1 Polish

- [ ] Voice few-shot injection (character language style lock)
- [ ] Relation matrix character switch sync
- [ ] Quality guard layer (usurpation detection, style filter)
- [ ] ST card importer refinement (handle more fields)

---

## V1.1.x — Knowledge Graph (Neo4j)

**Goal**: Relation matrix → relation reasoning network; causal chain → causal network

- [ ] **Neo4j Deployment**
  - [ ] Docker local deployment
  - [ ] Python neo4j driver integration
  - [ ] Dual-write strategy (SQLite backup + Neo4j query)

- [ ] **Graph Data Model**
  - [ ] Character nodes (8-layer summaries)
  - [ ] Event nodes (with world_impact)
  - [ ] WorldEntity nodes (scenes/items/factions)
  - [ ] RELATES_TO relationships (directed + historical evolution)
  - [ ] CAUSED / CONTRIBUTED_TO relationships (strong/weak causality)
  - [ ] INVOLVES / AFFECTS relationships

- [ ] **Graph Query APIs**
  - [ ] Indirect relation query (how A and B connect through intermediaries)
  - [ ] Multi-hop causal backtracking (all indirect causes of an event)
  - [ ] Relation evolution timeline (A→B trust from turn 1 to turn N)
  - [ ] Global relation network export (D3.js force-directed graph data)

- [ ] **Dashboard Frontend Upgrade**
  - [ ] Relation path exploration panel
  - [ ] Force-directed graph visualization

---

## V1.2.x — Novel Mode

**Goal**: Extend from RP engine to general narrative AI tool

- [ ] **Outline Agent**
  - [ ] Three-act structure auto-generation
  - [ ] Chapter beat planning
  - [ ] Author manual editing of outlines

- [ ] **Narrative Agent**
  - [ ] Narrative text generation following outline (third-person)
  - [ ] Character consistency across long form (500k+ words)
  - [ ] Mixed output: scene description + psychology + dialogue

- [ ] **Foreshadowing Tracker**
  - [ ] Auto-tag unredeemed foreshadowing
  - [ ] Foreshadowing redemption alert (warn if N chapters unmentioned)
  - [ ] Author manual foreshadowing management

- [ ] **Author Style Mimicry**
  - [ ] Style fingerprint extraction from 3-5 sample chapters
  - [ ] Sentence preference, rhetorical habits, narrative distance
  - [ ] Style consistency check

---

## V1.3.x — Multi-Agent Concurrency

**Goal**: Physically eliminate attention dilution, 5+ NPCs online simultaneously

- [ ] **Director Agent (Full Version)**
  - [ ] Focus scheduling (who speaks, who stays silent)
  - [ ] Inter-NPC information transfer (visibility rules)
  - [ ] Conflict detection and arbitration

- [ ] **Multi-Character Agent Parallelism**
  - [ ] Independent LLM call per NPC
  - [ ] Prompt length control (single Agent < 2.5k tokens)
  - [ ] Output merge logic

- [ ] **RAG Memory Retrieval**
  - [ ] Semantic retrieval (vector similarity)
  - [ ] Logical retrieval (graph association)
  - [ ] Hybrid ranking

---

## V1.4.x — Event Emergence Engine (Long-term)

- [ ] EventEngine: Auto-generate emergent events consistent with character state
- [ ] PacingEngine: Rhythm control (tension and release)
- [ ] PerturbationEngine: External perturbation injection (sudden events)

---

## Current Tasks (V1.0.0 In Development)

See GitHub Issues. Current priorities:

1. **Observability dashboard frontend** (aura_obs_demo/index.html glue code)
2. **@snapshot decorator** (LLM call intermediate process capture)
3. **8-layer state machine data model** (SQLite schema + adjective mapping)
4. **Director Agent prompt template** (intent recognition + scheduling instructions)

---

## How to Contribute

- **RP Players**: Try V1.0, report OOC scenarios, provide test cases
- **Novel Authors**: Follow V1.2 novel mode, share long-form creation pain points
- **Developers**: GitHub PRs. Currently most needed: quality guard layer, ST card importer

---

## Design Document Index

| Document | Content |
|----------|---------|
| [AURA_evaluation.agent.final.md](AURA_evaluation.agent.final.md) | Comprehensive project evaluation report |
| [AURA_维测架构_v2.md](AURA_维测架构_v2.md) | Observability architecture design (automated review) |
| [AURA_Neo4j_知识图谱数据模型.md](AURA_Neo4j_知识图谱数据模型.md) | Neo4j graph data model + Cypher queries |
| [AURA_项目价值重估_9成效果.md](AURA_项目价值重估_9成效果.md) | Project value reassessment at 90% implementation |
| [aura_obs_demo/index.html](aura_obs_demo/index.html) | Observability dashboard frontend demo |
| [aura_obs_demo/AURA维测前端开发文档.md](aura_obs_demo/AURA维测前端开发文档.md) | Frontend development integration document |

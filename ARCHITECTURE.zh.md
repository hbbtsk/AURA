# AURA 架构文档

> **版本:** v1.0.0 | **最后更新:** 2026-05-25

AURA 是一个双模式 AI 叙事引擎。本文档描述两种模式的技术架构。

---

## 目录

1. [系统概述](#1-系统概述)
2. [双模式架构](#2-双模式架构)
3. [模式 A：Prompt 编译器（LangGraph）](#3-模式-a-prompt-编译器langgraph)
4. [模式 B：世界平台（Director + NPC Agent）](#4-模式-b-世界平台director--npc-agent)
5. [元模型](#5-元模型)
6. [卡带系统](#6-卡带系统)
7. [共享基础设施](#7-共享基础设施)
8. [项目结构](#8-项目结构)
9. [版本历史](#9-版本历史)

---

## 1. 系统概述

AURA 作为 RP 前端（TAVO）与 LLM 后端之间的中间层，解决长篇角色扮演中的 15+ 个系统性痛点：

- **拆解**混沌的 TAVO System Prompt 为结构化组件
- **编译**为模型优化的区块化 Prompt
- **检索**上下文 via 三层记忆 + 因果图遍历（计划中）
- **质检**输出质量，自动检测越权、文风污染、长度异常
- **故障转移**——主模型超时时自动切换到备用模型

---

## 2. 双模式架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              TAVO / 玩家                                 │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                         │
              ▼                                         ▼
┌─────────────────────────────┐           ┌─────────────────────────────┐
│   模式 A: /chat/completions │           │   模式 B: /world/completions │
│   (Prompt 编译器)            │           │   (世界平台)                │
├─────────────────────────────┤           ├─────────────────────────────┤
│ LangGraph 14 节点状态机      │           │ Director                     │
│ ├─ PromptDecomposer         │           │ ├─ 场域快照                  │
│ ├─ ContextAssemble          │           │ ├─ 指代消解                  │
│ ├─ LLMGenerate              │           │ ├─ NPC 调度                  │
│ ├─ FormatGuard              │           │ ├─ 规则检查                  │
│ └─ MemoryExtract            │           │ └─ 仲裁                      │
│                             │           │                              │
│ 三层记忆 (FAISS)            │           │ NPC Agent (×N)              │
│ SQLite 对话存储             │           │ ├─ 独立 System Prompt        │
│ IntentTagger                │           │ ├─ Identity + Habitus        │
└─────────────────────────────┘           │ └─ LLM 调用（复用模式 A）    │
              │                           └─────────────────────────────┘
              └────────────────────┬────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         LLM 后端 (DeepSeek/Kimi/Gemini)                  │
│                         主模型 → 备用模型故障转移（3s 首 token 超时）     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 模式 A：Prompt 编译器（LangGraph）

### 3.1 状态机

```
[InputReceive] → [PromptDecomposer] → [EntityExtract] → [EmotionAnalyze]
                                                          │
                                                          ▼
[StateManager] ← [StyleInjection] ← [ModelDialectCompiler] ← [MemoryRetrieve]
       │
       ▼
[ContextAssemble] → [LLMGenerate] → [ParallelQualityCheck]
       │                                      │
       │                          [重试循环, 最多 2 次]
       │                                      │
       └──────────────────┬───────────────────┘
                          ▼
                   [OutputReturn] → [MemoryExtract]
```

### 3.2 关键节点

| 节点 | 文件 | 状态 | 说明 |
|------|------|------|------|
| InputReceive | `input_receive.py` | ✅ | 请求解析 + 意图预调用 |
| PromptDecomposer | `prompt_decomposer.py` | ✅ | 三层递进解析（`=====` / HTML / 回退） |
| MemoryRetrieve | `memory_nodes.py` | ✅ | FAISS RAG（语义 + 结构化 + 时间） |
| ContextAssemble | `context_assemble.py` | ✅ | 9 区块 System Prompt 组装 |
| LLMGenerate | `llm_quality_output.py` | ✅ | 非流式调用，主模型→备用模型故障转移 |
| FormatGuard | `llm_quality_output.py` | ✅ | 越权 + 文风污染 + 长度检查 |
| OutputReturn | `llm_quality_output.py` | ✅ | 响应包装 + SSE 模拟 |
| MemoryExtract | `memory_nodes.py` | ✅ | 对话同步 + 总结触发 |
| RetryStrategy | `retry_strategy.py` | ✅ | 失败分析 + 策略补丁 |
| EntityExtract | `entity_extract.py` | 🔲 Stub | 实体识别（预留） |
| EmotionAnalyze | `emotion_analyze.py` | 🔲 Stub | 情绪分析（预留） |
| StateManager | `state_style_compiler.py` | 🔲 Stub | 动态状态注入（预留） |
| StyleInjection | `state_style_compiler.py` | 🔲 Stub | 文风控制（预留） |
| ModelDialectCompiler | `state_style_compiler.py` | 🔲 Stub | 单模型格式优化（预留） |

### 3.3 9 区块 Prompt 结构

```
[MAIN_PROMPT]       ← 用户自定义提示词头部
[PROTOCOL]          ← 通信标记约定
[CONSTRAINTS]       ← 角色边界 + 负向指令
[CHARACTER_CARD]    ← 角色卡（来自 TAVO）
[USER_PROFILE]      ← 用户设定（来自 TAVO）
[CURRENT_STATE]     ← 实体当前状态（预留）
[RECENT_MEMORY]     ← 最近 10 条记忆摘要
[LONG_TERM_MEMORY]  ← RAG Top-5 / TAVO 降级透传
[WORLD_CONTEXT]     ← 世界书（条件注入）
[OUTPUT_SPEC]       ← 输出格式 + COT 自检
```

**近因效应**：`WORKING_MEMORY`（最近 5 轮）+ `USER_INTENT_TAG` 追加到最后一条 user 消息末尾，最大化遵循率。

---

## 4. 模式 B：世界平台（Director + NPC Agent）

### 4.1 单轮运转流程

```
玩家输入
    │
    ▼
Director.resolve_mention() ──→ Alias 匹配（多语言）
    │
    ▼
Director.get_field_snapshot() ──→ WorldField（地点、时间、环境、规则）
    │
    ▼
Director.check_rule_violation() ──→ WorldRule 校验
    │
    ▼
Director.schedule_npcs() ──→ 本轮哪些 NPC 该反应？
    │
    ▼
对每个调度的 NPC：
    Director.get_npc_field_slice() ──→ 按记忆权限过滤的场域切片
    NPCAgent.build_system_prompt() ──→ Identity + Habitus + 已知事件
    NPCAgent.generate_response() ──→ LLM 调用（复用 _call_single_llm）
    │
    ▼
Director.arbitrate_outputs() ──→ 冲突检测 + 戏剧性排序
    │
    ▼
World.apply_patch(EventPatch) ──→ 原子性状态提交
    │
    ▼
流式返回给玩家
```

### 4.2 Director

| 能力 | 状态 | 说明 |
|------|------|------|
| 场域快照 | ✅ | 从 WorldField + 全局状态渲染环境氛围 |
| 指代消解 | ✅ | 跨语言别名匹配，失败时语义兜底 |
| 规则检查 | 🟡 Mock | 基于关键词的规则违规检测 |
| NPC 调度 | 🟡 Mock | 返回所有在场 NPC（后续按 Habitus 匹配细化） |
| 场域切片 | ✅ | 按记忆权限过滤的每个 NPC 专属视图 |
| 仲裁 | 🟡 Mock | 简单拼接（后续增强冲突检测） |

### 4.3 NPC Agent

- **视角**：纯角色视角。只知道 `memory.known_events` 里的内容。
- **System Prompt**：由 `Identity + Habitus + State + known_events + relationships` 构建
- **LLM 调用**：独立调用，复用模式 A 的 `_call_single_llm`（含故障转移）
- **状态更新**：`update_emotion()` / `add_known_event()` 由 EventPatch 触发

---

## 5. 元模型

### 5.1 实体（三层结构）

| 层级 | 类 | 可变？ | 关键字段 |
|------|-----|--------|----------|
| **存在层** | `Identity` | ❌ | `entity_id`, `name`, `race`, `core_motivation`, `speech_fingerprint`, `aliases` |
| **实践层** | `Habitus` | ❌ | `Tendency[]`, `default_behavior`, `stress_response` |
| **涌现层** | `State` | ✅ | `location_id`, `EmotionalState`, `relationships`, `memory` |

### 5.2 EventPatch（状态差分 + 因果连接）

- `state_diffs`：每个实体的属性变更（支持点路径，如 `emotion.current_label`）
- `emotional_impacts`：每个实体的情感冲击叙事
- `caused_by` / `causes` / `activates` / `closes`：因果链连接
- `public_to` / `secret_to` / `hidden_from`：可见性权限

### 5.3 World（容器）

- `locations`：空间图，含 `connected_to` 通行时间
- `entities`：所有角色
- `events`：因果事件图
- `rules`：硬约束，含作用范围和例外事件
- `open_loops`：未闭合事件 ID（驱动叙事张力）

---

## 6. 卡带系统

```
example_world.aura/
├── meta.yaml          # 标题、作者、版本、依赖
├── world.yaml         # 规则 + 初始状态 + open_loops
├── entities/          # 角色 YAML 文件
│   └── weiss_schnee.yaml
├── locations/         # 空间结构
│   └── beacon_academy_gate.yaml
├── events/            # 种子事件
│   └── opening.yaml
└── assets/            # 可选资源
```

**加载器**：`CartridgeLoader` 解析 YAML → Pydantic 模型，支持多语言名称解析。
**校验器**：`CartridgeValidator` 检查内部一致性（地点连通性、事件因果链、关系引用）。

---

## 7. 共享基础设施

### 7.1 记忆（模式 A + 模式 B）

| 层级 | 实现 | 状态 |
|------|------|------|
| 向量检索 | FAISS (IndexFlatL2) + bge-small-zh-v1.5 | ✅ 运行中 |
| 结构化存储 | SQLite（对话、会话、动态状态） | ✅ 运行中 |
| 因果图 | Kuzu / NetworkX（预留） | ❌ 尚未接入 |

### 7.2 LLM 配置

```python
# 场景隔离配置
get_llm_config(provider="deepseek", scene="main")
# → temperature=0.7, max_tokens=4096, timeout=60, ttfb_timeout=3

get_llm_config(provider="kimi", scene="intent")
# → temperature=0.3, max_tokens=1024, timeout=15
```

### 7.3 故障转移

- 主模型受 `ttfb_timeout` 限制（默认 3 秒）
- `asyncio.TimeoutError` 时自动切换到 `fallback_provider`
- 备用模型使用完整 timeout，不限制首 token 时间
- 状态记录 `actual_backend`、`fallback_triggered`、`fallback_reason`

---

## 8. 项目结构

```
AURA/
├── app/
│   ├── main.py                 # FastAPI 入口 + 生命周期
│   ├── api/
│   │   ├── router.py           # Pydantic 模型 + 路由
│   │   ├── completions.py      # /chat/completions + /world/completions
│   │   └── streaming.py        # SSE 模拟
│   ├── core/
│   │   ├── config.py           # 场景隔离 LLM 配置
│   │   ├── intent_tagger.py    # 意图解析器
│   │   └── prompt_decomposer.py# Prompt 拆解器
│   ├── graph/                  # 模式 A: LangGraph 编排
│   │   ├── state.py
│   │   ├── workflow.py
│   │   └── nodes/              # 14 个节点实现
│   ├── memory/                 # 共享记忆层
│   │   ├── manager.py
│   │   ├── faiss_store.py
│   │   ├── sqlite_store.py
│   │   ├── embedding.py
│   │   ├── summarizer.py
│   │   └── models.py
│   ├── models/                 # 模式 B: 元模型
│   │   ├── entity.py
│   │   ├── event.py
│   │   └── world.py
│   ├── cartridge/              # 模式 B: 卡带系统
│   │   ├── loader.py
│   │   └── validator.py
│   ├── world/                  # 模式 B: 世界运行时
│   │   └── runtime.py
│   ├── director/               # 模式 B: Director
│   │   └── director.py
│   ├── npc/                    # 模式 B: NPC Agent
│   │   └── agent.py
│   ├── causal/                 # 预留: 因果引擎桩
│   └── engine/                 # 预留: 事件/节奏/扰动引擎桩
│
├── cartridges/                 # 示例世界卡带
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
├── README.md                   # 英文
├── README.zh.md                # 中文
├── ROADMAP.md                  # 英文
├── ROADMAP.zh.md               # 中文
├── ARCHITECTURE.md             # 本文件
├── ARCHITECTURE.zh.md          # 本文件中文版本
└── requirements.txt
```

---

## 9. 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v0.5.0 | 2026-05-03 | 基础转发 + Prompt 拆解 |
| v0.6.0 | 2026-05-04 | SQLite + FAISS 记忆 + RAG |
| v0.7.0 | 2026-05-10 | 三层记忆 + IntentTagger + 意图感知 RAG v2 |
| v0.8.0 | 2026-05-11 | LangGraph 14 节点状态机 |
| v0.8.3 | 2026-05-17 | 模块重组 + 文件拆分 |
| v1.0.0 | 2026-05-25 | 路线 B: 元模型、卡带系统、Director、NPC Agent、LLM 故障转移 |
| **v1.1.0** | **2026-05-30** | **多轮对话持久化：`chats` 表、按 chat 递增 turn、上下文恢复、Dashboard chat/轮次选择器、原始 Prompt 区块 + token 统计、日志持久化 + SSE 流式** |

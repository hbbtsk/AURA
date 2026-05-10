# AURA 架构文档

> **AURA** — Agentic Unified Roleplay Assistant
> 版本: v0.7.0 | 最后更新: 2026-05-10

---

## 目录

1. [项目概述](#1-项目概述)
2. [痛点映射表](#2-痛点映射表)
3. [系统架构总览](#3-系统架构总览)
4. [数据流](#4-数据流)
5. [模块详解](#5-模块详解)
   - 5.1 [入口层: `app/main.py`](#51-入口层-appmainpy)
   - 5.2 [配置层: `app/config.py`](#52-配置层-appconfigpy)
   - 5.3 [API 层: `app/api/completions.py`](#53-api-层-appapicompletionspy)
   - 5.4 [Prompt 拆解器: `app/prompt_decomposer.py`](#54-prompt-拆解器-appprompt_decomposerpy)
   - 5.5 [意图解析器: `app/intent_tagger.py`](#55-意图解析器-appintent_taggerpy)
   - 5.6 [记忆管理层: `app/memory/manager.py`](#56-记忆管理层-appmemorymanagerpy)
   - 5.7 [数据模型: `app/memory/models.py`](#57-数据模型-appmemorymodelspy)
6. [Prompt 编译管道](#6-prompt-编译管道)
7. [三层记忆架构](#7-三层记忆架构)
8. [意图感知 RAG (v2)](#8-意图感知-rag-v2)
9. [SSE 流式处理](#9-sse-流式处理)
10. [配置系统](#10-配置系统)
11. [错误处理与降级策略](#11-错误处理与降级策略)
12. [项目文件结构](#12-项目文件结构)

---

## 1. 项目概述

AURA 是一个**角色扮演专用的 Prompt 编译器 + 模型行为校正引擎**。它作为中间层（Middleware）部署在 TAVO（前端 RP 平台）与 LLM（后端模型）之间，拦截 TAVO 发出的请求，对 Prompt 进行拆解、重组、增强，再转发给 LLM。

### 核心使命

- **拆解** TAVO 的原始 Prompt 为结构化组件（角色卡、长记忆、世界书等）
- **编译** 为优化后的区块化 Prompt（注入 AURA 的约束、记忆、意图指令）
- **重组** 利用认知心理学原理（近因效应、启动效应、格式塔原则）提升 LLM 输出质量

### 设计原则

| 原则 | 说明 |
|------|------|
| **非侵入** | AURA 不修改 TAVO 的请求格式，完全兼容 TAVO 协议 |
| **降级韧性** | 任何模块失败都不阻断主流程，自动降级为原始透传 |
| **场景隔离** | 每个 LLM 调用场景（主对话/记忆总结/意图分析）有独立配置 |
| **认知驱动** | Prompt 布局基于认知心理学原理，而非随意排列 |

---

## 2. 痛点映射表

AURA 的每个模块都针对特定的 RP 用户体验痛点设计。下表展示 15 个系统性痛点与各模块的解决关系。

| # | 痛点 | 涉及模块 | 解决状态 |
|---|------|----------|----------|
| 1 | **越权输出** — 模型替 user 写台词/行动 | [`CONSTRAINTS`](app/api/completions.py:351) 区块 + [`OUTPUT_SPEC`](app/api/completions.py:567) COT 校验 + RAG 记忆压缩减少 Prompt 噪声 | ✅ 显著缓解 |
| 2 | **文风污染** — 垃圾小说训练痕迹（臀腿腰胸） | Week 2 FormatGuard（预留） | ❌ 待 Week 2 |
| 3 | **文风固化** — 长时间同一模型锁死 | Week 3 ModelDialectCompiler（预留） | ❌ 待 Week 3 |
| 4 | **状态回退** — 怀孕→生完→又怀孕 | [`CURRENT_STATE`](app/api/completions.py:366) 区块 + StateManager（预留 Day 4） | ✅ 部分缓解 |
| 5 | **RPG剧情回退** — 主线被带回过去 | PlotAnchor（预留 Day 4）+ RAG 召回主线事件 | ✅ 部分缓解 |
| 6 | **内心独白泄露** — LLM像有读心术 | Week 3 visibility 三层隔离（预留） | ⚠️ 间接缓解 |
| 7 | **跨角色记忆隔离** — 私密话共享 | Week 3 关系图谱隔离（预留） | ❌ 待 Week 3 |
| 8 | **RPG多角色状态记录缺失** — party/NPC 状态变化全丢 | [`MemoryManager.sync_dialogue_from_tavo()`](app/memory/manager.py:204) + RAG 召回多角色记忆 | ✅ 部分缓解 |
| 9 | **重复记忆/冗余信息** — 同一批 NPC 信息反复记录 | RAG 语义召回替代全量注入 → [`structured_aware_search()`](app/memory/manager.py:458) Top-5 | ✅ **根本解决** |
| 10 | **长记忆无 RAG，全量注入** — token 浪费 + 注意力稀释 | RAG 主动召回 Top-5 → [`LONG_TERM_MEMORY`](app/api/completions.py:454) 区块 | ✅ **根本解决** |
| 11 | **模型输出太少** — DeepSeek 输出过短 | [`OUTPUT_SPEC`](app/api/completions.py:567) 长度约束 + Week 2 ResponseLengthGuard | ⚠️ 间接缓解 |
| 12 | **模型输出太多** — Gemini 输出过长，推进剧情 | [`CONSTRAINTS`](app/api/completions.py:351) 负向指令 + [`OUTPUT_SPEC`](app/api/completions.py:567) 上限约束 | ⚠️ 间接缓解 |
| 13 | **系统提示词锁不住** — LLM 偏离人设 | Week 3 模型方言编译器（预留） | ❌ 待 Week 3 |
| 14 | **时间维度缺失 → 已完成事件重复生成** | FAISS 时间加权 + `insert_seq` 单调递增 | ⚠️ 部分缓解 |
| 15 | **用户输入意图隐含 → LLM 默认接话而非渲染反应** | [`IntentTagger`](app/intent_tagger.py:43) 解析意图 → [`USER_INTENT_TAG`](app/api/completions.py:544) 导演指令注入 → 意图感知 RAG 召回氛围记忆 | ✅ **显著缓解** |

### 各模块解决的痛点数量

| 模块 | 解决/缓解痛点数 | 关键痛点 |
|------|----------------|----------|
| RAG 记忆压缩 + 意图感知 | 9 个（1, 4, 5, 6, 8, 9, 10, 14, 15） | 9/10 根本解决，1/15 显著缓解 |
| Prompt 区块重组（CONSTRAINTS + OUTPUT_SPEC） | 4 个（1, 11, 12, 15） | 越权 + 输出长度控制 |
| IntentTagger + USER_INTENT_TAG | 1 个（15） | 意图隐含 — v0.7.0 核心新增 |
| 待 Week 2-3 实现 | 6 个（2, 3, 7, 11, 12, 13） | 文风/模型/隔离/输出控制 |

---

## 2. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                          TAVO (前端 RP 平台)                      │
│             发送 RP 请求 → 接收 SSE 流式回复                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP POST /v1/chat/completions
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     AURA 中间层 (FastAPI)                         │
│                                                                  │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────┐  │
│  │ PromptDecomposer│──▶│ 区块重组引擎      │──▶│ IntentTagger  │  │
│  │ (拆解原始Prompt)│    │ (9 区块组装)      │    │ (意图解析)    │  │
│  └──────────────┘    └──────────────────┘    └───────┬───────┘  │
│                                                       │          │
│  ┌──────────────┐    ┌──────────────────┐             │          │
│  │ MemoryManager │◀──│ 三层记忆注入      │◀────────────┘          │
│  │ (FAISS+SQLite)│    │ WORKING/RECENT/  │                       │
│  │               │    │ LONG_TERM        │                       │
│  └──────────────┘    └──────────────────┘                       │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ SSE 流式处理器 (先完整收集 → 质检 → 再模拟流式返回)       │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP POST (流式)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LLM 后端 (DeepSeek / Kimi)                     │
│             接收优化后的 Prompt → 返回 SSE 流式回复               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 数据流

### 完整请求生命周期

```
TAVO ──①──→ AURA ──②──→ LLM ──③──→ AURA ──④──→ TAVO
```

| 阶段 | 描述 | 关键操作 |
|------|------|----------|
| **① TAVO→AURA** | TAVO 发送 HTTP POST 请求 | 保存原始请求到 `tavo_input_*.txt` |
| **② AURA→LLM** | AURA 处理并转发 | Prompt 拆解 → 区块重组 → 记忆注入 → 意图注入 |
| **③ LLM→AURA** | LLM 流式返回 | 完整收集所有 SSE chunk → 质检（预留）→ 保存到 SQLite |
| **④ AURA→TAVO** | AURA 模拟流式返回 | 按段落+句子粒度切分 → SSE 格式封装 → 逐段发送 |

### 内部处理流程（阶段② 展开）

```
TAVO 原始请求
    │
    ▼
┌─────────────────────────────┐
│ 1. Prompt 拆解               │
│    PromptDecomposer.decompose│
│    → 越权禁令 / 长记忆 /      │
│      角色卡 / 世界书 / 对话    │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 2. 意图解析 (v0.7.0)         │
│    IntentTagger.analyze      │
│    → structure (RAG)         │
│    → implicit_instruction    │
│      (注入主LLM)             │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 3. 三层记忆注入 (v0.7.0)     │
│    a. WORKING_MEMORY (5轮)   │
│    b. RECENT_MEMORY (10条)   │
│    c. LONG_TERM_MEMORY (RAG) │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 4. 区块重组                   │
│    9 区块 System Prompt      │
│    + 近因效应追加到 user 消息  │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 5. 对话同步 + 记忆总结触发    │
│    sync_dialogue_from_tavo   │
│    → 每5轮触发 Kimi 总结     │
└──────────┬──────────────────┘
           ▼
        LLM 后端
```

---

## 4. 模块详解

### 4.1 入口层: [`app/main.py`](app/main.py)

FastAPI 应用入口，负责：

- **应用生命周期** (`lifespan`)：启动时调用 `initialize_aura()` 初始化 MemoryManager
- **CORS 配置**：允许所有来源（生产环境应限制）
- **路由注册**：`/v1/chat/completions` 为主路由
- **健康检查**：`/health` 和 `/` 端点

```python
# 关键配置
app = FastAPI(title="AURA", version="0.6.0")  # 待更新为 0.7.0
app.include_router(aura_router, prefix="/v1")
```

### 4.2 配置层: [`app/config.py`](app/config.py)

集中管理所有 LLM API 配置，设计原则：

- **所有 LLM 调用配置集中在此**，调用方不再硬编码任何参数
- **场景隔离**：每个使用场景（main/summary/intent）有独立的 temperature/max_tokens/timeout
- **安全降级**：API Key 未配置时返回 `None` 而非抛出异常

```python
# 场景参数示例
scene="main"    → temperature=0.7, max_tokens=4096, timeout=60
scene="summary" → temperature=0.3, max_tokens=2048, timeout=30
scene="intent"  → temperature=1.0, max_tokens=2048, timeout=60  # Kimi k2.6 特殊
```

**支持的 LLM 后端**：

| 后端 | 默认模型 | 用途 |
|------|----------|------|
| DeepSeek | deepseek-v4-flash | 主对话（默认） |
| Kimi | kimi-k2.6 | 意图分析（优先）、记忆总结 |
| Gemini | gemini-2.0-flash | 预留 |

### 4.3 API 层: [`app/api/completions.py`](app/api/completions.py)

核心业务逻辑所在，约 1160 行，包含：

#### `chat_completion()` — 主入口

1. **请求验证**：检查 messages 和 model 字段
2. **Prompt 保存**：保存原始请求到 `prompt_dumps/` 目录
3. **Prompt 拆解 + 重组**（核心）：
   - 调用 `PromptDecomposer.decompose()` 拆解原始 Prompt
   - 调用 `IntentTagger.analyze()` 解析用户意图
   - 调用 `MemoryManager` 进行三层记忆检索
   - 组装 9 区块 System Prompt
   - 利用近因效应将 WORKING_MEMORY + USER_INTENT_TAG 追加到最后一条 user 消息
4. **对话同步**：将 TAVO 对话同步到 SQLite，每 5 轮触发记忆总结
5. **转发**：根据 `stream` 参数选择流式或非流式处理

#### `_handle_streaming_request()` — 流式处理

采用"先完整收集 → 质检 → 再模拟流式返回"策略：

- **阶段 1**：完整收集 LLM 的 SSE 流（聚合所有 chunk）
- **阶段 1.5**：质检节点（预留 Day 3 LangGraph 介入点）
- **阶段 2**：按段落+句子粒度切分，模拟 SSE 流式返回给 TAVO

#### `_handle_non_streaming_request()` — 非流式处理

简单的 POST 请求转发，返回标准 JSON 响应。

### 4.4 Prompt 拆解器: [`app/prompt_decomposer.py`](app/prompt_decomposer.py)

将 TAVO 的原始 System Prompt 拆解为结构化组件。

**拆解策略（三层递进）**：

| 优先级 | 策略 | 示例 |
|--------|------|------|
| 1 (最高) | `=====` 格式标记 | `=====角色卡开始=====` / `=====角色卡结束=====` |
| 2 | HTML 注释标记 | `<!-- AURA_CHARACTER_CARD_START -->` |
| 3 (最低) | 基于格式的硬拆解 | 正则匹配英文角色描述、中文角色卡回退 |

**拆解产物**：

| 组件 | 说明 | 来源 |
|------|------|------|
| `authority_ban` | 越权禁令 | 用户自定义提示词头部 |
| `long_term_memory` | 长记忆列表 | `=====长记忆开始/结束=====` 或格式匹配 |
| `memory_usage_rules` | 记忆应用规则 | 长记忆与用户设定之间 |
| `user_profile` | 用户设定 | `=====用户设定开始/结束=====` 或格式匹配 |
| `character_card` | 角色卡 | 标记优先，中文格式回退 |
| `world_book` | 世界书 | `HISTORIA:` 开头 |
| `xml_character_cards` | XML 角色卡 | `<charname>...</charname>` 格式 |

### 4.5 意图解析器: [`app/intent_tagger.py`](app/intent_tagger.py)

在每轮用户输入后，调用轻量 LLM 解析用户真实意图。

**双字段输出设计**：

```
IntentResult
├── structure (IntentStructure) ──→ RAG 逐字段 embedding 软匹配（不传递给主 LLM）
├── implicit_instruction (str)  ──→ 注入 [USER_INTENT_TAG] 给主 LLM（自然语言）
├── expanded_scene (str)        ──→ embedding 粗排保底
├── confidence (float)          ──→ < 0.6 时跳过意图修正
├── input_type (str)            ──→ 仅用于日志和调试
└── user_expectation (str)      ──→ 仅用于日志和调试
```

**模型优先级**：Kimi (k2.6) → DeepSeek (回退)

**System Prompt 精简**：451 字符（适配 Kimi k2.6 的 reasoning 特性，过长会导致 timeout）

### 4.6 记忆管理层: [`app/memory/manager.py`](app/memory/manager.py)

统一记忆管理接口，约 990 行。

**存储架构**：

| 存储 | 用途 | 持久化 |
|------|------|--------|
| SQLite (`aura.db`) | 原始对话存储 | 磁盘 |
| FAISS (`faiss_index.bin`) | 向量记忆库 | 磁盘 |
| `faiss_meta.json` | 记忆元数据（含 structure） | 磁盘 |

**核心方法**：

| 方法 | 说明 |
|------|------|
| `save_dialogue()` | 保存单轮对话到 SQLite |
| `sync_dialogue_from_tavo()` | 倒序同步 TAVO 对话（处理编辑/撤回） |
| `search()` | 传统 embedding + 时间加权检索 |
| `structured_aware_search()` | 意图感知结构化检索（v2 核心） |
| `summarize_and_store()` | Kimi 总结 + 结构化字段提取 + 存入 FAISS |
| `add_memory()` | 新增单条记忆到 FAISS |
| `import_from_tavo()` | 从 TAVO System Prompt 导入已有记忆 |

### 4.7 数据模型: [`app/memory/models.py`](app/memory/models.py)

#### `IntentStructure` — 6 维结构化字段

```python
@dataclass
class IntentStructure:
    scene_type: str           # 场景类型（Where/When）
    action_type: str          # 行为模式（What）— 权重最高
    emotional_tone: str       # 情绪基调（How）
    tension_description: str  # 张力描述（Atmosphere）— 自然语言，无数字评分
    entities: List[str]       # 涉及角色（Who）— Jaccard 集合匹配
    pacing: str               # 节奏感（Rhythm）
```

**字段权重**：

| 字段 | 权重 | 匹配方式 |
|------|------|----------|
| `action_type` | 0.25 | embedding 语义相似度 |
| `scene_type` | 0.20 | embedding 语义相似度 |
| `emotional_tone` | 0.20 | embedding 语义相似度 |
| `entities` | 0.15 | Jaccard 集合相似度 |
| `tension_description` | 0.10 | embedding 语义相似度 |
| `pacing` | 0.10 | embedding 语义相似度 |

#### `IntentResult` — 意图解析完整输出

```python
@dataclass
class IntentResult:
    structure: IntentStructure    # → RAG 匹配
    implicit_instruction: str     # → [USER_INTENT_TAG] 注入主 LLM
    expanded_scene: str           # → embedding 粗排
    confidence: float             # → 置信度阈值 0.6
    input_type: str               # → 日志/调试
    user_expectation: str         # → 日志/调试
```

---

## 5. Prompt 编译管道

### 9 区块 System Prompt

```
[MAIN_PROMPT]       ← 用户自定义提示词头部（仅第一行，条件注入）
[PROTOCOL]          ← 通信标记约定（静态模板）
[CONSTRAINTS]       ← 角色边界 + 负向指令（静态模板）
[CHARACTER_CARD]    ← 角色卡（拆解自 TAVO）
[USER_PROFILE]      ← 用户设定（拆解自 TAVO）
[CURRENT_STATE]     ← 实体当前状态（Mock，待 Day 4 实现）
[RECENT_MEMORY]     ← 近时记忆摘要（最近 10 条）
[LONG_TERM_MEMORY]  ← 长记忆（RAG 召回 / TAVO 透传）
[WORLD_CONTEXT]     ← 世界书（条件注入）
[OUTPUT_SPEC]       ← 输出格式规范 + few-shot 示例 + COT 自我校验
```

### 近因效应策略 (v0.7.1)

```
System Prompt (messages[0]):
  [MAIN_PROMPT] [PROTOCOL] [CONSTRAINTS] [CHARACTER_CARD]
  [USER_PROFILE] [CURRENT_STATE] [RECENT_MEMORY]
  [LONG_TERM_MEMORY] [WORLD_CONTEXT] [OUTPUT_SPEC]

最后一条 user 消息末尾追加:
  [系统约束] 简短约束
  [WORKING_MEMORY] 最近 5 轮对话
  [USER_INTENT_TAG] 导演指令（条件注入）
```

**原理**：利用近因效应（Recency Effect），LLM 在生成回复时最近看到的就是当前语境 + 导演指令，从而优先遵循。

---

## 6. 三层记忆架构

```
┌─────────────────────────────────────────────────────────────┐
│                    三层记忆架构 (v0.7.0)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [WORKING_MEMORY]   最近 5 轮对话原文                         │
│  ├─ 位置：追加到最后一条 user 消息末尾（近因效应）              │
│  ├─ 来源：TAVO 发来的 messages 列表                           │
│  └─ 用途：提供即时语境，让 LLM 知道"刚才发生了什么"             │
│                                                             │
│  [RECENT_MEMORY]    最近 10 条记忆摘要                        │
│  ├─ 位置：System Prompt 区块                                 │
│  ├─ 来源：FAISS 中最近插入的 10 条记忆                        │
│  └─ 用途：提供近期剧情发展，比 WORKING 更精炼                   │
│                                                             │
│  [LONG_TERM_MEMORY] 意图感知 RAG 召回 Top-5                   │
│  ├─ 位置：System Prompt 区块                                 │
│  ├─ 来源：FAISS 结构化检索（IntentStructure 逐字段匹配）       │
│  ├─ 降级：FAISS 为空 → 透传 TAVO 原始长记忆                   │
│  └─ 用途：提供与当前场景最相关的长期记忆                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 记忆总结触发

- 每 5 轮对话触发一次（`memory_summary_interval = 5`）
- 调用 Kimi 总结最近对话 → 提取结构化字段 → 存入 FAISS
- 异步执行，不阻塞主流程

---

## 7. 意图感知 RAG (v2)

### 设计理念

**结构化字段对齐 + 逐字段 embedding 软匹配**，而非纯 embedding 软匹配。

例如：字段都是"情绪"，但一个记忆是"大笑"，另一个是"高兴"——两者的情绪部分在 embedding 空间中很相似，可以认为情绪是对齐的。

### 三阶段检索

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────┐
│ 阶段 1: 粗排                                 │
│ expanded_scene embedding → FAISS 搜索        │
│ 候选池: Top-K × 3                           │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ 阶段 2: 精排                                 │
│ 逐字段结构化匹配（如果候选有 structure）       │
│ 文本字段: 各自 embedding → cosine 相似度      │
│ entities: Jaccard 集合相似度                  │
└──────────────────┬──────────────────────────┘
                   ▼
┌─────────────────────────────────────────────┐
│ 阶段 3: 复合评分                              │
│ semantic × 0.3 + structure × 0.5 + time × 0.2│
│ → 排序取 Top-K                               │
└─────────────────────────────────────────────┘
```

### 匹配策略

| 字段类型 | 匹配方式 | 原因 |
|----------|----------|------|
| 文本字段（scene_type, action_type 等） | embedding 语义相似度 | 同义词/近义词可匹配 |
| entities（角色名） | Jaccard 集合相似度 | 角色名是 proper noun，embedding 不稳定 |

### 降级路径

1. 有 `IntentStructure` → 三阶段检索（semantic + structure + time）
2. 无 `IntentStructure` → 传统检索（semantic + time）
3. FAISS 为空 → 透传 TAVO 原始长记忆

---

## 8. SSE 流式处理

### 设计决策

采用"先完整收集 → 质检 → 再模拟流式返回"策略，而非实时透传。

**原因**：
- 流式传输的"不可撤回"特性（已发送到 TAVO 的内容无法收回）
- 需要在返回前进行质检（预留 Day 3 LangGraph 介入点）
- 对于重度 RP 用户，10-30 秒的等待换取 Sonnet 级别的沉浸体验，是可接受的

### 段落保留机制

```
LLM 原始返回（含 \n\n 段落分隔）：
  "阳光透过铁艺大门...\n\n几个女生停下脚步...\n\n校门口的石狮..."

切分策略：
  1. 按 \n\n 切分为段落
  2. 每个段落内按句子边界切分
  3. 段落末尾追加 \n\n（最后一段不加）

SSE chunk 序列：
  data: {"delta": {"content": "阳光透过铁艺大门..."}}
  data: {"delta": {"content": "\n\n"}}  ← 段落分隔保留
  data: {"delta": {"content": "几个女生停下脚步..."}}
  data: {"delta": {"content": "\n\n"}}
  data: {"delta": {"content": "校门口的石狮..."}}
  data: [DONE]
```

**关键修复**：段落分隔符 `\n\n` 必须追加到段落内容末尾，不能作为独立 segment 发送（TAVO 不渲染独立换行 segment）。

---

## 9. 配置系统

### 配置来源

- `.env` 文件（项目根目录）
- 环境变量覆盖

### 配置层级

```
Settings (pydantic BaseSettings)
├── debug_mode: bool
├── default_llm: str = "deepseek"
├── DeepSeek: base_url / api_key / model
├── Kimi: base_url / api_key / model
├── Gemini: base_url / api_key / model
├── 场景参数:
│   ├── main: temperature=0.7, max_tokens=4096, timeout=60
│   ├── summary: temperature=0.3, max_tokens=2048, timeout=30
│   └── intent: temperature=1.0, max_tokens=2048, timeout=60
└── memory_summary_interval: int = 5
```

### 获取配置

```python
# 统一入口
config = get_llm_config(provider="kimi", scene="intent")
# → 返回 LLMConfig 实例，或 None（配置不完整时）
```

---

## 10. 错误处理与降级策略

| 故障点 | 降级行为 | 影响范围 |
|--------|----------|----------|
| Prompt 拆解失败 | 原始透传（不重组） | 无 AURA 优化，但功能正常 |
| IntentTagger 不可用 | `IntentResult.fallback()`，跳过意图修正 | RAG 降级为传统检索 |
| FAISS 不可用/为空 | 透传 TAVO 原始长记忆 | 无 RAG 增强 |
| Kimi 不可用 | IntentTagger 回退到 DeepSeek | 意图分析仍可用 |
| LLM 后端超时 | HTTP 504 返回 TAVO | 该次请求失败 |
| 对话保存失败 | 日志警告，不阻断主流程 | 记忆无法积累 |
| 记忆总结失败 | 日志警告，下次触发重试 | 记忆更新延迟 |

---

## 11. 项目文件结构

```
c:\AURA/
├── .env                          # 环境变量（API Key 等）
├── .gitignore
├── requirements.txt
├── ARCHITECTURE.md               # 本文件
├── AURA-30天完整执行计划.md       # 完整执行计划与设计文档
├── VSCode启动指南.md
│
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI 入口
│   ├── config.py                 # 集中配置管理
│   ├── intent_tagger.py          # 意图解析器
│   ├── prompt_decomposer.py      # Prompt 拆解器
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── completions.py        # 核心 API（路由 + 流式处理）
│   │
│   └── memory/
│       ├── __init__.py
│       ├── manager.py            # 记忆管理器（FAISS + SQLite）
│       └── models.py             # 数据模型（IntentStructure, IntentResult）
│
├── prompt_dumps/                 # 调试日志目录（自动生成）
│   ├── prompt_*.txt              # TAVO 原始请求
│   ├── reassembled_*.txt         # AURA 重组后 Prompt
│   ├── tavo_input_*.txt          # TAVO 输入调试日志
│   └── aura_output_*.txt         # AURA→LLM 输出调试日志
│
├── faiss_index.bin               # FAISS 向量索引（自动生成）
├── faiss_meta.json               # FAISS 元数据（自动生成）
├── aura.db                       # SQLite 数据库（自动生成）
│
└── models/                       # 本地模型目录
    └── BAAI/
        └── bge-small-zh-v1.5/    # 本地 embedding 模型
```

---

## 附录：版本历史

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v0.5.0 | 2026-05-03 | 基础转发通道 + Prompt 拆解注入 |
| v0.6.0 | 2026-05-04 | SQLite + FAISS 记忆库 + RAG 召回 |
| v0.7.0 | 2026-05-10 | 三层记忆 + IntentTagger + 意图感知 RAG v2 |
| v0.7.1 | 2026-05-10 | 近因效应策略 + SSE 段落修复 + Kimi k2.6 适配 |

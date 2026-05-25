# AURA

**Agentic Unified Roleplay Assistant** — 基于 LLM 的文字冒险平台

AURA 是一个双模式 AI 叙事引擎，架设在 RP 前端平台（如 TAVO）与 LLM 后端之间。它既是**Prompt 编译器**（优化角色扮演交互），也是**文字冒险平台**（通过 Director + NPC Agent 架构运行沉浸式世界）。

---

## AURA 是什么？

AURA 位于你的 RP 前端和 LLM 后端之间，解决长篇角色扮演中的 15+ 个系统性痛点。不同于简单的 API 代理，AURA：

- **拆解**混沌的 TAVO System Prompt，重组为结构化 9 区块 Prompt
- **检索**上下文 via 三层记忆架构（工作记忆 + 短期记忆 + 长期 RAG）
- **质检**输出质量，自动检测越权、文风污染、长度异常
- **故障转移**——主模型超时时自动切换到备用模型
- **运行世界**——通过 Director/NPC Agent 架构实现真正的文字冒险 gameplay

---

## 双模式架构

AURA 通过不同的 API 端点提供两种运行模式：

### 模式 A：TAVO 兼容（Prompt 编译器）

经典的 LangGraph 14 节点状态机：

```
TAVO → InputReceive → PromptDecomposer → [6 个并行准备节点]
  → ContextAssemble → LLMGenerate → ParallelQualityCheck
  → [重试循环] → OutputReturn → MemoryExtract → TAVO
```

**端点：** `POST /v1/chat/completions`

适用于：直接 TAVO 集成、单角色扮演、Prompt 优化。

### 模式 B：世界平台（文字冒险引擎）

全新的 Director + NPC Agent 架构：

```
玩家输入 → Director（场域快照 + 指代消解 + NPC 调度）
  → NPC Agent（每个角色独立的 System Prompt + LLM 调用）
  → Director 仲裁 → 玩家响应
```

**端点：** `POST /v1/world/completions`

适用于：多角色叙事世界、持久化状态、涌现式 storytelling。

---

## 快速开始

### 环境要求

- Python 3.10+
- 8GB+ 内存（推荐）
- LLM API Key（DeepSeek、Kimi 或 Gemini）

### 安装

```bash
git clone https://github.com/hbbtsk/AURA.git
cd AURA
pip install -r requirements.txt
```

### 配置

创建 `.env` 文件：

```bash
# 必需：至少配置一个 LLM 后端
DEEPSEEK_API_KEY=sk-your-deepseek-key
KIMI_API_KEY=sk-your-kimi-key

# 可选：故障转移配置
LLM_MAIN_TTFB_TIMEOUT=3          # 首 token 超时时间（秒）
LLM_MAIN_FALLBACK_PROVIDER=kimi  # 超时后的备用模型
```

### 启动

```bash
python -m app.main
```

服务运行在 `http://localhost:8000`。

### 对接 TAVO（模式 A）

在 TAVO 的自定义 API 设置中：

| 设置项 | 值 |
|--------|-----|
| API 地址 | `http://localhost:8000/v1/chat/completions` |
| API Key | 任意值（AURA 不校验，但 TAVO 要求必填） |
| 模型 | `deepseek-v4-flash` / `kimi-k2.6` / `gemini-2.0-flash` |

### 游玩世界（模式 B）

```bash
curl -X POST http://localhost:8000/v1/world/completions \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好，魏丝。",
    "cartridge": "rwby_beacon",
    "model": "deepseek-v4-flash"
  }'
```

---

## 卡带系统（.aura）

AURA 的世界平台使用**卡带**——自包含的世界数据包：

```
rwby_beacon.aura/
├── meta.yaml          # 标题、作者、版本
├── world.yaml         # 全局规则 + 初始状态
├── entities/          # 角色卡（Identity + Habitus + State）
│   ├── weiss_schnee.yaml
│   └── ruby_rose.yaml
├── locations/         # 空间结构 + 连通关系
│   ├── beacon_academy_gate.yaml
│   └── dormitory.yaml
├── events/            # 种子事件（因果链起点）
│   └── opening.yaml
└── assets/            # 可选资源索引
```

角色通过**元模型**定义：

- **Identity** — 身份（名字、种族、动机、语言指纹）
- **Habitus** — 惯习（条件-行为映射，"当 X 时，倾向于 Y"）
- **State** — 状态（地点、情绪、关系、记忆）

Director 自动激活在场实体——无需关键词匹配。

---

## 核心功能

| 功能 | 说明 | 模式 |
|------|------|------|
| **Prompt 拆解** | 三层递进解析（标记/HTML/回退） | A |
| **9 区块 Prompt 组装** | 结构化 SYSTEM prompt | A |
| **三层记忆架构** | 工作记忆(5轮) + 近期记忆(10条) + 长期记忆(RAG Top-5) | A |
| **意图感知 RAG v2** | 6 维结构化搜索 + 字段级 embedding + 复合评分 | A |
| **LLM 故障转移** | 首 token 超时自动切换备用模型 | A/B |
| **质量质检** | 越权检测 + 文风污染过滤 + 长度控制 | A |
| **Director 调度** | 场域渲染、指代消解、规则检查、NPC 调度 | B |
| **NPC Agent** | 独立 System Prompt + 单角色 LLM 调用 | B |
| **卡带加载器** | YAML → Pydantic 解析器，多语言别名支持 | B |
| **世界状态管理** | 原子性 EventPatch 提交、存档/读档 | B |

---

## 元模型

AURA 的世界平台建立在三个相互关联的元模型之上：

### 实体（角色）
```python
class Entity(BaseModel):
    identity: Identity       # DNA — 不变
    habitus: Habitus         # 条件-行为映射
    location_id: str         # 当前位置
    emotion: EmotionalState  # 叙事化情绪
    relationships: dict      # 关系叙事
    memory: Memory           # 已知事件 + 秘密
```

### 事件（世界补丁）
```python
class EventPatch(BaseModel):
    event_id: str
    state_diffs: list        # 每个实体的属性变更
    emotional_impacts: list  # 情感冲击叙事
    caused_by: list          # 父事件 ID
    causes: list             # 子事件 ID
    narrative_text: str      # 给 LLM 看的自然语言
```

### 世界（容器）
```python
class World(BaseModel):
    locations: dict          # 空间图（含通行时间）
    entities: dict           # 所有角色
    events: dict             # 因果事件图
    rules: list              # 硬规则约束
    open_loops: list         # 未闭合事件 ID
```

---

## 项目结构

```
AURA/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── api/                    # API 层
│   ├── core/                   # 核心业务逻辑
│   ├── graph/                  # LangGraph 编排（模式 A）
│   ├── memory/                 # 记忆管理
│   ├── models/                 # 元模型（模式 B）
│   ├── cartridge/              # 卡带系统（模式 B）
│   ├── world/                  # 世界运行时（模式 B）
│   ├── director/               # Director（模式 B）
│   ├── npc/                    # NPC Agent（模式 B）
│   ├── causal/                 # 因果引擎（预留）
│   └── engine/                 # 事件/节奏/扰动引擎（预留）
├── cartridges/                 # 示例世界卡带
│   └── rwby_beacon/
├── ROADMAP.md                  # 愿景与路线图
└── requirements.txt
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| API 网关 | FastAPI + Pydantic v2 + Uvicorn |
| LLM 客户端 | httpx（直连） |
| 编排（模式 A） | LangGraph + LangChain Core |
| 向量记忆 | FAISS（IndexFlatL2）+ sentence-transformers（bge-small-zh-v1.5） |
| 结构化存储 | SQLite |
| 元模型 | Pydantic v2 |
| 卡带格式 | YAML |

---

## 开发路线图

| 阶段 | 重点 | 状态 |
|------|------|--------|
| **v1.0.x** | Prompt 编译器 — LangGraph 状态机、三层记忆、质检 | ✅ 稳定 |
| **v1.1.x** | 世界平台 — 元模型、卡带系统、Director、NPC Agent | 🚧 骨架 |
| **v1.2.x** | 因果引擎 — Kuzu 图数据库、因果链遍历、CausalRAG | 📋 计划中 |
| **v1.3.x** | 事件涌现 — EventEngine、PacingEngine、PerturbationEngine | 📋 计划中 |
| **v1.4.x** | 多 Agent — 并发 NPC LLM 调用、冲突检测、离线模拟 | 📋 计划中 |

---

## 设计哲学

1. **文字为根** — 叙事逻辑是唯一载体，图像/音乐是表现层增强
2. **状态驱动** — Entity 在场即激活，无需关键词匹配
3. **因果优先** — 事件是状态差分 + 因果连接，不是日志
4. **反八股** — 一致性保边界，不保轨道
5. **用户自带 API Key** — 平台不承担模型调用成本

---

## 许可证

MIT

---

## 致谢

献给 RWBY 宇宙及更远的世界。第一张卡带 `rwby_beacon` 将魏丝·雪倪和鲁比·罗丝置于信标学院的入学日大门前——致敬一切开始的地方。

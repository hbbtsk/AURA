# AURA — 愿景与路线图

> **AURA 是文字冒险平台，不是聊天工具。**
> 主机是游戏机，卡带是游戏世界。
> 导演调度演员，规则约束涌现。
> 玩家在确定性中体验自由，在自由中感受逻辑。

---

## 1. 项目定位

AURA 是一个基于 LLM 的文字冒险平台——一个**"可居住的文字世界"**。玩家进入这个世界，与 AI 扮演的 NPC 互动、推动剧情，而世界本身会根据物理定律和角色性格持续运转。

### 核心形态：主机 + 卡带

- **主机（AURA Runtime）**：半开源叙事引擎，与内容无关。负责世界运转、因果计算、一致性校验、LLM 路由、卡带管理。
- **卡带（.aura）**：创作者制作的世界/角色/剧本数据包，YAML 格式，Pydantic 校验。
- **玩家自带 API Key**：平台不承担模型调用成本。

### 双模式架构

| 模式 | 端点 | 架构 | 用途 |
|------|------|------|------|
| **A — Prompt 编译器** | `POST /v1/chat/completions` | LangGraph 14 节点状态机 | TAVO 兼容的角色扮演优化 |
| **B — 世界平台** | `POST /v1/world/completions` | Director + NPC Agent | 多角色文字冒险 |

模式 A 是地基，模式 B 是演进。两者共享同一套 LLM 调用基础设施；模式 B 将结构化世界数据作为新数据源注入模式 A 的 Prompt 编译器。

---

## 2. 核心哲学

### 三元组闭环

```
人（Entity）—— 以 Habitus（惯习）在客观场域中驱动行为
    ↓
事件（Event）—— 以状态差分反作用于人与世界，推动因果链
    ↓
世界（World）—— 以物理规则与空间结构提供新的客观条件
    ↓
回到人 —— 记忆更新、情绪变迁、关系演变
```

### 设计原则

1. **文字为根** — 叙事逻辑是唯一载体。图像/音乐是表现层增强，文字层 100% 稳定前不做。
2. **状态驱动** — Entity 在场即激活（`WorldField.present_entities`），无需关键词匹配。
3. **因果优先** — 事件是状态差分补丁 + 因果连接，不是日志。
4. **事件驱动** — 拒绝时间驱动 Tick 系统。世界只在事件发生时推进。
5. **情感叙事化** — 情绪与关系用自然语言叙事表达，不做数字量化。
6. **确定性优先** — 规则层（世界编辑器）必须 100% 确定，生成层（LLM）在规则内概率生成。
7. **反八股** — 一致性保边界（不 OOC、不瞬移），不保轨道（不规定句式结构）。
8. **无根不扰** — 戏剧性意外只来自有物理根因的场域突变，非随机注入。

---

## 3. 元模型

### 3.1 人（Entity / 角色）

三层结构：

| 层级 | 类 | 可变？ | 说明 |
|------|-----|--------|------|
| **存在层** | `Identity` | ❌ | DNA：`entity_id`、`name`、`race`、`core_motivation`、`speech_fingerprint`、`aliases` |
| **实践层** | `Habitus` | ❌ | 条件-行为映射：`Tendency[]` + `default_behavior` + `stress_response` |
| **涌现层** | `State` | ✅ | 临时状态：`location_id`、`EmotionalState`、`relationships`、`memory` |

**核心洞察**：`Habitus` 不是性格特质，而是一组条件-行为映射。"当在宿舍走廊遇到 Ruby 时，嘴上说别管我，实际上渴望她留下来。" 这才是驱动涌现事件的引擎。

### 3.2 事件（Event / 世界补丁）

事件**不是日志**。它是：
- 一组 `StateChange` 状态差分
- 一组 `EmotionalImpact` 情感冲击叙事
- 因果连接（`caused_by` / `causes` / `activates` / `closes`）
- 可见性权限（`public_to` / `secret_to` / `hidden_from`）

事件通过 `World.apply_patch(event)` 原子性应用。

### 3.3 世界（World / 容器）

- `Location` — 空间图，含通行时间和属性
- `WorldRule` — 硬约束，含作用范围和例外事件
- `WorldField` — 某一时刻的客观条件快照
- `World` — 运行时容器；所有变更通过 `EventPatch`

---

## 4. 运行时架构：导演 + 演员

### 导演（Director / 上帝视角）

- 渲染场域氛围（天气、声音、光线）
- 规则判定：此行动是否违反 `WorldRule`？
- NPC 调度：本轮哪些 NPC 该反应？
- 结果广播：按记忆权限过滤后广播给 NPC
- 输出仲裁：检测冲突、按戏剧性排序、插入旁白

### NPC Agent（演员 / 角色视角）

- 只知道 `memory.known_events` 里的内容
- 拥有独立的 `Identity + Habitus + State` 注入 System Prompt
- 独立调用 LLM（复用模式 A 的 `_call_single_llm`）
- 不可读取其他角色的记忆

### 单轮运转流程

```
玩家输入
    ↓
Director 指代消解（Alias 匹配）
    ↓
Director 更新 WorldField，检查规则
    ↓
Director 调度 NPC（谁在场、谁该反应）
    ↓
Director 为各 NPC 准备场域切片（按记忆权限过滤）
    ↓
各 NPC Agent 独立调用 LLM，生成行动
    ↓
Director 仲裁（校验冲突、排序输出、插入旁白）
    ↓
原子性提交 EventPatch
    ↓
流式返回给玩家
```

---

## 5. 关键引擎

### 已实现 ✅

| 引擎 | 状态 | 说明 |
|------|------|------|
| **PromptDecomposer** | ✅ | 三层递进解析（`=====` / HTML 注释 / 格式回退） |
| **ContextAssemble** | ✅ | 9 区块 Prompt 组装，含模型专属约束 |
| **LLMGenerate** | ✅ | 非流式调用，主模型→备用模型故障转移（3s 首 token 超时） |
| **FormatGuard** | ✅ | 越权检测 + 文风污染过滤 + 长度检查 |
| **IntentTagger** | ✅ | 轻量 LLM 前置调用，提取隐含指令 |
| **FAISS RAG** | ✅ | 语义 + 结构化字段 + 时间加权复合评分 |
| **MemoryManager** | ✅ | SQLite + FAISS 门面，每 5 轮自动总结 |
| **CartridgeLoader** | ✅ | YAML → Pydantic 解析器，多语言名称解析 |
| **WorldRuntime** | ✅ | 世界状态管理，支持存档/读档 |
| **Director** | 🟡 骨架 | 场域快照、指代消解、NPC 调度（mock）、仲裁（mock） |
| **NPCAgent** | 🟡 骨架 | 独立 System Prompt + 单角色 LLM 调用 |

### 计划中 📋

| 引擎 | 优先级 | 说明 |
|------|--------|------|
| **CausalRAG** | 高 | 图数据库（Kuzu/NetworkX）遍历：上游 2 层 + 下游 1 层 |
| **EventEngine** | 高 | `Habitus × Field + Perturbation` → 事件草稿生成 |
| **PacingEngine** | 中 | 起承转合四态叙事节奏控制 |
| **PerturbationEngine** | 中 | 检测长期压抑的因果链，释放积蓄势能 |
| **EventScheduler** | 中 | 离线 NPC 自主涌现；玩家回归时生成离线摘要 |
| **Deep FormatGuard** | 中 | WorldRule 违规检查、时空一致性（禁止瞬移）、Habitus 边界检查 |
| **ModelDialectCompiler** | 低 | 单模型 Prompt 格式优化（DeepSeek/Gemini/Kimi/Qwen） |
| **Multi-Agent Concurrency** | 低 | 多 NPC 并发 LLM 调用 + 冲突检测 |

---

## 6. 卡带系统（.aura）

```
example_world.aura/
├── meta.yaml          # 标题、作者、版本、依赖
├── world.yaml         # 全局规则 + 初始状态 + 未闭合事件
├── entities/          # 角色定义（Identity + Habitus + State）
├── locations/         # 空间结构 + 连通关系
├── events/            # 种子事件（因果链起点）
└── assets/            # 可选资源索引
```

**卡带即数据库**：运行时反序列化为 Pydantic 模型。
**卡带即存档**：退出时世界状态差分写回 `save/` 子目录。
**卡带即商品**：创作者打包上传市场，玩家下载后插卡即玩。

### 多语言支持

- `aliases: {en: [...], zh: [...], ja: [...]}` — 跨语言指代消解
- `name`、`core_motivation`、`speech_fingerprint` 支持按语言取值
- 运行时加载玩家语言；缺失时 fallback 到英文

---

## 7. 存储架构

| 存储层 | 数据 | 工具 | 状态 |
|--------|------|------|--------|
| **因果层（图数据库）** | 事件节点 + 因果边 | Kuzu / NetworkX | ❌ 尚未接入 |
| **实时层（状态缓存）** | NPC 当前最新状态 | SQLite / JSON | ✅ SQLite 表已存在 |
| **语义层（向量库）** | `narrative_text` 的 Embedding | FAISS（IndexFlatL2） | ✅ 运行中 |

---

## 8. 开发路线图

### Phase 0 — 地基（v0.8.x → v0.9.0）✅ 已完成

- [x] LangGraph 14 节点状态机
- [x] Prompt 拆解 + 9 区块组装
- [x] 三层记忆架构（工作/近期/长期）
- [x] 意图感知 RAG + 结构化字段匹配
- [x] 多后端 LLM + 故障转移
- [x] 元模型（Entity/Event/World）Pydantic 类
- [x] 卡带加载器 + 校验器
- [x] Director 骨架 + NPC Agent 骨架
- [x] 示例卡带：`rwby_beacon`（魏丝 & 鲁比）

### Phase 1 — 图与因果（v0.9.x → v0.10.x）

- [ ] 接入 Kuzu 或 NetworkX 因果图存储
- [ ] FAISS 纯向量检索替换为 CausalRAG（图遍历 + 向量兜底）
- [ ] EventEngine：`Habitus × Field` 生成 EventDraft
- [ ] 原子性 EventPatch 应用 + 冲突检测
- [ ] Deep FormatGuard：WorldRule + 时空一致性检查

### Phase 2 — 涌现与节奏（v0.10.x → v0.11.x）

- [ ] PacingEngine：起承转合四态叙事节奏控制
- [ ] PerturbationEngine：检测并释放压抑的因果势能
- [ ] EventScheduler：离线 NPC 自主行为
- [ ] 多 Agent 并发：所有在场 NPC 并行 LLM 调用

### Phase 3 — 打磨与生态（v0.12.x）

- [ ] ModelDialectCompiler：单模型 Prompt 优化
- [ ] 分支世界线：关键选择点存档分叉
- [ ] 卡带市场基础
- [ ] 可视化世界编辑器（AURA Pro）

### Phase 4 — 规模化

- [ ] 多人：同一世界实例中的多个玩家
- [ ] 云同步：跨设备世界状态持久化
- [ ] 创作者经济：付费卡带、收益分成

---

## 9. 设计铁律

1. **文字为根**
2. **先 Ruby 后抽象** — 先做具体，再泛化
3. **状态驱动** — 不做关键词匹配
4. **因果优先** — 事件驱动世界，不是 Tick
5. **事件驱动** — 拒绝时间驱动 Tick 系统
6. **无根不扰**
7. **情感叙事化** — 不做数字量化
8. **反八股** — 保边界，不保轨道
9. **主机固件不稳，卡带再精美也读不出来**

---

## 10. 缘起

> *"即使世界忘了角色的誓言，AURA 也会替他们记住。"*

第一张卡带 `rwby_beacon`，将魏丝·雪倪和鲁比·罗丝置于信标学院的入学日大门前——致敬一切开始的地方。

# AURA

> **确定性角色状态机驱动的事件叙事引擎。**
> 一个RP玩家为RP玩家打造的引擎。

<p align="center">
  <a href="README.md">English</a>
</p>

---

## AURA 是什么

AURA 在前端与 LLM 之间插入了一个**确定性状态层**。

现有工具（SillyTavern、Character.AI）把一切赌注押在 LLM 的上下文窗口和 Prompt 工程上。20轮之后：OOC、角色串味、状态倒退、风格污染。这些不是 Prompt 问题，而是**架构问题**。

AURA 用三个核心原语来解决这个问题：

| 原语 | 功能 |
|------|------|
| **8层角色模型** | 体格 / 声纹 / 根脉 / 人际 / 核心 / 张力 / 轨迹 / 钩锚 — 角色不是一张卡，角色是一个活的系统 |
| **EventPatch** | 事件不是日志，而是一个状态补丁：*某人（主体）做了某事（行为），造成了某种影响（后果）* |
| **因果图** | 事件以叙事因果性链接，而非仅按时间顺序。灵感源自叙事学理论（布雷蒙、托多罗夫、Trabasso） |

**一次 LLM 调用，产出两个输出：**

```json
{
  "narrative": {
    "content": "给玩家看的角色台词",
    "meta_action": "舞台指示：手指敲桌，目光移向某人"
  },
  "structured": {
    "intent_tags": ["evasion", "redirect"],
    "world_delta": [{"field": "审讯室.当前焦点", "value": "转回陈彪"}],
    "visibility": "public"
  }
}
```

玩家看到 `narrative.content`。系统直接消费 `structured` —— 零额外 LLM 调用。这**不是** Function Calling。LLM 不是在指挥系统干活。LLM 是在产出内容的同时自我标注。

---

## 为什么做 AURA

### 问题所在：OOC 是架构问题，不是模型问题

上下文窗口已经2M token。模型已经是 GPT-5 级别。**OOC 仍然发生。** 为什么？

因为 OOC 不是"忘记"导致的。而是因为**确定性状态层的缺失**。LLM 没有"状态"的概念。它有上下文。上下文不是状态。

| 问题 | 根因 | 为什么更大的上下文修不好 |
|------|------|------------------------|
| OOC | 没有持久角色状态 | 2M token 的不一致文本仍然是不一致的 |
| 角色串味 | NPC之间没有隔离 | 所有 NPC 共享同一锅上下文汤 |
| 风格污染 | 没有声纹层强制 | LLM 随时间漂移回训练数据的文风 |
| 状态倒退 | 没有 world_delta 校验 | LLM 声称的状态变化与物理/规则矛盾 |

### "5G 高速公路"类比

LLM 是高速公路基础设施。整个行业花了数年时间拓宽道路（更大的模型、更长的上下文）。但**路上的车**（应用）仍在漏油。

角色扮演是这条高速公路上少数被验证过的"车"之一 —— Character.AI 单平台 4500 万月活。但这辆 RP "车" 到处漏：20轮后OOC、记忆丢失、角色漂移。**AURA 是修车厂。** 我们不修路。我们修车。

---

## 叙事学理论基础

AURA 的架构根植于**叙事学**，而非仅工程实践：

| 叙事学理论 | AURA 实现 |
|-----------|----------|
| **布雷蒙叙事序列** | 序列层：`情况形成 → 采取行动 → 达到目的` |
| **托多罗夫平衡模型** | 世界状态管理器追踪平衡/失衡 |
| **Trabasso 因果标准** | `如果没有A，就没有B` —— 因果链接的判定测试 |
| **核心事件 vs 卫星事件（巴尔特）** | EventQualifier 区分推动剧情的事件与氛围文本 |
| **格雷马斯行动元模型** | EventPatch 中的主体-客体-过程结构 |

> *"最小的完整情节，是从一个平衡态到另一个平衡态的过渡。"*
> —— 茨维坦·托多罗夫

---

## 当前状态

| 模块 | 状态 | 备注 |
|------|------|------|
| **8层角色模型** | 已验证 | 定义锁定，schema 已定 |
| **事件总线设计** | 已验证 | EventPatch schema、因果字段、可见性规则 |
| **双输出架构** | 已定义 | `narrative` + `structured` 单次调用输出 |
| **Mode A：Prompt 编译器** | v0.8 可运行 | 15节点 LangGraph 工作流，兼容 TAVO |
| **Mode B：世界平台** | 架构已验证 | Director + NPC Agent 设计已锁定 |
| **序列层** | 已定义 | PresetSequence（Galgame）+ DynamicSequence（开放世界） |
| **因果图引擎** | 已定义 | Kuzu schema、Trabasso 因果测试、连接/镶嵌/两面式 |
| **质量守卫层** | 计划中 | 越权检测、风格过滤器、长度守卫（输出后处理，非阻塞） |
| **ST 卡导入器** | 计划中 | PNG 元数据 → 8层 JSON |

**目标时间线：**
- Mode A 稳定（非阻塞质量守卫 + 因果图 v0.1）：2026 Q3
- Mode B 原型（3-NPC 场景）：2026 Q4

---

## 架构：角色 · 事件 · 世界 · 序列

### 角色 —— 不是一张卡，而是一个活的系统

导入 SillyTavern 卡，AURA 自动填充 8 层。空字段保持为空 —— LLM 幻觉被阻断。事件动态填充空白。

| 层级 | 描述 | 叙事功能 |
|------|------|----------|
| **Physique（体格）** | 骨架、伤痕、穿着、痕迹、气场 | 场景中的物理存在感 |
| **Voice（声纹）** | 语速、口癖、语域、情绪基线、沉默习惯、潜台词模式 | 风格一致性守卫 |
| **Roots（根脉）** | 土壤、断裂、生计、社会面具、真实地位 | 深层动机 |
| **Network（人际）** | 公开关系、秘密关系、债务、联盟、信息位置 | 社交状态 |
| **Core（核心）** | 表层欲望、深层饥渴、恐惧、创伤、道德边界、价值观 | 决策驱动力 |
| **Tension（张力）** | 内在矛盾、外在摩擦、时间压力、身份裂痕 | 行为变异 |
| **Trajectory（轨迹）** | 人生阶段、近期转折点、当前负担、定时炸弹 | 弧线方向 |
| **Hooks（钩锚）** | 入场风格、催化事件、与他人的化学反应、叙事功能 | 场景激活 |

### 事件 —— 一个状态补丁，不是日志

```yaml
Event:
  header:
    id: evt_042
    type: utterance | action | state_change | narration
    causality:
      triggered_by: evt_038    # 直接触发
      root_cause: evt_001      # 根因追踪
    visibility: public | private | faction_only
  payload:
    source: char_001
    targets: [char_002]
    content: "你昨晚去哪儿了？"
    intent_tags: [inquiry, pressure]
    world_delta:
      proposed_changes:
        - {field: "char_002.psychological.stress", delta: +0.1}
    perspective: first_person | third_person_limited
  narrative_function: opening | actualization | result
  sequence_id: seq_007
```

**什么不是事件（否定定义）：**
- 没有实际发生的动作（纯想法、纯情绪、纯描述）
- 没有造成任何状态变化（闲聊）
- 没有参与的行动主体（没有叙事主体的环境描写）
- 没有期望-结果的差异（重复确认、机械回应）

> *事件 = 主体 + 行为 + 影响。三条腿缺任意一条，就是 `non_event` —— 存入向量记忆供语义检索，但不进入因果图。*

### 世界 —— 不是场景描写，而是仲裁者

- **物理状态**：位置、物品、环境规则（代码强制，无LLM介入）
- **规则引擎**：校验每一个 `world_delta`；拒绝物理/社会上不可能的状态变更
- **因果图**：`triggered_by` / `causes` 链接，用于长弧叙事追踪

### 序列 —— 事件之间的黏合剂

事件不是孤立的原子。它们被组织进**序列**：

| 序列类型 | 使用场景 | AURA 模式 |
|---------|----------|----------|
| **PresetSequence（预设序列）** | 手工编写的分支叙事（Galgame 结构） | Mode A + Cartridge |
| **DynamicSequence（动态序列）** | 由角色状态和世界规则自动生成的涌现叙事 | Mode B |

**基本序列结构**（布雷蒙）：
```
情况形成（可能性出现） → 采取行动（行动执行） → 达到目的（成功/失败）
```

**复合连接方式**：
- **连接式**：序列A的结果 = 序列B的情况形成
- **镶嵌式**：一个子序列嵌入另一个序列内部（闪回、支线）
- **两面式**：同一事件对不同角色有不同意义

---

## 双模式设计

### Mode A：Prompt 编译器（兼容 TAVO / ST）

```
TAVO → AURA → Prompt 分解 → 3层记忆 → 质量守卫（输出后处理） → LLM 双输出 → 返回
```

- 9块 Prompt 组装（约束 + 角色切片 + 世界切片 + 事件上下文 + 序列上下文）
- 3层记忆：WORKING（5轮）+ RECENT（摘要）+ LONG_TERM（CausalRAG + 向量 RAG）
- **质量守卫是输出后处理且非阻塞**：越权检测（轻量正则）、风格过滤（异步）、长度截断（异步）
- **双输出**：一次 LLM 调用同时产出 `narrative` 和 `structured`
- **零 LLM 重试**：输出守卫过滤或截断，从不请求 LLM 重新生成

**端点**：`POST /v1/chat/completions`

### Mode B：世界平台（多 Agent 叙事）

```
玩家输入 → Director（场域快照 + 提及解析 + NPC 调度 + 序列推进）
  → NPC Agent（独立 System Prompt + 每角色单次 LLM 调用 → 双输出）
  → Director 仲裁 → 合并输出
```

- 每个 NPC 拥有独立状态机；通过事件总线交换信息
- Director 处理物理仲裁、冲突解决、焦点调度、序列推进
- 可见性规则：每个 NPC 只能看到它应该看到的内容
- 支持 Cartridge 加载（`.aura` 格式）导入完整世界

**端点**：`POST /v1/world/completions`

---

## Cartridge 系统（.aura）

自包含的世界数据包：

```
rwby_beacon.aura/
├── meta.yaml          # 标题、作者、版本
├── world.yaml         # 全局规则 + 初始状态
├── sequences/         # 预设叙事序列
│   ├── vol1_defense.yaml
│   └── vol2_stalemate.yaml
├── entities/          # 角色卡（身份 + 习性 + 状态）
│   ├── weiss_schnee.yaml
│   └── ruby_rose.yaml
├── locations/         # 空间结构 + 连通性
├── events/            # 种子事件（因果链）
└── assets/            # 可选资源索引
```

Director 自动激活在场域中的实体 —— 无需关键词匹配。序列根据状态条件推进，而非脚本触发。

---

## 设计原则

1. **文本为根**：叙事逻辑是唯一载体；图像/音频只是表现层
2. **状态先于文本**：物理/心理状态变化由规则计算；LLM 只负责认知/表达层
3. **因果先于相似**：RAG 优先按因果链检索，嵌入相似度其次
4. **不 LLM 重试**：输出守卫过滤或截断，从不请求 LLM 重新生成
5. **玩家自带密钥**：我们不托管模型；我们托管架构
6. **叙事学驱动工程**：事件定义、序列结构、因果测试全部基于叙事学理论（布雷蒙、托多罗夫、巴尔特、格雷马斯、Trabasso）

---

## 技术栈

| 层级 | 技术 |
|------|------|
| API 网关 | FastAPI + Pydantic v2 + Uvicorn |
| LLM 客户端 | httpx (直连) |
| 编排（Mode A） | LangGraph + LangChain Core |
| 向量记忆 | FAISS + sentence-transformers |
| 因果图 | Kuzu（嵌入式图数据库）|
| 结构化存储 | SQLite |
| 元模型 | Pydantic v2 |
| Cartridge 格式 | YAML |

---

## 快速开始

```bash
git clone https://github.com/hbbtsk/AURA.git
cd AURA
pip install -r requirements.txt

# 配置 API Key
echo "DEEPSEEK_API_KEY=sk-your-key" > .env

# 启动 Mode A（Prompt 编译器）
python -m app.main
# 然后将 TAVO 连接至：http://localhost:8000/v1/chat/completions
```

> **注意**：当前版本是骨架。它能运行，但效果可能还比不上原生 ST。我们在验证架构，不是在交付产品。

---

## 路线图

详见 [ROADMAP.md](./ROADMAP.md)。

| 阶段 | 焦点 | 状态 |
|------|------|------|
| **v0.9.x** | Prompt 编译器：双输出架构、非阻塞质量守卫、兼容 ST | 骨架可运行 |
| **v1.0.x** | 质量守卫：越权检测、风格过滤、长度控制 | 开发中 |
| **v1.1.x** | 世界平台：元模型、Cartridge 系统、Director、NPC Agent | 架构已验证，代码待写 |
| **v1.2.x** | 因果引擎：Kuzu 图数据库、因果链遍历、CausalRAG | 已定义 |
| **v1.3.x** | 事件涌现：EventEngine、PacingEngine、PerturbationEngine | 计划中 |
| **v1.4.x** | 多 Agent 并发：并行 NPC LLM 调用、冲突检测 | 计划中 |

---

## 如何参与

**你不需要写代码就能帮忙。**

- **分享痛点**：你在 ST/CAI 中遇到过最崩溃的 OOC 场景是什么？我们需要真实测试用例。
- **评审架构**：8层角色模型对你的 RP 风格来说缺了什么关键东西吗？
- **分享场景**：你有没有 TTRPG 经历中"多个角色绝不能串味"的情况？告诉我们细节。
- **设计批判**：我们特别需要关于 EventPatch 可见性规则、序列层、以及世界 Agent 仲裁逻辑的反馈。

**开发者：**
- 详见 [ROADMAP.md](./ROADMAP.md) 了解当前任务
- 详见 [docs/](./docs/) 了解架构文档
- 欢迎 PR，特别是：
  - Mode A 质量守卫层（越权检测、风格过滤）
  - ST 卡导入器（PNG 元数据解析 → 8层 JSON）
  - YAML Cartridge 格式校验器

---

## 许可证

MIT

---

## 致谢

为 RWBY 宇宙及更广阔的叙事世界而构建。

第一个 Cartridge `rwby_beacon`，以宋·格雷迈恩与皮拉·尼可丝为主角 —— 一段由 500 次轮回循环与 21 万字同人小说凝练而成的叙事。

AURA 的 Cartridge 系统向任何虚构宇宙或 TTRPG 模组开放。欢迎 PR。

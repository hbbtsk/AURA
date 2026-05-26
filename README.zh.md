<p align="center">
  <a href="README.md">🇺🇸 English</a>
</p>

<h1 align="center">AURA 🚧</h1>

<p align="center">
  <strong>⚠️ 这不是一个开箱即用的产品。这是一个架构验证项目。</strong><br><br>
  我们正在构建<strong>事件驱动的 AI 叙事引擎：角色状态机 + 事件总线</strong>。<br>
  架构已验证，实现进行中。<br>
  ST 兼容前端，私有化部署，用户自带 Key。
</p>

---

## 为什么做这个项目

SillyTavern 和 TAVO 是优秀的前端，但它们把角色一致性全部押注在 LLM 的上下文窗口上。20 轮后 OOC、多角色串戏、状态回退、文风污染——这不是 Prompt 能修好的，是**架构缺陷**。

**我们想验证的假设**：如果在前端与 LLM 之间插入一层"事件总线 + 状态机"，角色能否真正拥有记忆、创伤与成长弧线？

如果你曾经历过心爱的 RP 角色突然忘记你们的共同历史，或者群聊里的两个 NPC 听起来像同一个人，你就理解我们想解决的痛苦。

---

## 当前状态

| 模块 | 状态 | 说明 |
|------|------|------|
| **事件总线设计** | ✅ 已验证 | 数据模型、因果链、Visibility 机制已定义 |
| **八层人物模型** | ✅ 已验证 | 存在/腔调/根底/脉络/内里/张力/轨迹/钩子 |
| **Mode A: Prompt 编译器** | 🚧 骨架可跑 | 可接入 TAVO，基础 3 层记忆，质量校验开发中 |
| **Mode B: 世界平台** | 📋 设计阶段 | Director + NPC Agent 架构文档完成，代码待实现 |
| **ST 角色卡导入器** | 📋 待开发 | PNG/JSON 解析，八层自动填充 |
| **因果引擎** | 📋 待开发 | Kuzu 图数据库，长线叙事追踪 |
| **本地 VLM 集成** | 📋 待开发 | Qwen2.5-VL / MiniCPM-V 图片解析 |

**预计可用时间**
- Mode A 稳定版：2026 年 Q3
- Mode B 原型：2026 年 Q4

---

## 我们在验证什么

### 目标架构：人物 · 事件 · 世界

AURA 的所有叙事逻辑建立在三个结构化实体上，不是聊天记录，而是**状态变更 + 因果链 + 规则仲裁**。

#### 人物（Entity）—— 不是静态卡，是活体

导入 SillyTavern 角色卡后，AURA 将其解析为**八层定义**：

- **存在**：皮囊、感官、当下可见状态
- **腔调**：语速、口癖、潜台词习惯、沉默方式
- **根底**：出身、关键断裂、谋生之道
- **脉络**：明线关系、暗线张力、债务链、信息位
- **内里**：执念、恐惧、旧伤、道德边界
- **张力**：内部矛盾、外部矛盾、时间压力、身份裂缝
- **轨迹**：人生阶段、近期转折、当前负荷、待爆雷
- **钩子**：进场方式、事件催化剂、信息节点、用途标签

**未提及的字段留空**，由后续事件动态填充，禁止 LLM 编造。

#### 事件（EventPatch）—— 不是日志，是状态补丁

```yaml
Event:
  header:
    id: evt_042
    type: utterance | action | state_change
    causality:
      triggered_by: evt_038   # 直接触发源
      root_cause: evt_001     # 根因追踪
    visibility: public | private | faction_only
  payload:
    source: char_001
    targets: [char_002]
    content: "你昨晚在哪？"
    intent_tags: [inquiry, pressure]
    world_delta:
      proposed_changes:
        - {field: "char_002.psychological.stress", delta: +0.1}
  routing:
    required_agents: [character, world]
```

#### 世界（World）—— 不是场景描述，是仲裁者

- **物理状态**：位置、物品、环境规则（代码层强制，不走 LLM）
- **规则引擎**：验证所有 `world_delta`，拒绝不合物理/社会规则的申请
- **因果图**：事件之间的 `triggered_by` 与 `causes` 链，支持长线叙事追踪

---

## 双模式设计

### Mode A：Prompt 编译器（TAVO / ST 兼容）

```
TAVO → AURA → Prompt 拆解 → 3 层记忆检索 → 质量校验 → LLM → 返回
```

- 9-Block Prompt 拼装（约束 + 角色切片 + 世界切片 + 事件上下文）
- 3 层记忆：WORKING（5 轮）+ RECENT（摘要）+ LONG_TERM（RAG Top-5）
- 轻量过滤：越权检测、文风校验、长度截断（**不打回 LLM，规则兜底**）

**Endpoint**: `POST /v1/chat/completions`

### Mode B：世界平台（多 Agent 叙事）

```
Player Input → Director（场域快照 + 提及解析 + NPC 调度）
  → NPC Agent（独立 System Prompt + 单次 LLM 调用 / 角色）
  → Director 仲裁 → 合并输出
```

- 每个 NPC 拥有独立状态机，通过事件总线交换信息
- Director 负责物理仲裁、冲突裁决、焦点调度
- 支持 cartridge（.aura 格式）加载完整世界观

**Endpoint**: `POST /v1/world/completions`

---

## 如何参与

**不需要写代码也可以帮忙。**

- **分享痛点**：你在 ST/CAI 里遇到的最恶心的 OOC 场景是什么？我们需要真实测试用例。
- **审架构**：八层人物定义对你的 RP 风格来说，有没有漏掉什么关键维度？
- **给场景**：如果你有"多角色绝对不能串戏"的跑团经历，把细节分享给我们。
- **设计 critique**：我们特别需要反馈的是事件总线的 Visibility 规则和世界 Agent 的仲裁逻辑。

**开发者：**
- 见 [ROADMAP.md](./ROADMAP.md) 了解当前任务
- 见 [docs/](./docs/) 查看架构文档
- 欢迎提 PR，尤其是：
  - Mode A 质量校验层（越权检测、文风过滤）
  - ST 角色卡导入器（PNG 元数据解析 → 八层 JSON）
  - YAML cartridge 格式校验器

---

## 快速体验（当前骨架）

```bash
git clone https://github.com/hbbtsk/AURA.git
cd AURA
pip install -r requirements.txt

# 配置 API Key
echo "DEEPSEEK_API_KEY=sk-your-key" > .env

# 启动 Mode A（Prompt 编译器）
python -m app.main
# 然后接入 TAVO: http://localhost:8000/v1/chat/completions
```

**⚠️ 注意**：当前版本是骨架。能跑，但效果不一定比原生 ST 好。我们在验证架构，不是发布产品。

---

## Cartridge 系统（.aura）—— 设计预览

自包含的世界数据包（格式已锁定，加载器待开发）：

```
rwby_beacon.aura/
├── meta.yaml          # 标题、作者、版本
├── world.yaml         # 全局规则 + 初始状态
├── entities/          # 角色卡（Identity + Habitus + State）
│   ├── weiss_schnee.yaml
│   └── ruby_rose.yaml
├── locations/         # 空间结构 + 连通性
├── events/            # 种子事件（因果链）
└── assets/            # 可选资源索引
```

Director 将自动激活当前场域内的实体——无需关键词匹配。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| API 网关 | FastAPI + Pydantic v2 + Uvicorn |
| LLM 客户端 | httpx（直连） |
| 编排（Mode A） | LangGraph + LangChain Core |
| 向量记忆 | FAISS + sentence-transformers |
| 结构化存储 | SQLite |
| 元模型 | Pydantic v2 |
| 卡带格式 | YAML |

---

## 路线图

| 阶段 | 重点 | 状态 |
|------|------|------|
| **v0.9.x** | Prompt 编译器：单角色深度优化，ST 兼容 | 🚧 骨架可跑 |
| **v1.0.x** | 质量校验层：越权检测、文风过滤、长度控制 | 📋 开发中 |
| **v1.1.x** | 世界平台：元模型、Cartridge 系统、Director、NPC Agent | 📋 架构已验证，代码待实现 |
| **v1.2.x** | 因果引擎：Kuzu 图数据库、因果链遍历、CausalRAG | 📋 计划 |
| **v1.3.x** | 事件涌现：EventEngine、PacingEngine、PerturbationEngine | 📋 计划 |
| **v1.4.x** | 多 Agent 并发：NPC 并行 LLM 调用、冲突检测 | 📋 计划 |

---

## 设计哲学

1. **文本即根**：叙事逻辑是唯一载体，图像/音乐只是表现层
2. **状态驱动**：实体由场域激活，而非关键词匹配
3. **因果优先**：事件是状态差分 + 因果链接，不是日志
4. **反模板**：一致性守卫边界，不守卫句式结构
5. **用户自带 Key**：平台不承担模型推理成本，数据不出域

---

## License

MIT

---

## Acknowledgements

Built for the RWBY universe and beyond.  
第一个 cartridge `rwby_beacon` 献给 Weiss Schnee 与 Ruby Rose 在 Beacon Academy 的入口——也是 AURA 的起点。  
AURA 的 cartridge 系统对任何虚构宇宙与跑团模组开放，欢迎提交 PR。

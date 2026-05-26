# AURA

> **开源、可私有化部署的 AI 互动叙事引擎**  
> 事件总线 × 角色状态机 × 八层人物定义  
> 让 SillyTavern 的角色卡真正拥有记忆、创伤与成长

---

## 这不是又一个 API 代理

SillyTavern 和 TAVO 是优秀的前端，但它们把"角色一致性"全部押注在 LLM 的上下文窗口上。20 轮后 OOC、多角色串戏、状态回退、文风污染——这些问题不是 Prompt 写得不够好，是**架构本身没有状态层**。

AURA 在前端与 LLM 之间增加了一层**确定性叙事架构**：

| 痛点 | 传统方案（Prompt 硬塞） | AURA（状态机驱动） |
|------|----------------------|------------------|
| 角色 20 轮后失忆/OOC | 靠 Summary 压缩历史 | **事件总线永久存储 + RAG 按需召回** |
| 多角色各说各话 | 单 Prompt 群聊，一个大脑分裂扮演多人 | **独立 NPC Agent，各自状态机，事件交换** |
| 怀孕→生完→又怀孕 | LLM 概率回退 | **世界 Agent 仲裁，状态快照不可篡改** |
| 文风污染/固化 | 模型训练痕迹无法清洗 | **八层人物定义锁定语言指纹，腔调层隔离** |
| 内心独白泄露 | LLM 像有读心术 | **Visibility 字段，私密事件不广播** |
| 玩家台词被越权代写 | 靠 Prompt 约束别写 | **JSON Schema 输出控制，规则引擎兜底** |
| 模型输出太长/太短 | 反复调 Temperature | **结构化输出 + 长度硬约束，不二次调用** |

**核心差异一句话**：ST 是"面具仓库"，AURA 是"骨骼与神经系统"。

---

## 核心架构：人物 · 事件 · 世界

AURA 的所有叙事逻辑建立在三个结构化实体上，不是聊天记录，而是**状态变更 + 因果链 + 规则仲裁**。

### 人物（Entity）—— 不是静态卡，是活体

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

### 事件（EventPatch）—— 不是日志，是状态补丁

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

### 世界（World）—— 不是场景描述，是仲裁者

- **物理状态**：位置、物品、环境规则（代码层强制，不走 LLM）
- **规则引擎**：验证所有 `world_delta`，拒绝不合物理/社会规则的申请
- **因果图**：事件之间的 `triggered_by` 与 `causes` 链，支持长线叙事追踪

---

## 双模式运行

AURA 暴露 OpenAI-compatible API，对前端零改造接入。

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

## SillyTavern 生态兼容

AURA 不试图取代 ST，而是让 ST 的存量资产（角色卡、世界书）获得**原生不支持的能力**：

- **ST 角色卡导入**：PNG/JSON 直接解析，自动填充八层定义
- **世界书转换**：Lorebook Entry → 世界规则 + 叙事锚点
- **图片解析**：本地 VLM（Qwen2.5-VL / MiniCPM-V）或云端 API（用户自填 Key）提取存在层描述
- **双向兼容**：Aura 补完的暗线、张力、轨迹可导出为扩展格式

**关键差异**：ST 的角色卡是"静态面具"，导入 AURA 后成为"可演进的生命体"——跨会话保留状态，经历事件后人格偏移。

---

## 快速开始

### 环境要求

- Python 3.10+
- 8GB+ RAM（推荐）
- LLM API Key（DeepSeek / Kimi / Gemini，用户自填）

### 安装

```bash
git clone https://github.com/hbbtsk/AURA.git
cd AURA
pip install -r requirements.txt
```

### 配置

创建 `.env`：

```env
# 至少配置一个 LLM 后端
DEEPSEEK_API_KEY=sk-your-deepseek-key
KIMI_API_KEY=sk-your-kimi-key

# 可选：超时与降级
LLM_MAIN_TTFB_TIMEOUT=3
LLM_MAIN_FALLBACK_PROVIDER=kimi
```

### 启动

```bash
python -m app.main
# 服务运行于 http://localhost:8000
```

### 接入 TAVO（Mode A）

| 设置 | 值 |
|------|-----|
| API URL | `http://localhost:8000/v1/chat/completions` |
| API Key | 任意值（AURA 不校验，TAVO 要求必填） |
| Model | `deepseek-v4-flash` / `kimi-k2.6` / `gemini-2.0-flash` |

### 运行世界（Mode B）

```bash
curl -X POST http://localhost:8000/v1/world/completions   -H "Content-Type: application/json"   -d '{
    "message": "Hello, Weiss.",
    "cartridge": "rwby_beacon",
    "model": "deepseek-v4-flash"
  }'
```

---

## Cartridge 系统（.aura）

自包含的世界数据包：

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

Director 自动激活当前场域内的实体——无需关键词匹配。

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
| **v1.0.x** | Prompt 编译器：LangGraph 状态机、3 层记忆、质量校验 | ✅ 稳定 |
| **v1.1.x** | 世界平台：元模型、Cartridge 系统、Director、NPC Agent | 🚧 骨架 |
| **v1.2.x** | 因果引擎：Kuzu 图数据库、因果链遍历、CausalRAG | 📋 计划 |
| **v1.3.x** | 事件涌现：EventEngine、PacingEngine、PerturbationEngine | 📋 计划 |
| **v1.4.x** | 多 Agent 并发：NPC 并行 LLM 调用、冲突检测、离线模拟 | 📋 计划 |

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

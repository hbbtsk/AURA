# AURA

**Agentic Unified Roleplay Assistant** — 角色扮演专用的 Prompt 编译器 + 模型行为校正引擎

AURA 是一个轻量级中间层服务，部署在 TAVO（前端 RP 平台）与 LLM（后端模型）之间。它拦截 TAVO 发出的请求，对 Prompt 进行拆解、重组、增强，再转发给 LLM，解决重度 RP 用户在长对话中遇到的 15 个系统性痛点。

---

## 快速开始

### 环境要求

- Python 3.10+
- 8GB+ RAM（推荐）


```bash
# 克隆仓库
git clone https://gitee.com/miaoshan-kebab/aura.git
cd aura

# 安装依赖
pip install -r requirements.txt
```

### 配置

复制 `.env` 文件并填写 API Key：

```bash
# .env 文件
DEEPSEEK_API_KEY=sk-your-deepseek-key
KIMI_API_KEY=sk-your-kimi-key
```

### 启动

```bash
python -m app.main
```

服务默认运行在 `http://localhost:8000`。

### 对接 TAVO

在 TAVO 的自定义 API 设置中：

| 设置项 | 值 |
|--------|-----|
| API 地址 | `http://localhost:8000/v1/chat/completions` |
| API Key | 任意值（AURA 不校验，但 TAVO 要求必填） |
| 模型名 | `deepseek` / `kimi` / `gemini`（自动映射到对应后端） |

---

## 使用说明：TAVO 角色卡格式要求

AURA 依赖 TAVO 角色卡中的 `=====` 格式标记来正确拆解各个区块。**你需要在 TAVO 角色卡的 System Prompt 中手动添加以下标记**，AURA 才能准确识别长记忆、用户设定和角色卡的边界。

### 标记格式

在 TAVO 角色卡的 System Prompt 中，按以下顺序插入标记：

```
（你的自定义提示词 / 越权禁令，可选）

=====长记忆开始=====
- 记忆条目 1
- 记忆条目 2
- ...
=====长记忆结束=====

# 记忆应用
（记忆应用规则，可选）

=====用户设定开始=====
（你的用户设定内容）
=====用户设定结束=====

=====角色卡开始=====
（你的角色卡内容）
=====角色卡结束=====

（世界书内容，可选。AURA 会自动识别 =====角色卡结束===== 之后、[Start a new Chat] 之前的内容作为世界书）
```

### 标记说明

| 标记 | 必填？ | 说明 |
|------|--------|------|
| `=====长记忆开始=====` / `=====长记忆结束=====` | 推荐 | 包裹长记忆条目（每行以 `- ` 开头）。不添加则 AURA 尝试格式回退匹配 |
| `=====用户设定开始=====` / `=====用户设定结束=====` | 推荐 | 包裹用户设定内容。不添加则 AURA 尝试正则匹配 `{用户名}是{用户名}` 格式 |
| `=====角色卡开始=====` / `=====角色卡结束=====` | **强烈推荐** | 包裹角色卡内容。不添加则 AURA 尝试英文格式 `Name is...` 或中文格式回退 |
| （世界书无需标记） | - | AURA 自动提取 =====角色卡结束===== ~ [Start a new Chat] 之间的内容 |

### 为什么需要这些标记？

TAVO 的 System Prompt 是一个混沌的文本块，混杂了越权禁令、长记忆、用户设定、角色卡、世界书等内容。没有标记时，AURA 只能靠正则猜测各区域的边界（如英文 `Name is...` 格式、中文 `{用户名}是{用户名}` 格式），**对于中文角色卡或非标准格式，猜测可能失败**。

添加 `=====` 标记后，AURA 可以精确识别每个区块的起止位置，确保：
- ✅ 角色卡完整保留到 `[CHARACTER_CARD]` 区块
- ✅ 用户设定完整保留到 `[USER_PROFILE]` 区块
- ✅ 长记忆正确提取，用于 RAG 透传降级
- ✅ 越权禁令正确保留到 `[MAIN_PROMPT]` 区块

### 不添加标记的后果

| 缺少标记 | 可能后果 |
|----------|----------|
| 无 `=====角色卡开始/结束=====` | 角色卡可能为空（`角色卡=0字符`），LLM 失去角色设定 |
| 无 `=====用户设定开始/结束=====` | 用户设定可能丢失，LLM 不知道 user 是谁 |
| 无 `=====长记忆开始/结束=====` | 长记忆可能无法正确提取，透传降级时内容不完整 |

### 验证标记是否生效

启动 AURA 后，查看日志中的拆解统计：

```
[AURA→拆解] System Prompt 组件: 越权禁令=0字符, 长记忆=779条, 角色卡=48314字符, ...
[AURA→标记] 使用 =====角色卡===== 标记定位: 行 42-198 | 48314字符
```

如果看到 `使用 =====角色卡===== 标记定位` 的日志，说明标记生效。如果看到 `使用格式回退提取角色卡`，说明标记未生效，AURA 在用猜测方式提取。

---

## 核心功能

| 功能 | 说明 | 版本 |
|------|------|------|
| **Prompt 拆解 + 9 区块重组** | 将 TAVO 混沌输入编译为结构化 Prompt | v0.5.0 |
| **三层记忆架构** | WORKING（5轮对话）+ RECENT（10条摘要）+ LONG_TERM（RAG Top-5） | v0.7.0 |
| **意图感知 RAG v2** | 6 维结构化字段 + 逐字段 embedding 软匹配 + 复合评分 | v0.7.0 |
| **用户意图解析** | 轻量 LLM 前置调用，输出自然语言导演指令注入主 LLM | v0.7.0 |
| **SSE 流式代理** | 先完整收集 → 质检（预留）→ 模拟流式返回，保留段落格式 | v0.5.0 |
| **多 LLM 后端** | DeepSeek（主对话）/ Kimi（意图分析+记忆总结）/ Gemini（预留） | v0.6.0 |
| **场景隔离配置** | 每个 LLM 调用场景有独立的 temperature/max_tokens/timeout | v0.7.0 |

---

## 痛点覆盖

AURA 针对 15 个 RP 用户体验痛点设计，当前版本已解决/缓解 **9 个**：

| # | 痛点 | 状态 | 对应模块 |
|---|------|------|---------|
| 1 | **越权输出** — 模型替 user 写台词/行动 | ✅ 显著缓解 | CONSTRAINTS 区块 + 越权禁令 |
| 2 | **文风污染** — 垃圾小说训练痕迹（臀腿腰胸） | 📅 Week 2 | StyleInjection |
| 3 | **文风固化** — 长时间同一模型锁死 | 📅 Week 3 | 多模型切换策略 |
| 4 | **状态回退** — 怀孕→生完→又怀孕 | ✅ 部分缓解 | StateManager + dynamic_state |
| 5 | **RPG剧情回退** — 主线被带回过去 | ✅ 部分缓解 | 时间加权 RAG + insert_seq |
| 6 | **内心独白泄露** — LLM 像有读心术 | 📅 Week 3 | OOCCheck |
| 7 | **跨角色记忆记忆隔离** — 私密话共享 | 📅 Week 3 | 会话隔离 + 关系图谱 |
| 8 | **多角色状态记录缺失** — party/NPC 状态变化全丢 | ✅ 部分缓解 | dynamic_state 表 + StateManager |
| 9 | **重复记忆/冗余信息** — 同一批 NPC 信息反复记录 | ✅ 根本解决 | FAISS 去重 + 结构化字段 |
| 10 | **长记忆无 RAG，全量注入** — token 浪费 + 注意力稀释 | ✅ 根本解决 | FAISS 语义召回 Top-5 |
| 11 | **模型输出太少** — DeepSeek 输出过短 | 📅 Week 2 | FormatGuard + 长度控制 |
| 12 | **模型输出太多** — Gemini 输出过长 | 📅 Week 2 | FormatGuard + 长度限制 |
| 13 | **系统提示词锁不住** — LLM 偏离人设 | 📅 Week 3 | ModelDialectCompiler |
| 14 | **时间维度缺失** — 已完成事件重复生成 | ✅ 部分缓解 | insert_seq 动态归一化 |
| 15 | **用户输入意图隐含** — LLM 默认接话而非渲染反应 | ✅ 显著缓解 | IntentTagger + USER_INTENT_TAG |

---

## 架构概览

```
TAVO ──①──→ AURA ──②──→ LLM ──③──→ AURA ──④──→ TAVO
```

| 阶段 | 说明 |
|------|------|
| ① TAVO→AURA | 接收 RP 请求，保存原始 Prompt 到调试日志 |
| ② AURA→LLM | Prompt 拆解 → 意图解析 → 三层记忆注入 → 9 区块重组 → 近因效应追加 |
| ③ LLM→AURA | 完整收集 SSE 流 → 质检（预留）→ 保存到 SQLite |
| ④ AURA→TAVO | 按段落+句子粒度切分 → 模拟 SSE 流式返回 |

详细架构说明见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

---

## 项目结构

```
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 集中配置管理（场景隔离）
│   ├── intent_tagger.py        # 意图解析器
│   ├── prompt_decomposer.py    # Prompt 拆解器
│   ├── api/
│   │   └── completions.py      # 核心 API（路由 + 流式处理）
│   └── memory/
│       ├── manager.py          # 记忆管理器（FAISS + SQLite）
│       └── models.py           # 数据模型
├── ARCHITECTURE.md             # 架构文档
└── AURA-30天完整执行计划.md     # 完整执行计划与设计文档
```

---

## 技术栈

| 层级 | 选型 |
|------|------|
| API 网关 | FastAPI + Pydantic + Uvicorn |
| 模型层 | httpx 直连多后端 |
| 向量记忆 | FAISS（IndexFlatL2）+ bge-small-zh-v1.5 |
| 结构化存储 | SQLite |
| 记忆总结 | Kimi API（每 5 轮触发） |

---

## 开发计划

| 阶段 | 日期 | 主题 | 核心交付 | 状态 |
|------|------|------|---------|------|
| **Week 1** | 4.30-5.11 | 核心骨架 + 端到端跑通 | FastAPI、PromptDecomposer、FAISS RAG、LangGraph 15节点状态机、IntentTagger、3层记忆架构、SSE 流式修复 | ✅ v0.8.0 |
| **Week 2** | 5.12-5.18 | 意图感知 + 记忆增强 | FormatGuard 真实化、ContentFilter、StateManager 完善、实体识别、情绪分析、集成测试 | 📅 待实现 |
| **Week 3** | 5.19-5.25 | 模型方言编译器 + 格式控制 | StyleInjection、多模型切换、ModelDialectCompiler、OOCCheck、100轮调参 | 📅 待实现 |
| **Week 4** | 5.26-6.1 | 优化 + 文档 + 部署 | ARCHITECTURE.md、README、Docker、CI/CD、验收测试 | 📅 待实现 |
| **缓冲** | 6.1-6.5 | 面试前调整 | 修 bug、调参、模拟面试 | 📅 待实现 |
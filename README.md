# AURA

**Agentic Unified Roleplay Assistant** — 角色扮演专用的 Prompt 编译器 + 模型行为校正引擎

AURA 是一个轻量级中间层服务，部署在 TAVO（前端 RP 平台）与 LLM（后端模型）之间。它拦截 TAVO 发出的请求，对 Prompt 进行拆解、重组、增强，再转发给 LLM，解决重度 RP 用户在长对话中遇到的 15 个系统性痛点。

---

## 快速开始

### 环境要求

- Python 3.10+
- 8GB+ RAM（推荐）

### 安装

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

| # | 痛点 | 状态 |
|---|------|------|
| 1 | 越权输出 — 模型替 user 写台词/行动 | ✅ 显著缓解 |
| 9 | 重复记忆/冗余信息 — 同一批 NPC 信息反复记录 | ✅ 根本解决 |
| 10 | 长记忆无 RAG，全量注入 — token 浪费 | ✅ 根本解决 |
| 15 | 用户输入意图隐含 — LLM 默认接话而非渲染反应 | ✅ 显著缓解 |
| 4 | 状态回退 — 怀孕→生完→又怀孕 | ✅ 部分缓解 |
| 5 | RPG剧情回退 — 主线被带回过去 | ✅ 部分缓解 |
| 8 | 多角色状态记录缺失 — party/NPC 状态变化全丢 | ✅ 部分缓解 |
| 14 | 时间维度缺失 — 已完成事件重复生成 | ✅ 部分缓解 |

剩余 6 个痛点（文风污染/固化、内心独白泄露、跨角色记忆隔离、输出长度控制、系统提示词锁不住）将在 Week 2-3 实现。

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

| 阶段 | 内容 | 状态 |
|------|------|------|
| Day 1 | 项目骨架 + Tavo→AURA→LLM 转发通道 + Prompt 拆解注入 | ✅ v0.5.0 |
| Day 2 | SQLite + FAISS 记忆库 + RAG 召回 | ✅ v0.6.0 |
| Day 2.5 | 意图感知 RAG v2 + 三层记忆 + IntentTagger | ✅ v0.7.0 |
| Day 3 | LangGraph 状态机 + 模型方言编译器 | 📅 待实现 |
| Day 4 | 记忆策略算法 + FormatGuard + StateManager | 📅 待实现 |
| Day 5 | LLM 对接 + Tavo 兼容 + 50 轮测试 | 📅 待实现 |

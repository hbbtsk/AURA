# AURA — 30天完整执行计划

> 项目代号：**AURA** (Agentic Unified Roleplay Assistant)
> 目标：面试用 + 自己用（ST/Tavo 重度用户，氪金数千）
> 原则：纯后端、不做前端、不做调包侠
> 时间线：30天（五一5天骨架 + 3周血肉 + 1周面试武器）
> 面试日期：五月底

---

## 一、项目愿景

> "即使世界忘了角色的誓言，AURA 也会替他们记住。"

**给 RWBY 一个赛博老家。**

AURA 不是再造 SillyTavern 或 Tavo，而是做 **ST/Tavo 与 LLM 之间的智能编排层 + 质量控制系统**。对客户端来说，AURA 就是一个"戴着面具的 DeepSeek"——暴露 OpenAI-compatible API，零改造接入。

**AURA 的本质定位：角色扮演专用的 API 网关 + 智能编排层。**

```
TAVO ──→ AURA（API 网关）
              ├── 路由层 → DeepSeek / Kimi / Gemini / ...
              ├── Prompt 优化层（拆解 + 9 区块重组）
              ├── 记忆管理层（SQLite + FAISS RAG）
              └── 质量控制层（两头约束 / StateManager / ...）
```

用户只需在 TAVO 中配置一个 API 地址（AURA），所有流量都经过 AURA。AURA 内部负责模型切换、Prompt 优化、记忆管理、质量检测——用户无感知。

### 核心策略：拆解 → 优化 → 重组

AURA 的核心工作流程是 **"拆解 → 优化 → 重组"**：

1. **拆解**：将 TAVO 发送的原始 Prompt（System Prompt 中混杂了越权禁令、长记忆、角色卡、世界书、USER设定等）按格式标记拆解为结构化组件
2. **优化**：对各组件分别应用优化策略（RAG压缩长记忆、增量注入约束指令、状态一致性校验等）
3. **重组**：将优化后的组件重新组装为更精准、更高效的 Prompt 发送给 LLM

> 由于 TAVO 是闭源软件，无法在其输出中添加自定义字段，因此采用 **"格式拆解 + 区块重组"** 策略——通过硬解析识别 System Prompt 中的各区域边界，重组为 9 个标准化区块，并应用"两头约束"（开头 Priming + 结尾 Recency Effect）。

---

## 二、12 个系统性痛点

宋作为重度 RP 用户，真金白银买来的真实体验：

| # | 痛点 | 五一 | 节后 |
|---|------|------|------|
| 1 | **越权输出** — 模型替 user 写台词/行动 | ✅ | — |
| 2 | **文风污染** — 垃圾小说训练痕迹（臀腿腰胸） | — | Week 2 |
| 3 | **输出结构模板化** — 模型形成固定写作八股（环境→动作→心理→对话），尤其Gemini明显 | — | Week 3 |
| 4 | **状态回退** — 怀孕→生完→又怀孕 | ✅ | — |
| 5 | **RPG剧情回退** — 主线被带回过去 | — | Week 2 |
| 6 | **内心独白泄露** — LLM像有读心术 | — | Week 3 |
| 7 | **跨角色记忆隔离** — 私密话共享 | — | Week 3 |
| 8 | **冲突消解过快** — A驳斥B，B直接认怂 | — | Week 3 |
| 9 | **LLM维护官配** — 强行回归原作剧情 | — | Week 3 |
| 10 | **关系称谓/身份漂移** — A是B亲妈，20轮后B叫A"姐姐"；剧情破裂后B仍叫"妈" | — | Week 3 |
| 11 | **被动RAG导致默认行为矛盾** — 用户不提记忆，LLM按默认生成，与角色状态冲突 | — | Week 1（随StateManager） |
| **12** | **模型输出长度失控** — DeepSeek太少剧情推不动，Gemini太多抢玩家戏 | — | Week 2 |

---

## 三、技术栈

| 层级 | 选型 | 说明 |
|------|------|------|
| API 网关 | FastAPI + Pydantic + Uvicorn | OpenAI-compatible `/v1/chat/completions` |
| 模型层 | httpx 直连 | 多后端切换（DeepSeek/Kimi） |
| 结构化存储 | SQLite（直接 sqlite3） | 原始对话、会话、dynamic_state、plot_anchors、关系边 |
| 向量记忆 | FAISS（IndexFlatL2） | LLM API 生成 embedding（Kimi → DeepSeek 回退），时间加权 RAG |
| 记忆总结 | Kimi API | 每 5 轮自动总结对话 → 提取新记忆 → 存入 FAISS |
| 工作记忆 | Python dict | 最近 N 轮热缓存 |
| 关系图谱 | SQLite（骨架） | 角色节点 + 情感权重边（待 Day 4 完善） |
| 辅助 | httpx、numpy、faiss-cpu |

### 技术栈名词通俗解释

| 名词 | 干什么的 | 类比 |
|------|---------|------|
| **FastAPI** | Python Web 框架，写 API 接口 | 饭店前台，收客人订单、端菜回去 |
| **Pydantic** | 数据格式校验工具 | 菜单模板，规定"菜名必须是字符串" |
| **Uvicorn** | FastAPI 的运行服务器 | 饭店的电源开关，让服务跑起来 |
| **httpx** | HTTP 客户端，请求 LLM API | 传菜员，把订单送到后厨 |
| **FAISS** | 本地向量检索引擎，按"语义"检索记忆 | 图书馆管理员，你说"保护朋友"就找出相关情节 |
| **SQLite** | 嵌入式数据库，存对话记录和元数据 | 账本，记下每轮对话的内容 |
| **numpy** | 数值计算库，处理向量运算 | 计算器，算两个记忆的相似度 |

---

## 四、30天总览

| 周次 | 日期 | 主题 | 核心交付 |
|------|------|------|---------|
| **Week 1** | 4.30-5.5 | 核心骨架 + 端到端跑通 | FastAPI、双源角色卡、分层记忆、13节点状态机、LLM对接、50轮测试、Streamlit面板 |
| **Week 2** | 5.6-5.11 | 质量控制层完整实现 | FormatGuard真实化、ContentFilter、StateManager完善、PlotAnchor、集成测试 |
| **Week 3** | 5.12-5.18 | 深度优化 + 进阶特性 | StyleInjection、多模型切换、100轮调参、关系图谱优化、独白/隔离/冲突/官配 |
| **Week 4** | 5.19-5.25 | 面试武器 | ARCHITECTURE.md、README、CSDN文章、面试话术、演示视频 |
| **缓冲** | 5.26-5.31 | 面试前调整 | 修bug、调参、模拟面试 |

---

## 五、Week 1｜五一假期详细任务与验收

---

### Day 1｜项目骨架 + Tavo→AURA→LLM 纯转发通道 + Prompt 拆解注入

**目标**：后端跑起来，成为 Tavo 和 LLM 之间的桥梁，实现完整的请求转发链路，并在中间打印每一跳的传输数据用于调试。同时实现 TAVO Prompt 的格式拆解与增量注入机制。

#### 上午：FastAPI 骨架
1. `app/main.py` FastAPI入口，注册 `completions_simple` 路由
2. `app/api/completions_simple.py`：`POST /v1/chat/completions`
   - 接收 Tavo 请求 → 映射模型名到后端名 → 转发给 LLM → 返回响应
   - 支持流式（SSE 透传）和非流式两种模式
3. `app/config.py`：LLM 后端配置（DeepSeek/Gemini），`get_llm_config()` 按后端名获取配置
4. `app/api/completions.py`：备用 API 处理器（已修复模型名映射，但未注册为路由）
5. 启动：`python -m app.main`（uvicorn 监听 `0.0.0.0:8000`）

#### 下午：Tavo→AURA→LLM 传输日志打印
1. **请求日志**（`[TAVO→AURA]`）：
   - 收到 Tavo 请求时打印：会话ID、模型名、消息数、消息预览
   - 记录请求完整结构到日志文件
2. **转发日志**（`[AURA→LLM]`）：
   - 转发给 LLM 时打印：目标 URL、后端名、模型名
   - 调试模式下打印 API Key 掩码和请求体
3. **响应日志**（`[LLM→AURA]`）：
   - 流式模式：聚合所有 chunk，打印 chunk 数、内容长度、内容预览
   - 非流式模式：打印响应内容预览、token 用量、finish_reason
4. **返回日志**（`[AURA→TAVO]`）：
   - 返回给 Tavo 时打印：状态码、响应长度

#### 晚上：日志管理 + 项目精简 + Prompt 拆解注入
1. **日志轮转**：`RotatingFileHandler`，每个文件 5MB，保留 3 个备份，输出到 `logs/aura.log`
2. **终端降噪**：控制台只输出 INFO 及以上，抑制 httpx/httpcore 的 DEBUG 日志
3. **项目精简**：删除未参与管道的文件（database、models、services、middleware、test 等）
4. **模型名映射修复**：`get_backend_for_model()` 将 `deepseek-v4-flash` 映射到 `deepseek` 后端

#### 晚上（续）：Prompt 拆解器 + 增量注入器
5. **Prompt 拆解器**（`app/prompt_decomposer.py`）：
   - `PromptDecomposer`：将 TAVO 的 System Prompt 按格式标记拆解为结构化组件
   - `IncrementalInjector`：在不修改原始内容的前提下，在 System Prompt 末尾追加优化指令
   - 拆解组件：越权禁令、长记忆、记忆应用规则、USER设定、角色卡、世界书、XML角色卡、多轮对话
   - 注入模板：FormatGuard（越权控制）、StyleInjection（结构多样化）、StateManager（状态一致性）
6. **接入转发流程**：在 `completions_simple.py` 的 `chat_completion()` 中，转发前执行拆解→注入→转发

#### 晚上（续）：Prompt Dump + 三层标记解析 + 用户自定义提示词检测
7. **Prompt Dump 功能**（`completions_simple.py:183`）：
   - 每次请求自动保存到 `prompt_dumps/prompt_YYYYMMDD_HHMMSS.txt`
   - 记录完整请求结构（role、content长度、完整内容）
   - 文件名使用系统时间，可读性强
   - `prompt_dumps/` 已加入 `.gitignore`
8. **三层递进标记解析**（`prompt_decomposer.py`）：
   - **Phase 1**：`=====` 格式标记（用户在角色卡中约定的结构化边界标记）
     - `=====长记忆开始=====` / `=====长记忆结束=====`
     - `=====用户设定开始=====` / `=====用户设定结束=====`
     - `=====角色卡开始=====` / `=====角色卡结束=====`
   - **Phase 2**：HTML 注释标记回退（`<!-- AURA_CHARACTER_CARD_START/END -->`）
   - **Phase 3**：无标记时回退到基于格式的硬拆解（正则匹配旧格式边界）
9. **用户自定义提示词检测**（`prompt_decomposer.py`）：
   - 检测 System Prompt 第一行是否为 `"以下是关于..."`（TAVO 默认格式）
   - 如果第一行是 `"以下是关于..."` → 用户没写自定义提示词 → **替换为 AURA 严谨系统提示词**（含越权禁令 + 角色扮演规则）
   - 如果第一行不是 `"以下是关于..."` → 用户写了自定义提示词 → **保留原始内容 + 增量注入**
   - 替换后的 System Prompt 结构：`[AURA系统提示词] + [长记忆] + [记忆应用规则] + [USER设定] + [角色卡] + [世界书] + [XML角色卡] + [增量注入指令]`
10. **重组逻辑保留标记**（`completions_simple.py`）：
   - 拆解后重组时，保留 `=====` 标记在原始位置
   - 确保 TAVO 的格式标记在转发后仍然完整，不影响后续轮次解析

#### 晚上（规划）：区块化 Prompt 重组方案（待实现）

**目标**：将拆解后的组件重新组装为结构化区块 Prompt，替代 TAVO 原始的"大杂烩" System Prompt，让 LLM 明确理解每个区块的用途和格式约定。

**核心思路**：用 `[SECTION_NAME]` 区块标题 + 结构化内容，替代自然语言混杂的原始 System Prompt。同时与 LLM 约定通信标记（双引号=台词、**星号=动作、（）=心理），让输入输出格式一致。

**重组后的 Prompt 结构**：

```
[PROTOCOL]        ← 通信标记约定（元指令，放在最前面）
[CONSTRAINTS]     ← 角色边界 + 负向指令
[CHARACTER_CARD]  ← 角色卡（完整保留，不裁剪）
[DYNAMIC_STATE]   ← 实体当前状态 [state: xxx]
[WORKING_MEMORY]  ← 最近 N 轮对话（保持原始标记）
[RAG_EPISODIC]    ← 召回记忆 [recall_memory: xxx]
[WORLD_CONTEXT]   ← 世界书（有则注入，无则跳过）
[OUTPUT_SPEC]     ← 输出格式 + 标记使用规范
```

**区块分类（按生成方式）**：

| 类别 | 区块 | 生成方式 | 说明 |
|------|------|---------|------|
| **静态模板**（写死） | `[PROTOCOL]` | 固定文本，直接组装 | 标记约定规则，不依赖任何动态数据 |
| | `[CONSTRAINTS]` | 固定文本，直接组装 | 越权禁令 + 负向指令，不依赖任何动态数据 |
| | `[OUTPUT_SPEC]` | 固定文本，直接组装 | 输出格式规范，不依赖任何动态数据 |
| **拆解自 TAVO**（不裁剪） | `[CHARACTER_CARD]` | 从 TAVO System Prompt 拆解，**完整保留** | 角色卡是 LLM 理解角色的核心依据，缩写会丢失细节 |
| | `[WORKING_MEMORY]` | 从 TAVO 对话历史拆解，最近 N 轮 | 保持原始标记格式不变 |
| | `[WORLD_CONTEXT]` | 从 TAVO System Prompt 拆解，**有则注入，无则跳过** | 位置：`=====角色卡结束=====` 与 `[Start a new Chat]` 之间的内容 |
| **Agent 动态生成** | `[DYNAMIC_STATE]` | StateManager 从数据库读取结构化状态，格式化为 `[state: xxx]` | Day 4 真实化 |
| | `[RAG_EPISODIC]` | Chroma 语义检索 + 重排序，召回 Top-5 最相关记忆，格式化为 `[recall_memory: xxx]` | Day 2 实现向量库后可用 |

**各区块详细设计**：

| 区块 | 内容 | 来源 |
|------|------|------|
| `[PROTOCOL]` | 标记约定：`"对话"`=台词、`**动作**`=动作描写、`（心理）`=内心独白；说明 LLM 输出也需遵循此格式 | 静态模板（写死） |
| `[CONSTRAINTS]` | 越权禁令（禁止替 user 行动/台词）、负向指令（禁止臀腿腰胸、禁止推进剧情）、角色边界 | 静态模板（写死） |
| `[CHARACTER_CARD]` | 角色卡**完整保留**，不裁剪、不缩写 | 拆解自 `=====角色卡开始/结束=====` 标记区域 |
| `[DYNAMIC_STATE]` | 用 `[state: 实体名=状态值]` 格式列出所有实体的当前状态 | Agent（StateManager）从数据库读取后生成 |
| `[WORKING_MEMORY]` | 最近 3-5 轮对话，保持原始标记格式（双引号/**/（）） | 拆解自 `[Start a new Chat]` 之后的多轮对话 |
| `[RAG_EPISODIC]` | 用 `[recall_memory: 事件描述]` 格式列出召回的记忆事件 | Chroma 语义检索 Top-5（Day 2 实现） |
| `[WORLD_CONTEXT]` | 世界书内容，**有则注入，无则跳过** | 拆解自 `=====角色卡结束=====` 与 `[Start a new Chat]` 之间的内容 |
| `[OUTPUT_SPEC]` | 输出长度、结构比例（环境30%/NPC40%/行动空间30%）、标记使用规范、禁止项 | 静态模板（写死） |

**标记约定（`[PROTOCOL]` 核心内容）**：

```
[PROTOCOL]
- "对话内容"（双引号）= 角色台词，表示角色说出口的话
- **动作描写**（星号）= 角色动作、表情、行为
- （心理活动）（小括号）= 角色内心独白，未说出口的想法
- 输入格式：user 的消息会使用上述标记，LLM 需正确理解
- 输出格式：LLM 的回复也必须使用上述标记，保持格式一致
```

**与 TAVO 原始格式的兼容性**：
- TAVO 的对话历史中可能已经使用了 `"对话"`、`**动作**`、`（心理）` 等格式
- `[WORKING_MEMORY]` 区块保持原始标记不变，LLM 通过 `[PROTOCOL]` 理解其含义
- 后续轮次中，LLM 的输出也遵循相同标记，TAVO 前端可以正常渲染

**世界书检测逻辑**：
- System Prompt 中 `=====角色卡结束=====` 与 `[Start a new Chat]` 之间的内容 = 世界书
- 有内容 → 注入 `[WORLD_CONTEXT]` 区块
- 无内容 → 跳过 `[WORLD_CONTEXT]` 区块，不生成
- 不需要语义匹配或格式识别，纯位置检测

**实现时机**：Day 1 完成拆解后，重组方案在 Day 3（LangGraph 状态机）或 Day 4（质量控制真实化）时实现，届时 PromptReassembler 将使用此结构化区块方案替代当前的简单拼接。

**🎯 验收标准**：
```bash
# 1. Tavo能连接AURA后端
# 在Tavo中配置：API地址=http://localhost:8000/v1，API密钥=任意值

# 2. 完整传输链路通
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash","messages":[{"role":"system","content":"你是Ruby..."},{"role":"user","content":"你好"}],"stream":false}'
# 返回：LLM 真实响应（非 mock）

# 3. 传输日志打印正常
# 终端/日志文件应看到四条标记：
#   [TAVO→AURA] 收到请求 | 会话: xxx | 模型: deepseek-v4-flash | ...
#   [AURA→LLM] 转发请求 | URL: https://api.deepseek.com/... | 后端: deepseek
#   [LLM→AURA] 非流式响应完成 | 内容长度: xxx | token用量: ...
#   [AURA→TAVO] 返回响应 | 状态码: 200

# 4. 日志文件管理
# 检查 logs/aura.log 应有完整传输记录
# 日志文件自动轮转，不无限增长

# 5. 数据结构清晰
# 能明确看到：Tavo发送了什么 → AURA收到了什么 → LLM返回了什么 → AURA返回了什么

# 6. Prompt 拆解日志
# 日志中应看到：
#   [AURA→拆解] System Prompt 组件: 越权禁令=xx字符, 长记忆=xx条, ...
#   [AURA→注入] 已注入优化指令: ['formatguard', 'style_injection'] | System Prompt: xxx→xxx字符

# 7. Prompt Dump 文件
# 检查 prompt_dumps/ 目录应有请求快照文件
# 文件名格式：prompt_20260503_175044.txt（系统时间）

# 8. 三层标记解析验证
# 日志中应看到标记检测日志：
#   [AURA→标记] 使用 =====长记忆===== 标记定位: 行 3-264 | 255条
#   [AURA→标记] 使用 =====用户设定===== 标记定位: 行 269-269 | 180字符
#   [AURA→标记] 使用 =====角色卡===== 标记定位: 行 273-304 | 3188字符

# 9. 用户自定义提示词检测
# 日志中应看到：
#   [AURA→检测] 用户未写自定义提示词，替换为 AURA 系统提示词
#   或
#   [AURA→检测] 检测到用户自定义提示词，保留原始内容 + 增量注入
```

---

### Day 1 实际完成情况（2026-05-03）

#### 已完成功能清单（v0.6.0）

| 功能 | 文件 | 状态 |
|------|------|------|
| FastAPI 骨架 + 路由注册 | `app/main.py` | ✅ |
| 纯转发通道（流式+非流式） | `app/api/completions_simple.py` | ✅ |
| LLM 后端配置（DeepSeek/Gemini） | `app/config.py` | ✅ |
| 备用 API 处理器（已删除，统一使用 completions_simple.py） | — | ✅ |
| 传输日志打印（TAVO→AURA→LLM→AURA→TAVO） | `app/api/completions_simple.py` | ✅ |
| 日志轮转（5MB×3） + 终端降噪 | `app/api/completions_simple.py` | ✅ |
| 项目精简（删除未参与文件） | — | ✅ |
| 模型名映射修复（deepseek-v4-flash → deepseek） | `app/api/completions_simple.py` | ✅ |
| Prompt 拆解器（三层递进标记解析） | `app/prompt_decomposer.py` | ✅ |
| Prompt 区块重组（9 区块，内联实现，已移除 PromptReassembler） | `app/api/completions_simple.py` | ✅ |
| Prompt Dump（自动保存请求到 prompt_dumps/） | `app/api/completions_simple.py` | ✅ |
| 用户自定义提示词检测（替换/保留双分支） | `app/prompt_decomposer.py` | ✅ |
| 重组逻辑保留 `=====` 标记 | `app/api/completions_simple.py` | ✅ |
| 区块化 Prompt 重组（9 区块，统一流程） | `app/api/completions_simple.py` | ✅ |
| 用户名动态提取（从对话第一条 user 消息） | `app/api/completions_simple.py` | ✅ |
| 重组后 Prompt 保存到独立文件 | `app/api/completions_simple.py` | ✅ |
| COT 自我校验指令（[OUTPUT_SPEC] 末尾追加 5 步检查） | `app/api/completions_simple.py` | ✅ |

#### 关键决策记录

1. **TAVO 闭源 → 格式拆解 + 增量注入**：最初计划让 TAVO 在请求中添加 `aura_meta` 字段传递结构化数据，但发现 TAVO 是闭源软件无法修改。改为通过硬解析 System Prompt 格式边界来拆解组件，在不修改原始内容的前提下追加优化指令。

2. **三层递进标记策略**：为了解决不同角色卡格式不一致的问题，设计了三层递进解析策略：
   - Phase 1：`=====` 格式标记（用户在角色卡中手动添加，最高优先级）
   - Phase 2：HTML 注释标记（`<!-- AURA_CHARACTER_CARD_START/END -->`，第二优先级）
   - Phase 3：格式硬拆解（无标记时回退，最低优先级）

3. **用户自定义提示词检测**：System Prompt 第一行如果是 `"以下是关于..."`（TAVO 默认格式），说明用户没写自定义提示词，此时替换为 AURA 的严谨系统提示词；否则保留原始内容。

4. **Prompt Dump 文件名**：从 `prompt_{timestamp}_{id}.txt` 改为 `prompt_{YYYYMMDD_HHMMSS}.txt`，提高可读性。

5. **区块化 Prompt 重组（已实现 v0.5.0）**：将拆解后的组件重组为结构化区块 Prompt，替代 TAVO 原始的混杂 System Prompt。9 个区块按生成方式分为三类：
   - **静态模板（写死）**：`[PROTOCOL]`（标记约定）、`[CONSTRAINTS]`（越权禁令+负向指令）、`[OUTPUT_SPEC]`（输出格式规范）— 固定文本，直接组装
   - **拆解自 TAVO（不裁剪）**：`[CHARACTER_CARD]`（完整保留）、`[USER_PROFILE]`（用户设定）、`[RECENT_DIALOGUE]`（最近N轮对话）、`[LONG_TERM_MEMORY]`（长记忆，去重后全部注入）、`[WORLD_CONTEXT]`（世界书，有则注入无则跳过）
   - **Agent 动态生成**：`[CURRENT_STATE]`（StateManager 从数据库读取，当前为 Mock）、`[MAIN_PROMPT]`（用户自定义提示词，有条件出现）
   - 同时与 LLM 约定通信标记（双引号=台词、**星号=动作、（）=心理），让输入输出格式一致。
   - 验证结果（2026-05-03 21:26:27）：原始 28,735 字符 → 重组后 30,511 字符，9 个区块，LLM 正常流式响应 605 字符。

6. **用户名动态提取（从对话第一条 user 消息）**：最初使用 `user_profile` 正则 `^(.+?)是\1` 提取用户名，但该格式可能因用户设定写法不同而匹配失败。改为从对话中第一条 `role == "user"` 的消息内容提取冒号前的内容作为用户名（TAVO 格式固定为 `"用户名: 对话内容"`），更准确可靠。`user_profile` 正则作为后备方案保留。

7. **COT 自我校验指令**：实测发现开启 DeepSeek 思考模式后约束遵循效果显著提升，但思考模式会增加 1-3 秒延迟且需确认 API 兼容性。折中方案：在 System Prompt 的 `[OUTPUT_SPEC]` 区块末尾追加 5 步 COT 自我校验指令，让模型在输出前先逐项检查（越权/OOC/标记/长度），几乎无延迟增加。思考模式作为后续优化选项保留。

8. **AURA 定位为"角色扮演专用 API 网关"**：最初计划开发独立软件，后改为 TAVO 与 LLM 之间的智能编排层。AURA 暴露 OpenAI-compatible API，TAVO 只需配置一个 API 地址，所有流量经过 AURA 处理。AURA 内部负责模型切换（DeepSeek/Gemini/Claude/Qwen）、Prompt 优化、记忆管理、质量检测——用户无感知。本质上是"给 API 前端套壳"，解决用户切换 API 时的记忆断裂问题。

9. **"RAG First, FormatGuard Later" 策略**：分析发现长记忆占 Prompt 的 66%（20,000/30,511 字符），大量冗余记忆是越权输出的根本诱因。决定先实现 Day 2 的 RAG 记忆压缩（314 条 → Top-5），观察效果后再实现 FormatGuard。预期 RAG 压缩后越权率下降 50-60%，FormatGuard 只需处理剩余问题。

10. **时间加权 RAG 公式**：TAVO 的长记忆没有时间戳，但位置隐含时间顺序（开头的发生在前，后面的发生在后）。设计时间加权公式 `final_score = semantic × 0.6 + time_weight × 0.4`，其中 `time_weight = position`（0.0=最早, 1.0=最新），确保最新记忆在检索中占优势。

11. **AURA 自建记忆数据库（替代依赖 TAVO）**：TAVO 的长记忆生成存在根本问题——无上下文总结、重复严重、质量不可控。决定 AURA 自建 SQLite + Chroma 数据库，从 TAVO 已有记忆作为"初始种子"导入，后续由 AURA 接管记忆的总结、存储、召回全流程。每 5 轮调用 LLM 总结一次，新记忆存入 Chroma。

12. **记忆碎片化应对方案**：用户可能绕过 AURA 直接连接 LLM（如切换 API），导致 AURA 本地数据库出现记忆断裂。应对策略：每次请求时对比 TAVO 的长记忆列表与 AURA 数据库，检测新增记忆并导入。这样即使中间有断裂，也能从 TAVO 侧恢复。

13. **FormatGuard 优先级调低 — "RAG First" 策略**：分析发现长记忆占 Prompt 的 66%（20,000/30,511 字符），大量冗余记忆是越权输出的根本诱因。决定先做 RAG 记忆压缩，如果越权问题自然缓解，则 FormatGuard 不需要实现。FormatGuard 的详细三层设计（正则 Layer 1 + 语义 Layer 2 + Agent Layer 3）已在讨论中完成方案设计，但暂不写入执行计划，等 RAG 落地后评估是否需要。

#### 验证结果（v0.5.0）

- **2026-05-03 17:50:44 请求** — 三个标记全部准确识别：
  - `[AURA→标记] 使用 =====长记忆===== 标记定位: 行 3-264 | 255条`
  - `[AURA→标记] 使用 =====用户设定===== 标记定位: 行 269-269 | 180字符`
  - `[AURA→标记] 使用 =====角色卡===== 标记定位: 行 273-304 | 3188字符`
  - 拆解结果：越权禁令=92字符, 长记忆=255条, 角色卡=3188字符, 世界书=0字符, 对话=11轮

- **2026-05-03 21:26:27 请求** — 区块化重组首次真实流程验证通过：
  - 拆解：长记忆=314条（标记定位），角色卡=3188字符（标记定位），对话=13轮
  - 重组：原始 28,735 字符 → 重组后 **30,511 字符**（9 个区块，+1,776 字符）
  - LLM 响应：✅ 200 OK，流式 315 chunks，605 字符
  - 保存文件：`prompt_dumps/prompt_20260503_212627.txt` + `reassembled_20260503_212628.txt`
  - 用户名动态提取：从对话第一条 user 消息 `"宋·格雷迈恩: *第二天魏思夏沫跟我出来*"` → 提取 `"宋·格雷迈恩"` ✅

- 当前状态：**区块化重组模式 v0.5.0**，AURA 运行中（PID 2016, 端口 8000, DeepSeek 后端）


### Day 2｜AURA 自建记忆数据库 + RAG 召回 ✅

**目标**：AURA 接管记忆管理，从 TAVO 的 System Prompt 中拆解已有记忆导入 FAISS，后续每轮对话由 AURA 自己总结 + 存储 + RAG 召回。解决痛点 11（被动RAG矛盾），显著缓解痛点 1/4/5/7/10/12。

#### 背景：为什么 AURA 要自建记忆数据库

TAVO 的长记忆生成方式存在根本问题：
- **无上下文总结**：TAVO 每次把最近几轮对话独立塞给 LLM 总结，没有"已有记忆列表"作为上下文
- **重复严重**：NPC 基本信息被反复总结（如"Ruby 是 RWBY 队长"出现多次），314 条记忆中可能有大量重复
- **质量不可控**：TAVO 的总结 prompt 无法由 AURA 控制

**AURA 的方案**：自建 SQLite + FAISS 向量数据库，从 TAVO 的已有记忆作为"初始种子"导入，后续由 AURA 接管记忆的总结、存储、召回全流程。

**架构决策**：使用 FAISS（IndexFlatL2）替代 ChromaDB
- ChromaDB 在 Windows 上有严重的 native 依赖问题（chromadb_rust_bindings DLL 加载失败）
- FAISS 纯 CPU 版本（faiss-cpu）安装简单，无 native 依赖冲突
- 使用 LLM API（Kimi → DeepSeek 回退）生成 embedding，无需本地模型
- 持久化：FAISS 索引保存为 `faiss_index.bin`，元数据保存为 `faiss_meta.json`

#### 上午：SQLite Schema（原始对话存储）

```sql
-- 原始对话存储（每轮对话完整保留）
CREATE TABLE raw_dialogues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,          -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,
    round_number INTEGER NOT NULL,  -- 轮次编号
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 会话管理
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    character_id TEXT,
    model_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 动态状态（痛点4）
CREATE TABLE dynamic_state (
    session_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,    -- 角色/物品名
    state_json TEXT NOT NULL,     -- {"status": "已生产", "location": "信号盒"}
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, entity_name)
);

-- 剧情锚点（痛点5）
CREATE TABLE plot_anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_text TEXT NOT NULL,
    importance REAL DEFAULT 0.5,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 关系图谱（痛点10）
CREATE TABLE relationship_graph (
    session_id TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation_type TEXT,           -- 'family', 'friend', 'enemy', 'lover'
    weight REAL DEFAULT 0.0,     -- -1.0 ~ 1.0
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, source, target)
);
```

#### 下午：FAISS 向量记忆库 + 时间加权 RAG

**FAISS 初始化**：
```python
import faiss
import numpy as np

_dimension = 768  # 向量维度
index = faiss.IndexFlatL2(_dimension)  # L2 距离
documents: List[str] = []   # 与索引对应的文档
metadatas: List[dict] = []  # 与索引对应的元数据
```

**Embedding 生成**（使用 LLM API，无需本地模型）：
```python
async def _get_embedding(self, text: str) -> List[float]:
    # 优先 Kimi（便宜），回退 DeepSeek
    for provider in ["kimi", "deepseek"]:
        try:
            llm_config = get_llm_config(provider)
            # 调用 /v1/embeddings API
            response = await client.post(embed_url, json=payload)
            return response["data"][0]["embedding"]
        except:
            continue
    # 都不可用时返回零向量（降级）
    return [0.0] * self._dimension
```

**记忆导入（首次启动）**：
1. 从 TAVO System Prompt 的 `=====长记忆=====` 区域拆解出记忆列表
2. 每条记忆附带 metadata：`{index, position, source="tavo_import"}`
3. `position = index / total_count`（0.0=最早, 1.0=最新）
4. 逐条生成 embedding 并添加到 FAISS IndexFlatL2
5. 每 10 条保存一次进度到磁盘

**每轮 RAG 召回（时间加权）**：
```python
async def search(self, query: str, top_k: int = 5) -> List[str]:
    query_emb = await self._get_embedding(query)
    query_array = np.array([query_emb], dtype=np.float32)
    
    k = min(top_k * 2, len(self.documents))
    distances, indices = self.index.search(query_array, k)
    
    # 时间加权排序
    scored = []
    for i, idx in enumerate(indices[0]):
        semantic = 1.0 / (1.0 + distances[0][i])  # L2 → similarity
        position = self.metadatas[idx].get('position', 0.5)
        final_score = semantic * 0.6 + position * 0.4
        scored.append((final_score, self.documents[idx]))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for score, doc in scored[:top_k]]
```

**增量更新（每轮对话后）**：
1. 每 5 轮调用 Kimi 总结一次（AURA 自己的优化 prompt，带已有记忆上下文防重复）
2. 新记忆向量化后存入 FAISS，`position` 设为 1.0（最新）
3. 自动保存到磁盘（`faiss_index.bin` + `faiss_meta.json`）

**降级策略**：
- FAISS 不可用 → 回退到全量注入
- Embedding API 不可用 → 使用零向量（语义排序退化为时间排序）
- Kimi 未配置 → 跳过自动总结，不影响主流程

#### 晚上：MemoryManager 封装 + 接入转发流程

`app/memory/manager.py`：
```python
class MemoryManager:
    """统一记忆管理接口 — 使用 FAISS 做向量检索"""
    
    async def initialize(self):
        """初始化：创建 SQLite 表 + 加载 FAISS 索引"""
    
    async def import_from_tavo(self, memories: List[str]):
        """从 TAVO System Prompt 导入已有记忆到 FAISS"""
    
    async def search(self, query: str, top_k: int = 5) -> List[str]:
        """时间加权 RAG 召回"""
    
    async def add_memory(self, text: str, metadata: dict):
        """新增单条记忆到 FAISS"""
    
    async def summarize_and_store(self, session_id: str, recent_dialogues: List[dict]):
        """调用 Kimi 总结最近对话 → 提取新记忆 → 存入 FAISS"""
    
    async def get_recent_messages(self, session_id: str, n: int = 20) -> List[dict]:
        """从 SQLite 读取最近 N 轮对话"""
    
    async def save_dialogue(self, session_id: str, role: str, content: str, round_number: int):
        """保存单轮对话到 SQLite"""
    
    async def get_round_number(self, session_id: str) -> int:
        """获取当前会话的轮次编号（自动递增）"""
```

**接入 completions_simple.py 转发流程**：
```
TAVO 请求 → 拆解 System Prompt
  → 提取 TAVO 的长记忆列表
  → 对比 AURA 数据库，检测新增记忆
  → FAISS 时间加权召回 Top-5
  → 注入 [LONG_TERM_MEMORY] 区块（仅 Top-5，非全量）
  → 区块重组 → 转发 LLM
  → LLM 返回后，保存本轮对话到 SQLite
  → 每 5 轮调用 Kimi 总结一次（异步，不阻塞）
```

**🎯 验收标准**：
1. 首次启动：从 TAVO System Prompt 导入记忆到 FAISS ✅
2. RAG 召回：根据关键词召回 Top-3，结果中包含相关记忆 ✅
3. 时间加权：最新记忆的排序高于早期记忆 ✅
4. 增量更新：新对话产生后，Kimi 总结出新记忆并存入 FAISS ✅
5. 降级：FAISS/Embedding 不可用时，回退到全量注入 ✅
6. 持久化：服务重启后 FAISS 索引自动加载 ✅
7. Prompt 变化：`[LONG_TERM_MEMORY]` 从全量（~20,000 字符）→ Top-5（~300 字符）✅

---

### RAG 记忆压缩对 12 个痛点的影响分析 ✅

在实现 Day 2 的 RAG 记忆压缩（长记忆从 314 条全量 → Top-5 语义召回）后，对 12 个痛点的预期影响如下：

| # | 痛点 | RAG 影响 | 说明 |
|---|------|---------|------|
| 1 | **越权输出** | ✅ **显著缓解** | 长记忆从 20,000 字符压缩到 ~300 字符，Prompt 噪声大幅减少，LLM 混淆角色边界的概率降低。预期越权率下降 50-60% |
| 2 | **文风污染** | ❌ 无影响 | 文风污染是 LLM 训练数据问题，与记忆长度无关 |
| 3 | **输出结构模板化** | ❌ 无影响 | 输出结构是 LLM 生成策略问题，与记忆长度无关 |
| 4 | **状态回退** | ✅ **部分缓解** | RAG 召回相关记忆后，LLM 更容易记住当前状态。但状态回退的根本解决依赖 StateManager 的强制注入 |
| 5 | **RPG剧情回退** | ✅ **部分缓解** | PlotAnchor 强制注入 + RAG 召回主线事件，减少剧情丢失。但 PlotAnchor 的完整实现依赖 Day 4 |
| 6 | **内心独白泄露** | ⚠️ 间接缓解 | 记忆噪声减少后，LLM 对"用户心理活动"和"角色心理活动"的边界更清晰。但根本解决依赖 Week 3 的 visibility 三层隔离 |
| 7 | **跨角色记忆隔离** | ❌ 无影响 | 这是 Week 3 的专门任务，与记忆长度无关 |
| 8 | **冲突消解过快** | ⚠️ 间接缓解 | 精简后的 Prompt 让 LLM 更聚焦当前场景，减少"和稀泥"倾向。但根本解决依赖 Week 3 的 conflict_heat 机制 |
| 9 | **LLM维护官配** | ❌ 无影响 | 官配回归是 LLM 训练数据 bias，与记忆长度无关 |
| 10 | **关系称谓/身份漂移** | ✅ **部分缓解** | RAG 召回包含关系信息的记忆后，LLM 更可能记住正确称谓。但根本解决依赖 Week 3 的 identity_label 动态称谓 |
| 11 | **被动RAG默认行为** | ✅ **根本解决** | 这是 RAG 的直接目标——主动召回相关记忆替代 LLM 的默认生成 |
| 12 | **输出长度失控** | ⚠️ 间接缓解 | Prompt 精简后，LLM 的 token 预算分配更合理。但根本解决依赖 Week 2 的 ResponseLengthGuard |

**总结**：RAG 记忆压缩可以**解决/缓解 7 个痛点**（1, 4, 5, 6, 8, 10, 11），其中痛点 11 是根本解决，痛点 1 是显著缓解。剩余 5 个痛点（2, 3, 7, 9, 12）需要 Week 2-3 的专门质量控制层来处理。

---

### Day 3｜LangGraph 核心状态机

**目标**：13节点状态图跑通，支持循环回退，状态持久化，有可视化。

#### 上午：状态图设计
节点（执行顺序）：
1. **InputReceive** — 收输入，读Redis最近N轮
2. **EmotionAnalyze** — 情绪走向（mock）
3. **MemoryDecision** — 查记忆吗？（mock）
4. **MemoryRetrieve** — 检索：工作记忆+情节记忆+主线锚点（mock）
5. **StateManager** — 加载dynamic_state注入prompt（痛点4骨架）
6. **StyleInjection** — 结构随机化 + mes_example多样化，打破输出模板化（mock）
7. **ContextAssemble** — 组装：人设+动态状态+主线锚点+唤醒记忆+工作记忆+风格约束
8. **LLMGenerate** — 调用LLM（mock）
9. **FormatGuard** — 越权输出检测（痛点1骨架）
10. **OOCCheck** — 人设一致性（mock）
11. **ContentFilter** — 文风污染过滤（mock）
12. **OutputReturn** — 返回客户端
13. **MemoryExtract** — 提取事件+状态变更，更新记忆库（mock）

边（条件）：
- FormatGuard/OOCCheck/ContentFilter通过 → OutputReturn → MemoryExtract → 结束
- 任一不通过 → ContextAssemble（加约束标记）→ LLMGenerate（retry_count+1，最多2次）

#### 下午：LangGraph实现
1. `AgentState` TypedDict：`messages, character, session_id, memory_decision, retrieved_memories, dynamic_state, ooc_passed, format_passed, content_passed, retry_count`
2. `StateGraph`定义13节点和条件边
3. `checkpointer`：`MemorySaver`或`RedisSaver`
4. 编译：`app = workflow.compile()`

#### 晚上：接口打通 + 日志 + 可视化
1. FastAPI调用LangGraph，`thread_id=session_id`
2. structlog每节点打印：名称、耗时、状态摘要
3. mermaid状态图：`docs/state_diagram.md`

**🎯 验收标准**：
- curl发消息，日志显示完整链路：`InputReceive → ... → OutputReturn`
- 同session_id发第二条，状态延续（thread_id正确）
- `docs/state_diagram.md`有mermaid图

---

### Day 4｜记忆策略算法 + FormatGuard + StateManager真实化

**目标**：Agent开始"思考"；痛点1和痛点4的真实逻辑到位。

**前置说明 — "RAG First, FormatGuard Later" 策略**：

在实现 FormatGuard 之前，必须先完成 Day 2 的 RAG 记忆压缩。原因如下：

- 当前 Prompt 中长记忆占 ~20,000 字符（314 条），占整个 Prompt 的 66%
- 大量冗余记忆是 LLM 越权输出的**根本诱因**——记忆噪声导致模型混淆角色边界
- 如果 RAG 压缩到 Top-5（~300 字符），Prompt 从 30,511 → ~10,000 字符，越权问题可能自然缓解 50%+
- **执行顺序**：Day 2 RAG 压缩 → 观察效果 → Day 4 实现 FormatGuard 处理剩余问题

#### 上午：事件提取 + 重要性评分
1. **事件提取**（MemoryExtract真实化）：
   - 接入便宜LLM（Gemini Flash / DeepSeek / GLM）
   - Prompt提取：`{subject, action, object, emotion, importance_hint, state_changes}`
   - 示例："Ruby紧握Crescent Rose：我永远不会丢下Yang" → `state_changes:[]`，hint="极高"
2. **重要性评分**：
   - 规则：`vow/conflict/revelation`→0.9，`chat/action`→0.3
   - LLM hint映射：极高→0.95，高→0.8，中→0.5，低→0.2
   - `importance = 规则*0.5 + hint*0.5`
   - vow/revelation/main_quest → `plot_critical=True`（免疫衰减）

#### 下午：混合检索 + 唤醒决策 + PlotAnchor
1. **混合检索**：
   - Chroma语义检索Top-20
   - 重排序：`score = semantic*0.4 + importance*0.4 + time_decay*0.2`
   - `time_decay = exp(-λ*天数)`，`plot_critical`免疫
   - 返回Top-5
2. **唤醒决策**（MemoryDecision真实化）：
   - 输入：用户文本 + 情绪走向 + 敏感关系边（weight<0.3）
   - 规则引擎（快，不用LLM）：
     - 情感关键词（"背叛""相信""离开""危险"）→ 查情节层
     - 敏感关系边 → 查关系相关事件
     - 普通聊天 → 只查工作记忆
   - 输出：`{should_query, query_type, keywords}`
3. **PlotAnchor优先级**：
   - `get_plot_anchors`返回的事件**优先占用prompt token预算**
   - 即使语义检索没命中，主线锚点也强制注入

#### 晚上：质量控制（痛点1 FormatGuard + 痛点3 StyleInjection + 痛点4 StateManager）

**FormatGuard（痛点1-越权输出）— 待 RAG 完成后评估**：

FormatGuard 的优先级已调低。策略是 **"RAG First, FormatGuard Later"**：

1. **先做 Day 2 RAG 记忆压缩**：长记忆从 314 条全量（~20,000 字符）→ Top-5 语义召回（~300 字符），Prompt 从 30,511 精简到 ~10,000 字符
2. **观察效果**：如果 RAG 压缩后越权问题自然缓解（预期下降 50-60%），则 FormatGuard 可能不需要实现
3. **再评估**：如果仍有剩余越权问题，再根据实际表现设计针对性方案

> 详细的三层 FormatGuard 设计（正则 Layer 1 + 语义 Layer 2 + Agent Layer 3）已在讨论中完成方案设计，但暂不写入执行计划。等 RAG 落地后评估是否需要。

**StyleInjection真实化**（痛点3-输出结构模板化）：
- **结构随机化**：在 ContextAssemble 中随机选择输出结构指令注入 prompt
  ```python
  structures = [
      "先从角色的内心感受开始写，再写环境和动作",
      "先写对话，再通过对话带出环境和动作",
      "从某个细节道具/物品切入，展开场景",
      "以角色B的视角观察角色A，再切换到角色A",
      "倒叙：先写结果，再写原因和过程",
  ]
  selected = random.choice(structures)
  ```
- **mes_example 多样化**：存放结构不同的例句（对话开头/动作开头/心理开头/倒叙），而非固定几条"写得好"的
- **历史结构检测**：检测最近 N 轮输出是否都以相同模式开头（如环境描写），是则强制切换结构指令

**StateManager真实化**（痛点4-状态回退 + 痛点11-被动RAG默认行为）：
- MemoryExtract检测`state_changes`（如`{"Yang.status":"已生产"}`）
- 自动`update_dynamic_state`
- **ContextAssemble强制注入dynamic_state（最高优先级，不裁剪）—— 每轮必注，不是用户问了才查**
- **状态一致性校验（OOCCheck扩展）**：生成内容与dynamic_state矛盾 → 回退
  - 示例：state里A"怀孕不能战斗"，但回复让A去巡逻 → 触发回退

**🎯 验收标准**：
- 模拟：第1轮"Ruby发誓保护Yang"（save_event + plot_critical=True）
- 第5轮"Yang有危险了"
- 日志：MemoryDecision→查情节层→search_episodes返回第1轮→注入prompt
- FormatGuard：RAG 落地后评估越权率，如果已自然缓解则跳过实现
- StyleInjection测试：连续10轮输出，检查输出结构是否多样化（不以同一模式开头）
- StateManager测试：输入"Yang生了"，dynamic_state自动更新，下轮prompt含"已生产"

---

### Day 5｜LLM对接 + Tavo兼容 + 50轮测试 + Streamlit面板

**目标**：真刀真枪跑起来，50轮验证记忆连贯，能可视化观察Agent决策。

#### 上午：LLM对接
1. `app/config.py`：`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`
2. LLMGenerate节点接入LangChain `ChatOpenAI`（兼容任意OpenAI格式端点）
3. 先接便宜模型跑通（DeepSeek-V3 / GLM-4 / Gemini-1.5-Flash）
4. 支持SSE流式返回

#### 下午：50轮长对话测试 + Tavo兼容
1. RWBY角色卡启动session
2. 手工或脚本跑50+轮
3. **Tavo端到端测试**：
   - Tavo配置自定义API地址为AURA后端
   - 发送对话，验证返回正常
4. 关键测试点：
   - 第5轮：Ruby发誓保护Yang（plot_critical锚定）
   - 第25轮：提到Yang（信任度正常，不突兀唤醒）
   - 第45轮："如果Yang有危险"（Agent必须唤醒第5轮事件）
   - FormatGuard：偶尔不发user输入，观察模型是否越权

#### 晚上：Streamlit调试面板 + ARCHITECTURE.md初稿
1. `dashboard.py`：
   - 当前session唤醒记忆列表（时间、类型、重要性、来源）
   - dynamic_state当前值展示
   - plot_anchors列表
   - NetworkX关系图可视化
   - FormatGuard/OOC/Content检测日志表格
2. `ARCHITECTURE.md`初稿：
   - 项目背景（你的痛点故事）
   - 分层架构图
   - 13节点数据流
   - 关键算法（混合检索公式、唤醒决策规则、状态变更检测）

**🎯 验收标准**：
- `curl`或Tavo → AURA → 真实LLM → 返回，完整链路通
- 50轮后，第45轮Agent仍能唤醒第5轮事件（检查日志）
- Streamlit面板能看记忆唤醒过程
- `ARCHITECTURE.md`有初稿
- **GitHub commit**：`git commit -m "Week 1: skeleton + FormatGuard + StateManager"`

---

## 六、Week 2｜质量控制层完整实现（5.6-5.11）

**目标**：痛点1/2/4/5全部真实化，集成测试通过。

| 日期 | 任务 | 验收 |
|------|------|------|
| **5.6** | FormatGuard完整实现 | 10+种越权样本，拦截率>95%，触发回退重写 |
| **5.7** | ContentFilter + ResponseLengthGuard（痛点2+12） | 黑名单拦截；模型专属长度/节奏配置（DeepSeek/Gemini适配） |
| **5.8** | StateManager完善（痛点4） | 状态变更LLM提取准确率>80%；冲突检测工作；100轮不回退 |
| **5.9** | PlotAnchor完整实现（痛点5） | 主线事件强制注入；检索优先级正确；旧锚点降级逻辑 |
| **5.10-11** | 集成测试 | RWBY卡100轮测试；所有质量检测节点工作；metrics记录 |

**🎯 Week 2 总验收**：
- 跑100轮RWBY对话
- FormatGuard拦截率>95%
- ContentFilter拦截率>90%，误伤率<5%
- ResponseLengthGuard：DeepSeek输出不再"挤牙膏"，Gemini不再"抢戏"
- 状态变更检测准确率>80%
- PlotAnchor主线不丢失
- 记录拦截次数、回退次数、唤醒准确率

---

## 七、Week 3｜深度优化 + 进阶特性（5.12-5.18）

**目标**：从"能用"到"好用"，解决痛点3/6/7/8/9。

| 日期 | 任务 | 验收 |
|------|------|------|
| **5.12-13** | StyleInjection（痛点3-输出结构模板化） | 结构随机化 + mes_example多样化 + 历史结构检测，打破模型固定写作八股 |
| **5.14** | 多模型切换 | 配置支持多后端key；生成/提取分离；可选模型轮询 |
| **5.15-16** | 100轮调参 | 混合检索权重调优；唤醒阈值调优；token预算分配优化 |
| **5.17** | 关系图谱优化 | 不同relation_type不同更新速率；冲突不对称性 |
| **5.18** | 独白/隔离/冲突/官配/称谓（痛点6/7/8/9/10） | internal_thoughts表；visibility三层；conflict_heat；官配覆盖canonical；identity_label动态称谓 |

**🎯 Week 3 总验收**：
- 100轮测试，输出结构多样化（对比Week 1，不再每轮都是"环境→动作→心理→对话"的固定模板）
- 内心独白不被泄露（用户写心理活动，LLM不直接说出）
- 跨角色私密隔离（对A说的B不知道）
- 冲突张力维持（被驳斥方不直接认怂）
- 官配不强行回归（Pyrrha-User线稳定）

---

## 八、Week 4｜文档 + 演示 + 面试武器（5.19-5.25）

| 日期 | 任务 | 验收 |
|------|------|------|
| **5.19** | ARCHITECTURE.md定稿 | 完整架构文档，可直接贴简历附件 |
| **5.20** | README.md + GitHub整理 | 快速开始、架构图、GIF/截图、徽章 |
| **5.21-22** | CSDN技术文章 | 《从零构建Agentic角色扮演记忆引擎》或类似；文末附GitHub |
| **5.23** | 面试话术准备 | 5分钟介绍、15分钟深挖、抗压问题答案 |
| **5.24** | 简历更新 | 项目名+GitHub链接+CSDN文章链接 |
| **5.25** | 演示视频录制 | 3分钟：Tavo接入→对话→Streamlit面板展示记忆唤醒 |

**🎯 Week 4 总验收**：
- ARCHITECTURE.md完整可读
- CSDN文章发布
- 简历已更新
- 3分钟演示视频录制完成
- GitHub仓库public，README完善

---

## 九、缓冲周（5.26-5.31）

- 根据简历投递反馈微调话术
- 修bug（长对话中发现的edge case）
- 性能最后调优
- 模拟面试（我可以帮你练）

---

## 十、依赖

```txt
# 核心框架
fastapi==0.115.0
uvicorn[standard]==0.32.0
pydantic==2.9.0
python-multipart==0.0.12

# AI / Agent
langgraph==0.2.0
langchain==0.3.0
langchain-openai==0.2.0

# 数据层
sqlalchemy[asyncio]==2.0.35
asyncpg==0.30.0
redis==5.1.0
chromadb==0.5.0
networkx==3.4.0

# 工具
pillow==11.0.0
httpx==0.27.0
structlog==24.4.0

# 调试面板
streamlit==1.40.0

# 开发
pytest==8.3.0
pytest-asyncio==0.24.0
```

---

## 十一、每晚汇报模板

```
Day X 汇报：
1. 今天完成了哪个/哪些验收标准？
2. 卡在哪？（报错信息 / 逻辑瓶颈 / 不确定怎么实现）
3. 明天是否调整任务优先级？
4. 代码是否commit到GitHub？
```

---

**宋，30天计划已定，9个痛点有归宿，验收标准全部量化。**

现在开始 Day 1。 ❤️‍🔥

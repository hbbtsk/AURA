# AURA 面试宝典（精简版）

> v0.8.3+ | A4 打印友好 | 面试前 30 分钟速览

---

## 一、1 分钟自我介绍

> AURA 是**角色扮演专用的 Prompt 编译器 + 模型行为校正引擎**，部署在 TAVO（前端 RP 平台）与 LLM 之间，解决重度 RP 用户长对话中的 15 个系统性痛点，已解决/缓解 9 个。
>
> 技术栈：FastAPI + LangGraph + FAISS + SQLite + 本地 bge-small-zh-v1.5。
>
> 长期演进为「主机 + 卡带」模式的文字冒险平台。

**一句话：** FastAPI + LangGraph 构建的 LLM 中间层，解决 RP 场景的 Prompt 工程、记忆管理和行为校正问题。

---

## 二、技术栈 & 架构

| 层级 | 选型 | 一句话原因 |
|------|------|-----------|
| API | FastAPI + Pydantic | 原生异步、类型安全 |
| 编排 | LangGraph StateGraph | 状态机可视化、条件边重试、零侵入业务代码 |
| HTTP | httpx | 异步、精细超时控制 |
| 向量 | FAISS IndexFlatL2 | 本地零依赖、内存索引 <10ms |
| Embedding | bge-small-zh-v1.5 | 中文优秀、512维、CPU可跑 |
| 存储 | SQLite | 零配置、单用户够用 |
| 配置 | pydantic-settings | 类型安全、场景隔离（main/summary/intent） |

**数据流：** TAVO → AURA(拆解→意图→记忆→重组) → LLM → AURA(收集→保存) → TAVO(SSE模拟)

**LangGraph 14 节点：** 输入接收 → Prompt拆解 → 并行{实体抽取|情绪分析|记忆检索|状态管理|文风注入|模型方言编译} → 汇入Prompt编译 → LLM生成 → 并行质检 → {通过→输出返回→记忆固化 | 失败→重试策略→回退Prompt编译}。最大重试2次。

---

## 三、15 个痛点（已解决 9 个）

| # | 痛点 | 状态 | 模块 |
|---|------|------|------|
| 1 | **越权输出** — 模型替user写台词/行动 | ✅显著缓解 | CONSTRAINTS + 越权禁令 |
| 2 | **文风污染** — 垃圾小说训练痕迹（臀腿腰胸） | 📅待实现 | 文风注入节点 |
| 3 | **文风固化** — 长时间同一模型锁死 | 📅待实现 | 多模型切换 + few-shot随机 |
| 4 | **状态回退** — 怀孕→生完→又怀孕 | ✅部分缓解 | 状态管理 + dynamic_state |
| 5 | **RPG剧情回退** — 主线被带回过去 | ✅部分缓解 | 时间加权RAG + insert_seq |
| 6 | **内心独白泄露** — LLM像有读心术 | 📅待实现 | OOCCheck |
| 7 | **跨角色记忆隔离** — 私密话共享 | 📅待实现 | 会话隔离 + 关系图谱 |
| 8 | **多角色状态缺失** — party/NPC状态变化全丢 | ✅部分缓解 | dynamic_state + 状态管理 |
| 9 | **重复记忆/冗余** — 同一批NPC信息反复记录 | ✅**根本解决** | FAISS去重 + 结构化字段 |
| 10 | **长记忆无RAG** — 全量注入，token浪费+注意力稀释 | ✅**根本解决** | FAISS语义召回Top-5 |
| 11 | **模型输出太少** — DeepSeek输出过短 | 📅待实现 | FormatGuard + 长度控制 |
| 12 | **模型输出太多** — Gemini输出过长 | 📅待实现 | FormatGuard + 长度限制 |
| 13 | **系统提示词锁不住** — LLM偏离人设 | 📅待实现 | 模型方言编译 |
| 14 | **时间维度缺失** — 已完成事件重复生成 | ✅部分缓解 | insert_seq动态归一化 |
| 15 | **用户输入意图隐含** — LLM默认接话而非渲染反应 | ✅**显著缓解** | IntentTagger + USER_INTENT_TAG |

**面试话术（被问"解决了什么问题"）：**
> 聚焦RP场景，识别15个系统性痛点，已解决9个。三个根本解决：长记忆RAG替代全量注入(#10)、FAISS去重(#9)、意图解析让LLM从"接话"变"渲染反应"(#15)。两个显著缓解：越权输出(#1)、意图隐含(#15)。

---

## 四、核心模块速答

### 4.1 Prompt拆解 — 三层递进
1. `=====`标记优先（角色卡开始/结束等）
2. HTML注释回退
3. 格式硬拆解（正则匹配Name is... / 中文回退）

**产物7组件：** 越权禁令、长记忆、记忆规则、用户设定、角色卡、世界书、XML角色卡。

**没标记怎么办？** 降级到格式硬拆解 + 最终回退（从user_profile结束到world_book之间提取）。日志提示用户添加标记。

### 4.2 IntentTagger — 双字段输出
- **为什么单独做？** 痛点#15：用户输入是动作（`*推门而入*`），LLM默认"接话"而非"渲染反应"。IntentTagger生成**导演指令**注入主LLM，告诉它"用户在做动作，请渲染环境和其他角色反应"。
- **structure**（6维）→ RAG逐字段匹配（不传给主LLM）
- **implicit_instruction**（导演指令）→ 注入[USER_INTENT_TAG]给主LLM
- **模型：** 优先Kimi(intent场景)、回退DeepSeek

**6维结构化字段：** scene_type(0.20) | action_type(0.25) | emotional_tone(0.20) | tension_description(0.10) | **entities(Jaccard 0.15)** | pacing(0.10)。entities用Jaccard不用embedding（专有名词embedding不稳定）。

### 4.3 三层记忆
| 层级 | 内容 | 位置 | 原理 |
|------|------|------|------|
| WORKING | 最近5轮对话原文 | 追加到最后一条user消息末尾 | **近因效应** |
| RECENT | 最近10条记忆摘要 | System Prompt区块 | FAISS最近插入 |
| LONG_TERM | RAG召回Top-5 | System Prompt区块 | 意图感知结构化检索 |

**为什么分三层？** 痛点#10：全量注入→token浪费+注意力稀释。WORKING给即时语境，RECENT给近期脉络，LONG_TERM精准打击。

**记忆总结：** 每5轮触发Kimi总结→提取结构化字段→存入FAISS。异步不阻塞。

### 4.4 意图感知RAG v2 — 三阶段检索
1. **粗排：** expanded_scene embedding → FAISS搜索Top-K×3
2. **精排：** 逐字段结构化匹配（文本字段embedding cosine，entities用Jaccard）
3. **复合评分：** semantic×0.3 + structure×0.5 + time×0.2 → Top-K

**时间加权：** `time_score = ((seq-min_seq)/seq_range)^gamma`。解决痛点#14（已完成事件重复生成）。

### 4.5 Prompt编译 — 9区块 + 近因效应
**9区块（按认知心理学排列）：** MAIN_PROMPT → PROTOCOL → CONSTRAINTS → CHARACTER_CARD → USER_PROFILE → CURRENT_STATE → RECENT_MEMORY → LONG_TERM_MEMORY → WORLD_CONTEXT → **OUTPUT_SPEC（放最后，注意力最强）**

**近因效应：** 最后一条user消息末尾追加`[系统约束]`+`[WORKING_MEMORY]`+`[USER_INTENT_TAG]`。LLM生成前最后看到的是当前语境+导演指令。

### 4.6 SSE流式 — 先收集再模拟
**为什么？** ①流式不可撤回（已发送无法收回）②质检需在返回前介入 ③RP用户对质量敏感、延迟可接受。

**关键修复：** `\n\n`段落分隔符必须追加到段落内容末尾一起发送，不能作为独立segment。

### 4.7 多LLM后端 — 场景隔离
| 场景 | temp | max_tokens | timeout | 用途 |
|------|------|-----------|---------|------|
| main | 0.7 | 4096 | 60s | 主对话(DeepSeek) |
| summary | 0.3 | 2048 | 30s | 记忆总结(Kimi) |
| intent | 0.3 | 1024 | 15s | 意图分析(Kimi优先) |

**降级：** API Key未配置→返回None→调用方fallback（如IntentTagger不可用→fallback）。

### 4.8 LangGraph — 为什么引入？
可视化 + 可扩展性 + 重试机制。**零侵入：** 业务代码完全不知道LangGraph存在，节点只是薄包装器。

**并行：** Prompt拆解分叉6个节点（无依赖），LangGraph自动并行，完成后汇入Prompt编译。

---

## 五、设计决策（一句话版）

| 决策 | 选择 | 原因 |
|------|------|------|
| FAISS vs Pinecone | FAISS | 本地零依赖、单用户够用 |
| SQLite vs PG | SQLite | 零配置、无并发压力 |
| 本地embedding vs API | bge-small-zh-v1.5 | 中文优秀、无费用、懒加载 |
| 非流式vs实时流式 | 非流式+模拟 | RP质量优先、延迟可接受 |

---

## 六、5个挑战 & 解决

1. **Kimi超时：** System Prompt 1200→451字符，intent timeout 60s→15s，支持回退DeepSeek
2. **SSE段落丢失：** `\n\n`追加到段落末尾发送，不作为独立segment
3. **角色卡为空：** 引入`=====`标记 + 最终回退提取 + 日志引导用户
4. **AgentState序列化失败：** dataclass→TypedDict(total=False)
5. **意图JSON格式不稳：** 正则匹配代码块→json.loads→fallback，不影响主流程

---

## 七、开放性问题（回答要点）

**Q1: 用户量1→1000怎么扩展？** Uvicorn多worker+Nginx | SQLite→PostgreSQL | FAISS→Milvus | 本地embedding→微服务 | MemorySaver→Redis | LLM限流

**Q2: LLM后端3→10个怎么改？** 动态配置模式：后端列表从配置文件读取，注册表管理，get_llm_config()从注册表查找

**Q3: 怎么评估效果？** 主观：角色一致性评分、越权频率；客观：RAG召回相关性、延迟P50/P95；A/B：TAVO→LLM vs TAVO→AURA→LLM盲测

**Q4: 文风固化(#3)怎么解决？** ①文风注入节点 ②多模型轮换 ③文风指纹库检测趋同 ④**多风格few-shot随机切换**（预置不同风格示例，利用LLM模仿能力隐性引导） ⑤用户自定义文风

**Q5: 与MemGPT的区别？** MemGPT通用，AURA为RP深度定制：意图感知RAG（6维结构化）、显式IntentTagger、9区块Prompt重组、近因效应策略

**Q6: 0.8→1.0演进关系？** 1.0不是空中楼阁，是0.8验证能力的架构化升级：
- PromptDecomposer → 卡带Schema
- IntentTagger 6维 → Habitus惯习模型
- 三层记忆 → CausalRAG+主观史观
- 9区块 → U型Prompt
- FormatGuard → 一致性校验引擎
- LangGraph状态机 → 导演+演员架构

**Q7: Habitus是什么？** 普通角色卡=静态描述（"她很活泼"），LLM自行推断易OOC。Habitus=条件-行为映射（condition="companion=Ruby,emotion=angry"→behavior="嘴嫌行动不丢"），直接注入行为指令。

**Q8: 导演+演员vs单LLM？** 单LLM同时扮演旁白+所有NPC→风格趋同、边界模糊。导演=上帝视角（场域渲染、规则判定、NPC调度、旁白推进）。演员=角色视角（独立LLM调用，只含该角色Identity+Habitus+State）。优势：NPC不趋同、旁白分离、Director控制谁反应谁沉默。

**Q9: 反八股怎么做？** 减法不是加法：①给氛围(mood/pacing)不给模板 ②Prompt常驻反八股指令 ③FormatGuard只硬拦截OOC/瞬移，不拦截不完整句子/纯动作/零台词沉默 ④多风格few-shot随机切换

**Q10: 卡带（Cartridge）是什么？创作者怎么写？**

卡带是世界内容的封装包，标准文件结构：

```
example_world.aura/
├── meta.yaml      # 标题、作者、版本
├── world.yaml     # 世界规则 + 全局状态 + 初始时间
├── entities/      # 角色卡（Identity + Habitus + State）
├── locations/     # 地点卡（坐标 + 连通关系）
├── events/        # 种子事件（剧情导火索）
└── assets/        # 可选资源
```

**卡带即数据库**（运行时反序列化为Pydantic模型）、**卡带即存档**（退出时状态差分写回save/）、**卡带即商品**（创作者上传市场，玩家下载插卡即玩）。

**创作者只需要写YAML定义Entity和WorldRule，主机自动处理：** Entity在场即激活（不需要关键词匹配），Habitus驱动行为涌现，EventPatch记录状态差分。

**Q11: EventPatch是什么？和普通日志有什么区别？**

普通日志 = "某时某地发生了某事"（文本记录）。EventPatch = **状态差分补丁 + 因果连接 + 情感冲击**：

| 维度 | 普通日志 | EventPatch |
|------|----------|------------|
| 状态变更 | 无 | StateChange（entity_id/attribute/old→new） |
| 因果链 | 无 | caused_by[] / causes[] / activates[] / closes[] |
| 情感冲击 | 无 | EmotionalImpact（narrative_delta + 关系更新） |
| 可见性 | 全员可见 | public_to[] / secret_to[] / hidden_from[] |
| 语言依赖 | 有（文本块） | 无（event_id是无语言的） |

**举例：** 玩家帮Weiss打赢一场战斗。
- 普通日志："Weiss和玩家一起打败了Grimm"
- EventPatch：①StateChange(Weiss.emotion→elated) ②StateChange(Weiss.relationship.player→信任增加) ③EmotionalImpact(Weiss→"第一次感受到被保护的安心") ④causes→激活后续事件"Weiss邀请玩家参加家族晚宴"

**Q12: 商业模式是什么？怎么冷启动？**

| 维度 | 策略 |
|------|------|
| 收入 | 主机Pro版收费（编辑器、云同步、多人协作） |
| 成本 | 用户自带API KEY，平台不承担模型调用成本 |
| 内容 | 官方Demo免费（技术展示），UGC市场创作者定价，平台抽成15%-30% |
| 冷启动 | Phase0封闭测试(10-20人)→Phase1创作者内测(30-50人)→Phase2小范围公测(100-500人) |

**Q13: 三元组闭环是什么？**

叙事宇宙的底层由三个元定义构成闭环：

```
人(Entity) —— 以Habitus在客观场域中驱动行为
    ↓
事件(Event) —— 以状态差分反作用于人与世界，推动因果链
    ↓
世界(World) —— 以物理规则与空间结构提供新的客观条件
    ↓
回到人 —— 记忆更新、情绪变迁、关系演变
```

**核心：** 事件不是编剧硬写的，是 `Habitus × Field + Perturbation` 涌现的结果。规则层（世界编辑器）100%确定，生成层（LLM）在规则内概率生成。

---

## 八、代码速查

### 8.1 关键文件

| 文件 | 行数 | 核心 |
|------|------|------|
| app/main.py | ~80 | FastAPI入口 |
| app/core/config.py | ~180 | 场景隔离配置 |
| app/core/prompt_decomposer.py | ~550 | Prompt三层拆解 |
| app/core/intent_tagger.py | ~200 | 意图解析+6维structure |
| app/graph/workflow.py | ~150 | LangGraph 14节点编排 |
| app/graph/nodes/context_assemble.py | ~320 | 9区块Prompt编译 |
| app/memory/faiss_store.py | ~300 | 意图感知RAG三阶段检索 |
| app/api/streaming.py | ~460 | SSE段落切分模拟流式 |

### 8.2 关键常量

```python
memory_summary_interval = 5      # 每5轮触发Kimi总结
confidence >= 0.6                # 意图置信度阈值
SEARCH_WEIGHTS = {"semantic":0.3, "structure":0.5, "time":0.2}
max_retries = 2                  # 质检失败最大重试
OUTPUT_SPEC: 400-600字           # 输出长度约束
```

### 8.3 降级路径（口述即可）
Prompt拆解失败→原始透传 | IntentTagger不可用→fallback | FAISS为空→透传TAVO原始记忆 | Kimi不可用→回退DeepSeek | LLM超时→HTTP 504 | 保存失败→日志警告不阻断

---

## 九、演进时间线

| 版本 | 核心交付 | 面试重点 |
|------|----------|----------|
| v0.7.0 | 三层记忆+IntentTagger+意图感知RAG | **重点** |
| **v0.8.0** | **LangGraph 14节点+零侵入编排** | **重点** |
| v0.8.1-3 | 日志提取、模块重组、大文件拆分 | 工程化能力 |
| v0.9.0 | 图结构真实化+多后端型号切换 | 最新版本 |
| **v1.0(规划)** | 主机+卡带、导演+演员、Habitus、因果引擎 | 架构演进方向 |

---

## 十、面试前速览清单

- [ ] 1分钟自我介绍（含15个痛点+9个已解决+演进方向）
- [ ] 数据流四阶段图（TAVO→AURA→LLM→AURA→TAVO）
- [ ] LangGraph节点链路（14节点+并行6+条件边重试）
- [ ] 三层记忆原理（WORKING近因效应/RECENT/LONG_TERM RAG）
- [ ] 意图感知RAG三阶段（粗排→精排→复合评分）
- [ ] 9区块排列逻辑（OUTPUT_SPEC放最后+近因效应追加user消息）
- [ ] IntentTagger双字段（structure→RAG / implicit_instruction→导演指令）
- [ ] 6维structure字段+权重（action_type 0.25最高，entities用Jaccard）
- [ ] 5个挑战中的至少2个
- [ ] 开放性问题：扩展/评估/MemGPT对比/0.8→1.0映射/Habitus/导演+演员/反八股/卡带/EventPatch/商业模式/三元组

---

*精简版约10页A4，祝面试顺利。*

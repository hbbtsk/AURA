# AURA 1.0 架构总纲

> AURA 项目进化方向 — 从 Prompt 编译器到文字冒险平台

---

## 一、项目定位

**AURA 是一个基于 LLM 的文字冒险平台。**

它不是聊天机器人，不是传统 Galgame，而是一个**"可居住的文字世界"**——玩家进入这个世界，与由 AI 扮演的 NPC 互动，推动剧情，而世界本身会根据物理定律和角色性格持续运转。

核心形态：**主机（Runtime）+ 卡带（Cartridge）**。
- 主机是半开源的叙事引擎
- 卡带是创作者制作的世界/角色/剧本数据包
- 玩家自带 API KEY，平台不承担模型调用成本

---

## 二、核心哲学

### 2.1 三元组闭环

叙事宇宙的底层由三个元定义构成闭环：

```
人（Entity）—— 以 Habitus（惯习）在客观场域中驱动行为
    ↓
事件（Event）—— 以状态差分反作用于人与世界，推动因果链
    ↓
世界（World）—— 以物理规则与空间结构提供新的客观条件
    ↓
回到人 —— 记忆更新、情绪变迁、关系演变
```

### 2.2 关键原则

- **文字为根**：叙事逻辑的唯一载体。图像/音乐是表现层增强，在文字层 100% 稳定前不做。
- **顺理成章**：事件不是编剧硬写的，是 `Habitus × Field + Perturbation` 涌现的结果。
- **主观史观**：同一客观事件，不同角色拥有不同的记忆切片和解读滤镜。
- **情感叙事化**：情绪与关系不做数字量化，用自然语言叙事与历史事件链表达。
- **确定性优先**：规则层（世界编辑器）必须 100% 确定，生成层（LLM）在规则内概率生成。
- **反八股**：一致性保边界（不 OOC、不瞬移），不保轨道（不规定句式结构）。

---

## 三、系统架构：主机 + 卡带

### 3.1 主机（AURA Runtime）

主机是通用叙事操作系统，与内容无关，提供：

- **世界运转**：维护场域、全局时钟、状态缓存
- **因果计算**：EventEngine、CausalRAG、PerturbationEngine
- **一致性校验**：FormatGuard 确保卡带不违反物理定律
- **LLM 路由**：接入玩家自带 API KEY，流式返回
- **插卡管理**：加载/卸载/校验卡带，初始化世界状态

**主机不内置任何角色或剧情。** 空机状态下，它是一个等待卡带的规则引擎。

### 3.2 卡带（.aura Cartridge）

卡带是世界内容的封装包，标准结构：

```
example_world.aura/
├── meta.yaml              # 卡带元信息（标题、作者、版本、依赖）
├── world.yaml             # 世界规则 + 全局状态 + 初始时间
├── entities/              # 角色卡（NPC/PC 定义）
├── locations/             # 地点卡（空间坐标 + 连通关系）
├── events/                # 种子事件（剧情导火索）
└── assets/                # 可选资源（立绘索引、音频索引）
```

**卡带即数据库**：运行时反序列化为 Pydantic 模型，写入内存与图数据库。
**卡带即存档**：玩家退出时，世界状态差分写回 `save/` 子目录。
**卡带即商品**：创作者打包上传市场，玩家下载后插卡即玩。

### 3.3 插卡机制

1. **校验**：Schema 合法性、依赖满足、版本兼容、冲突检测
2. **加载**：YAML 转为 Pydantic 模型，写入运行时
3. **初始化**：种子事件入库，标记为 `open_loops`，全局状态复位
4. **运行**：Director 接管，开始调度 NPC Agent

---

## 四、运行时架构：导演 + 演员

AURA 不是"一个 LLM 扮演所有人"，而是**"一个导演（Director）调度多个演员（NPC Agent）同台演出"**。

### 4.1 导演（Director / GM Agent）

| 维度 | 职责 |
|------|------|
| **视角** | 上帝视角，知道客观事实 |
| **场域渲染** | 每轮生成环境描写、天气、背景音提示 |
| **规则判定** | 行动是否违反 WorldRule？是否触发状态变更？ |
| **NPC 调度** | 决定本轮哪些 NPC 应该反应、哪些保持沉默 |
| **旁白推进** | 在对话间插入客观叙事，推动因果链 |
| **结果广播** | 将事件结果广播给 NPC，但严格按记忆权限过滤 |

### 4.2 演员（NPC Agent）

| 维度 | 特性 |
|------|------|
| **视角** | 角色视角，只知道 `memory.known_events` 里的东西 |
| **存在形态** | 多实例，按需 new / 激活 / 休眠 / 销毁 |
| **LLM 调用** | 独立 System Prompt（仅包含该角色的 Identity + Habitus + State） |
| **状态权限** | 只读写自己的 Entity.state，不可访问其他角色记忆 |

### 4.3 单轮运转流程

```
玩家输入
    ↓
Director 更新 WorldField，检查规则
    ↓
Director 调度 NPC Agent（谁在场、谁该反应）
    ↓
Director 向各 Agent 广播（按记忆权限过滤后的场域切片）
    ↓
各 NPC Agent 独立调用 LLM，生成行动
    ↓
Director 仲裁（校验冲突、排序输出、插入旁白）
    ↓
原子性提交 EventPatch（更新世界状态）
    ↓
流式返回给玩家
```

### 4.4 动态 NPC 创建

跑团过程中，Director 可基于卡带模板动态实例化新 NPC：

- 玩家走进酒馆 → Director 从卡带加载 `generic_bartender` 模板 → new 一个酒保实例 → 赋予唯一 ID、初始位置、与玩家的关系种子 → 注册到世界 → 创建 Agent 实例

---

## 五、元模型定义（Meta-Model）

### 5.1 人（Entity）

三层结构：

| 层级 | 名称 | 说明 |
|------|------|------|
| **存在层** | Identity | DNA，不变。`entity_id`, `name`, `race`, `core_motivation`, `speech_fingerprint` |
| **实践层** | Habitus | 惯习。`Tendency[]`（条件-行为映射） |
| **涌现层** | State | 临时状态。`location_id`, `emotion`, `relationships`, `memory` |

#### Identity

```python
class Identity(BaseModel):
    entity_id: str
    name: str
    race: str = "human"
    age: int
    core_motivation: str        # 一句话灵魂锚点，直接进 System Prompt
    speech_fingerprint: str     # 口头禅、句式习惯、修辞特征
```

#### Habitus

```python
class Tendency(BaseModel):
    condition_type: Literal["location", "companion", "emotion", "event_type", "time", "object"]
    condition_value: str
    behavior: str               # 行为描述
    salience: Literal["core", "strong", "moderate", "weak", "situational"]
    can_override_motivation: bool = False

class Habitus(BaseModel):
    tendencies: List[Tendency] = []
    default_behavior: str
    stress_response: str
```

#### EmotionalState（叙事化，非量化）

```python
class EmotionalState(BaseModel):
    current_label: Literal["calm", "anxious", "angry", "grieving", "elated", "conflicted", "numb", "desperate"]
    narrative: str              # 自然语言内心戏，直接进 Prompt
    anchored_by: List[str]      # 塑造此情绪的关键事件 ID
    formed_at: int
    last_updated: int
```

#### Relationship（叙事化，非量化）

```python
class Relationship(BaseModel):
    target_id: str
    relation_type: Literal["trust", "hostility", "love", "debt", "fear", "obligation", "rivalry", "kinship", "unknown"]
    history: List[str]          # 关键事件链
    current_narrative: str      # 当前关系状态的叙事描述
```

#### Memory

```python
class Memory(BaseModel):
    known_events: List[str] = []     # 知道的事实 ID
    known_secrets: List[str] = []    # 知道的秘密 ID
```

#### Entity 组装

```python
class Entity(BaseModel):
    identity: Identity
    habitus: Habitus
    location_id: str
    emotion: EmotionalState
    relationships: Dict[str, Relationship] = {}
    memory: Memory = Memory()
    aliases: Dict[str, List[str]] = {}
    # 多语言别名映射，跨语言指代消解的基础
    # 示例：{"en": ["Weiss", "Ice Queen"], "zh": ["魏丝", "小白"]}
```

### 5.2 事件（Event）

事件不是日志，而是**世界状态差分补丁 + 因果连接 + 情感冲击**。

```python
class StateChange(BaseModel):
    entity_id: str
    attribute: str              # 支持点路径，如 "emotion.current_label"
    old_value: Optional[str]
    new_value: str
    reason: str

class EmotionalImpact(BaseModel):
    entity_id: str
    narrative_delta: str      # 情感变化的叙事描述
    adds_to_history: List[str]
    updates_relationship_narrative: Dict[str, str]

class EventPatch(BaseModel):
    event_id: str
    timestamp: int
    location_id: str
    participants: List[str]   # 客观在场

    state_diffs: List[StateChange] = []
    emotional_impacts: List[EmotionalImpact] = []
    narrative_text: str         # 给 LLM 看的自然语言

    caused_by: List[str] = []   # 父事件
    causes: List[str] = []     # 子事件
    activates: List[str] = []    # 激活伏笔
    closes: List[str] = []     # 闭合未决

    public_to: List[str] = []
    secret_to: List[str] = []
    hidden_from: List[str] = []

    causal_weight: float = Field(ge=0.0, le=1.0, default=0.5)  # 因果重要性排序，非情感量化
    is_key_foreshadowing: bool = False
    is_closed: bool = False
```

### 5.3 世界（World）

```python
class Location(BaseModel):
    location_id: str
    name: str
    coordinates: tuple[float, float, float]
    connected_to: Dict[str, float] = {}   # 相邻地点: 通行时间
    properties: List[str] = []
    current_entities: List[str] = []       # 当前在场角色（客观）

class WorldRule(BaseModel):
    rule_id: str
    description: str          # 如 "信标学院禁止 Grimm 进入"
    scope: List[str] = []
    exception_events: List[str] = []

class WorldField(BaseModel):
    location_id: str
    time: int
    present_entities: List[str]
    ambient: List[str] = []
    active_rules: List[str] = []

class World(BaseModel):
    world_id: str
    name: str
    locations: Dict[str, Location] = {}
    entities: Dict[str, Entity] = {}
    events: Dict[str, EventPatch] = {}
    rules: List[WorldRule] = []
    global_state: Dict[str, Any] = {}
    current_time: int = 0
    open_loops: List[str] = []
```

### 5.4 跨语言与国际化

AURA 1.0 是全球化的文字冒险平台，必须解决玩家语言与卡带语言不一致的问题。核心思路：**状态驱动消灭关键词匹配，Alias 系统消解语言壁垒。**

#### 核心认知：不存在"世界书关键词激活"

传统 ST/TAVO 的痛点来源于它的机制：

```
用户输入包含"Ruby" → 匹配关键词 → 注入 Ruby 的设定文本
```

这套机制必须做字符串匹配，所以中英文必然打架。

AURA 1.0 的机制是**状态驱动**：

```
Ruby 在场（WorldField.present_entities 包含 "ruby_rose"）→
自动加载 Ruby 的 Identity + Habitus 进 Prompt →
不需要任何关键词匹配
```

**在 AURA 1.0 里，Entity 在场即激活，不在场即静默。** 创作者不需要写"触发关键词"，只需要定义 Entity。主机自动处理。

#### 多语言别名系统（Alias System）

玩家用中文说"魏丝"，系统需要知道是 Weiss。这在 Entity 元模型中通过 `aliases` 字段解决：

```python
class Entity(BaseModel):
    # ... identity, habitus, emotion, relationships, memory ...
    aliases: Dict[str, List[str]] = {}
    # 示例：
    # {
    #   "en": ["Weiss", "Weiss Schnee", "Ice Queen", "Snow Angel"],
    #   "zh": ["魏丝", "小白", "雪倪", "冰女王"],
    #   "ja": ["ワイス", "ワイス・シュニー"]
    # }
```

**识别流程（Director 层）：**

```python
class Director:
    def resolve_mention(self, player_input: str, field: WorldField) -> Optional[str]:
        # 1. 优先匹配在场角色的别名（减少误匹配）
        for entity_id in field.present_entities:
            entity = self.world.entities[entity_id]
            for lang, names in entity.aliases.items():
                if any(name.lower() in player_input.lower() for name in names):
                    return entity_id
        # 2. 兜底：跨语言 Embedding 语义匹配
        return self.semantic_resolve(player_input)
```

这不是"关键词注入设定"，而是**指代消解**（Coreference Resolution）——把玩家的自然语言指称，映射到世界内的唯一实体 ID。

#### RAG 层的跨语言免疫

CausalRAG 走**图遍历**，不是关键词匹配：

```
玩家输入："魏丝最近怎么了？"
    ↓
语义解析：提到"魏丝" → resolve 到 "weiss_schnee"
    ↓
图数据库查询：Weiss 的 known_events + 未闭合因果链
    ↓
召回的是事件节点（event_id），不是文本块
    ↓
把事件节点的 narrative_text 塞进 Prompt
```

**图节点（event_id）是无语言的。** `evt_003_save_life` 不会因为玩家说中文就变成 `evt_003_救命`。

只有最后一公里的 `narrative_text` 有语言问题，而 LLM 可以自然处理——把英文的 `narrative_text` 丢给中文 LLM，它自然能翻译成中文输出。

#### 卡带内容的语言策略

卡带需要支持**多语言内容预置**，而不是运行时翻译：

```yaml
# weiss_schnee.yaml 示例
entity_id: weiss_schnee
identity:
  name:
    en: "Weiss Schnee"
    zh: "魏丝·雪倪"
    ja: "ワイス・シュニー"
  core_motivation:
    en: "Restore the Schnee family honor without becoming my father."
    zh: "重振雪倪家族荣誉，但不成为父亲那样的人。"

habitus:
  # 行为逻辑与语言无关

speech_fingerprint:
  en: "Formal, uses proper grammar, occasional aristocratic slang."
  zh: "正式，语法严谨，偶尔使用贵族式措辞，冷傲但内心柔软。"
```

**运行时策略：**
- 主机检测玩家使用的 LLM 语言（或玩家手动设置）
- 加载对应语言的 `name`、`core_motivation`、`speech_fingerprint`
- 如果某语言缺失，fallback 到英文，由 LLM 实时翻译（兜底）

#### 最小可行方案（MVP）

| 层级 | 做法 |
|------|------|
| Entity | 加 `aliases` 字段，至少支持 `en` 和 `zh` 两组别名 |
| Director | 加 `resolve_mention` 层：优先别名匹配，失败再走语义 |
| Embedding | 兜底用跨语言模型（如 `BAAI/bge-m3`）做语义召回 |
| 卡带规范 | 鼓励创作者在 `identity` 里写多语言 `name` 和 `core_motivation` |

> **TAVO 用全量输入解决匹配问题，是"用蛮力掩盖架构缺陷"。AURA 1.0 的解法是"用状态驱动消灭匹配问题"——Entity 在场即激活，不需要关键词；Alias 系统消解中英文指代；CausalRAG 的图结构天然跨语言。匹配问题在 AURA 里，本来就不该存在。**

---

## 六、关键引擎

### 6.1 EventEngine（事件涌现引擎）

```
EventDraft = Entity.Habitus x WorldField + Perturbation
```

1. 匹配 Habitus（筛选符合场域条件的倾向）
2. 情绪加权（基于 `emotion.narrative` 语义）
3. 关系修正（基于 `relationship.current_narrative`）
4. 世界硬规则过滤
5. 戏剧性扰动（释放因果势能，非随机注入）

### 6.2 CausalRAG（因果检索引擎）

替代传统向量相似检索：

```
用户 Query
    ├─ 1. 状态缓存：查角色当前状态与已知事件
    ├─ 2. 图数据库：遍历未闭合事件的因果链（上游 2 层 + 下游 1 层）
    ├─ 3. 向量语义：因果链不足时兜底补充
    └─ 4. 组装：按因果紧迫性排序，输出"因果诊断书"
```

### 6.3 FormatGuard（一致性校验）

- 校验参与者是否在场
- 校验是否违反 WorldRule
- 校验是否超出 Entity.habitus 边界（OOC 检测）
- 校验时空一致性（禁止瞬移）

### 6.4 PacingEngine（叙事节奏引擎）

| 状态 | 条件 | 建议 |
|------|------|------|
| 起 | 未闭合事件 < 2 | 铺垫新伏笔 |
| 承 | 未闭合事件 2-4，链深度 < 3 | 推进因果链 |
| 转 | 角色情绪极端（narrative 出现"崩溃""绝望"），链深度 >= 3 | 触发 stress_response |
| 合 | 未闭合事件 > 6 | 闭合事件，聚焦主线 |

### 6.5 PerturbationEngine（扰动引擎）

- 不凭空制造"为了戏剧而戏剧"的意外
- 检测长期压抑的因果链，释放积蓄势能
- 真正的意外只来自场域突变（有物理根因）

### 6.6 EventScheduler（事件调度器）

- 玩家在线：由输入触发事件
- 玩家离线：NPC 基于 Habitus 自主涌现，因果链自动推进
- 玩家回归：离线摘要生成器压缩为 3-5 条关键变化

---

## 七、LLM 层与 Prompt 工程

### 7.1 U 型注意力 Prompt 结构

```
[头部：System Prompt]
  ├─ Identity + Habitus 核心倾向
  └─ 当前场域快照

[中部：因果上下文]
  └─ CausalRAG 召回的因果诊断书

[尾部：最近状态 + 用户输入]
  ├─ EmotionalState.narrative
  ├─ 关键关系的 current_narrative
  ├─ 最近 3 轮对话
  └─ 用户输入
```

### 7.2 反八股设计

System Prompt 常驻：
> "不要每次都用同一种结构。你可以突然沉默，可以只说半句话，可以只有动作没有台词。格式服务于情绪。"

- 给 LLM **氛围**（mood / energy_level / pacing），不给 **模板**
- 允许不完整句子、纯动作描写、零台词沉默
- FormatGuard 只做 OOC 硬拦截，不做文风软约束

### 7.3 低成本 LLM 修正

- 状态机切片注入：每轮只注入 Active NPC 的 Habitus，不 Dump 全量记忆
- 输出后校验：FormatGuard 校验，违规触发重写或拦截

---

## 八、存储架构

| 存储层 | 数据 | 工具 |
|--------|------|------|
| **图数据库（因果层）** | 事件节点 + 因果边 | Kuzu / NetworkX |
| **状态缓存（实时层）** | NPC 当前最新状态 | SQLite / JSON |
| **向量数据库（语义层）** | narrative_text 的 Embedding | Chroma（可选） |

---

## 九、持久化与存档

- **存档单位**：世界状态快照（所有 Entity 的 state、Location 的 current_entities、未闭合事件）
- **时间回溯**：加载 checkpoint_N 并重放
- **分支世界线**：关键选择点后状态分叉保存

---

## 十、商业化与生态

### 10.1 商业模式

- **主机收费**：AURA Pro 版（可视化编辑器、云同步、多人协作）
- **内容免费**：官方 Demo 世界免费，作为技术展示
- **UGC 市场**：创作者免费/付费发卡，平台抽成（生态成熟后启动）
- **用户自带 API KEY**：平台不承担模型调用成本

### 10.2 卡带生态

- **官方种子**：免费，展示主机机能（RWBY 信标篇、公共域模组）
- **第三方/UGC**：创作者定价，平台抽成 15%-30%
- **人物卡独立**：单个 `.aura_npc` 可作为最小卡带，插入任何兼容世界

### 10.3 冷启动路径

1. **Phase 0**：封闭测试（10-20 人），验证 Ruby 100 轮不崩
2. **Phase 1**：创作者内测（30-50 人），开放简化版编辑器
3. **Phase 2**：小范围公测（100-500 人），角色卡市场上线

---

## 十一、设计铁律

1. **文字为根**
2. **先 Ruby 后抽象**
3. **状态驱动**
4. **因果优先**
5. **事件驱动**（拒绝时间驱动 Tick 系统）
6. **无根不扰**
7. **情感叙事化**（不量化情绪与关系）
8. **反八股**（一致性保边界，不保轨道）
9. **主机固件不稳，卡带再精美也读不出来**

---

## 十二、一句话定义

> **AURA 是文字冒险平台，不是聊天工具。主机是游戏机，卡带是游戏世界；导演调度演员，规则约束涌现；玩家在确定性中体验自由，在自由中感受逻辑。**

# AURA 观测台 — 维测前端开发文档

## 一、文件说明

- **前端文件**: `index.html`（纯静态HTML+CSS+JS，无框架依赖）
- **接入方式**: FastAPI提供REST API + SSE实时推送
- **目标**: LLM读取本文档后，可直接编写FastAPI后端和JS胶水代码，无需额外解释

---

## 二、页面结构总览

4个Tab导航：

| Tab ID | 名称 | 用途 |
|--------|------|------|
| `tab-now` | 实时面板 | 当前轮次的三元组状态快照 |
| `tab-timeline` | 时序面板 | 多轮趋势（预留） |
| `tab-compare` | 对比面板 | 调整前后差异（预留） |
| `tab-engine` | 引擎面板 | LLM调用链路 + 历史轮次查询 |

切换函数：`switchTab(tabId)` — 通过`data-tab`属性匹配导航按钮。

---

## 三、实时面板（`tab-now`）

布局：**三元组** = 左上人物 + 右上事件 + 下方世界

### 3.1 人物区（`.tri-upper-left`）

#### 角色切换栏（`#char-select`）
- 下拉菜单，选项值为角色ID
- 切换时调用 `switchChar(charId)`
- 需要数据：**当前会话的所有角色列表**（ID + 名称 + 角色标签）

#### 卡片1：八层状态（`#card-layer`）
- 容器：`.layer-grid`（2列网格）
- 每个层级一个 `.layer-item`：
  - `.layer-name`：层级名称（如"一层 体格"）
  - `.layer-status`：状态标记（`ok`=绿色✓ / `warn`=黄色!）
  - `.layer-value`：该层的当前值（文字描述）
  - `.layer-bar` + `.layer-bar-fill`：进度条（可选，如声纹稳定度）
- **8层固定顺序**：一层体格 → 二层声纹 → 三层根源 → 四层人际 → 五层核心 → 六层张力 → 七层轨迹 → 八层钩子
- 需要数据：**指定角色的8层状态对象**，每个字段包含当前值（字符串，形容词描述）

#### 卡片2：关系（`#card-relation`）
- 容器：`#relation-content`，由 `renderRelations(charName)` 渲染
- 分两个区块：
  - `"{角色名} 如何看待他人"` — 该角色的出边关系
  - `"他人如何看待 {角色名}"` — 该角色的入边关系
- 每行 `.rel-row`：
  - `.rel-name`：对方角色名
  - `.rel-type`：关系类型（情侣/养父女/师徒/陌生人/上下级/同事等）
  - `.rel-tag`：态度程度标签（见形容词映射表）
  - 附加 `.tag-yellow`：动态标签（如"动摇中"）
- **关系数据结构**（有向图）：
  ```json
  {
    "from": "皮拉",
    "to": "玩家",
    "type": "情侣",
    "level": "trust-basic",
    "label": "基本信任",
    "tags": ["动摇中"]
  }
  ```
- 需要数据：**全场所有角色的关系边列表**（有向，每条边独立）

#### 卡片3：状态变更（`#card-delta`，默认折叠）
- 表格 `.delta-table`，列：字段 / 变更 / 原因
- 每行展示一个字段的变化：
  - `.delta-field`：字段名（如"审讯室.紧张度"）
  - `.delta-before` → `.delta-after`：变更前后（形容词）
  - `.delta-pos/.delta-neg/.delta-zero`：上升/下降/未变标记
  - `.delta-reason`：变更原因
- 需要数据：**当前轮次的状态变更列表**（字段、前值、后值、原因）

#### 卡片4：叙事输出（`#card-llm`，默认折叠）
- `.llm-narrative`：LLM生成的叙事文本（带`*动作*`和`"对话"`）
- `.code-block`：结构化输出（JSON，含意图标签、世界变更、可见性）
- `.llm-meta`：元信息（模型、温度、延迟）
- 需要数据：**当前轮次的LLM输出**（ narrative文本 + structured JSON + 元信息）

---

### 3.2 事件区（`.tri-upper-right`）

#### 卡片1：事件补丁（`#card-event`）
- `.event-id`：事件ID
- `.event-type-badge`：事件类型（对话/动作/世界变更等）
- `.event-kv` 键值对：
  - 发起者 → 角色名
  - 目标 → 角色名
  - 意图 → 标签列表
  - 可见性 → 公开/私密
  - 世界影响 → 变更描述（用↑↓箭头，不用数字）
- 需要数据：**当前轮次的事件补丁对象**

#### 卡片2：因果链（`#card-causal`）
- `.causal-chain` 纵向时间线
- 每个 `.chain-node`：
  - `.chain-turn`：轮次
  - `.chain-text`：事件摘要
  - `.current` 类标记当前轮次
  - `.root` 类标记根事件
- 底部可附加 `.chain-contradiction`：矛盾检测提示
- 需要数据：**当前事件的前置因果链**（轮次 → 事件摘要列表）

---

### 3.3 世界区（`.tri-lower`）

#### 世界条（`.world-strip`）
4列网格（`.world-grid`）：

| 列 | 类名 | 内容 |
|----|------|------|
| 场景 | `.world-section` | 标识、名称、描述 |
| 物理状态 | `.world-section` | 灯光、温度、门锁等 |
| 在场角色 | `.world-section` | 角色名 + 身份标签 |
| 生效规则 | `.world-section` | 触发规则 + 当前值 |

- 字段值使用 `.alert` 类标红异常值
- `.world-rule`：规则标签（黄色边框）
- 需要数据：**当前场景的完整世界状态对象**

---

## 四、引擎面板（`tab-engine`）

### 4.1 轮次选择器（`#turn-select`）
- 下拉菜单选项值为轮次数字
- 切换时调用 `loadTurn(turnNum)`
- 需要数据：**当前会话的所有轮次列表**（轮次号 + 简要标记）

### 4.2 该轮次基础信息
- 玩家输入摘要 / 皮拉输出摘要 / 延迟

### 4.3 5个步骤卡片（`#tab-engine .chain-step`，按顺序）

| 序号 | 内容 | 需要数据 |
|------|------|----------|
| 0 | 对话记录（玩家输入 + 角色回复） | `player`: 玩家输入文本, `char`: 角色回复文本 |
| 1 | 记忆检索结果 | `memories[]`: {score, text} |
| 2 | 记忆压缩 | `compress`: {before, after} |
| 3 | 意图识别 | `intent[]`: 意图标签, `directive`: 导演指令 |
| 4 | 最终Prompt | `prompt`: {system, memory, recent, user}, `tokens`: token数 |

**历史数据结构**（每轮一个对象）：
```json
{
  "player": "玩家输入文本",
  "char": "角色回复文本（可含\\n换行）",
  "intent": ["辩解", "求和"],
  "directive": "导演指令文本",
  "memories": [
    {"score": 0.92, "text": "第5轮 — 皮拉..."}
  ],
  "compress": {
    "before": "压缩前文本",
    "after": "压缩后摘要"
  },
  "prompt": {
    "system": "System Prompt内容",
    "memory": "压缩记忆内容",
    "recent": "近期对话",
    "user": "当前用户输入"
  },
  "latency": "1.24秒",
  "tokens": 2847
}
```

---

## 五、形容词映射表（关键！数字→文字）

### 5.1 通用程度标签（`.level-tag`）
| CSS类 | 含义 | 适用场景 |
|-------|------|----------|
| `level-none` | 无 | 无压力/无情感 |
| `level-low` | 低 | 低压力/低紧张 |
| `level-mid` | 中等 | 中等程度 |
| `level-high` | 较高 | 较高程度 |
| `level-extreme` | 极高 | 极端状态 |

### 5.2 信任度专用（`.trust-*`）
| CSS类 | 含义 | 数值映射参考 |
|-------|------|-------------|
| `trust-hostile` | 敌对 | < -0.5 |
| `trust-distrust` | 不信任 | -0.5 ~ 0 |
| `trust-cautious` | 谨慎 | 0 ~ 0.3 |
| `trust-basic` | 基本信任 | 0.3 ~ 0.6 |
| `trust-deep` | 深厚羁绊 | 0.6 ~ 0.85 |
| `trust-absolute` | 绝对信任 | > 0.85 |

### 5.3 状态标记（`.tag-*`）
| CSS类 | 颜色 | 用途 |
|-------|------|------|
| `tag-purple` | 紫 | 关系类型、意图标签 |
| `tag-green` | 绿 | 正常/稳定 |
| `tag-yellow` | 黄 | 警告/动态标签 |
| `tag-red` | 红 | 危险/异常 |
| `tag-blue` | 蓝 | 信息/玩家标识 |

---

## 六、JS函数清单

| 函数 | 参数 | 用途 | 调用时机 |
|------|------|------|----------|
| `switchTab(tabId)` | tab的ID（不含`tab-`前缀） | Tab切换 | 导航按钮点击 |
| `switchChar(charId)` | 角色ID | 切换当前角色 | 角色下拉选择 |
| `toggleCard(cardId)` | 卡片DOM ID | 折叠/展开卡片 | 卡片头部点击 |
| `renderRelations(charName)` | 角色显示名 | 渲染关系列表 | 角色切换后 |
| `loadTurn(turnNum)` | 轮次数字 | 加载历史轮次数据 | 轮次选择器切换 |

**DOM加载完成初始化**：
- 展开4个默认卡片（八层、关系、事件、因果链）
- 调用 `renderRelations('皮拉')` 初始化关系列表

---

## 七、FastAPI端点建议

```
GET  /api/sessions                    → 会话列表
GET  /api/session/{id}                → 会话基础信息
GET  /api/session/{id}/characters     → 角色列表（给下拉菜单）
GET  /api/session/{id}/character/{cid}/layers      → 八层状态
GET  /api/session/{id}/character/{cid}/relations  → 关系数据（出边+入边）
GET  /api/session/{id}/events/latest  → 最新事件补丁
GET  /api/session/{id}/events/{turn}  → 指定轮次事件
GET  /api/session/{id}/causal/{event_id}           → 事件因果链
GET  /api/session/{id}/world          → 世界状态
GET  /api/session/{id}/turns          → 轮次列表（时序面板）
GET  /api/session/{id}/engine/{turn}  → 引擎面板完整数据
SSE  /api/session/{id}/stream         → 实时推送（新轮次/状态变更）
```

**SSE推送事件类型**：
- `new_turn`: 新轮次完成 → 刷新实时面板
- `state_change`: 状态变更 → 刷新对应卡片
- `world_update`: 世界状态变更 → 刷新世界区

---

## 八、开发顺序建议

1. **先做静态数据**：API返回mock数据，页面能正确渲染
2. **再做实时面板**：SSE推送 → 实时面板自动刷新
3. **再做引擎面板**：历史查询 → 轮次切换联动
4. **最后时序+对比**：预留Tab后续实现

---

## 九、颜色变量（CSS `:root`）

前端已定义，后端无需关心，但SSE/REST返回的数据中不需要颜色信息，纯文本+标签类名即可。

```
--bg-0: #0d1117      页面底色
--bg-1: #161b22      卡片底色
--bg-2: #1c2128      次级卡片
--accent: #7B6D8D    主色调（紫灰）
--ok: #5b8c5a        绿色-正常
--warn: #c4a35a      黄色-警告
--alert: #c4715b     红色-异常
--info: #6B8CBB      蓝色-信息
--fg: #c9d1d9        主文字
--fg-dim: #8b949e    次级文字
--fg-dark: #484f58   暗色文字/标签
```

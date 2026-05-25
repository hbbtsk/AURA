"""
AURA Director（导演）

职责：
  - 上帝视角，维护客观世界状态
  - 场域渲染：每轮生成环境描写
  - 规则判定：行动是否违反 WorldRule？
  - NPC 调度：决定本轮哪些 NPC 应该反应
  - 旁白推进：插入客观叙事
  - 结果广播：按记忆权限过滤后广播给 NPC

当前实现为骨架阶段：
  - 场域渲染：已实现（基于 WorldField）
  - NPC 调度：mock — 返回所有在场 NPC
  - 规则判定：mock — 只检查 location_id 匹配
  - 旁白推进：mock — 返回空
  - 指代消解：已实现（Alias 匹配）

设计原则：
  - Director 不直接调用 LLM，只负责"决策"和"数据准备"
  - LLM 调用由 NPC Agent 完成
"""
from typing import Dict, List, Optional, Any, Tuple

from app.models import World, WorldField, Entity, WorldRule
from app.world import world_runtime
from app.utils import get_logger

logger = get_logger("aura-director")


class Director:
    """
    导演：AURA 文字冒险平台的核心调度器。

    每轮运转流程（目标态）：
        1. 接收玩家输入
        2. 更新 WorldField
        3. 指代消解（resolve_mention）
        4. 规则判定
        5. 调度 NPC（决定哪些 NPC 该反应）
        6. 为每个 NPC 准备场域切片（按记忆权限过滤）
        7. 收集各 NPC Agent 输出
        8. 仲裁（校验冲突、排序输出、插入旁白）
        9. 原子性提交 EventPatch
        10. 流式返回给玩家

    当前骨架态：
        - 步骤 1-4 已实现
        - 步骤 5 为 mock（所有在场 NPC 都反应）
        - 步骤 6-10 由外部调用方完成
    """

    def __init__(self):
        self._logger = logger

    # ------------------------------------------------------------------
    # 场域渲染
    # ------------------------------------------------------------------
    def get_field_snapshot(self, location_id: Optional[str] = None) -> WorldField:
        """获取当前场域快照。"""
        return world_runtime.get_field(location_id)

    def render_ambient(self, field: WorldField) -> str:
        """
        渲染环境氛围描述。

        基于 WorldField 的 ambient 列表生成自然语言段落。
        """
        if not field.ambient:
            return ""

        parts = []
        for item in field.ambient:
            parts.append(item)

        # 在场角色列表
        if field.present_entities:
            entity_names = []
            for eid in field.present_entities:
                entity = world_runtime.get_entity(eid)
                if entity:
                    entity_names.append(entity.get_name("zh"))
            if entity_names:
                parts.append(f"在场: {', '.join(entity_names)}")

        return "；".join(parts)

    # ------------------------------------------------------------------
    # 指代消解
    # ------------------------------------------------------------------
    def resolve_mention(self, player_input: str, field: WorldField) -> Optional[str]:
        """
        将玩家的自然语言指称映射到世界内的唯一实体 ID。

        策略：
        1. 优先匹配在场角色的别名（减少误匹配）
        2. 如果匹配失败，返回 None（调用方可走语义兜底）
        """
        text_lower = player_input.lower()

        # 1. 优先匹配在场角色的别名
        for entity_id in field.present_entities:
            entity = world_runtime.get_entity(entity_id)
            if not entity:
                continue
            for alias in entity.get_all_aliases():
                if alias.lower() in text_lower:
                    return entity_id

        return None

    # ------------------------------------------------------------------
    # 规则判定
    # ------------------------------------------------------------------
    def check_rule_violation(
        self,
        action_description: str,
        entity_id: str,
        location_id: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        检查某行动是否违反世界规则。

        Returns:
            (是否违规, 违规原因) — 未违规时返回 (False, None)

        当前为 mock 实现：只检查 location_id 匹配，不涉及语义分析。
        """
        rules = world_runtime.world.get_active_rules(location_id) if world_runtime.world else []
        for rule in rules:
            # mock：简单检查 action_description 中是否包含规则关键词
            # 后续接入 LLM 进行语义判定
            keywords = self._extract_keywords(rule.description)
            for kw in keywords:
                if kw in action_description.lower():
                    return True, f"违反规则 [{rule.rule_id}]: {rule.description}"
        return False, None

    # ------------------------------------------------------------------
    # NPC 调度
    # ------------------------------------------------------------------
    def schedule_npcs(self, field: WorldField) -> List[str]:
        """
        决定本轮哪些 NPC 应该反应。

        当前 mock：返回所有在场 NPC。
        后续应基于：
        - Habitus 条件匹配
        - 情绪状态
        - 与玩家的关系
        - 上一轮是否已反应（避免某个 NPC 话太多）
        """
        npcs = []
        for entity_id in field.present_entities:
            # 假设 entity_id 不以 "player" 开头的就是 NPC
            # 后续应有明确的 is_player 标记
            if not entity_id.startswith("player"):
                npcs.append(entity_id)
        return npcs

    def get_npc_field_slice(self, entity_id: str, field: WorldField) -> Dict[str, Any]:
        """
        为指定 NPC 准备场域切片（按记忆权限过滤）。

        NPC 只能看到：
        - 客观场域（地点、时间、环境）
        - 自己 known_events 中的事件 narrative_text
        - 在场的其他角色（但可能不知道对方的秘密）
        """
        entity = world_runtime.get_entity(entity_id)
        if not entity:
            return {}

        # 客观场域
        slice_data = {
            "location_id": field.location_id,
            "time": field.time,
            "ambient": field.ambient,
            "present_entities": field.present_entities,
            "my_identity": entity.identity.model_dump(),
            "my_habitus": entity.habitus.model_dump(),
            "my_emotion": entity.emotion.model_dump(),
        }

        # 按记忆权限过滤的事件
        if world_runtime.world:
            known_events = []
            for event_id in entity.memory.known_events:
                event = world_runtime.world.events.get(event_id)
                if event:
                    narrative = event.get_narrative_for(entity_id)
                    if narrative:
                        known_events.append({
                            "event_id": event_id,
                            "narrative": narrative,
                        })
            slice_data["known_events"] = known_events

        # 关系信息
        relationships = {}
        for target_id, rel in entity.relationships.items():
            relationships[target_id] = rel.model_dump()
        slice_data["relationships"] = relationships

        return slice_data

    # ------------------------------------------------------------------
    # 旁白 / 仲裁（mock）
    # ------------------------------------------------------------------
    def narrate_scene_transition(self, from_field: WorldField, to_field: WorldField) -> str:
        """
        生成场景转换的旁白文本。

        当前 mock：返回空字符串。
        后续应由 LLM 根据场域变化生成。
        """
        return ""

    def arbitrate_outputs(self, npc_outputs: Dict[str, str]) -> str:
        """
        仲裁多个 NPC 的输出，组装为最终叙事文本。

        当前 mock：简单拼接。
        后续应：
        - 检测冲突（两个 NPC 说矛盾的话）
        - 按戏剧性排序
        - 插入旁白过渡
        """
        parts = []
        for entity_id, output in npc_outputs.items():
            entity = world_runtime.get_entity(entity_id)
            name = entity.get_name("zh") if entity else entity_id
            parts.append(f"【{name}】\n{output}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _extract_keywords(self, description: str) -> List[str]:
        """从规则描述中提取关键词（mock 实现）。"""
        # 简单的中文分词：按标点切分，取 2-4 字词组
        import re
        # 移除常见虚词
        stopwords = {"的", "了", "在", "是", "和", "或", "禁止", "允许", "必须"}
        words = re.findall(r'[\u4e00-\u9fff]{2,4}', description)
        return [w for w in words if w not in stopwords]


# 全局单例
director = Director()

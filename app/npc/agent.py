"""
AURA NPC Agent（演员）

职责：
  - 角色视角，只知道 memory.known_events 里的东西
  - 独立 System Prompt（仅包含该角色的 Identity + Habitus + State）
  - 独立 LLM 调用
  - 只读写自己的 Entity.state，不可访问其他角色记忆

当前实现为骨架阶段：
  - System Prompt 组装：已实现（基于元模型）
  - LLM 调用：复用路线A的 _call_single_llm
  - 多实例并发：预留接口，当前先实现单实例

设计原则：
  - 每个 NPC Agent 是一个轻量对象，持有 entity_id 引用
  - 不持有 World 全局引用，只通过 Director 获取过滤后的场域切片
  - 输出后由 Director 仲裁，Agent 不自行决定剧情走向
"""
from typing import Dict, Any, List, Optional

from app.models import Entity
from app.director import director
from app.world import world_runtime
from app.utils import get_logger
from app.core.config import settings, get_llm_config

logger = get_logger("aura-npc")


class NPCAgent:
    """
    NPC 演员：持有角色身份，独立生成回应。

    生命周期：
        1. Director 决定调度哪些 NPC → new NPCAgent(entity_id)
        2. Agent 从 Director 获取场域切片（已按记忆权限过滤）
        3. Agent 组装 System Prompt → 调用 LLM
        4. Agent 返回生成的文本
        5. Director 收集所有 Agent 输出 → 仲裁 → 返回玩家
    """

    def __init__(self, entity_id: str):
        self.entity_id = entity_id
        self._entity: Optional[Entity] = None
        self._refresh_entity()

    def _refresh_entity(self) -> None:
        """刷新实体引用（因为 World 状态可能在运行时被更新）。"""
        self._entity = world_runtime.get_entity(self.entity_id)

    # ------------------------------------------------------------------
    # Prompt 组装
    # ------------------------------------------------------------------
    def build_system_prompt(self, field_slice: Dict[str, Any], lang: str = "zh") -> str:
        """
        组装 NPC 专属的 System Prompt。

        只包含：
        - 该角色的 Identity + Habitus
        - 当前情绪状态
        - 按记忆权限过滤后的已知事件
        - 当前场域（客观条件）

        不包含：
        - 其他角色的秘密
        - 不在场角色的信息
        - 全局因果链
        """
        if not self._entity:
            return ""

        lines = []

        # --- 角色身份 ---
        lines.append("=" * 40)
        lines.append("【你是谁】")
        lines.append("=" * 40)
        lines.append(self._entity.to_prompt_fragment(lang))
        lines.append("")

        # --- 当前场域 ---
        lines.append("=" * 40)
        lines.append("【你在哪】")
        lines.append("=" * 40)
        location_id = field_slice.get("location_id", "")
        ambient = field_slice.get("ambient", [])
        lines.append(f"地点: {location_id}")
        lines.append(f"环境: {'; '.join(ambient)}")
        present = field_slice.get("present_entities", [])
        if present:
            names = []
            for eid in present:
                if eid == self.entity_id:
                    continue
                e = world_runtime.get_entity(eid)
                if e:
                    names.append(e.get_name(lang))
            if names:
                lines.append(f"在场: {', '.join(names)}")
        lines.append("")

        # --- 已知事件 ---
        known_events = field_slice.get("known_events", [])
        if known_events:
            lines.append("=" * 40)
            lines.append("【你知道什么】")
            lines.append("=" * 40)
            for evt in known_events:
                lines.append(f"- {evt['event_id']}: {evt['narrative']}")
            lines.append("")

        # --- 关系 ---
        relationships = field_slice.get("relationships", {})
        if relationships:
            lines.append("=" * 40)
            lines.append("【你与他人的关系】")
            lines.append("=" * 40)
            for target_id, rel_data in relationships.items():
                target = world_runtime.get_entity(target_id)
                target_name = target.get_name(lang) if target else target_id
                lines.append(f"- {target_name}: {rel_data.get('current_narrative', '')}")
            lines.append("")

        # --- 核心约束（反八股）---
        lines.append("=" * 40)
        lines.append("【叙事原则】")
        lines.append("=" * 40)
        lines.append("- 你只知道上面列出的信息，不要编造你不知道的事")
        lines.append("- 用第一人称或角色视角叙事，不要跳出角色")
        lines.append("- 你可以突然沉默，可以只说半句话，可以只有动作没有台词")
        lines.append("- 格式服务于情绪，不要每次都按同一种结构输出")
        lines.append("- 禁止替用户（玩家）生成任何行动或台词")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # LLM 调用
    # ------------------------------------------------------------------
    async def generate_response(
        self,
        player_input: str,
        field_slice: Dict[str, Any],
        backend: str = None,
        temperature: float = 0.7,
    ) -> str:
        """
        生成 NPC 对玩家输入的回应。

        复用路线A的 LLM 调用能力（通过 httpx 直接调用）。
        """
        from app.graph.nodes.llm_quality_output import _call_single_llm

        system_prompt = self.build_system_prompt(field_slice)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": player_input},
        ]

        payload = {
            "model": settings.default_llm,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }

        backend = backend or settings.default_llm
        llm_config = get_llm_config(backend, scene="main")

        try:
            llm_data, error = await _call_single_llm(
                backend,
                None,
                payload,
                timeout=llm_config.timeout if llm_config else 30,
            )
            if error or llm_data is None:
                logger.error(f"[NPCAgent] LLM 调用失败: {error}")
                return f"[系统: {self._entity.get_name('zh') if self._entity else self.entity_id} 暂时无法回应]"

            message = llm_data.get("choices", [{}])[0].get("message", {})
            content = message.get("content", "")
            return content

        except Exception as e:
            logger.exception(f"[NPCAgent] 生成回应异常: {e}")
            return f"[系统: 回应生成失败]"

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------
    def update_emotion(self, new_label: str, narrative: str) -> None:
        """更新角色情绪（由 EventPatch 触发）。"""
        if self._entity:
            self._entity.emotion.current_label = new_label
            self._entity.emotion.narrative = narrative
            import time
            self._entity.emotion.last_updated = int(time.time())

    def add_known_event(self, event_id: str) -> None:
        """添加已知事件（由 Director 广播触发）。"""
        if self._entity and event_id not in self._entity.memory.known_events:
            self._entity.memory.known_events.append(event_id)

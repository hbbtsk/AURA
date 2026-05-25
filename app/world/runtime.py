"""
AURA 世界运行时

职责：
  - 维护当前加载的世界状态（World 实例）
  - 管理世界时钟推进
  - 提供世界状态的查询接口（被 Director 和 NPC Agent 使用）
  - 原子性提交 EventPatch（apply_patch）

设计原则：
  - WorldRuntime 是 World 的包装层，不直接修改 World 内部字段
  - 所有状态变更通过 apply_patch() 原子性提交
  - 支持存档/读档（checkpoint）
"""
from typing import Dict, List, Optional, Any

from app.models import World, EventPatch, WorldField
from app.cartridge import CartridgeLoader
from app.utils import get_logger

logger = get_logger("aura-world")


class WorldRuntime:
    """世界运行时：当前激活世界的状态管理器。"""

    def __init__(self):
        self.world: Optional[World] = None
        self._cartridge_name: Optional[str] = None
        self._checkpoints: Dict[str, World] = {}  # 简易存档

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def load_cartridge(self, cartridge_name: str, base_path: str = "cartridges") -> World:
        """加载卡带，初始化世界。"""
        loader = CartridgeLoader(base_path)
        self.world = loader.load(cartridge_name)
        self._cartridge_name = cartridge_name
        logger.info(
            f"[WorldRuntime] 卡带已加载 | {cartridge_name} | "
            f"实体: {len(self.world.entities)} | 地点: {len(self.world.locations)}"
        )
        return self.world

    def is_loaded(self) -> bool:
        """是否有世界已加载。"""
        return self.world is not None

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------
    def get_field(self, location_id: Optional[str] = None) -> WorldField:
        """
        获取当前场域快照。

        Args:
            location_id: 指定地点，None 则使用世界当前主地点
        """
        if not self.world:
            return WorldField()

        loc_id = location_id or self._infer_main_location()
        location = self.world.locations.get(loc_id)

        if location:
            present = location.current_entities.copy()
            active_rules = [
                r.rule_id for r in self.world.get_active_rules(loc_id)
            ]
            ambient = location.properties.copy()
        else:
            present = []
            active_rules = []
            ambient = []

        # 添加全局氛围（天气、季节等）
        global_state = self.world.global_state
        if global_state.get("weather"):
            ambient.append(f"天气: {global_state['weather']}")
        if global_state.get("season"):
            ambient.append(f"季节: {global_state['season']}")
        if global_state.get("time_of_day"):
            ambient.append(f"时段: {global_state['time_of_day']}")

        return WorldField(
            location_id=loc_id,
            time=self.world.current_time,
            present_entities=present,
            ambient=ambient,
            active_rules=active_rules,
        )

    def get_entity(self, entity_id: str) -> Optional[Any]:
        """获取指定实体。"""
        if not self.world:
            return None
        return self.world.entities.get(entity_id)

    def get_entities_at(self, location_id: str) -> List[Any]:
        """获取指定地点的所有在场实体。"""
        if not self.world:
            return []
        return self.world.get_entities_at(location_id)

    def get_all_entities(self) -> Dict[str, Any]:
        """获取所有实体。"""
        if not self.world:
            return {}
        return self.world.entities

    def get_location(self, location_id: str) -> Optional[Any]:
        """获取指定地点。"""
        if not self.world:
            return None
        return self.world.locations.get(location_id)

    # ------------------------------------------------------------------
    # 状态变更
    # ------------------------------------------------------------------
    def apply_patch(self, patch: EventPatch) -> None:
        """原子性应用事件补丁。"""
        if not self.world:
            logger.warning("[WorldRuntime] 未加载世界，忽略补丁")
            return
        self.world.apply_patch(patch)
        logger.info(
            f"[WorldRuntime] 补丁已应用 | {patch.event_id} | "
            f"参与者: {patch.participants} | 闭合: {patch.closes}"
        )

    def advance_time(self, delta: int = 1) -> None:
        """推进世界时钟。"""
        if self.world:
            self.world.current_time += delta

    def move_entity(self, entity_id: str, to_location_id: str) -> bool:
        """
        移动实体到指定地点。

        Returns:
            bool: 是否成功
        """
        if not self.world:
            return False

        entity = self.world.entities.get(entity_id)
        if not entity:
            logger.warning(f"[WorldRuntime] 实体不存在: {entity_id}")
            return False

        from_loc = self.world.locations.get(entity.location_id)
        to_loc = self.world.locations.get(to_location_id)
        if not to_loc:
            logger.warning(f"[WorldRuntime] 地点不存在: {to_location_id}")
            return False

        # 从原地点移除
        if from_loc and entity_id in from_loc.current_entities:
            from_loc.current_entities.remove(entity_id)

        # 添加到新地点
        if entity_id not in to_loc.current_entities:
            to_loc.current_entities.append(entity_id)

        # 更新实体状态
        entity.location_id = to_location_id

        logger.info(
            f"[WorldRuntime] 实体移动 | {entity_id} → {to_location_id}"
        )
        return True

    # ------------------------------------------------------------------
    # 存档 / 读档
    # ------------------------------------------------------------------
    def save_checkpoint(self, name: str) -> None:
        """保存当前世界状态的深拷贝。"""
        if not self.world:
            return
        import copy
        self._checkpoints[name] = copy.deepcopy(self.world)
        logger.info(f"[WorldRuntime] 存档已保存: {name}")

    def load_checkpoint(self, name: str) -> Optional[World]:
        """加载存档。"""
        checkpoint = self._checkpoints.get(name)
        if checkpoint:
            self.world = checkpoint
            logger.info(f"[WorldRuntime] 存档已加载: {name}")
        return self.world

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _infer_main_location(self) -> str:
        """推断当前主地点（取第一个有实体的地点，或第一个地点）。"""
        if not self.world:
            return ""
        for loc_id, loc in self.world.locations.items():
            if loc.current_entities:
                return loc_id
        return next(iter(self.world.locations.keys()), "")


# 全局单例
world_runtime = WorldRuntime()

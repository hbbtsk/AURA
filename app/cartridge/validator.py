"""
AURA 卡带验证器

职责：
  - Schema 合法性校验
  - 依赖满足检测
  - 版本兼容检查
  - 冲突检测（实体 ID 重复、地点 ID 重复等）

当前为轻量实现，后续可扩展为严格的 JSON Schema 校验。
"""
from typing import List, Dict, Set, Tuple
from pathlib import Path

from app.cartridge.loader import CartridgeLoader, CartridgeLoadError
from app.models import World, Entity, Location, EventPatch
from app.utils import get_logger

logger = get_logger("aura-cartridge")


class ValidationResult:
    """校验结果"""
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def merge(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


class CartridgeValidator:
    """卡带验证器"""

    def __init__(self, base_path: str = "cartridges"):
        self.loader = CartridgeLoader(base_path)

    def validate(self, cartridge_name: str) -> ValidationResult:
        """
        完整校验一个卡带。

        Returns:
            ValidationResult: 包含 errors 和 warnings
        """
        result = ValidationResult()

        # 1. 尝试加载（YAML 语法 + 基础结构）
        try:
            world = self.loader.load(cartridge_name)
        except CartridgeLoadError as e:
            result.add_error(str(e))
            return result

        # 2. 校验 World 内部一致性
        self._validate_world(world, result)

        return result

    def _validate_world(self, world: World, result: ValidationResult) -> None:
        """校验 World 内部一致性。"""
        # 2.1 实体引用的地点是否存在
        for entity_id, entity in world.entities.items():
            if entity.location_id and entity.location_id not in world.locations:
                result.add_warning(
                    f"实体 {entity_id} 引用了不存在的地点: {entity.location_id}"
                )

        # 2.2 地点连通性是否双向
        for loc_id, loc in world.locations.items():
            for connected_id, travel_time in loc.connected_to.items():
                if connected_id not in world.locations:
                    result.add_error(
                        f"地点 {loc_id} 连通到不存在的地点: {connected_id}"
                    )
                elif travel_time <= 0:
                    result.add_warning(
                        f"地点 {loc_id} → {connected_id} 的通行时间应大于 0"
                    )

        # 2.3 事件引用的参与者是否存在
        for event_id, event in world.events.items():
            for participant in event.participants:
                if participant not in world.entities:
                    result.add_warning(
                        f"事件 {event_id} 引用了不存在的参与者: {participant}"
                    )

        # 2.4 事件的因果链是否完整
        for event_id, event in world.events.items():
            for parent_id in event.caused_by:
                if parent_id not in world.events:
                    result.add_warning(
                        f"事件 {event_id} 的父事件不存在: {parent_id}"
                    )
            for child_id in event.causes:
                if child_id not in world.events:
                    result.add_warning(
                        f"事件 {event_id} 的子事件不存在: {child_id}"
                    )

        # 2.5 规则引用的例外事件是否存在
        for rule in world.rules:
            for exception_id in rule.exception_events:
                if exception_id not in world.events:
                    result.add_warning(
                        f"规则 {rule.rule_id} 引用了不存在的事件: {exception_id}"
                    )

        # 2.6 关系引用的目标是否存在
        for entity_id, entity in world.entities.items():
            for target_id in entity.relationships:
                if target_id not in world.entities:
                    result.add_warning(
                        f"实体 {entity_id} 的关系引用了不存在的目标: {target_id}"
                    )

        # 2.7 open_loops 中的事件是否存在
        for loop_id in world.open_loops:
            if loop_id not in world.events:
                result.add_error(
                    f"open_loops 引用了不存在的事件: {loop_id}"
                )

        logger.info(
            f"[CartridgeValidator] 校验完成 | 错误: {len(result.errors)} | "
            f"警告: {len(result.warnings)}"
        )

"""
AURA 卡带解析器

职责：
  - 加载 .aura 目录，解析 YAML 为元模型 Pydantic 实例
  - 支持多语言别名解析
  - 生成 World 运行时对象

卡带目录结构：
  example.aura/
  ├── meta.yaml
  ├── world.yaml
  ├── entities/
  │   ├── weiss_schnee.yaml
  │   └── ruby_rose.yaml
  ├── locations/
  │   ├── beacon_academy.yaml
  │   └── dormitory.yaml
  ├── events/
  │   └── opening.yaml
  └── assets/
      └── (可选资源索引)
"""
import os
from typing import Dict, List, Optional
from pathlib import Path

import yaml

from app.models import World, Location, WorldRule, Entity, EventPatch
from app.utils import get_logger

logger = get_logger("aura-cartridge")


class CartridgeLoadError(Exception):
    """卡带加载错误"""
    pass


class CartridgeLoader:
    """卡带加载器：YAML 目录 → World 对象"""

    def __init__(self, base_path: str = "cartridges"):
        self.base_path = Path(base_path)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def load(self, cartridge_name: str) -> World:
        """
        加载指定卡带，返回 World 运行时对象。

        Args:
            cartridge_name: 卡带目录名，如 "rwby_beacon"

        Returns:
            World 实例

        Raises:
            CartridgeLoadError: 卡带不存在或格式错误
        """
        cartridge_path = self.base_path / cartridge_name
        if not cartridge_path.exists():
            raise CartridgeLoadError(f"卡带不存在: {cartridge_path}")

        logger.info(f"[Cartridge] 加载卡带: {cartridge_name}")

        # 1. 读取 meta.yaml（仅校验，不写入 World）
        meta = self._load_yaml(cartridge_path / "meta.yaml", required=True)
        self._validate_meta(meta)

        # 2. 读取 world.yaml
        world_data = self._load_yaml(cartridge_path / "world.yaml", required=True)

        # 3. 解析 locations
        locations = self._load_locations(cartridge_path / "locations")

        # 4. 解析 entities
        entities = self._load_entities(cartridge_path / "entities")

        # 5. 解析 events（种子事件）
        events = self._load_events(cartridge_path / "events")

        # 6. 组装 World
        world = World(
            world_id=cartridge_name,
            name=world_data.get("name", cartridge_name),
            locations=locations,
            entities=entities,
            events=events,
            rules=self._parse_rules(world_data.get("rules", [])),
            global_state=world_data.get("global_state", {}),
            current_time=world_data.get("initial_time", 0),
            open_loops=world_data.get("open_loops", []),
        )

        # 7. 初始化地点的 current_entities（根据 entity 的初始 location_id）
        for entity_id, entity in world.entities.items():
            if entity.location_id:
                loc = world.locations.get(entity.location_id)
                if loc and entity_id not in loc.current_entities:
                    loc.current_entities.append(entity_id)

        logger.info(
            f"[Cartridge] 加载完成 | 地点: {len(world.locations)} | "
            f"实体: {len(world.entities)} | 事件: {len(world.events)} | "
            f"规则: {len(world.rules)}"
        )
        return world

    def list_available(self) -> List[str]:
        """列出所有可用卡带目录名。"""
        if not self.base_path.exists():
            return []
        return [
            d.name for d in self.base_path.iterdir()
            if d.is_dir() and (d / "meta.yaml").exists()
        ]

    # ------------------------------------------------------------------
    # 内部解析
    # ------------------------------------------------------------------
    def _load_yaml(self, path: Path, required: bool = False) -> dict:
        if not path.exists():
            if required:
                raise CartridgeLoadError(f"缺少必需文件: {path}")
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise CartridgeLoadError(f"YAML 解析失败: {path} | {e}")

    def _validate_meta(self, meta: dict) -> None:
        """校验卡带元信息。"""
        required_fields = ["title", "version"]
        for field in required_fields:
            if field not in meta:
                logger.warning(f"[Cartridge] meta.yaml 缺少字段: {field}")

    def _resolve_name(self, name_data, default: str = "", lang: str = "zh") -> str:
        """解析可能为多语言字典的名称，返回指定语言的值。"""
        if isinstance(name_data, str):
            return name_data
        if isinstance(name_data, dict):
            return name_data.get(lang, name_data.get("en", default))
        return default

    def _load_locations(self, locations_dir: Path) -> Dict[str, Location]:
        """解析 locations/ 目录下的所有 YAML 文件。"""
        locations = {}
        if not locations_dir.exists():
            return locations

        for file_path in locations_dir.glob("*.yaml"):
            data = self._load_yaml(file_path)
            if "location_id" not in data:
                logger.warning(f"[Cartridge] 地点文件缺少 location_id: {file_path}")
                continue
            loc = Location(
                location_id=data["location_id"],
                name=self._resolve_name(data.get("name"), data["location_id"]),
                coordinates=tuple(data.get("coordinates", [0.0, 0.0, 0.0])),
                connected_to=data.get("connected_to", {}),
                properties=data.get("properties", []),
                current_entities=data.get("current_entities", []),
            )
            locations[loc.location_id] = loc

        return locations

    def _load_entities(self, entities_dir: Path) -> Dict[str, Entity]:
        """解析 entities/ 目录下的所有 YAML 文件。"""
        from app.models import Identity, Habitus, Tendency, EmotionalState, Relationship, Memory

        entities = {}
        if not entities_dir.exists():
            return entities

        for file_path in entities_dir.glob("*.yaml"):
            data = self._load_yaml(file_path)
            if "entity_id" not in data:
                logger.warning(f"[Cartridge] 实体文件缺少 entity_id: {file_path}")
                continue

            # 解析 Identity
            identity_data = data.get("identity", {})
            identity = Identity(
                entity_id=data["entity_id"],
                name=self._resolve_name(identity_data.get("name"), data["entity_id"]),
                race=identity_data.get("race", "human"),
                age=identity_data.get("age", 0),
                core_motivation=self._resolve_name(
                    identity_data.get("core_motivation", ""), ""
                ),
                speech_fingerprint=self._resolve_name(
                    identity_data.get("speech_fingerprint", ""), ""
                ),
                aliases=identity_data.get("aliases", {}),
            )

            # 解析 Habitus
            habitus_data = data.get("habitus", {})
            tendencies = []
            for t_data in habitus_data.get("tendencies", []):
                tendencies.append(Tendency(**t_data))
            habitus = Habitus(
                tendencies=tendencies,
                default_behavior=habitus_data.get("default_behavior", ""),
                stress_response=habitus_data.get("stress_response", ""),
            )

            # 解析 State
            emotion_data = data.get("emotion", {})
            emotion = EmotionalState(
                current_label=emotion_data.get("current_label", "calm"),
                narrative=emotion_data.get("narrative", ""),
                anchored_by=emotion_data.get("anchored_by", []),
                formed_at=emotion_data.get("formed_at", 0),
                last_updated=emotion_data.get("last_updated", 0),
            )

            # 解析 Relationships
            relationships = {}
            for rel_data in data.get("relationships", []):
                rel = Relationship(**rel_data)
                relationships[rel.target_id] = rel

            # 解析 Memory
            memory_data = data.get("memory", {})
            memory = Memory(
                known_events=memory_data.get("known_events", []),
                known_secrets=memory_data.get("known_secrets", []),
            )

            entity = Entity(
                identity=identity,
                habitus=habitus,
                location_id=data.get("location_id", ""),
                emotion=emotion,
                relationships=relationships,
                memory=memory,
            )
            entities[entity.identity.entity_id] = entity

        return entities

    def _load_events(self, events_dir: Path) -> Dict[str, EventPatch]:
        """解析 events/ 目录下的种子事件。"""
        events = {}
        if not events_dir.exists():
            return events

        for file_path in events_dir.glob("*.yaml"):
            data = self._load_yaml(file_path)
            if "event_id" not in data:
                logger.warning(f"[Cartridge] 事件文件缺少 event_id: {file_path}")
                continue

            # 解析 state_diffs
            from app.models import StateChange, EmotionalImpact
            state_diffs = [StateChange(**sd) for sd in data.get("state_diffs", [])]
            emotional_impacts = [EmotionalImpact(**ei) for ei in data.get("emotional_impacts", [])]

            event = EventPatch(
                event_id=data["event_id"],
                timestamp=data.get("timestamp", 0),
                location_id=data.get("location_id", ""),
                participants=data.get("participants", []),
                state_diffs=state_diffs,
                emotional_impacts=emotional_impacts,
                narrative_text=data.get("narrative_text", ""),
                caused_by=data.get("caused_by", []),
                causes=data.get("causes", []),
                activates=data.get("activates", []),
                closes=data.get("closes", []),
                public_to=data.get("public_to", []),
                secret_to=data.get("secret_to", []),
                hidden_from=data.get("hidden_from", []),
                causal_weight=data.get("causal_weight", 0.5),
                is_key_foreshadowing=data.get("is_key_foreshadowing", False),
                is_closed=data.get("is_closed", False),
            )
            events[event.event_id] = event

        return events

    def _parse_rules(self, rules_data: List[dict]) -> List[WorldRule]:
        """解析世界规则。"""
        return [
            WorldRule(
                rule_id=r.get("rule_id", f"rule_{i}"),
                description=r.get("description", ""),
                scope=r.get("scope", []),
                exception_events=r.get("exception_events", []),
            )
            for i, r in enumerate(rules_data)
        ]

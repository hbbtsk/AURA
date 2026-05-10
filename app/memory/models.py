"""
AURA 记忆系统数据模型

意图感知 RAG 的核心数据结构：
- IntentStructure: 入库记忆 + 意图识别共用的结构化字段（6 维）
- IntentResult: IntentTagger 的完整输出（含 structure + implicit_instruction + expanded_scene）
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict


@dataclass
class IntentStructure:
    """
    结构化字段 — 入库记忆和意图识别共用同一格式
    
    6 个字段覆盖 RP 场景的完整语义维度：
    - scene_type: 场景类型（Where/When）
    - action_type: 行为模式（What）— 核心匹配维度，权重最高
    - emotional_tone: 情绪基调（How）
    - tension_description: 张力描述（Atmosphere）— 替代数字评分
    - entities: 涉及角色（Who）— 用 Jaccard 集合匹配
    - pacing: 节奏感（Rhythm）
    
    每个字段的值是自然语言短语，匹配时走 embedding 语义相似度。
    entities 除外，用字符串集合的 Jaccard 系数。
    """
    scene_type: str = ""
    action_type: str = ""
    emotional_tone: str = ""
    tension_description: str = ""
    entities: List[str] = field(default_factory=list)
    pacing: str = ""

    def is_empty(self) -> bool:
        """检查是否所有字段都为空"""
        return not any([
            self.scene_type,
            self.action_type,
            self.emotional_tone,
            self.tension_description,
            self.entities,
            self.pacing
        ])

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict，用于 FAISS metadata 存储"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "IntentStructure":
        """从 dict 反序列化"""
        return cls(
            scene_type=data.get("scene_type", ""),
            action_type=data.get("action_type", ""),
            emotional_tone=data.get("emotional_tone", ""),
            tension_description=data.get("tension_description", ""),
            entities=data.get("entities", []),
            pacing=data.get("pacing", ""),
        )

    @classmethod
    def empty(cls) -> "IntentStructure":
        """返回空结构"""
        return cls()


# 字段权重配置（用于结构化匹配时的综合评分）
STRUCTURE_FIELD_WEIGHTS = {
    "scene_type": 0.20,
    "action_type": 0.25,   # 核心行为模式，权重最高
    "emotional_tone": 0.20,
    "tension_description": 0.10,
    "entities": 0.15,
    "pacing": 0.10,
}

# 复合排序权重（用于 structured_aware_search）
SEARCH_WEIGHTS = {
    "semantic": 0.3,    # expanded_scene embedding 相似度（保底）
    "structure": 0.5,   # 逐字段结构化匹配（核心改进）
    "time": 0.2,        # 时间加权（新鲜度）
}


@dataclass
class IntentResult:
    """
    IntentTagger 的完整输出
    
    双字段设计，流向不同下游：
    1. structure → RAG 逐字段 embedding 软匹配（不传递给主 LLM）
    2. implicit_instruction → 注入 [USER_INTENT_TAG] 给主 LLM
    
    辅助字段：
    - expanded_scene: 整段场景叙事，用于 embedding 粗排保底
    - confidence: 置信度，< 0.6 时跳过意图修正
    - input_type: 输入类型分类
    - user_expectation: 用户期望的 LLM 输出类型
    """
    structure: IntentStructure = field(default_factory=IntentStructure.empty)
    implicit_instruction: str = ""
    expanded_scene: str = ""
    confidence: float = 0.0
    input_type: str = ""
    user_expectation: str = ""

    def should_use(self) -> bool:
        """是否应该使用意图修正结果"""
        return self.confidence >= 0.6 and not self.structure.is_empty()

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict"""
        return {
            "structure": self.structure.to_dict(),
            "implicit_instruction": self.implicit_instruction,
            "expanded_scene": self.expanded_scene,
            "confidence": self.confidence,
            "input_type": self.input_type,
            "user_expectation": self.user_expectation,
        }

    @classmethod
    def empty(cls) -> "IntentResult":
        """返回空结果（置信度 0，跳过意图修正）"""
        return cls(confidence=0.0)

    @classmethod
    def fallback(cls, user_input: str) -> "IntentResult":
        """
        降级方案：当 IntentTagger 不可用时，
        直接用用户输入作为 expanded_scene，跳过结构化匹配
        """
        return cls(
            structure=IntentStructure.empty(),
            implicit_instruction="",
            expanded_scene=user_input,
            confidence=0.0,
            input_type="FALLBACK",
            user_expectation="",
        )

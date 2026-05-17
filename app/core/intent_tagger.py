"""
AURA IntentTagger — 用户意图解析器

职责：在每轮用户输入后，调用轻量 LLM 解析用户真实意图，输出双字段：
1. structure（结构化数据）→ RAG 逐字段 embedding 软匹配
2. implicit_instruction（导演指令）→ 注入 [USER_INTENT_TAG] 给主 LLM
3. expanded_scene（场景叙事）→ embedding 粗排保底

位置：LangGraph 中位于 InputReceive → EmotionAnalyze 之间
当前：直接作为独立模块调用，由 completions.py 在转发前调用
"""

import json
import logging
from typing import Optional

import httpx

from app.core.config import settings, get_llm_config
from app.memory.models import IntentStructure, IntentResult

logger = logging.getLogger("aura.intent_tagger")

# IntentTagger 的 System Prompt（精简版，适配 Kimi k2.6 的 reasoning 特性）
SYSTEM_PROMPT = """你是角色扮演场景中的用户意图分析师。分析用户输入，输出 JSON。

字段：
- input_type: 纯动作/纯台词/动作+台词/情绪表达/场景指令/其他
- user_expectation: A(继续自己行动)/B(看其他角色反应)/C(推进剧情)/D(等待回应)
- confidence: 0-1
- implicit_instruction: 导演指令，如"请渲染环境氛围"、"不要替用户行动"
- expanded_scene: 第三人称场景描写，含地点/动作/氛围，不含元指令
- structure.scene_type: 场景类型
- structure.action_type: 核心行为模式
- structure.emotional_tone: 情绪基调
- structure.tension_description: 自然语言描述张力
- structure.entities: 角色名列表
- structure.pacing: 节奏感

输出纯 JSON，不要解释。"""


class IntentTagger:
    """用户意图解析器 — 轻量 LLM 前置调用"""

    def __init__(self):
        self._llm_config = None

    def _get_llm_config(self):
        """获取轻量 LLM 配置（优先用 Kimi，回退到 DeepSeek）"""
        if self._llm_config is not None:
            return self._llm_config

        # 优先用 Kimi（便宜，适合意图分析）
        kimi_config = get_llm_config("kimi", scene="intent")
        if kimi_config and kimi_config.api_key:
            self._llm_config = kimi_config
            logger.info("[IntentTagger] 使用 Kimi 作为意图分析模型")
            return self._llm_config

        # 回退到 DeepSeek
        ds_config = get_llm_config("deepseek", scene="intent")
        if ds_config and ds_config.api_key:
            self._llm_config = ds_config
            logger.info("[IntentTagger] 使用 DeepSeek 作为意图分析模型（回退）")
            return self._llm_config

        logger.warning("[IntentTagger] 无可用 LLM 配置，意图分析将降级")
        return None

    async def analyze(
        self,
        user_input: str,
        context: Optional[dict] = None,
    ) -> IntentResult:
        """
        解析用户输入的真实意图

        Args:
            user_input: 用户输入的原始文本
            context: 可选上下文信息（场景类型、活跃角色等）

        Returns:
            IntentResult: 意图解析结果
        """
        llm_config = self._get_llm_config()
        if not llm_config:
            logger.warning("[IntentTagger] LLM 未配置，降级为原始查询")
            return IntentResult.fallback(user_input)

        # 构建上下文描述
        context_str = ""
        if context:
            scene_type = context.get("scene_type", "未知")
            active_entities = context.get("active_entities", [])
            context_str = (
                f"【当前场景上下文】\n"
                f"场景类型: {scene_type}\n"
                f"活跃角色: {', '.join(active_entities) if active_entities else '未知'}\n"
            )

        # 构建用户 Prompt
        user_prompt = (
            f"{context_str}"
            f"【用户输入】\n"
            f"{user_input}\n\n"
            f"请分析上述用户输入，输出 JSON。"
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.api_key}"
        }

        payload = {
            "model": llm_config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": llm_config.temperature,
            "max_tokens": llm_config.max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(llm_config.timeout)) as client:
                response = await client.post(
                    f"{llm_config.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )

                if response.status_code != 200:
                    logger.error(
                        f"[IntentTagger] LLM 调用失败: "
                        f"{response.status_code} {response.text[:200]}"
                    )
                    return IntentResult.fallback(user_input)

                result = response.json()
                content = result["choices"][0]["message"]["content"]

                # 解析 JSON（处理可能的 markdown 代码块包裹）
                return self._parse_response(content, user_input)

        except httpx.TimeoutException:
            logger.warning("[IntentTagger] LLM 超时，降级为原始查询")
            return IntentResult.fallback(user_input)
        except Exception as e:
            logger.error(f"[IntentTagger] 调用异常: {e}", exc_info=True)
            return IntentResult.fallback(user_input)

    def _parse_response(self, content: str, user_input: str) -> IntentResult:
        """解析 LLM 返回的 JSON 响应"""
        try:
            # 处理可能的 markdown 代码块包裹
            # 匹配 ```json ... ``` 或 ``` ... ```（贪婪匹配第一个代码块）
            import re
            code_block_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
            if code_block_match:
                content = code_block_match.group(1).strip()

            data = json.loads(content)

            # 提取 structure
            structure_data = data.get("structure", {})
            structure = IntentStructure(
                scene_type=structure_data.get("scene_type", ""),
                action_type=structure_data.get("action_type", ""),
                emotional_tone=structure_data.get("emotional_tone", ""),
                tension_description=structure_data.get("tension_description", ""),
                entities=structure_data.get("entities", []),
                pacing=structure_data.get("pacing", ""),
            )

            # 提取 expanded_scene，如果为空则用用户输入
            expanded_scene = data.get("expanded_scene", "") or user_input

            result = IntentResult(
                structure=structure,
                implicit_instruction=data.get("implicit_instruction", ""),
                expanded_scene=expanded_scene,
                confidence=float(data.get("confidence", 0.0)),
                input_type=data.get("input_type", ""),
                user_expectation=data.get("user_expectation", ""),
            )

            logger.info(
                f"[IntentTagger] 解析结果: "
                f"type={result.input_type}, "
                f"confidence={result.confidence:.2f}, "
                f"structure={structure.to_dict()}"
            )

            return result

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"[IntentTagger] JSON 解析失败: {e}, content={content[:200]}")
            return IntentResult.fallback(user_input)


# 全局单例
intent_tagger = IntentTagger()

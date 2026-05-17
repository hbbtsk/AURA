"""
AURA 记忆总结器

职责：
  - 调用 Kimi/DeepSeek 总结最近对话，提取新记忆
  - 对每条新记忆提取结构化字段（IntentStructure）
  - 调用 LLM 进行记忆总结与结构化提取
"""
import json
import re
import httpx
import logging
from datetime import datetime
from typing import List, Optional

from app.core.config import get_llm_config
from app.memory.models import IntentStructure

logger = logging.getLogger("aura.memory")


class MemorySummarizer:
    """LLM 驱动的记忆总结与结构化提取"""

    def __init__(self, faiss_store, sqlite_store):
        self._faiss = faiss_store
        self._sqlite = sqlite_store

    async def summarize_and_store(self, session_id: str, recent_dialogues: List[dict]) -> None:
        """调用 Kimi 总结最近对话 → 提取新记忆 → 结构化字段提取 → 存入 FAISS"""
        if not recent_dialogues:
            return

        try:
            dialogue_text = self._format_dialogue_for_summary(recent_dialogues)
            existing_memories = await self._faiss.get_recent(5)

            summary_prompt = f"""你是一个角色扮演记忆提取助手。请分析以下对话，提取需要长期记住的关键信息。

提取要求：
1. 只提取**新出现的、重要的**信息（角色关系变化、重要事件、情感转折、承诺誓言等）
2. 不要重复已有记忆中的内容
3. 每条记忆用一段简短而生动的叙述描写，包含场景感（地点、氛围、关键动作/台词）
4. 如果本轮对话没有值得长期记住的内容，返回空列表

输出格式：
请以 JSON 数组格式返回新记忆列表，例如：
[
  "信标学院宿舍。夕阳斜照进窗户，Ruby转身看向Yang，银色的眼睛里闪烁着坚定：'我绝对不会丢下你的。'",
  "图书馆二楼。Weiss和Blake因为战术分歧发生了激烈争执，气氛一度十分紧张。"
]
如果没有新记忆，返回 []

已有记忆（供参考，避免重复）：
{existing_memories}

最近对话：
{dialogue_text}
"""

            kimi_config = get_llm_config("kimi", scene="summary")
            new_memories = await self._call_llm_for_summary(kimi_config, summary_prompt)

            if new_memories:
                for mem in new_memories:
                    structure = await self._extract_structure(mem)
                    metadata = {
                        "source": "aura_summary",
                        "session_id": session_id,
                        "summarized_at": datetime.now().isoformat(),
                    }
                    if structure and not structure.is_empty():
                        metadata["structure"] = structure.to_dict()
                        logger.debug(
                            f"[AURA→总结] 记忆结构化字段: "
                            f"scene={structure.scene_type}, "
                            f"action={structure.action_type}, "
                            f"emotion={structure.emotional_tone}"
                        )
                    await self._faiss.add(mem, metadata)
                logger.info(f"[AURA→总结] Kimi 提取了 {len(new_memories)} 条新记忆（含结构化字段）")
            else:
                logger.info("[AURA→总结] Kimi 未提取到新记忆")

        except Exception as e:
            logger.error(f"[AURA→总结] 记忆总结失败: {e}")

    async def _extract_structure(self, memory_text: str) -> Optional[IntentStructure]:
        """对单条记忆文本提取结构化字段（使用轻量 LLM）"""
        try:
            llm_config = get_llm_config("kimi", scene="intent")
            if not llm_config or not llm_config.api_key:
                llm_config = get_llm_config("deepseek", scene="intent")
                if not llm_config or not llm_config.api_key:
                    logger.debug("[AURA→总结] 无可用 LLM 配置，跳过结构化字段提取")
                    return None

            system_prompt = """你是一个角色扮演场景的结构化分析助手。
分析以下记忆文本，提取 6 个结构化字段，以 JSON 格式输出（不要解释）：

{
  "scene_type": "场景类型（如'宿舍私聊'、'战斗'、'谈判'）",
  "action_type": "核心行为模式（如'用点烟打破沉默'）",
  "emotional_tone": "情绪基调（如'压抑中寻求突破'）",
  "tension_description": "用自然语言描述张力状态（如'表面平静下的暗流涌动'）",
  "entities": ["涉及角色名列表"],
  "pacing": "节奏感（如'停顿后的小动作'）"
}

如果某个字段无法推断，用空字符串""代替。"""

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {llm_config.api_key}"
            }

            payload = {
                "model": llm_config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"记忆文本：{memory_text}"}
                ],
                "temperature": llm_config.temperature,
                "max_tokens": llm_config.max_tokens,
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(llm_config.timeout)) as client:
                response = await client.post(
                    f"{llm_config.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )

                if response.status_code != 200:
                    logger.warning(
                        f"[AURA→总结] 结构化提取 LLM 调用失败: {response.status_code}"
                    )
                    return None

                result = response.json()
                content = result["choices"][0]["message"]["content"]

                # 解析 JSON（处理可能的 markdown 代码块包裹）
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                data = json.loads(content)
                return IntentStructure(
                    scene_type=data.get("scene_type", ""),
                    action_type=data.get("action_type", ""),
                    emotional_tone=data.get("emotional_tone", ""),
                    tension_description=data.get("tension_description", ""),
                    entities=data.get("entities", []),
                    pacing=data.get("pacing", ""),
                )

        except httpx.TimeoutException:
            logger.debug("[AURA→总结] 结构化提取超时，跳过")
            return None
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"[AURA→总结] 结构化提取 JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"[AURA→总结] 结构化提取异常: {e}")
            return None

    def _format_dialogue_for_summary(self, dialogues: List[dict]) -> str:
        """将对话列表格式化为总结用的文本"""
        lines = []
        for d in dialogues:
            role = d.get("role", "unknown")
            content = d.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    async def _call_llm_for_summary(self, llm_config, prompt: str) -> List[str]:
        """调用 LLM 进行记忆总结"""
        if not llm_config or not llm_config.api_key:
            logger.warning("[AURA→总结] Kimi 未配置，跳过总结")
            return []

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.api_key}"
        }

        payload = {
            "model": llm_config.model,
            "messages": [
                {"role": "system", "content": "你是一个记忆提取助手，只输出 JSON 数组。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": llm_config.temperature,
            "max_tokens": llm_config.max_tokens
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(llm_config.timeout)) as client:
            response = await client.post(
                f"{llm_config.base_url}/chat/completions",
                headers=headers,
                json=payload
            )

            if response.status_code != 200:
                logger.error(f"[AURA→总结] LLM 调用失败: {response.status_code} {response.text[:200]}")
                return []

            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            try:
                if content.startswith("["):
                    memories = json.loads(content)
                else:
                    json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content, re.DOTALL)
                    if json_match:
                        memories = json.loads(json_match.group(1))
                    else:
                        logger.warning(f"[AURA→总结] 无法解析 LLM 输出: {content[:200]}")
                        return []

                if isinstance(memories, list):
                    return [str(m) for m in memories if m]
                return []

            except json.JSONDecodeError as e:
                logger.warning(f"[AURA→总结] JSON 解析失败: {e}, 原始内容: {content[:200]}")
                return []

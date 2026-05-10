"""
TAVO Prompt 数据拆解器

功能：将 TAVO 发送的原始 Prompt（messages[0].content）拆解为结构化组件

拆解组件：
  - 越权禁令（Authority Ban）
  - 长记忆（Long-term Memory）
  - 记忆应用规则（Memory Usage Rules）
  - USER 设定（User Profile）
  - 角色卡（Character Card）
  - 世界书（World Book）
  - XML 角色卡（XML Character Cards）
  - 多轮对话（Dialogue）
  - 最后用户输入（Last User Input）

拆解策略（三层递进）：
  1. ===== 标记优先（用户在角色卡中约定的 =====xxx开始===== / =====xxx结束===== 格式）
  2. HTML 注释标记回退（<!-- AURA_CHARACTER_CARD_START/END -->）
  3. 无标记时回退到基于格式的硬拆解
"""

import re
import json
import logging
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("aura-decomposer")


class PromptDecomposer:
    """TAVO Prompt 拆解器 — 标记优先 + 格式回退"""

    # ============================================================
    # ===== 格式标记 — 用户在 TAVO 角色卡中约定的结构化边界标记
    # 格式：=====xxx开始===== / =====xxx结束=====
    # 支持：长记忆、用户设定、角色卡
    # ============================================================
    MARKER_MEMORY_START = "=====长记忆开始====="
    MARKER_MEMORY_END = "=====长记忆结束====="
    MARKER_USER_START = "=====用户设定开始====="
    MARKER_USER_END = "=====用户设定结束====="
    MARKER_CARD_START = "=====角色卡开始====="
    MARKER_CARD_END = "=====角色卡结束====="

    # ============================================================
    # HTML 注释标记回退（旧版 AURA 标记格式）
    # ============================================================
    AURA_MARKER_CHAR_CARD_START = "<!-- AURA_CHARACTER_CARD_START -->"
    AURA_MARKER_CHAR_CARD_END = "<!-- AURA_CHARACTER_CARD_END -->"

    # ============================================================
    # 边界标记常量（旧格式回退用）
    # ============================================================

    # 越权禁令：以"禁止生成"开头，到"以下是关于"之前
    AUTHORITY_BAN_PATTERN = r"^(禁止生成.+?)(?=\n\n以下是关于|\n*$)"

    # 长记忆区域：从"以下是关于{{char}}与{{user}}之间的关键记忆与事件："到"# 记忆应用"之前
    LONG_TERM_MEMORY_START = "以下是关于"
    LONG_TERM_MEMORY_PATTERN = r"^以下是关于.+与.+之间的关键记忆与事件"
    MEMORY_USAGE_START = "# 记忆应用"

    # USER 设定：格式为 "{username}是{username}，{username}..."（通用匹配）
    # 匹配模式：任意中文字符开头，后跟"是"，再跟相同前缀
    USER_PROFILE_PATTERN = r"^(.+?)是\1[，,].+"

    # 角色卡（英文）：以英文角色描述开头（如 "Weiss Schnee is..."）
    CHARACTER_CARD_PATTERN = r"^[A-Z][a-z]+ [A-Z][a-z]+ is .+"

    # 世界书：以 "HISTORIA:" 开头（西班牙文）
    WORLD_BOOK_START = "HISTORIA:"

    # 角色卡（XML 标签格式）：<charname>...</charname>
    XML_CHAR_CARD_PATTERN = r"<[a-z]+>.*?</[a-z]+>"

    # 结尾标记
    END_MARKER = "[Start a new Chat]"

    # 记忆条目格式：以 "- " 开头
    MEMORY_ITEM_PATTERN = r"^- .+"

    def decompose(self, request_data: dict) -> dict:
        """
        拆解 TAVO 的完整请求数据

        参数:
            request_data: TAVO 发送的原始请求 (包含 model, messages, temperature 等)

        返回:
            拆解后的结构化数据
        """
        messages = request_data.get("messages", [])
        system_content = messages[0]["content"] if messages else ""
        dialogue_messages = messages[1:] if len(messages) > 1 else []

        # 拆解 System Prompt
        system_components = self._decompose_system_prompt(system_content)

        # 拆解对话
        dialogue_components = self._decompose_dialogue(dialogue_messages)

        result = {
            "metadata": {
                "model": request_data.get("model"),
                "temperature": request_data.get("temperature"),
                "stream": request_data.get("stream", True),
                "max_tokens": request_data.get("max_tokens"),
                "message_count": len(messages),
                "dialogue_rounds": dialogue_components["total_rounds"],
                "system_prompt_length": len(system_content),
            },
            "system_prompt": system_components,
            "dialogue": dialogue_components,
            "raw": {
                "system_content": system_content,
                "messages": messages,
            },
        }

        logger.info(
            "Prompt 拆解完成: "
            f"越权禁令={len(system_components['authority_ban'])}字符, "
            f"长记忆={len(system_components['long_term_memory'])}条, "
            f"角色卡={len(system_components['character_card'])}字符, "
            f"世界书={len(system_components['world_book'])}字符, "
            f"对话={dialogue_components['total_rounds']}轮"
        )

        return result

    def _decompose_system_prompt(self, content: str) -> dict:
        """拆解 System Prompt 内容"""
        if not content:
            return self._empty_system_components()

        lines = content.split("\n")
        result = {
            "authority_ban": "",
            "long_term_memory": [],
            "memory_usage_rules": "",
            "user_profile": "",
            "character_card": "",
            "world_book": "",
            "xml_character_cards": [],
            "full_content": content,
            # 用户是否写了自定义提示词前缀
            # 检测逻辑：第一行如果是"以下是关于..."开头，说明用户没写自定义提示词
            "has_user_prefix": not bool(re.match(self.LONG_TERM_MEMORY_PATTERN, lines[0].strip())),
            # 是否检测到 ===== 格式标记
            "has_markers": self.MARKER_CARD_START in content,
        }

        # 阶段1: 识别各区域的起始行号
        sections = self._identify_sections(lines, content)

        # 阶段2: 按区域提取内容
        # ============================================================
        # 优先使用 ===== 格式标记提取（最高优先级）
        # ============================================================
        has_markers = (
            sections["marker_memory_start"] is not None
            or sections["marker_user_start"] is not None
            or sections["marker_card_start"] is not None
        )

        if has_markers:
            # 长记忆 — 用 =====长记忆开始/结束===== 标记
            if sections["marker_memory_start"] is not None and sections["marker_memory_end"] is not None:
                memory_lines = lines[sections["marker_memory_start"] + 1:sections["marker_memory_end"]]
                result["long_term_memory"] = self._extract_memory_items(memory_lines)
                logger.info(
                    f"[AURA→标记] 使用 =====长记忆===== 标记定位: "
                    f"行 {sections['marker_memory_start']+1}-{sections['marker_memory_end']-1} | "
                    f"{len(result['long_term_memory'])}条"
                )
            elif sections["marker_memory_start"] is not None:
                memory_lines = lines[sections["marker_memory_start"] + 1:]
                result["long_term_memory"] = self._extract_memory_items(memory_lines)

            # 记忆应用规则 — 在长记忆结束标记之后、用户设定开始标记之前
            if sections["marker_memory_end"] is not None and sections["marker_user_start"] is not None:
                result["memory_usage_rules"] = "\n".join(
                    lines[sections["marker_memory_end"] + 1:sections["marker_user_start"]]
                ).strip()

            # USER 设定 — 用 =====用户设定开始/结束===== 标记
            if sections["marker_user_start"] is not None and sections["marker_user_end"] is not None:
                result["user_profile"] = "\n".join(
                    lines[sections["marker_user_start"] + 1:sections["marker_user_end"]]
                ).strip()
                logger.info(
                    f"[AURA→标记] 使用 =====用户设定===== 标记定位: "
                    f"行 {sections['marker_user_start']+1}-{sections['marker_user_end']-1} | "
                    f"{len(result['user_profile'])}字符"
                )

            # 角色卡 — 用 =====角色卡开始/结束===== 标记
            if sections["marker_card_start"] is not None and sections["marker_card_end"] is not None:
                result["character_card"] = "\n".join(
                    lines[sections["marker_card_start"] + 1:sections["marker_card_end"]]
                ).strip()
                logger.info(
                    f"[AURA→标记] 使用 =====角色卡===== 标记定位: "
                    f"行 {sections['marker_card_start']+1}-{sections['marker_card_end']-1} | "
                    f"{len(result['character_card'])}字符"
                )

            # 越权禁令 — 在开头到 =====长记忆开始===== 之间
            if sections["marker_memory_start"] is not None:
                ban_lines = lines[0:sections["marker_memory_start"]]
                ban_text = "\n".join(ban_lines).strip()
                if ban_text:
                    result["authority_ban"] = ban_text

        else:
            # ============================================================
            # 无标记 → 回退到 HTML 注释标记 + 格式硬拆解
            # ============================================================

            # 越权禁令（仅当用户写了自定义提示词时才有）
            if result["has_user_prefix"] and sections["authority_ban_start"] is not None and sections["memory_start"] is not None:
                result["authority_ban"] = "\n".join(
                    lines[sections["authority_ban_start"]:sections["memory_start"]]
                ).strip()
            elif result["has_user_prefix"] and sections["authority_ban_start"] is not None:
                result["authority_ban"] = lines[sections["authority_ban_start"]].strip()

            # 长记忆
            if sections["memory_start"] is not None and sections["memory_usage_start"] is not None:
                memory_lines = lines[sections["memory_start"]:sections["memory_usage_start"]]
                result["long_term_memory"] = self._extract_memory_items(memory_lines)
            elif sections["memory_start"] is not None:
                memory_lines = lines[sections["memory_start"]:]
                result["long_term_memory"] = self._extract_memory_items(memory_lines)

            # 记忆应用规则
            if sections["memory_usage_start"] is not None and sections["user_profile_start"] is not None:
                result["memory_usage_rules"] = "\n".join(
                    lines[sections["memory_usage_start"]:sections["user_profile_start"]]
                ).strip()
            elif sections["memory_usage_start"] is not None:
                result["memory_usage_rules"] = "\n".join(
                    lines[sections["memory_usage_start"]:]
                ).strip()

            # USER 设定
            if sections["user_profile_start"] is not None and sections["char_card_start"] is not None:
                result["user_profile"] = "\n".join(
                    lines[sections["user_profile_start"]:sections["char_card_start"]]
                ).strip()
            elif sections["user_profile_start"] is not None:
                result["user_profile"] = lines[sections["user_profile_start"]].strip()

            # 角色卡 — HTML 注释标记优先，格式回退
            if sections["char_card_marker_start"] is not None and sections["char_card_marker_end"] is not None:
                result["character_card"] = "\n".join(
                    lines[sections["char_card_marker_start"] + 1:sections["char_card_marker_end"]]
                ).strip()
                logger.info(
                    f"[AURA→标记] 使用 HTML 注释标记定位角色卡: "
                    f"行 {sections['char_card_marker_start']+1}-{sections['char_card_marker_end']-1} | "
                    f"{len(result['character_card'])}字符"
                )
            elif sections["char_card_start"] is not None and sections["world_book_start"] is not None:
                result["character_card"] = "\n".join(
                    lines[sections["char_card_start"]:sections["world_book_start"]]
                ).strip()
            elif sections["char_card_start"] is not None:
                result["character_card"] = "\n".join(
                    lines[sections["char_card_start"]:]
                ).strip()

            # ============================================================
            # 最终回退：如果角色卡仍为空，尝试从 user_profile 结束到 world_book 之间提取
            # 适用于中文角色卡格式（如 "角色名：..." 或 "【角色名】..."）
            # ============================================================
            if not result["character_card"]:
                # 确定 user_profile 的结束行
                profile_end = None
                if sections["user_profile_start"] is not None:
                    if sections["char_card_start"] is not None:
                        profile_end = sections["char_card_start"]
                    elif sections["world_book_start"] is not None:
                        profile_end = sections["world_book_start"]
                    elif sections["xml_start"] is not None:
                        profile_end = sections["xml_start"]
                    else:
                        profile_end = len(lines)
                elif sections["memory_usage_start"] is not None:
                    if sections["char_card_start"] is not None:
                        profile_end = sections["char_card_start"]
                    elif sections["world_book_start"] is not None:
                        profile_end = sections["world_book_start"]
                    else:
                        profile_end = len(lines)

                if profile_end is not None and profile_end < len(lines):
                    # 从 user_profile 结束行开始，到下一个已知区域结束
                    card_end = len(lines)
                    if sections["world_book_start"] is not None and sections["world_book_start"] > profile_end:
                        card_end = sections["world_book_start"]
                    elif sections["xml_start"] is not None and sections["xml_start"] > profile_end:
                        card_end = sections["xml_start"]

                    candidate_lines = lines[profile_end:card_end]
                    candidate_text = "\n".join(candidate_lines).strip()
                    # 只提取非空、非标记行
                    meaningful_lines = []
                    for cl in candidate_lines:
                        stripped_cl = cl.strip()
                        if stripped_cl and not stripped_cl.startswith("=====") and not stripped_cl.startswith("<!--"):
                            meaningful_lines.append(cl)
                    if meaningful_lines:
                        result["character_card"] = "\n".join(meaningful_lines).strip()
                        if result["character_card"]:
                            logger.info(
                                f"[AURA→回退] 使用格式回退提取角色卡: "
                                f"行 {profile_end+1}-{card_end} | "
                                f"{len(result['character_card'])}字符"
                            )

            # 世界书
            if sections["world_book_start"] is not None and sections["xml_start"] is not None:
                result["world_book"] = "\n".join(
                    lines[sections["world_book_start"]:sections["xml_start"]]
                ).strip()
            elif sections["world_book_start"] is not None:
                result["world_book"] = "\n".join(
                    lines[sections["world_book_start"]:]
                ).strip()

            # XML 角色卡
            if sections["xml_start"] is not None:
                xml_content = "\n".join(lines[sections["xml_start"]:])
                result["xml_character_cards"] = self._extract_xml_cards(xml_content)

        return result

    def _identify_sections(self, lines: List[str], full_content: str = "") -> dict:
        """
        识别 System Prompt 中各区域的起始行号

        策略（三层递进）：
          1. ===== 标记优先（=====xxx开始===== / =====xxx结束=====）
          2. HTML 注释标记回退（<!-- AURA_CHARACTER_CARD_START/END -->）
          3. 无标记时回退到基于格式的硬拆解
        """
        sections = {
            "authority_ban_start": None,
            "memory_start": None,
            "memory_usage_start": None,
            "user_profile_start": None,
            "char_card_start": None,          # 旧格式：英文角色描述开头
            "char_card_marker_start": None,   # HTML 注释标记开始行
            "char_card_marker_end": None,     # HTML 注释标记结束行
            "world_book_start": None,
            "xml_start": None,
            # ===== 格式标记（标记优先）
            "marker_memory_start": None,
            "marker_memory_end": None,
            "marker_user_start": None,
            "marker_user_end": None,
            "marker_card_start": None,
            "marker_card_end": None,
        }

        # ============================================================
        # 阶段1: 检测 ===== 格式标记（最高优先级）
        # ============================================================
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == self.MARKER_MEMORY_START and sections["marker_memory_start"] is None:
                sections["marker_memory_start"] = i
            if stripped == self.MARKER_MEMORY_END and sections["marker_memory_end"] is None:
                sections["marker_memory_end"] = i
            if stripped == self.MARKER_USER_START and sections["marker_user_start"] is None:
                sections["marker_user_start"] = i
            if stripped == self.MARKER_USER_END and sections["marker_user_end"] is None:
                sections["marker_user_end"] = i
            if stripped == self.MARKER_CARD_START and sections["marker_card_start"] is None:
                sections["marker_card_start"] = i
            if stripped == self.MARKER_CARD_END and sections["marker_card_end"] is None:
                sections["marker_card_end"] = i

        # ============================================================
        # 阶段2: 检测 HTML 注释标记（第二优先级）
        # ============================================================
        if full_content:
            if self.AURA_MARKER_CHAR_CARD_START in full_content:
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped == self.AURA_MARKER_CHAR_CARD_START and sections["char_card_marker_start"] is None:
                        sections["char_card_marker_start"] = i
                    if stripped == self.AURA_MARKER_CHAR_CARD_END and sections["char_card_marker_end"] is None:
                        sections["char_card_marker_end"] = i

        # ============================================================
        # 阶段3: 基于格式的硬拆解（最低优先级，标记和旧格式同时检测）
        # ============================================================
        for i, line in enumerate(lines):
            stripped = line.strip()

            # 越权禁令：以"禁止生成"开头（仅当用户写了自定义提示词时）
            if stripped.startswith("禁止生成") and sections["authority_ban_start"] is None:
                sections["authority_ban_start"] = i

            # 长记忆开始：匹配 "以下是关于{{char}}与{{user}}之间的关键记忆与事件"
            if re.match(self.LONG_TERM_MEMORY_PATTERN, stripped) and sections["memory_start"] is None:
                sections["memory_start"] = i

            # 记忆应用规则
            if stripped.startswith(self.MEMORY_USAGE_START) and sections["memory_usage_start"] is None:
                sections["memory_usage_start"] = i

            # USER 设定：通用匹配 "{username}是{username}，"
            if sections["user_profile_start"] is None:
                match = re.match(self.USER_PROFILE_PATTERN, stripped)
                if match:
                    sections["user_profile_start"] = i

            # 角色卡（英文格式回退）：以 "XXX is" 格式
            if re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+ is ", stripped) and sections["char_card_start"] is None:
                # 确保不是在世界书区域
                if sections["world_book_start"] is None:
                    sections["char_card_start"] = i

            # 世界书
            if stripped.startswith(self.WORLD_BOOK_START) and sections["world_book_start"] is None:
                sections["world_book_start"] = i

            # XML 角色卡
            if stripped.startswith("<") and stripped.endswith(">") and sections["xml_start"] is None:
                if re.match(r"^<[a-z]+>$", stripped):
                    sections["xml_start"] = i

        return sections

    def _extract_memory_items(self, lines: List[str]) -> List[str]:
        """从行列表中提取长记忆条目（以 '- ' 开头的行）"""
        items = []
        current_item = None

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- "):
                # 新条目开始
                if current_item is not None:
                    items.append(current_item)
                current_item = stripped[2:]  # 去掉 "- " 前缀
            elif current_item is not None and stripped:
                # 续行（跨行的记忆条目）
                current_item += " " + stripped
            elif current_item is not None and not stripped:
                # 空行，结束当前条目
                items.append(current_item)
                current_item = None

        if current_item is not None:
            items.append(current_item)

        return items

    def _extract_xml_cards(self, content: str) -> List[dict]:
        """提取 XML 标签格式的角色卡"""
        cards = []
        pattern = r"<([a-z]+)>\s*(.*?)\s*</\1>"
        matches = re.findall(pattern, content, re.DOTALL)
        for name, card_content in matches:
            cards.append({
                "name": name,
                "content": card_content.strip(),
            })
        return cards

    def _decompose_dialogue(self, messages: List[dict]) -> dict:
        """拆解多轮对话"""
        rounds = []
        current_user = None

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                if current_user is not None:
                    # 连续 user 消息，作为独立轮次
                    rounds.append({
                        "user": current_user,
                        "assistant": None,
                    })
                current_user = content
            elif role == "assistant":
                if current_user is not None:
                    rounds.append({
                        "user": current_user,
                        "assistant": content,
                    })
                    current_user = None
                else:
                    # 没有前序 user 的 assistant 消息
                    rounds.append({
                        "user": None,
                        "assistant": content,
                    })

        # 处理最后一条未配对的 user 消息
        if current_user is not None:
            rounds.append({
                "user": current_user,
                "assistant": None,
            })

        # 提取最后一条用户输入
        last_user_input = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_input = msg.get("content", "")
                break

        # 提取最近 N 轮对话（默认取全部）
        recent_rounds = rounds[-5:] if len(rounds) > 5 else rounds

        return {
            "rounds": rounds,
            "total_rounds": len(rounds),
            "recent_rounds": recent_rounds,
            "last_user_input": last_user_input,
            "raw_messages": messages,
        }

    def _empty_system_components(self) -> dict:
        """返回空的 System Prompt 组件"""
        return {
            "authority_ban": "",
            "long_term_memory": [],
            "memory_usage_rules": "",
            "user_profile": "",
            "character_card": "",
            "world_book": "",
            "xml_character_cards": [],
            "full_content": "",
            "has_user_prefix": False,
            "has_markers": False,
        }

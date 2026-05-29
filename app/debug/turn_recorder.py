"""
AURA 维测系统 — TurnRecorder（轮次全链路记录器）

设计原则：
  - 每轮次一个记录对象，请求入口创建，各阶段填充，请求结束一次性写入
  - 异步写入 SQLite（不阻塞主流程）
  - 内存缓存最近 100 轮（供实时查询 / SSE 推送）
  - 所有 JSON 字段 ensure_ascii=False，中文可读
  - 大文本字段截断存储（避免单条记录过大）

数据流：
  1. 请求入口 → TurnRecorder.start_turn() 创建记录
  2. LangGraph 各节点 → recorder.set_XXX() 填充中间产物
  3. LLM 调用前后 → recorder.set_llm_payload() / set_llm_response()
  4. 请求返回前 → recorder.commit() 异步写入 SQLite + 更新缓存
  5. 前端 API → 从缓存或 SQLite 查询

这是单人开发最核心的基础设施——没有它，AURA 等于盲飞。
"""

import json
import os
import sqlite3
import time
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict

from app.utils import get_logger

logger = get_logger("aura-telemetry")

# ------------------------------------------------------------------
# 配置
# ------------------------------------------------------------------
DB_PATH = Path("data/debug.db")
MAX_TEXT_LENGTH = 50000  # 单字段最大字符数，超限截断
CACHE_SIZE = 100  # 内存缓存最近 N 轮

# ------------------------------------------------------------------
# 数据模型
# ------------------------------------------------------------------

@dataclass
class TurnRecord:
    """单轮次全链路记录。"""
    session_id: str = ""
    turn_num: int = 0
    timestamp: float = 0.0
    mode: str = "chat"  # 'chat' | 'world'

    # === 输入层 ===
    player_input: str = ""
    backend: str = ""
    model: str = ""
    temperature: float = 0.7

    # === Prompt 编译层（核心）===
    original_system: str = ""           # 原始 System Prompt（TAVO 发来）
    decomposed_json: str = ""           # PromptDecomposer 拆解结果
    blocks_json: str = ""               # 9 区块列表
    optimized_system: str = ""          # 重组后的 System Prompt
    messages_list_json: str = ""        # 最终发给 LLM 的 messages 列表
    working_memory_text: str = ""       # 追加到 user 消息的 WORKING_MEMORY

    # === 意图 & 记忆 ===
    intent_result_json: str = ""        # 意图识别结果
    retrieved_memories_json: str = ""   # RAG 召回的记忆列表

    # === LLM 交互层（核心）===
    llm_payload_json: str = ""          # 发给 LLM 的请求体
    llm_response_content: str = ""      # LLM 生成的内容
    llm_reasoning_content: str = ""     # LLM 思考过程（reasoning_content）
    llm_raw_response_json: str = ""     # LLM 原始 JSON 响应
    actual_backend: str = ""            # 实际使用的后端（fallback 后可能变化）
    fallback_triggered: bool = False
    fallback_reason: str = ""

    # === 质检层 ===
    format_passed: bool = True
    format_reason: str = ""
    ooc_passed: bool = True
    ooc_reason: str = ""
    content_passed: bool = True
    content_reason: str = ""

    # === 节点日志 ===
    node_logs_json: str = ""            # LangGraph 各节点执行日志

    # === 输出层 ===
    response_content: str = ""          # 最终返回给 TAVO 的内容
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    # === World 模式专用 ===
    world_mode_data_json: str = ""      # Director 决策、NPC 输出、场域切片等

    # === 内部 ===
    _dirty: bool = field(default=False, repr=False)  # 是否有新数据待写入


# ------------------------------------------------------------------
# TurnRecorder — 核心记录器
# ------------------------------------------------------------------

class TurnRecorder:
    """
    轮次全链路记录器。

    使用方式（最小侵入）：
        recorder = TurnRecorder()
        record = recorder.start_turn(session_id, turn_num, mode='chat')
        
        # ... LangGraph 执行后 ...
        recorder.set_prompt_compiled(record, final_state)
        
        # ... LLM 调用前 ...
        recorder.set_llm_payload(record, payload)
        
        # ... LLM 调用后 ...
        recorder.set_llm_response(record, raw_response)
        
        # ... 请求返回前 ...
        recorder.commit(record, response_content, latency_ms)
    """

    def __init__(self):
        self._cache: Dict[str, TurnRecord] = {}  # key = "session_id:turn_num"
        self._cache_order: List[str] = []        # LRU 顺序
        self._lock = asyncio.Lock()
        self._ensure_db()

    # ------------------------------------------------------------------
    # 数据库初始化
    # ------------------------------------------------------------------
    def _ensure_db(self) -> None:
        """确保数据库和表存在。"""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cursor = conn.cursor()

            # 主表：轮次全链路记录
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS turn_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_num INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'chat',

                    player_input TEXT,
                    backend TEXT,
                    model TEXT,
                    temperature REAL,

                    original_system TEXT,
                    decomposed_json TEXT,
                    blocks_json TEXT,
                    optimized_system TEXT,
                    messages_list_json TEXT,
                    working_memory_text TEXT,

                    intent_result_json TEXT,
                    retrieved_memories_json TEXT,

                    llm_payload_json TEXT,
                    llm_response_content TEXT,
                    llm_reasoning_content TEXT,
                    llm_raw_response_json TEXT,
                    actual_backend TEXT,
                    fallback_triggered INTEGER DEFAULT 0,
                    fallback_reason TEXT,

                    format_passed INTEGER DEFAULT 1,
                    format_reason TEXT,
                    ooc_passed INTEGER DEFAULT 1,
                    ooc_reason TEXT,
                    content_passed INTEGER DEFAULT 1,
                    content_reason TEXT,

                    node_logs_json TEXT,

                    response_content TEXT,
                    latency_ms REAL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,

                    world_mode_data_json TEXT,

                    UNIQUE(session_id, turn_num)
                )
            """)

            # 索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_turn_session
                ON turn_records(session_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_turn_time
                ON turn_records(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_turn_session_turn
                ON turn_records(session_id, turn_num)
            """)

            # 保留旧表 state_snapshots（不删除，兼容已有数据）
            # 但新数据全部写入 turn_records

            conn.commit()
            logger.info("[Telemetry] turn_records 表初始化完成")
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 生命周期：创建记录
    # ------------------------------------------------------------------
    def start_turn(
        self,
        session_id: str,
        turn_num: int,
        mode: str = "chat",
        player_input: str = "",
        backend: str = "",
        model: str = "",
        temperature: float = 0.7,
    ) -> TurnRecord:
        """在请求入口处创建一条新记录。"""
        record = TurnRecord(
            session_id=session_id,
            turn_num=turn_num,
            timestamp=time.time(),
            mode=mode,
            player_input=player_input,
            backend=backend,
            model=model,
            temperature=temperature,
        )
        self._add_to_cache(record)
        logger.info(f"[Telemetry] 开始记录 | session={session_id} | turn={turn_num} | mode={mode}")
        return record

    # ------------------------------------------------------------------
    # 填充：Prompt 编译层
    # ------------------------------------------------------------------
    def set_prompt_compiled(self, record: TurnRecord, final_state: Dict[str, Any]) -> None:
        """从 LangGraph final_state 中提取 Prompt 编译产物。"""
        record.original_system = self._truncate(final_state.get("original_system", ""))
        record.decomposed_json = self._json_dumps(final_state.get("decomposed"))
        record.blocks_json = self._json_dumps(final_state.get("blocks"))
        record.optimized_system = self._truncate(final_state.get("optimized_system", ""))
        record.messages_list_json = self._json_dumps(final_state.get("messages_list"))
        record.working_memory_text = self._truncate(final_state.get("working_memory_text", ""))
        record.intent_result_json = self._json_dumps(final_state.get("intent_result"))
        record.retrieved_memories_json = self._json_dumps(final_state.get("retrieved_memories"))
        record.node_logs_json = self._json_dumps(final_state.get("node_logs", []))
        record._dirty = True
        logger.debug(f"[Telemetry] Prompt 编译产物已记录 | turn={record.turn_num}")

    # ------------------------------------------------------------------
    # 填充：LLM 交互层
    # ------------------------------------------------------------------
    def set_llm_payload(self, record: TurnRecord, payload: Dict[str, Any]) -> None:
        """记录发给 LLM 的请求体。"""
        record.llm_payload_json = self._json_dumps(payload)
        record._dirty = True

    def set_llm_response(
        self,
        record: TurnRecord,
        content: str = "",
        reasoning_content: str = "",
        raw_response: Optional[Dict[str, Any]] = None,
        actual_backend: str = "",
        fallback_triggered: bool = False,
        fallback_reason: str = "",
    ) -> None:
        """记录 LLM 响应。"""
        record.llm_response_content = self._truncate(content)
        record.llm_reasoning_content = self._truncate(reasoning_content)
        record.llm_raw_response_json = self._json_dumps(raw_response)
        record.actual_backend = actual_backend or record.backend
        record.fallback_triggered = fallback_triggered
        record.fallback_reason = fallback_reason
        if raw_response and "usage" in raw_response:
            usage = raw_response["usage"]
            record.prompt_tokens = usage.get("prompt_tokens", 0)
            record.completion_tokens = usage.get("completion_tokens", 0)
        record._dirty = True
        logger.debug(f"[Telemetry] LLM 响应已记录 | turn={record.turn_num} | backend={actual_backend}")

    # ------------------------------------------------------------------
    # 填充：质检层
    # ------------------------------------------------------------------
    def set_quality_check(self, record: TurnRecord, final_state: Dict[str, Any]) -> None:
        """记录质检结果。"""
        record.format_passed = final_state.get("format_passed", True)
        record.format_reason = final_state.get("format_reason", "")
        record.ooc_passed = final_state.get("ooc_passed", True)
        record.ooc_reason = final_state.get("ooc_reason", "")
        record.content_passed = final_state.get("content_passed", True)
        record.content_reason = final_state.get("content_reason", "")
        record._dirty = True

    # ------------------------------------------------------------------
    # 填充：World 模式
    # ------------------------------------------------------------------
    def set_world_mode_data(self, record: TurnRecord, data: Dict[str, Any]) -> None:
        """记录 World 模式的 Director 决策、NPC 输出等。"""
        record.world_mode_data_json = self._json_dumps(data)
        record._dirty = True

    # ------------------------------------------------------------------
    # 提交：异步写入数据库
    # ------------------------------------------------------------------
    def commit(
        self,
        record: TurnRecord,
        response_content: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        """请求结束时调用，异步写入 SQLite。"""
        record.response_content = self._truncate(response_content)
        record.latency_ms = latency_ms
        record._dirty = True

        # 异步写入（不阻塞主流程）
        asyncio.ensure_future(self._async_commit(record))
        logger.info(
            f"[Telemetry] 提交记录 | session={record.session_id} | "
            f"turn={record.turn_num} | latency={latency_ms:.1f}ms | "
            f"prompt={record.prompt_tokens} | completion={record.completion_tokens}"
        )

    async def _async_commit(self, record: TurnRecord) -> None:
        """异步写入数据库。"""
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._sync_write, record)
        except Exception as e:
            logger.warning(f"[Telemetry] 写入数据库失败（不影响主流程）: {e}")

    def _sync_write(self, record: TurnRecord) -> None:
        """同步写入 SQLite（在 executor 中执行）。"""
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO turn_records (
                    session_id, turn_num, timestamp, mode,
                    player_input, backend, model, temperature,
                    original_system, decomposed_json, blocks_json,
                    optimized_system, messages_list_json, working_memory_text,
                    intent_result_json, retrieved_memories_json,
                    llm_payload_json, llm_response_content, llm_reasoning_content,
                    llm_raw_response_json, actual_backend, fallback_triggered, fallback_reason,
                    format_passed, format_reason, ooc_passed, ooc_reason,
                    content_passed, content_reason,
                    node_logs_json,
                    response_content, latency_ms, prompt_tokens, completion_tokens,
                    world_mode_data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id, record.turn_num, record.timestamp, record.mode,
                    record.player_input, record.backend, record.model, record.temperature,
                    record.original_system, record.decomposed_json, record.blocks_json,
                    record.optimized_system, record.messages_list_json, record.working_memory_text,
                    record.intent_result_json, record.retrieved_memories_json,
                    record.llm_payload_json, record.llm_response_content, record.llm_reasoning_content,
                    record.llm_raw_response_json, record.actual_backend,
                    int(record.fallback_triggered), record.fallback_reason,
                    int(record.format_passed), record.format_reason,
                    int(record.ooc_passed), record.ooc_reason,
                    int(record.content_passed), record.content_reason,
                    record.node_logs_json,
                    record.response_content, record.latency_ms,
                    record.prompt_tokens, record.completion_tokens,
                    record.world_mode_data_json,
                ),
            )
            conn.commit()
            record._dirty = False
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------
    def _add_to_cache(self, record: TurnRecord) -> None:
        """将记录加入内存缓存（LRU）。"""
        key = f"{record.session_id}:{record.turn_num}"
        self._cache[key] = record
        if key in self._cache_order:
            self._cache_order.remove(key)
        self._cache_order.append(key)
        # 淘汰旧记录
        while len(self._cache_order) > CACHE_SIZE:
            old_key = self._cache_order.pop(0)
            self._cache.pop(old_key, None)

    def _get_from_cache(self, session_id: str, turn_num: int) -> Optional[TurnRecord]:
        """从缓存获取记录。"""
        key = f"{session_id}:{turn_num}"
        return self._cache.get(key)

    # ------------------------------------------------------------------
    # 查询接口（供 routes.py 使用）
    # ------------------------------------------------------------------
    def get_turn(self, session_id: str, turn_num: int) -> Optional[Dict[str, Any]]:
        """查询单轮次完整记录（先查缓存，再查数据库）。"""
        # 先查缓存
        record = self._get_from_cache(session_id, turn_num)
        if record:
            return self._record_to_dict(record)

        # 再查数据库
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM turn_records WHERE session_id = ? AND turn_num = ?",
                (session_id, turn_num),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)
        finally:
            conn.close()

    def get_turns_by_session(
        self, session_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """查询某会话的所有轮次（摘要列表）。"""
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, turn_num, timestamp, mode,
                       player_input, backend, model, latency_ms,
                       prompt_tokens, completion_tokens, fallback_triggered
                FROM turn_records
                WHERE session_id = ?
                ORDER BY turn_num DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_latest_turn(self, session_id: str) -> Optional[Dict[str, Any]]:
        """查询某会话的最新一轮。"""
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM turn_records WHERE session_id = ? ORDER BY turn_num DESC LIMIT 1",
                (session_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)
        finally:
            conn.close()

    def get_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """查询所有会话列表。"""
        conn = sqlite3.connect(str(DB_PATH))
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, MAX(timestamp) as last_time,
                       COUNT(*) as turn_count, MAX(turn_num) as max_turn
                FROM turn_records
                GROUP BY session_id
                ORDER BY last_time DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _truncate(text: str, max_len: int = MAX_TEXT_LENGTH) -> str:
        """截断超长文本，避免数据库单条记录过大。"""
        if not text:
            return text
        if len(text) > max_len:
            return text[:max_len] + f"\n... [截断，原长度 {len(text)} 字符]"
        return text

    @staticmethod
    def _json_dumps(obj: Any) -> str:
        """安全 JSON 序列化。"""
        if obj is None:
            return ""
        try:
            return json.dumps(obj, ensure_ascii=False, default=_json_default)
        except Exception as e:
            return json.dumps({"_error": f"序列化失败: {e}"}, ensure_ascii=False)

    @staticmethod
    def _record_to_dict(record: TurnRecord) -> Dict[str, Any]:
        """将 TurnRecord 转为 dict，并反序列化 JSON 字段。"""
        result = {}
        for k, v in asdict(record).items():
            if k.startswith("_"):
                continue
            if k.endswith("_json") and v:
                try:
                    result[k.replace("_json", "")] = json.loads(v)
                except json.JSONDecodeError:
                    result[k.replace("_json", "")] = {"_raw": v}
            else:
                result[k] = v
        return result

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """将 sqlite3.Row 转为 dict，并反序列化 JSON 字段。"""
        result = dict(row)
        # 反序列化 JSON 字段
        for key in list(result.keys()):
            if key.endswith("_json") and result[key]:
                try:
                    result[key.replace("_json", "")] = json.loads(result[key])
                except json.JSONDecodeError:
                    result[key.replace("_json", "")] = {"_raw": result[key]}
                del result[key]
        # 布尔值转换
        for key in ["fallback_triggered", "format_passed", "ooc_passed", "content_passed"]:
            if key in result:
                result[key] = bool(result[key])
        return result


# ------------------------------------------------------------------
# 全局单例
# ------------------------------------------------------------------
turn_recorder = TurnRecorder()


def _json_default(obj: Any) -> Any:
    """处理无法直接 JSON 序列化的对象。"""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

"""
AURA 实时日志流 — 内存环形缓冲区 + SSE 推送

设计原则：
  - 不依赖文件读取，日志产生时直接进入内存队列
  - 环形缓冲区防止内存无限增长（默认保留最近 2000 条）
  - SSE 长连接推送，前端无需轮询
  - 支持按节点类型过滤（director/memory/character/review/world/system）

用法：
  1. 在 logging.py 中注册 LogStreamHandler
  2. 前端通过 EventSource('/api/logs/stream') 接收
"""
import asyncio
import logging
import time
from collections import deque
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

# ------------------------------------------------------------------
# 数据模型
# ------------------------------------------------------------------

@dataclass
class LogEntry:
    """单条日志条目，与前端运行日志格式对齐。"""
    timestamp: float          # 时间戳（秒）
    time_str: str            # 格式化时间 HH:MM:SS.mmm
    node: str                # 节点类型：director/memory/character/review/world/system
    node_name: str           # 原始 logger 名
    level: str               # DEBUG/INFO/WARNING/ERROR
    action: str              # 主内容（日志消息，截断后用于列表展示）
    detail: str              # 附加详情（可空）
    duration_ms: int         # 耗时（如果日志中包含，否则 0）
    status: str              # ok/warn/error/running
    full_action: str = ""    # 完整日志消息（用于详情面板展开查看）

# ------------------------------------------------------------------
# 环形缓冲区
# ------------------------------------------------------------------

class LogRingBuffer:
    """
    线程安全的日志环形缓冲区。

    -  maxlen: 最大保留条数，超限自动淘汰最旧的
    -  支持按 node 类型过滤查询
    -  新日志到达时通知所有等待的 SSE 消费者
    """

    def __init__(self, maxlen: int = 2000):
        self._buffer: deque[LogEntry] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()
        self._waiters: List[asyncio.Queue] = []

    def append(self, entry: LogEntry) -> None:
        """追加一条日志，并通知所有等待者。"""
        self._buffer.append(entry)
        # 通知所有 SSE 消费者
        for q in list(self._waiters):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def get_recent(self, limit: int = 200, node_filter: Optional[str] = None) -> List[LogEntry]:
        """获取最近 N 条日志，可选按节点过滤。"""
        items = list(self._buffer)
        if node_filter and node_filter != 'all':
            items = [e for e in items if e.node == node_filter]
        return items[-limit:]

    def subscribe(self) -> asyncio.Queue:
        """订阅实时日志流，返回一个 asyncio.Queue。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._waiters.append(q)
        # 先推送缓冲区中的最近 100 条作为历史
        for e in list(self._buffer)[-100:]:
            try:
                q.put_nowait(e)
            except asyncio.QueueFull:
                break
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """取消订阅。"""
        if q in self._waiters:
            self._waiters.remove(q)


# 全局单例
log_ring = LogRingBuffer(maxlen=2000)


# ------------------------------------------------------------------
# 从日志文件加载历史日志（服务器重启后恢复）
# ------------------------------------------------------------------

def load_logs_from_file(log_path: str, limit: int = 500) -> int:
    """
    从文本日志文件加载最近 N 条历史记录到 LogRingBuffer。

    解析格式: 2026-05-03 15:27:53,437 - aura-completions - DEBUG - message
    支持多行消息（traceback 等）。

    返回成功加载的条数。
    """
    import os
    import re
    from datetime import datetime

    if not os.path.exists(log_path):
        return 0

    # 正则: 时间 - logger名 - 级别 - 消息
    log_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (.+?) - (DEBUG|INFO|WARNING|ERROR) - (.*)$"
    )

    entries: List[LogEntry] = []
    current_entry: Optional[LogEntry] = None

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n\r")
                m = log_re.match(line)
                if m:
                    # 保存上一条
                    if current_entry is not None:
                        entries.append(current_entry)

                    ts_str, logger_name, level_name, msg = m.groups()
                    try:
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S,%f")
                        timestamp = dt.timestamp()
                        time_str = dt.strftime("%H:%M:%S") + ".{:03d}".format(dt.microsecond // 1000)
                    except ValueError:
                        timestamp = time.time()
                        time_str = ts_str

                    # 节点映射
                    node = "system"
                    for prefix, ntype in LogStreamHandler.NODE_MAP.items():
                        if prefix in logger_name.lower():
                            node = ntype
                            break

                    # 状态
                    status = "error" if level_name == "ERROR" else "warn" if level_name == "WARNING" else "ok"

                    # 耗时提取
                    duration_ms = 0
                    for keyword in ["耗时", "elapsed", "latency", "ms"]:
                        if keyword in msg:
                            nums = re.findall(r"(\d+\.?\d*)\s*ms", msg)
                            if nums:
                                try:
                                    duration_ms = int(float(nums[-1]))
                                except ValueError:
                                    pass
                            break

                    current_entry = LogEntry(
                        timestamp=timestamp,
                        time_str=time_str,
                        node=node,
                        node_name=logger_name,
                        level=level_name,
                        action=msg[:200],
                        detail="",
                        duration_ms=duration_ms,
                        status=status,
                        full_action=msg,
                    )
                else:
                    # 多行消息的续行
                    if current_entry is not None:
                        current_entry.full_action += "\n" + line
                        # 如果 action 还没截满，也追加
                        if len(current_entry.action) < 200:
                            current_entry.action += "\n" + line[:200 - len(current_entry.action)]

            # 最后一条
            if current_entry is not None:
                entries.append(current_entry)

    except Exception as e:
        logging.getLogger("aura.log_stream").warning(f"[LogStream] 加载历史日志失败: {e}")
        return 0

    # 只保留最近 limit 条，按时间排序后写入 ring buffer
    entries = entries[-limit:]
    for e in entries:
        log_ring.append(e)

    loaded = len(entries)
    logging.getLogger("aura.log_stream").info(f"[LogStream] 从历史日志加载 {loaded} 条记录")
    return loaded


# ------------------------------------------------------------------
# 自定义 Handler：将标准日志转为 LogEntry 写入环形缓冲区
# ------------------------------------------------------------------

class LogStreamHandler(logging.Handler):
    """
    logging.Handler 子类，将日志记录转换为 LogEntry 并写入 LogRingBuffer。

    使用方式（在 setup_logging 中注册）：
        logger.addHandler(LogStreamHandler())
    """

    # logger 名 → 节点类型映射
    NODE_MAP: Dict[str, str] = {
        "aura-completions": "director",
        "aura-graph": "director",
        "aura-memory": "memory",
        "aura-telemetry": "system",
        "aura-world": "world",
        "aura-npc": "character",
        "aura-director": "director",
    }

    def __init__(self, level: int = logging.DEBUG):
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = self._record_to_entry(record)
            log_ring.append(entry)
        except Exception:
            self.handleError(record)

    def _record_to_entry(self, record: logging.LogRecord) -> LogEntry:
        # 解析 logger 名得到节点类型
        logger_name = record.name
        node = "system"
        for prefix, ntype in self.NODE_MAP.items():
            if prefix in logger_name.lower():
                node = ntype
                break

        # 解析耗时（如果消息中包含 "耗时" 或 "ms"）
        msg = record.getMessage()
        duration_ms = 0
        for keyword in ["耗时", "elapsed", "latency", "ms"]:
            if keyword in msg:
                # 简单提取数字
                import re
                nums = re.findall(r"(\d+\.?\d*)\s*ms", msg)
                if nums:
                    try:
                        duration_ms = int(float(nums[-1]))
                    except ValueError:
                        pass
                break

        # 状态判断
        level_name = record.levelname
        if level_name == "ERROR":
            status = "error"
        elif level_name == "WARNING":
            status = "warn"
        else:
            status = "ok"

        # 时间格式化
        t = time.localtime(record.created)
        time_str = time.strftime("%H:%M:%S", t) + ".{:03d}".format(int((record.created % 1) * 1000))

        return LogEntry(
            timestamp=record.created,
            time_str=time_str,
            node=node,
            node_name=logger_name,
            level=level_name,
            action=msg[:200],  # 截断避免列表过长
            detail="",          # 详情可后续扩展
            duration_ms=duration_ms,
            status=status,
            full_action=msg,  # 保留完整消息，详情面板展开时显示原始内容
        )


# ------------------------------------------------------------------
# SSE 生成器
# ------------------------------------------------------------------

async def log_stream_generator(node_filter: Optional[str] = None):
    """
    SSE 日志流生成器。

    用法（FastAPI）：
        return StreamingResponse(
            log_stream_generator(node_filter),
            media_type="text/event-stream",
        )
    """
    import json

    q = log_ring.subscribe()
    try:
        while True:
            entry: LogEntry = await asyncio.wait_for(q.get(), timeout=30.0)
            # 过滤
            if node_filter and node_filter != "all" and entry.node != node_filter:
                continue
            # 构造 SSE 数据
            data = {
                "time": entry.time_str,
                "node": entry.node,
                "node_name": entry.node_name,
                "action": entry.action,
                "detail": entry.detail,
                "duration": str(entry.duration_ms) + "ms" if entry.duration_ms else "—",
                "status": entry.status,
                "level": entry.level,
                "full_action": entry.full_action,
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    except asyncio.TimeoutError:
        # 30 秒无新日志，发送心跳保持连接
        yield "data: {}\n\n"
    finally:
        log_ring.unsubscribe(q)

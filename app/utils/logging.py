"""
AURA 日志配置模块

将日志配置从 app/api/completions.py 中拆离，统一管理：
  - RotatingFileHandler（文件轮转，5MB/文件，保留 3 个备份）
  - StreamHandler（控制台输出）
  - 第三方库日志抑制（httpx、httpcore）

用法：
    from app.utils.logging import setup_logging, get_logger

    # 在应用入口处调用一次
    setup_logging()

    # 获取模块级 logger
    logger = get_logger(__name__)
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

from app.core.config import settings

# 日志目录（相对于项目根目录）
LOG_DIR = "logs"

# 默认日志格式
_DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 全局标志，防止重复配置
_initialized = False


def setup_logging(
    log_dir: Optional[str] = None,
    log_file: str = "aura.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    encoding: str = "utf-8",
    file_level: int = logging.DEBUG,
    console_level: int = logging.INFO,
    log_format: str = _DEFAULT_FORMAT,
) -> None:
    """
    配置全局日志系统。

    参数：
        log_dir:      日志文件存放目录，默认 "logs"
        log_file:     日志文件名，默认 "aura.log"
        max_bytes:    单个日志文件最大字节数，默认 5MB
        backup_count: 保留的备份文件数，默认 3
        encoding:     文件编码，默认 utf-8
        file_level:   文件处理器级别，默认 DEBUG
        console_level:控制台处理器级别，默认 INFO
        log_format:   日志格式字符串
    """
    global _initialized
    if _initialized:
        return  # 已初始化，跳过

    _log_dir = log_dir or LOG_DIR
    os.makedirs(_log_dir, exist_ok=True)

    # 根日志器级别
    _log_level = logging.DEBUG if settings.debug_mode else logging.INFO

    # 文件处理器 - 带轮转
    _file_handler = RotatingFileHandler(
        os.path.join(_log_dir, log_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding=encoding,
    )
    _file_handler.setLevel(file_level)

    # 控制台处理器
    _console_handler = logging.StreamHandler()
    _console_handler.setLevel(console_level)

    # 统一格式
    _formatter = logging.Formatter(log_format)
    _file_handler.setFormatter(_formatter)
    _console_handler.setFormatter(_formatter)

    # 配置根日志器
    logging.basicConfig(
        level=_log_level,
        handlers=[_file_handler, _console_handler],
    )

    # 抑制第三方库的 DEBUG 日志（太嘈杂）
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # 注册实时日志流 Handler（内存缓冲区，供 SSE 推送）
    from app.utils.log_stream import LogStreamHandler
    _stream_handler = LogStreamHandler(level=logging.DEBUG)
    logging.getLogger().addHandler(_stream_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    获取一个模块级 logger。

    用法：
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)


def suppress_library_logging(library_name: str, level: int = logging.WARNING) -> None:
    """
    抑制指定第三方库的日志级别。

    参数：
        library_name: 库的 logger 名称，如 "httpx"
        level:        要设置的级别，默认 WARNING
    """
    logging.getLogger(library_name).setLevel(level)

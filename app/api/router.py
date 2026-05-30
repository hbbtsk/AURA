"""
AURA API 路由定义 + 请求/响应模型

职责：
  - Pydantic 数据模型（请求验证、响应序列化）
  - FastAPI APIRouter 实例
  - 轻量级端点（/models、/health）
  - 模型 → 后端映射工具
"""
import time
from typing import List, Literal, Optional, Dict, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, ConfigDict

from app.core.config import settings

router = APIRouter()


# --- 请求响应模型 ---
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    chat_id: Optional[str] = None  # TAVO 传来的稳定 chat ID，继续同一剧情


class ChatMessageResponse(BaseModel):
    role: str
    content: str


class Choice(BaseModel):
    index: int = 0
    message: ChatMessageResponse
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")  # 允许额外字段如 usage, system_fingerprint
    id: str = "aura-direct"
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[Choice]
    aura_debug: Optional[Dict[str, Any]] = None


# --- 平台模式请求模型 ---
class WorldCompletionRequest(BaseModel):
    """AURA 平台模式请求 — 文字冒险入口"""
    message: str                        # 玩家输入
    cartridge: Optional[str] = None     # 卡带名称（如 "rwby_beacon"），未加载时必填
    model: str = "deepseek-v4-flash"
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False
    max_tokens: Optional[int] = None
    player_entity_id: Optional[str] = "player"  # 玩家在世界中的实体 ID
    location_id: Optional[str] = None   # 指定地点，None 则使用当前场域


# 模型 → 后端名称映射
BACKEND_MAP = {
    # DeepSeek
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "deepseek-v4": "deepseek",
    "deepseek": "deepseek",
    # Kimi
    "kimi-k2.6": "kimi",
    "kimi-k2-turbo-preview": "kimi",
    "kimi": "kimi",
    # Gemini
    "gemini-2.0-flash": "gemini",
    "gemini": "gemini",
}


def get_backend_for_model(model: str) -> tuple[str, str]:
    """根据模型名称返回 (后端标识, 具体型号)

    例如:
        "deepseek-v4-pro"  -> ("deepseek", "deepseek-v4-pro")
        "kimi-k2.6"        -> ("kimi", "kimi-k2.6")
        "gemini"           -> ("gemini", "gemini")
        "unknown-model"    -> (settings.default_llm, "unknown-model")
    """
    if model in BACKEND_MAP:
        backend = BACKEND_MAP[model]
        return backend, model
    # 前缀匹配兜底
    for prefix, backend in [("deepseek", "deepseek"), ("kimi", "kimi"), ("gemini", "gemini")]:
        if model.startswith(prefix):
            return backend, model
    # 否则使用默认后端，型号透传（由下游决定是否 fallback 到默认型号）
    return settings.default_llm, model


# --- TAVO兼容接口 ---
@router.get("/models")
async def get_models():
    """获取可用模型列表（TAVO兼容性）

    仅返回 .env 中已配置 API Key 的模型。
    """
    from app.core.config import validate_llm_config

    config_status = validate_llm_config()

    all_models = [
        {"id": "deepseek-v4-flash", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
        {"id": "deepseek-v4-pro", "object": "model", "created": 1700000000, "owned_by": "deepseek"},
        {"id": "kimi-k2.6", "object": "model", "created": 1700000000, "owned_by": "kimi"},
        {"id": "kimi-k2-turbo-preview", "object": "model", "created": 1700000000, "owned_by": "kimi"},
        {"id": "gemini-2.0-flash", "object": "model", "created": 1700000000, "owned_by": "gemini"},
    ]

    # 过滤：只返回已配置 API Key 后端的模型
    available = [m for m in all_models if config_status.get(m["owned_by"], False)]

    return {"object": "list", "data": available}


# --- 健康检查 ---
@router.get("/health")
async def health_check():
    """健康检查"""
    from app.world import world_runtime
    from app.cartridge import CartridgeLoader

    loader = CartridgeLoader("cartridges")
    cartridges = loader.list_available()

    return {
        "status": "healthy",
        "service": "AURA",
        "version": "1.0.0",
        "mode": "dual",
        "modes": {
            "tavo": "LangGraph 状态机 + Prompt 编译器（/chat/completions）",
            "world": "Director + NPC Agent 文字冒险平台（/world/completions）",
        },
        "world_loaded": world_runtime.is_loaded(),
        "cartridge": world_runtime._cartridge_name if world_runtime.is_loaded() else None,
        "available_cartridges": cartridges,
        "debug": settings.debug_mode,
    }

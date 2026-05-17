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


# 模型 → 后端名称映射 (可根据需要扩展)
BACKEND_MAP = {
    "deepseek-v4-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    # 其他模型可在此添加
}


def get_backend_for_model(model: str) -> str:
    """根据模型名称返回对应的后端标识"""
    if model in BACKEND_MAP:
        return BACKEND_MAP[model]
    # 后备：如果模型名以 deepseek 开头，使用 deepseek 后端
    if model.startswith("deepseek"):
        return "deepseek"
    # 否则使用默认后端
    return settings.default_llm


# --- TAVO兼容接口 ---
@router.get("/models")
async def get_models():
    """获取可用模型列表（TAVO兼容性）"""
    return {
        "object": "list",
        "data": [
            {
                "id": "deepseek-v4-flash",
                "object": "model",
                "created": 1700000000,
                "owned_by": "deepseek"
            },
            {
                "id": "deepseek-v4-pro",
                "object": "model",
                "created": 1700000000,
                "owned_by": "deepseek"
            }
        ]
    }


# --- 健康检查 ---
@router.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "AURA",
        "version": "0.8.2",
        "mode": "langgraph-state-machine",
        "debug": settings.debug_mode
    }

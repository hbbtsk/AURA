"""
AURA配置管理
管理LLM API连接和多后端配置

设计原则：
- 所有 LLM API 调用的配置集中在此处管理
- 每个使用场景有独立的 LLMConfig 实例，避免互相影响
- 调用方统一使用 get_llm_config(scene) 获取配置，不再硬编码任何参数
"""
import os
import logging
from typing import Dict, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("aura.config")


# 项目根目录（config.py 从 app/core/ 需要上溯两层才到项目根）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LLMConfig(BaseSettings):
    """LLM后端配置"""
    base_url: str
    api_key: str
    model: str
    max_tokens: Optional[int] = 2048
    temperature: float = 0.7
    timeout: int = 30  # httpx 超时秒数（连接+读取）


class Settings(BaseSettings):
    """应用配置"""
    model_config = SettingsConfigDict(
        env_file=os.path.join(_PROJECT_ROOT, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ========== 调试 ==========
    debug_mode: bool = True

    # ========== 默认LLM ==========
    default_llm: str = "deepseek"

    # ========== DeepSeek ==========
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"

    # ========== Kimi ==========
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_api_key: str = ""
    kimi_model: str = "kimi-k2.6"

    # ========== Gemini ==========
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # ========== 场景参数：主对话（main） ==========
    llm_main_temperature: float = 0.7
    llm_main_max_tokens: int = 4096
    llm_main_timeout: int = 60          # 总超时（HTTP 连接+读取）
    llm_main_ttfb_timeout: int = 3      # 首 token 超时（秒）：超过此时间未收到任何响应则触发 fallback
    llm_main_fallback_provider: str = "kimi"  # 主模型 ttfb 超时后的备用后端

    # ========== 场景参数：记忆总结（summary） ==========
    llm_summary_temperature: float = 0.3
    llm_summary_max_tokens: int = 2048
    llm_summary_timeout: int = 30

    # ========== 场景参数：意图分析（intent） ==========
    llm_intent_temperature: float = 0.3  # 意图分析用低 temperature 保证一致性
    llm_intent_max_tokens: int = 1024  # 意图分析输出很小，不需要太多 token
    llm_intent_timeout: int = 15  # 非 reasoning 模型，15 秒足够

    # ========== 记忆总结 ==========
    memory_summary_interval: int = 5  # 每 N 轮对话触发一次记忆总结


# 全局单例
settings = Settings()


def get_llm_config(provider: str = None, scene: str = "main", model_name: str = None) -> Optional[LLMConfig]:
    """
    获取指定LLM后端 + 指定场景的配置

    Args:
        provider: LLM 后端名称（deepseek/kimi/gemini），None 则用 default_llm
        scene: 使用场景（main/summary/intent），不同场景有不同的 temperature/max_tokens/timeout
        model_name: 用户指定的具体型号（如 "deepseek-v4-pro"）。
                    传入时优先使用，否则 fallback 到 settings 中的默认型号。

    Returns:
        LLMConfig 实例，如果配置不完整则返回 None
    """
    provider = provider or settings.default_llm

    # 根据场景选择参数
    if scene == "main":
        temperature = settings.llm_main_temperature
        max_tokens = settings.llm_main_max_tokens
        timeout = settings.llm_main_timeout
    elif scene == "summary":
        temperature = settings.llm_summary_temperature
        max_tokens = settings.llm_summary_max_tokens
        timeout = settings.llm_summary_timeout
    elif scene == "intent":
        temperature = settings.llm_intent_temperature
        max_tokens = settings.llm_intent_max_tokens
        timeout = settings.llm_intent_timeout
    else:
        # 未知场景用安全默认值
        temperature = 0.7
        max_tokens = 2048
        timeout = 30

    if provider == "deepseek":
        if not settings.deepseek_api_key:
            logger.warning("[Config] DeepSeek API密钥未配置，返回 None")
            return None
        return LLMConfig(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            model=model_name or settings.deepseek_model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    elif provider == "gemini":
        if not settings.gemini_api_key:
            logger.warning("[Config] Gemini API密钥未配置，返回 None")
            return None
        return LLMConfig(
            base_url=settings.gemini_base_url,
            api_key=settings.gemini_api_key,
            model=model_name or settings.gemini_model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    elif provider == "kimi":
        if not settings.kimi_api_key:
            logger.warning("[Config] Kimi API密钥未配置，返回 None")
            return None
        # 用户指定型号优先；未指定时使用 settings 默认值
        actual_model = model_name or settings.kimi_model
        # 意图分析场景用快速版（无 reasoning），但仅在用户未显式指定型号时切换
        if scene == "intent" and model_name is None:
            actual_model = "kimi-k2-turbo-preview"
        return LLMConfig(
            base_url=settings.kimi_base_url,
            api_key=settings.kimi_api_key,
            model=actual_model,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    else:
        logger.warning(f"[Config] 不支持的LLM后端: {provider}，返回 None")
        return None


def validate_llm_config() -> Dict[str, bool]:
    """验证各LLM后端配置是否完整"""
    results = {}

    # 检查DeepSeek
    results["deepseek"] = bool(settings.deepseek_api_key)

    # 检查Kimi
    results["kimi"] = bool(settings.kimi_api_key)

    # 检查Gemini
    results["gemini"] = bool(settings.gemini_api_key)

    return results

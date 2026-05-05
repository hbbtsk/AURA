"""
AURA配置管理
管理LLM API连接和多后端配置
"""
import os
from typing import Dict, Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    """LLM后端配置"""
    base_url: str
    api_key: str
    model: str
    max_tokens: Optional[int] = 2048
    temperature: float = 0.7
    timeout: int = 30


class Settings(BaseSettings):
    """AURA全局配置"""
    
    # 数据库配置
    database_url: str = "sqlite+aiosqlite:///./aura.db"
    
    # LLM后端配置
    default_llm: str = "deepseek"
    
    # DeepSeek配置（生成主模型）
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = Field(default="sk-2a932b6c56db464d8e7e5c73d80bc182", env="DEEPSEEK_API_KEY")
    deepseek_model: str = "deepseek-v4-flash"
    # deepseek_model: str = "deepseek-v4-pro"
    
    # Kimi配置（记忆总结/便宜模型）
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_api_key: str = Field(default="", env="KIMI_API_KEY")
    kimi_model: str = "kimi-k2.6"
    
    # Gemini配置（暂时禁用）
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_api_key: str = Field(default="", env="GEMINI_API_KEY")
    gemini_model: str = "gemini-1.5-flash"
    
    # 记忆管理配置
    memory_summary_interval: int = 5  # 每 N 轮对话总结一次记忆
    
    # 调试配置
    debug_mode: bool = True
    log_requests: bool = True
    log_responses: bool = True
    
    # Tavo拦截配置
    enable_interception: bool = True
    debug_header: str = "X-Tavo-Debug"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 全局配置实例
settings = Settings()

def get_llm_config(provider: str = None) -> LLMConfig:
    """获取指定LLM后端的配置"""
    provider = provider or settings.default_llm
    
    if provider == "deepseek":
        return LLMConfig(
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            max_tokens=2048,
            temperature=0.7
        )
    elif provider == "gemini":
        # 检查Gemini配置是否完整
        if not settings.gemini_api_key:
            raise ValueError(f"Gemini API密钥未配置")
        return LLMConfig(
            base_url=settings.gemini_base_url,
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            max_tokens=2048,
            temperature=0.7
        )
    elif provider == "kimi":
        if not settings.kimi_api_key:
            raise ValueError(f"Kimi API密钥未配置")
        return LLMConfig(
            base_url=settings.kimi_base_url,
            api_key=settings.kimi_api_key,
            model=settings.kimi_model,
            max_tokens=4096,
            temperature=0.3  # 总结用低温度，更稳定
        )
    else:
        raise ValueError(f"不支持的LLM后端: {provider}")

def validate_llm_config() -> Dict[str, bool]:
    """验证各LLM后端配置是否完整"""
    results = {}
    
    # 检查DeepSeek
    results["deepseek"] = bool(settings.deepseek_api_key)
    
    # 检查Kimi
    results["kimi"] = bool(settings.kimi_api_key)
    
    # 检查Gemini（暂时禁用）
    results["gemini"] = False  # bool(settings.gemini_api_key)
    
    return results

# 环境变量模板
ENV_TEMPLATE = """
# AURA配置
AURA_DEBUG=false

# LLM API密钥
DEEPSEEK_API_KEY=your_deepseek_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

# 数据库配置（可选）
# DATABASE_URL=sqlite+aiosqlite:///./aura.db
"""
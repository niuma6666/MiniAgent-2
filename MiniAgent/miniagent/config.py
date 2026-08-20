"""
Configuration module providing LLM API parameter setup and loading functionality.
"""

import os
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass, field

# Try to import dotenv if installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Ignore if dotenv is not installed

# Configure logging - use existing logger instead of initializing again
from .logger import get_logger
logger = get_logger(__name__)

@dataclass
class LLMConfig:
    """LLM configuration（只保留真正被消费的字段：cli 构造 MiniAgent 时使用）"""
    
    model: str = "gpt-3.5-turbo"
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    organization: Optional[str] = None
    temperature: float = 0.7

@dataclass
class AgentConfig:
    """Agent configuration（字段与消费方一一对应：cli 构造 MiniAgent 时使用）"""
    
    llm: LLMConfig = field(default_factory=LLMConfig)
    system_prompt: str = "You are a helpful AI assistant."
    default_tools: List[str] = field(default_factory=list)
    enable_reflection: bool = False
    # 工具执行限制（cli 传给 MiniAgent；bash 工具的 BASH_TIMEOUT/BASH_MAX_OUTPUT
    # 由 code_tools.bash 直接读环境变量，此处不重复声明）
    tool_result_limit: int = 800000   # TOOL_RESULT_LIMIT: 工具结果回传上限（与 agent 默认对齐）
    max_context_messages: int = 20    # MAX_CONTEXT_MESSAGES: 消息数超限自动压缩
    confirm_dangerous: bool = True    # CONFIRM_DANGEROUS: 危险 bash 命令需确认

def load_config(config_path: Optional[str] = None) -> AgentConfig:
    """
    Load configuration from file
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Loaded configuration
    """
    # Default configuration
    config = AgentConfig()
    
    # Try to get API key from environment variables with multiple fallbacks
    # Priority order: LLM_API_KEY > OPENAI_API_KEY > DEEPSEEK_API_KEY > GEMINI_API_KEY
    # > GOOGLE_API_KEY > ANTHROPIC_API_KEY > AZURE_OPENAI_API_KEY
    env_api_key = (
        os.environ.get("LLM_API_KEY") or 
        os.environ.get("OPENAI_API_KEY") or 
        os.environ.get("DEEPSEEK_API_KEY") or 
        os.environ.get("GEMINI_API_KEY") or
        os.environ.get("GOOGLE_API_KEY") or
        os.environ.get("ANTHROPIC_API_KEY") or 
        os.environ.get("AZURE_OPENAI_API_KEY")
    )
    
    if env_api_key:
        config.llm.api_key = env_api_key
        
    # Try to get API base URL from environment variables with multiple fallbacks
    # Priority order: LLM_API_BASE > OPENAI_API_BASE > DEEPSEEK_API_BASE > ANTHROPIC_API_BASE > AZURE_OPENAI_ENDPOINT
    env_api_base = (
        os.environ.get("LLM_API_BASE") or 
        os.environ.get("OPENAI_API_BASE") or 
        os.environ.get("DEEPSEEK_API_BASE") or 
        os.environ.get("ANTHROPIC_API_BASE") or 
        os.environ.get("AZURE_OPENAI_ENDPOINT")
    )
    
    if env_api_base:
        config.llm.api_base = env_api_base
        
    # Try to get organization from environment variables
    env_organization = os.environ.get("LLM_ORGANIZATION") or os.environ.get("OPENAI_ORGANIZATION")
    if env_organization:
        config.llm.organization = env_organization
        
    # Try to get model from environment variables
    env_model = os.environ.get("LLM_MODEL")
    if env_model:
        config.llm.model = env_model
    
    # Load tool execution limits from environment
    # （BASH_TIMEOUT/BASH_MAX_OUTPUT 由 code_tools.bash 直接读取，此处不重复）
    def _safe_int(key: str, default: int) -> int:
        val = os.environ.get(key, "")
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            logger.warning(f"Invalid integer for {key}={val!r}, using default {default}")
            return default

    config.tool_result_limit = _safe_int("TOOL_RESULT_LIMIT", config.tool_result_limit)
    config.max_context_messages = _safe_int("MAX_CONTEXT_MESSAGES", config.max_context_messages)
    if os.environ.get("CONFIRM_DANGEROUS") is not None:
        config.confirm_dangerous = os.environ["CONFIRM_DANGEROUS"].lower() not in ("0", "false", "no")
    if os.environ.get("ENABLE_REFLECTION") is not None:
        config.enable_reflection = os.environ["ENABLE_REFLECTION"].lower() not in ("0", "false", "no")
        
    # Determine likely provider based on API_BASE and set appropriate default model
    if config.llm.api_base:
        api_base_lower = config.llm.api_base.lower()
        if "deepseek" in api_base_lower and not env_model:
            config.llm.model = "deepseek-chat"
        elif ("generativelanguage.googleapis.com" in api_base_lower or "gemini" in api_base_lower) and not env_model:
            config.llm.model = "gemini-2.5-flash"
        elif "anthropic" in api_base_lower and not env_model:
            config.llm.model = "claude-3-sonnet-20240229"
        elif "azure" in api_base_lower and not env_model:
            # Azure OpenAI requires deployment name instead of model name
            deployment_name = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
            if deployment_name:
                config.llm.model = deployment_name
                
    # If no configuration file, return default configuration
    if not config_path:
        return config
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            
        # Load LLM configuration
        if "llm" in config_data:
            for key, value in config_data["llm"].items():
                if hasattr(config.llm, key):
                    setattr(config.llm, key, value)
                    
        # Load agent configuration
        for key, value in config_data.items():
            if key != "llm" and hasattr(config, key):
                setattr(config, key, value)
                
        logger.info(f"Configuration loaded from {config_path}")
    except Exception as e:
        logger.error(f"Failed to load configuration from {config_path}: {e}")
        
    return config

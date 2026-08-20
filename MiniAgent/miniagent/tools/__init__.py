"""
Tools module for MiniAgent.

This module provides a set of tools that can be used by the agent to interact with the world.
"""

import inspect
from typing import Any, Callable, Dict, List, Optional

from ..logger import get_logger

logger = get_logger(__name__)

# Tool function type
ToolFunction = Callable[..., Any]

__all__ = [
    'register_tool',
    'get_registered_tools',
    'get_tool',
    'get_tool_description',
]

# Dictionary to store registered tools
_TOOLS: Dict[str, ToolFunction] = {}

def register_tool(func: ToolFunction) -> ToolFunction:
    """
    Decorator to register a function as a tool.
    
    Args:
        func: Function to register as a tool
        
    Returns:
        The registered function
    """
    _TOOLS[func.__name__] = func
    return func

def get_registered_tools() -> Dict[str, ToolFunction]:
    """
    Get all registered tools.
    
    Returns:
        Dictionary of tool name to function mapping
    """
    return _TOOLS

def get_tool(name: str) -> Optional[ToolFunction]:
    """
    Get a tool by name.
    
    Args:
        name: Name of the tool
        
    Returns:
        Tool function or None if not found
    """
    return _TOOLS.get(name)





def get_tool_description(tool: ToolFunction) -> Dict[str, Any]:
    """
    Get description of a tool.
    
    Args:
        tool: Tool function
        
    Returns:
        Dictionary with tool description
    """
    # Get function signature
    sig = inspect.signature(tool)
    
    # Get docstring
    doc = inspect.getdoc(tool) or ""
    
    # Get parameters
    properties = {}
    required = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
            
        param_desc = {"type": "string"}  # Default type
        
        # Check if parameter has a type annotation
        if param.annotation != inspect.Parameter.empty:
            # Convert type annotation to string
            # Check compound types (List, Dict) BEFORE simple types
            # to avoid e.g. List[str] matching "str" first
            type_str = str(param.annotation)
            if "List" in type_str or "list" in type_str:
                param_desc["type"] = "array"
            elif "Dict" in type_str or "dict" in type_str:
                param_desc["type"] = "object"
            elif "bool" in type_str:
                param_desc["type"] = "boolean"
            elif "int" in type_str:
                param_desc["type"] = "integer"
            elif "float" in type_str:
                param_desc["type"] = "number"
            elif "str" in type_str:
                param_desc["type"] = "string"
        
        # Check if parameter has a default value
        if param.default != inspect.Parameter.empty:
            param_desc["default"] = param.default
        else:
            # Required parameter
            required.append(name)
        
        properties[name] = param_desc
    
    return {
        "name": tool.__name__,
        "description": doc,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required
        }
    }


# Try to import built-in tools, handle import errors gracefully
try:
    from .basic_tools import (
        calculator, get_current_time, system_info, file_stats,
        disk_usage, process_list, system_load, web_search, http_request,
        open_browser, open_app, clipboard_copy, clipboard_read,
        create_docx, env_get, env_set
    )
    logger.debug("Imported all tools from basic_tools")
except ImportError as e:
    logger.warning(f"Failed to import some tools: {e}")

# Code tools (optional import so the package remains robust)
try:
    from .code_tools import read, write, edit, glob, grep, bash
    logger.debug("Imported all tools from code_tools")
except ImportError as e:
    logger.warning(f"Failed to import code tools: {e}")


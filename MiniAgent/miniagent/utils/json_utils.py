"""JSON utilities module, providing parsing and validation functions for JSON"""

import json
import re
from typing import Dict, Any, Union, List

from ..logger import get_logger

logger = get_logger(__name__)


def parse_json(json_str: str) -> Union[Dict, List]:
    """
    Parse JSON string, handling various error cases
    
    Args:
        json_str: JSON string
        
    Returns:
        Parsed dictionary or list
    """
    if not json_str:
        logger.debug("Received empty JSON string")
        return {}
    
    try:
        # First try direct parsing
        return json.loads(json_str)
    except json.JSONDecodeError:
        logger.debug(f"JSON parsing failed, attempting to fix: {truncate_message_content(json_str)}")
        
        # Try with strict=False to allow control characters (newlines in strings)
        try:
            return json.loads(json_str, strict=False)
        except json.JSONDecodeError:
            pass

        # Try to fix invalid backslash escapes (e.g. Windows paths like D:\Internet\Temp
        # where \I and \T are not valid JSON escapes) — common in LLM output.
        try:
            fixed = _fix_invalid_escapes(json_str)
            return json.loads(fixed)
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Try to fix unescaped newlines in string values
        # This is common when LLM generates multi-line code
        try:
            # Replace actual newlines within string values with \\n
            fixed_json = _fix_unescaped_newlines(json_str)
            return json.loads(fixed_json)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try to fix common issues and parse again
        # 1. Try to extract JSON from text
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```|```([\s\S]*?)```|(\{[\s\S]*\})', json_str)
        if json_match:
            extracted_json = json_match.group(1) or json_match.group(2) or json_match.group(3)
            try:
                return json.loads(extracted_json)
            except json.JSONDecodeError:
                try:
                    return json.loads(extracted_json, strict=False)
                except json.JSONDecodeError:
                    try:
                        fixed = _fix_unescaped_newlines(extracted_json)
                        return json.loads(fixed)
                    except (json.JSONDecodeError, ValueError):
                        pass
        
        # 2. Try to fix quote issues
        fixed_json = json_str.replace("'", '"')
        try:
            return json.loads(fixed_json)
        except json.JSONDecodeError:
            pass
        
        # 3. Try to fix trailing comma issues
        fixed_json = re.sub(r',\s*}', '}', json_str)
        fixed_json = re.sub(r',\s*]', ']', fixed_json)
        try:
            return json.loads(fixed_json)
        except json.JSONDecodeError:
            logger.debug(f"All JSON parse attempts failed for input: {truncate_message_content(json_str)}")
            return {}


def _fix_invalid_escapes(json_str: str) -> str:
    """
    Fix invalid backslash escapes in a JSON string.

    LLMs frequently emit Windows paths (e.g. ``D:\\Internet\\Temp``) with a single
    backslash: ``"path": "D:\\Internet\\Temp\\out.md"``. In strict JSON, ``\\I`` and
    ``\\T`` are invalid escapes and ``json.loads`` rejects the whole document.

    Valid escapes are kept as-is: ``\\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX``.
    Any other ``\\x`` is rewritten so the backslash becomes a literal ``\\``
    (JSON-escaped), preserving the intended character.
    """
    result = []
    i = 0
    n = len(json_str)
    valid = ('"', "\\", "/", "b", "f", "n", "r", "t", "u")
    while i < n:
        ch = json_str[i]
        if ch == "\\" and i + 1 < n and json_str[i + 1] in valid:
            result.append(ch)
            result.append(json_str[i + 1])
            i += 2
            continue
        if ch == "\\" and i + 1 < n:
            # Invalid escape: keep the backslash as a literal (escaped in JSON)
            result.append("\\\\")
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _fix_unescaped_newlines(json_str: str) -> str:
    """
    Fix unescaped newlines inside JSON string values.
    This handles the common case where LLM generates multi-line code
    without properly escaping newlines.
    """
    result = []
    in_string = False
    escape_next = False
    
    for char in json_str:
        if escape_next:
            result.append(char)
            escape_next = False
            continue
            
        if char == '\\':
            result.append(char)
            escape_next = True
            continue
            
        if char == '"':
            in_string = not in_string
            result.append(char)
            continue
            
        if in_string and char == '\n':
            result.append('\\n')
            continue
            
        if in_string and char == '\r':
            continue  # Skip carriage returns
            
        if in_string and char == '\t':
            result.append('\\t')
            continue
            
        result.append(char)
    
    return ''.join(result)

def truncate_message_content(content: str, max_length: int = 100) -> str:
    """
    Truncate message content for log display
    
    Args:
        content: Message content
        max_length: Maximum length
        
    Returns:
        Truncated content
    """
    if not content or not isinstance(content, str):
        return str(content)
    if len(content) <= max_length:
        return content
    return content[:max_length] + "..."





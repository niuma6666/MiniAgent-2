"""Main module of MiniAgent, providing core Agent functionality"""

import os
import json
import re
import time
from typing import Any, Callable, Dict, Generator, List, Optional
from tenacity import retry, stop_after_attempt, wait_random_exponential

from .logger import get_logger
from .utils.json_utils import parse_json
from .utils.text_utils import smart_truncate
from .utils.reflector import Reflector
from .tools import get_registered_tools, get_tool, get_tool_description

from rich.console import Console
console = Console()

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Dangerous command patterns for tool confirmation
# ---------------------------------------------------------------------------

_DANGEROUS_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*f|-[a-zA-Z]*r|--force|--recursive)\b",  # rm -rf
    r"\brm\s+-[a-zA-Z]*\s+/",      # rm anything under /
    r"\bmkfs\b",                     # format filesystem
    r"\bdd\s+",                      # disk dump
    r":>\s*/",                       # truncate root files
    r"\bchmod\s+-R\s+777\b",        # open permissions recursively
    r"\bchown\s+-R\b",              # recursive ownership change
    r">\s*/etc/",                    # overwrite system config
    r"\bsudo\b",                     # sudo commands
    r"\bshutdown\b|\breboot\b",     # system control
    r"\bkill\s+-9\b",              # force kill
    r"\bpkill\b|\bkillall\b",      # mass kill
    r"\bcurl\b.*\|\s*\bsh\b",      # pipe curl to shell
    r"\bwget\b.*\|\s*\bsh\b",      # pipe wget to shell
    r"[;&|]\s*\brm\s",             # chained rm after other commands
]

_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS), re.IGNORECASE)

class MiniAgent:
    """
    Main MiniAgent class, providing core functionality for LLM interaction and tool calling
    """

    # Template for text-mode system prompt (tools list injected at runtime)
    
    _TEXT_MODE_PROMPT = """\
{base_prompt}

You are a helpful, empathetic assistant with access to tools. Follow these rules:

Available tools: {tools_prompt}

1. **Tool format** (required):
   TOOL: <tool_name>
   ARGS: {{"parameter_name": "parameter_value"}}
   - Use double quotes for strings, no quotes for numbers.
   - For multiline content, use \n for newlines.
   - For example, when the user asks "Create a file hello.py", you should respond:
   TOOL: write
   ARGS: {{"path": "hello.py", "content": "print('Hello World')"}}

2. **When to search**:
   - For factual, recent, or verifiable info (news, data, citations), ALWAYS use tavily_search or web_search first.
   - Use internal knowledge only for common sense, or if search returns nothing.
   - If unsure about a citation, verify via search before quoting.

3. **Batch search** (for efficiency):
   - Combine multiple related queries with ` | ` (OR) in one call, e.g., `"paper A" | "paper B"`.
   - Max 400 characters per call; split if exceeded.

4. **Response & Termination**:
   - After executing a tool, explain the result clearly.
   - **When you believe you have fully answered the user's question (whether or not you used a tool), you MUST start your final response with `FINAL_ANSWER:`**.
   - After using `FINAL_ANSWER:`, do NOT call any more tools. This is the only way to end the task.

5. **Final Output Format**:
   - Use Simplified Chinese as the primary language. Proper nouns, technical terms, acronyms, and file/API names may remain in English.
   - Use markdown for readability when helpful.
   - **Length discipline**: If the user specifies a length (e.g. "800字", "2000 words"), your final answer MUST stay close to it (allow ±15%). Never write a much longer essay than requested. When in doubt, be concise rather than verbose.

6. **File writing safety**:
   - Before using `write` or `edit` tools to create or modify files, ALWAYS ask the user for confirmation first (e.g., "I'll write this to {{path}}, ok?").
   - Only proceed if the user agrees. If the user didn't explicitly request a file, output the content directly in your response instead.
   - This rule does NOT apply to reading files, searching, or running non-destructive commands.

7. **Interpersonal skills**:
   - Greet briefly when appropriate.
   - If request is vague, ask clarifying questions BEFORE using tools.
   - Acknowledge user's emotions (e.g., "I understand you're looking for...").
   - Respond naturally, politely, and helpfully.


Remember: Be accurate, concise, and human-like. If unsure, ask rather than guess."""

    # Native FC 模式专用模板：不需要文本 TOOL: 格式，改用 tool_schemas 调用
    _NATIVE_MODE_PROMPT = """\
{base_prompt}

You are a helpful, empathetic assistant with access to tools. Follow these rules:

You have the following tools available (use them via the tool-calling interface, never print TOOL:/ARGS: text): {tools_prompt}

1. **Tool usage**:
   - When you need information or need to perform an action, call the appropriate tool with correct arguments.
   - Wait for the tool result, then continue.

2. **When to search**:
   - For factual, recent, or verifiable info (news, data, citations), ALWAYS use tavily_search or web_search first.
   - Use internal knowledge only for common sense, or if search returns nothing.

3. **Response & Termination**:
   - After executing a tool, explain the result clearly.
   - **When you believe you have fully answered the user's question (whether or not you used a tool), you MUST start your final response with `FINAL_ANSWER:`**.
   - After using `FINAL_ANSWER:`, do NOT call any more tools. This is the only way to end the task.

4. **Final Output Format**:
   - Use Simplified Chinese as the primary language. Proper nouns, technical terms, acronyms, and file/API names may remain in English.
   - Use markdown for readability when helpful.
   - **Length discipline**: If the user specifies a length (e.g. "800字", "2000 words"), your final answer MUST stay close to it (allow ±15%). Never write a much longer essay than requested. When in doubt, be concise rather than verbose.

5. **File writing safety**:
   - Before using `write` or `edit` tools to create or modify files, ALWAYS ask the user for confirmation first.
   - Only proceed if the user agrees. If the user didn't explicitly request a file, output the content directly in your response instead.

Remember: Be accurate, concise, and human-like. If unsure, ask rather than guess."""



    
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        system_prompt: str = "You are a helpful assistant that can use tools to get information and perform tasks.",
        use_reflector: bool = False,
        confirm_dangerous: bool = False,
        confirm_callback: Optional[Callable[[str], bool]] = None,
        confirm_file_writes: Optional[bool] = None,
        auto_route_skills: bool = True,
        llm_route_skills: Optional[bool] = None,
        **kwargs
    ):
        """
        Initialize MiniAgent
        
        Args:
            model: Model name, e.g. "gpt-3.5-turbo", "deepseek-chat"
            api_key: API key for the model provider
            base_url: Base URL for the model provider
            temperature: Model temperature
            system_prompt: System prompt to use for the agent
            use_reflector: Whether to use the Reflector to improve reasoning
            confirm_dangerous: If True, dangerous bash commands require confirmation
            confirm_callback: Function(cmd) -> bool for confirmation. Defaults to stdin prompt.
            confirm_file_writes: If True, write/edit tool calls require user confirmation
                before touching the filesystem (default: env CONFIRM_FILE_WRITES, or True).
            auto_route_skills: If True, automatically load a matching skill from the user's
                query before the agent loop starts (no longer relies on the LLM deciding
                on its own to call use_skill).
            llm_route_skills: If True, skill routing is decided by the LLM (send the skill
                list + user query to the model, it picks one skill or "none"), with the
                keyword scoring system only as a fallback when the LLM call fails or its
                answer is unparseable. Defaults to env LLM_ROUTE_SKILLS (enabled unless "0").
            **kwargs: Additional parameters for the OpenAI client
        """
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self._base_temperature = temperature  # 保存初始基准温度，用于重置
        self.system_prompt = system_prompt
        self.auto_route_skills = auto_route_skills
        # LLM 路由：默认开启（把 skill 列表 + 用户问题交给模型决策，评分系统仅兜底）。
        # 可用 LLM_ROUTE_SKILLS=0 关闭，退回纯评分路由。
        if llm_route_skills is None:
            llm_route_skills = os.environ.get("LLM_ROUTE_SKILLS", "1").lower() not in ("0", "false", "no")
        self.llm_route_skills = llm_route_skills

        

        # ========== 插入开始：注入 Skill 目录到 system_prompt ==========
        from .skills import _SKILLS
        skills_catalog_parts = []
        for name, skill in _SKILLS.items():
            desc = skill.description or "无描述"
            skills_catalog_parts.append(f"- {name}: {desc}")
        if skills_catalog_parts:
            skills_catalog = "\n".join(skills_catalog_parts)
            self.system_prompt = self.system_prompt + "\n\n## 可用技能 (Available Skills)\n" + skills_catalog + "\n当用户问题匹配某技能时，可调用 use_skill 工具加载。"
        # ========== 插入结束 ==========

        

        self.tools = []
        self.client = None
        self.use_reflector = use_reflector
        self.confirm_dangerous = confirm_dangerous
        self.confirm_callback = confirm_callback
        # 文件写入确认：默认开启（用户明确要求 write/edit 前必须先征求同意），
        # 可用 CONFIRM_FILE_WRITES=0 关闭（如无人值守/自动化场景）
        if confirm_file_writes is None:
            confirm_file_writes = os.environ.get("CONFIRM_FILE_WRITES", "1").lower() not in ("0", "false", "no")
        self.confirm_file_writes = confirm_file_writes
        self._skill_tool_whitelist = None   # 存储技能允许的工具名称列表，None表示不过滤
        
        # 工具描述 prompt 缓存（_build_tools_prompt 的结果，按工具集变化失效）
        self._tools_prompt_cache: Optional[str] = None
        self._tools_prompt_cache_key: Optional[tuple] = None
        
        # Cache config limits (read env vars once, not per-request)
        self._max_context_messages = int(os.environ.get("MAX_CONTEXT_MESSAGES", "20"))
        self._tool_result_limit = int(os.environ.get("TOOL_RESULT_LIMIT", "800000"))     #16000改到800000，同步改.env文件
        
        # Initialize the LLM client
        self._init_llm_client()
        
        # Initialize reflector if enabled
        if use_reflector:
            self.reflector = Reflector(self.client, self.model)
        else:
            self.reflector = None


        # ==================== 【改动 1 插入开始】 ====================
        # 注册内置的 use_skill 工具
        self.add_tool({
            "name": "use_skill",
            "description": "加载指定名称的技能。当用户的问题匹配某个特定技能（如 coder、researcher、literature_reviewer）时，调用此工具加载其完整指引。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "技能名称，例如 'coder', 'researcher', 'literature_reviewer'"
                    }
                },
                "required": ["skill_name"]
            },
            "executor": self._use_skill_handler  # 指向下面的处理方法
        })
        # 初始化一个占位，用于存储当前加载的技能
        self._loaded_skill = None
        # ==================== 【改动 1 插入结束】 ====================

        
        logger.info(f"MiniAgent initialized, model: {model}, base URL: {base_url or 'default'}, temperature: {temperature}, reflector: {use_reflector}")
    
    def _init_llm_client(self):
        """Initialize the LLM client (OpenAI-compatible for all providers)"""
        try:
            import openai as _openai
            self.client = _openai.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            logger.info(f"LLM client initialized: model={self.model}, base_url={self.base_url or 'default'}")
        except ImportError:
            logger.error("OpenAI package not installed. Please run 'uv sync' or 'pip install -r requirements.txt'")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize LLM client: {e}")
            raise
    
    def add_tool(self, tool: Dict[str, Any]) -> None:
        """
        Add a tool to the agent
        
        Args:
            tool: Tool definition, containing name, description, and executor
        """
        if not isinstance(tool, dict):
            raise TypeError("Tool must be a dictionary type")
            
        required_keys = ["name", "description", "executor"]
        for key in required_keys:
            if key not in tool:
                raise ValueError(f"Tool is missing a required field: {key}")
                
        self.tools.append(tool)
        # 工具集变化，使工具描述缓存失效
        self._tools_prompt_cache = None
        self._tools_prompt_cache_key = None
        logger.debug(f"Added tool: {tool['name']}")
    
    def load_builtin_tool(self, tool_name: str) -> bool:
        """
        Load a built-in tool
        
        Args:
            tool_name: Tool name
            
        Returns:
            Whether the load was successful
        """
        tool_func = get_tool(tool_name)
        if tool_func:
            # Create tool definition
            tool_desc = get_tool_description(tool_func)
            tool = {
                "name": tool_desc["name"],
                "description": tool_desc["description"],
                "parameters": tool_desc.get("parameters", {}),
                "executor": tool_func
            }
            self.add_tool(tool)
            logger.info(f"Loaded built-in tool: {tool_name}")
            return True
        else:
            logger.warning(f"Built-in tool not found: {tool_name}")
            return False
    
    def get_available_tools(self) -> List[str]:
        """
        Get all available built-in tool names
        
        Returns:
            List of tool names
        """
        return list(get_registered_tools().keys())

    def load_all_tools(self) -> None:
        """Load all registered built-in tools into this agent."""
        for name in self.get_available_tools():
            self.load_builtin_tool(name)


    
    
    
    # ==================== 【改动 2 插入开始】 ====================
    
    def _reset_skill_state(self):
        """
        重置技能加载状态，确保每次新的 run() 调用不受上一次技能残留影响。
        """
        self._loaded_skill = None
        self._skill_tool_whitelist = None
        # 恢复用户最初设定的温度，避免被上次技能修改
        self.temperature = self._base_temperature
        # 技能变化，工具描述缓存失效
        self._tools_prompt_cache = None
        self._tools_prompt_cache_key = None
        logger.debug("Skill state has been reset.")

    
    
    
    def _use_skill_handler(self, **kwargs) -> str:
        """
        处理 use_skill 工具调用的执行器。
        只负责加载 Skill 对象并暂存到 self._loaded_skill，不修改 messages。
        主循环会检测到这个变量并注入 prompt。
        """

        from .skills import get_skill, _SKILLS
        
        start = time.perf_counter()
        skill_name = kwargs.get("skill_name") or kwargs.get("skill")  # 从 kwargs 提取

        skill = get_skill(skill_name)
        if not skill:
            # 修复：加载失败不应清空已加载的 skill 状态（原代码调用 _reset_skill_state 会误清）
            console.print(f"[dim]❌ Skill load FAILED: '{skill_name}' (not found)[/dim]")
            return f"错误：未找到技能 '{skill_name}'。可用技能：{list(_SKILLS.keys())}"
    
        self._loaded_skill = skill
        self._skill_tool_whitelist = skill.tools
        if skill.temperature is not None:
            self.temperature = skill.temperature

        elapsed = time.perf_counter() - start
        console.print(f"[dim]✅ SKILL LOADED: '{skill_name}' | temp={self.temperature} | tools_whitelist={self._skill_tool_whitelist} | max_iter={skill.max_iterations} | elapsed={elapsed:.3f}s[/dim]")
        
        return f"✅ 成功加载技能 '{skill_name}'。请根据该技能的指引执行任务。"
    # ==================== 【改动 2 插入结束】 ====================


    def _get_filtered_tools(self) -> List[Dict]:
        """
        根据当前加载的技能返回过滤后的工具列表。
        如果技能未指定白名单（_skill_tool_whitelist 为 None），则返回全部工具。
        """
        if self._loaded_skill and self._skill_tool_whitelist is not None:
            return [t for t in self.tools if t["name"] in self._skill_tool_whitelist]
        return self.tools

  
    def _build_tools_prompt(self) -> str:
        """
        构建工具描述字符串，供 system prompt 使用。
        如果当前加载了技能且技能指定了工具白名单，则只显示白名单中的工具。

        使用缓存：同一技能/同一工具集下只构建一次，避免每轮迭代重复拼接。
        """
        # 获取当前应该展示的工具列表（根据技能白名单过滤）
        tools_to_show = self._get_filtered_tools()

        # 缓存键：白名单工具名序列（同一技能下工具不变，无需重复构建）
        cache_key = tuple(t["name"] for t in tools_to_show)
        if self._tools_prompt_cache_key == cache_key and self._tools_prompt_cache is not None:
            return self._tools_prompt_cache

        # 如果最终列表为空，直接返回提示信息（避免空描述）
        if not tools_to_show:
            self._tools_prompt_cache, self._tools_prompt_cache_key = "(没有可用工具)", cache_key
            return self._tools_prompt_cache

        tools_desc = []
        for tool in tools_to_show:
            params = tool.get("parameters", {})
            param_desc = []
            # 构建参数描述
            for name, schema in params.get("properties", {}).items():
                required = name in params.get("required", [])
                param_desc.append(f"    - {name}: {schema.get('description', '')} {'(required)' if required else ''}")
            params_text = "\n".join(param_desc) if param_desc else "    (none)"
        
            # 组装单个工具的描述（格式与原来保持一致）
            desc = (
                f"\n            Tool: {tool['name']}\n"
                f"            Description: {tool['description']}\n"
                f"            Parameters:\n"
                f"            {params_text}\n"
                f"            "
            )
            tools_desc.append(desc)
    
        result = "\n".join(tools_desc)
        self._tools_prompt_cache, self._tools_prompt_cache_key = result, cache_key
        return result
    



    def _parse_tool_call(self, content: str) -> Optional[Dict]:
        """Parse the FIRST tool call from LLM response (backward-compatible wrapper).

        Delegates to _parse_all_tool_calls and returns the first result, or None.
        """
        calls = self._parse_all_tool_calls(content)
        return calls[0] if calls else None

    def _parse_all_tool_calls(self, content: str) -> List[Dict]:
        """
        Parse ALL tool calls from LLM response (handles batch calls).

        Supports these text patterns:
          1. TOOL: <name>  ARGS: {json}
          2. <TOOL: name>  ARGS: {json}   (deepseek-v4-flash style, with angle brackets)
          3. Tool/工具: <name>  Args/参数: {json}
          4. MCP DSML XML format

        When the model emits multiple TOOL blocks in one response, all are parsed
        and returned in order. The caller (run_with_tools) executes them sequentially.

        Args:
            content: LLM response content

        Returns:
            List of tool call dicts, each with "name" and "arguments".
        """
        logger.debug(f"Parsing tool calls from content (length={len(content)})")
        calls: List[Dict] = []

        # ========== 1) MCP DSML XML format ==========
        xml_pattern = re.compile(
            r'<\uFF5C\uFF5CDSML\uFF5C\uFF5Ctool_calls>\s*(.*?)\s*</\uFF5C\uFF5CDSML\uFF5C\uFF5Ctool_calls>',
            re.DOTALL
        )
        xml_match = xml_pattern.search(content)
        if xml_match:
            inner = xml_match.group(1)
            invoke_pattern = re.compile(
                r'<\uFF5C\uFF5CDSML\uFF5C\uFF5Cinvoke\s+name="([^"]+)"\s*>(.*?)</\uFF5C\uFF5CDSML\uFF5C\uFF5Cinvoke>',
                re.DOTALL
            )
            invokes = invoke_pattern.findall(inner)
            for name, args_xml in invokes:
                param_pattern = re.compile(
                    r'<\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter\s+name="([^"]+)"(?:\s+string="true")?\s*>(.*?)</\uFF5C\uFF5CDSML\uFF5C\uFF5Cparameter>',
                    re.DOTALL
                )
                params = param_pattern.findall(args_xml)
                args = {pname: pvalue.strip() for pname, pvalue in params}
                calls.append({"name": name, "arguments": args})
                logger.info(f"Parsed MCP tool call: {name} with {len(args)} args")
            if calls:
                return calls

        # ========== 2) Standard TOOL: / <TOOL: > patterns ==========
        registered_tool_names = [tool["name"] for tool in self.tools]

        # Regex handles: TOOL:, <TOOL:, Tool:, 工具:  with optional > after name
        tool_start_patterns = [
            re.compile(r"<?TOOL:\s*(\w+)\s*>?\s*ARGS:\s*", re.IGNORECASE),
            re.compile(r"(?:Tool|工具|USE TOOL|使用工具|工具名称|TOL):\s*(\w+)\s*>?\s*(?:ARGS|Args|参数|WITH ARGS|工具参数|Arguments):\s*", re.IGNORECASE),
        ]

        for pattern in tool_start_patterns:
            for match in pattern.finditer(content):
                name = match.group(1)
                remaining = content[match.end():]
                args_str = self._extract_balanced_json(remaining)
                if not args_str:
                    logger.debug(f"Found TOOL header '{name}' but no balanced JSON after it")
                    continue

                # Try strict JSON parse first, then loose
                try:
                    args = json.loads(args_str)
                    calls.append({"name": name, "arguments": args})
                    logger.info(f"Parsed tool call: {name} with {len(args)} args")
                except json.JSONDecodeError:
                    args = parse_json(args_str)
                    if args:
                        calls.append({"name": name, "arguments": args})
                        logger.info(f"Parsed tool call (loose): {name} with {len(args)} args")
                    else:
                        logger.warning(f"Failed to parse args for {name}: {args_str[:100]}...")

            if calls:
                return calls  # Return as soon as a pattern family matches

        # ========== 3) Fallback: func({...}) / func: {...} ==========
        fallback_patterns = [
            r'(\w+)\s*\(\s*(\{.*?\})\s*\)',
            r'(\w+)[：:]\s*(\{.*\})',
            r'(\w+)\s*\(\s*([^)]*)\)',
        ]
        for pattern in fallback_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                name = match.group(1)
                args_candidate = match.group(2).strip()
                if name not in registered_tool_names:
                    continue
                try:
                    if not args_candidate.startswith('{'):
                        args_candidate = '{' + args_candidate + '}'
                    args = json.loads(args_candidate)
                    calls.append({"name": name, "arguments": args})
                    return calls
                except json.JSONDecodeError:
                    args = parse_json(args_candidate)
                    if args:
                        calls.append({"name": name, "arguments": args})
                        return calls

        # ========== Warning if TOOL: was present but nothing parsed ==========
        if not calls and re.search(r'</?TOOL:|工具:', content, re.IGNORECASE):
            console.print(f"[dim]⚠️ 无法解析的工具调用内容(前200字符): {content[:200]}[/dim]")

        return calls
        



    def _extract_balanced_json(self, text: str) -> Optional[str]:
        """
        Extract a balanced JSON object from text by counting braces.

        Args:
            text: Text starting near a JSON object

        Returns:
            Extracted JSON string or None
        """
        # Find the first opening brace
        start = text.find('{')
        if start == -1:
            return None

        brace_count = 0
        in_string = False
        escape_next = False

        for i, char in enumerate(text[start:], start):
            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return text[start:i+1]

        logger.debug(f"Unbalanced braces (count={brace_count}), cannot extract JSON")
        return None
    


   
        
    def _execute_tool(
        self,
        tool_call: Dict,
        tool_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ) -> Any:

        """
        Execute a tool call
        
        Args:
            tool_call: Tool call information
            
        Returns:
            Tool execution result
        """


        start = time.perf_counter()
        tool_name = tool_call["name"]
        args = tool_call.get("arguments", {})


        # 原有白名单校验...
        if (tool_name != "use_skill" 
            and self._loaded_skill is not None 
            and self._skill_tool_whitelist is not None 
            and tool_name not in self._skill_tool_whitelist):
            elapsed = time.perf_counter() - start
            console.print(f"[dim]🚫 Tool BLOCKED: {tool_name} (not in skill whitelist) | elapsed={elapsed:.3f}s[/dim]")
            return f"错误：工具 '{tool_name}' 不在当前技能 '{self._loaded_skill.name}' 的允许列表中。"


        tool = next((t for t in self.tools if t["name"] == tool_name), None)
        if not tool:
            elapsed = time.perf_counter() - start
            console.print(f"[dim]❌ Tool NOT FOUND: {tool_name} | elapsed={elapsed:.3f}s[/dim]")
            return f"错误：找不到工具 '{tool_name}'"


        try:
            if tool_callback:
                tool_callback("start", tool_name, {"arguments": args})
            result = tool["executor"](**args)
            if tool_callback:
                tool_callback("end", tool_name, {"result": result})
            elapsed = time.perf_counter() - start
        

            # 关键：区分是否 use_skill
            if tool_name == "use_skill":
                console.print(f"[dim]🧠 SKILL TOOL CALL: {tool_name} args={str(args)[:80]} elapsed={elapsed:.3f}s[/dim]")
            else:
                console.print(f"[dim]🔧 TOOL CALL: {tool_name} args={str(args)[:80]} elapsed={elapsed:.3f}s[/dim]")
            return result

        except Exception as e:
            elapsed = time.perf_counter() - start
            console.print(f"[dim]💥 TOOL ERROR: {tool_name} | elapsed={elapsed:.3f}s | error={str(e)[:50]}[/dim]")
            return f"错误：执行工具 '{tool_name}' 时出错：{str(e)}"

    


    def _maybe_reflect(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Apply reflection if enabled and conversation has history."""
        if self.use_reflector and len(messages) > 1 and self.reflector:
            return self.reflector.apply_reflection(messages)
        return messages

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=60))
    def _call_llm(self, messages: List[Dict[str, str]], temperature: Optional[float] = None,
                  reflect: bool = True) -> str:
        """
        Call LLM with messages
        
        Args:
            messages: Conversation messages
            temperature: Override temperature (None → self.temperature).
                The skill router passes 0.0 for a deterministic decision.
            reflect: Whether to run the reflector on this call. The skill router
                passes False to keep the routing call cheap and deterministic.
            
        Returns:
            LLM response content
        """
        start = time.perf_counter()  # <--- 计时开始

        try:
            logger.debug(f"Calling LLM with API key: {self.api_key[:6]}...")
            logger.debug(f"Base URL: {self.base_url or 'default OpenAI'}")
            logger.debug(f"Model: {self.model}")
            
            if not self.api_key:
                raise ValueError("API key is not set. Please check your environment variables.")
            
            # Apply reflection if enabled
            if reflect:
                messages = self._maybe_reflect(messages)
                
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature if temperature is None else temperature
            )
            content = response.choices[0].message.content
            elapsed = time.perf_counter() - start  # <--- 计算耗时

            # <--- 日志打印位置（成功时） --->
            console.print(f"[dim]🤖 LLM call ({self.model}) succeeded in {elapsed:.3f}s[/dim]")
            return content

        except Exception as e:
            elapsed = time.perf_counter() - start  # <--- 计算耗时（即使报错）
            logger.error(f"Error calling LLM: {str(e)}")

            # <--- 日志打印位置（失败时） --->
            console.print(f"[dim]💥 LLM call ({self.model}) failed in {elapsed:.3f}s: {str(e)[:60]}[/dim]")
            raise



    def _call_llm_stream(self, messages: List[Dict[str, str]]) -> Generator[str, None, None]:
        """
        Call LLM with streaming, yielding tokens as they arrive.
        
        Args:
            messages: Conversation messages
            
        Yields:
            Token strings as they stream in
        """
        start = time.perf_counter()  # <--- 计时开始

        if not self.api_key:
            raise ValueError("API key is not set.")
        
        messages = self._maybe_reflect(messages)
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            stream=True,
        )
        try:
            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content

            # <--- 正常流式结束，打印耗时（在循环外、try内部） --->
            elapsed = time.perf_counter() - start
            console.print(f"[dim]🤖 LLM stream ({self.model}) completed in {elapsed:.3f}s[/dim]")

        except Exception as e:
            # <--- 流式过程出错，打印失败耗时 --->
            elapsed = time.perf_counter() - start
            logger.error(f"Streaming error during iteration: {e}")
            console.print(f"[dim]💥 LLM stream ({self.model}) failed in {elapsed:.3f}s: {str(e)[:60]}[/dim]")
            raise




    @staticmethod
    def _summarize_messages(messages: List[Dict[str, str]], keep_last: int = 10) -> List[Dict[str, str]]:
        """
        Compress conversation history when it grows too long.
        
        Keeps the system prompt + a summary of old messages + the last N messages.
        This prevents token overflow in long-running sessions.
        
        Args:
            messages: Full message list
            keep_last: Number of recent messages to keep verbatim
            
        Returns:
            Compressed message list
        """
        if len(messages) <= keep_last + 2:  # system + enough messages
            return messages
        
        system = messages[0] if messages[0]["role"] == "system" else None
        start = 1 if system else 0
        old_messages = messages[start:-keep_last]
        recent = messages[-keep_last:]
        


        # ========== 改进点 1：限制摘要条目数，防止摘要过长 ==========
        # 最多保留最近 15 条旧消息做摘要，避免压缩本身产生大量 token
        if len(old_messages) > 15:
            old_messages = old_messages[-15:]

        summary_parts = []
        for m in old_messages:
            role = m.get("role", "").upper()
            content = (m.get("content", "") or "")

            # ========== 改进点 2：用 smart_truncate 替代硬截断 ==========
            # smart_truncate 会尝试在完整句子边界处截断，避免切词
            truncated = smart_truncate(content, 300)

            # ========== 改进点 3：保留结构化角色标记 ==========
            if role == "USER":
                summary_parts.append(f"[用户] {truncated}")
            elif role == "ASSISTANT":
                summary_parts.append(f"[助手] {truncated}")
            elif role == "TOOL":
                summary_parts.append(f"[工具结果] {truncated}")
            else:
                summary_parts.append(f"[{role}] {truncated}")

        summary = "\n".join(summary_parts)

        # ========== 改进点 4：更清晰的压缩标记 ==========
        total_compressed = len(messages) - keep_last - (1 if system else 0)
        summary_msg = {
            "role": "user",
            "content": (
                f"[历史会话压缩] 已将较早的 {total_compressed} 条消息压缩为摘要：\n"
                f"{summary}\n"
                f"[压缩结束，请基于上述摘要和最近的对话继续]"
            )
        }

        #===改动结束
        
        result = []
        if system:
            result.append(system)
        result.append(summary_msg)
        result.extend(recent)
        return result



    def _check_dangerous(self, tool_call: Dict) -> bool:
        """
        Check if a tool call needs user confirmation before execution.

        Two independent confirmation gates:
        1. write / edit —— 文件写入确认（confirm_file_writes，默认开启）。
           模型不得在用户同意前创建或修改文件。
        2. bash —— 危险命令确认（confirm_dangerous，需显式开启）。

        Returns True if the call is safe to proceed, False if user rejected.
        """
        name = tool_call.get("name")
        args = tool_call.get("arguments", {})

        # ---- 文件写入确认 ----
        if name in ("write", "edit"):
            if not self.confirm_file_writes:
                return True
            path = str(args.get("path", "?"))
            action = "写入文件" if name == "write" else "修改文件"
            desc = f"{action} {path}"
            if self.confirm_callback:
                return self.confirm_callback(desc)
            # Default: stdin prompt
            try:
                answer = input(f"\n⚠️ 即将{desc}，是否继续？[y/N]: ").strip().lower()
                return answer in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                return False

        # ---- 危险 bash 命令确认 ----
        if not self.confirm_dangerous:
            return True

        if name != "bash":
            return True

        cmd = str(args.get("cmd", ""))
        if not _DANGEROUS_RE.search(cmd):
            return True

        # Ask for confirmation
        if self.confirm_callback:
            return self.confirm_callback(cmd)

        # Default: stdin prompt
        try:
            answer = input(f"\n⚠️  Dangerous command detected: {cmd}\nAllow execution? [y/N]: ").strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    # ------------------------------------------------------------------
    # Shared helpers for both run modes
    # ------------------------------------------------------------------

    def _compress_if_needed(self, messages, max_context_messages):
        """Compress conversation history when it exceeds the limit."""
        if len(messages) > max_context_messages:
            messages = self._summarize_messages(messages)
            logger.info(f"Compressed conversation to {len(messages)} messages")
        return messages

    def _safe_execute_tool(self, tool_call, tool_callback, status_callback, limit):
        """Execute a tool with safety check, status callbacks, and result truncation.
        
        Returns:
            (result_str, rejected): result_str is None if rejected.
        """
        if not self._check_dangerous(tool_call):
            return None, True
        
        if status_callback:
            status_callback(f"Executing tool: {tool_call['name']}...")
        
        logger.info(f"Executing tool: {tool_call['name']} with args: {tool_call['arguments']}")
        result = self._execute_tool(tool_call, tool_callback=tool_callback)
        return smart_truncate(str(result), limit), False
    


    

    def _build_dynamic_system_prompt(self, mode: str = "text") -> str:
        """根据当前加载的技能动态构建系统提示词

        Args:
            mode: "text" 或 "native"，决定使用哪个模板
        """
        base = self._loaded_skill.prompt if self._loaded_skill else self.system_prompt
        if self._loaded_skill:
            console.print(f"[dim]📄 Using SKILL PROMPT: {self._loaded_skill.name}[/dim]")
        else:
            console.print(f"[dim]📄 Using DEFAULT SYSTEM PROMPT (no skill loaded)[/dim]")

        template = self._NATIVE_MODE_PROMPT if mode == "native" else self._TEXT_MODE_PROMPT
        return template.format(
            base_prompt=base,
            tools_prompt=self._build_tools_prompt(),
        )



    #============新增两个方法，改进 run_with_tools 与 run_with_native_tools 大量重复 的问题

    def _init_run(self, query: str):
        """
        初始化每次运行的公共环境：重置技能状态、初始化消息列表、获取限制参数
        """
        self._reset_skill_state()
        # ===== 自动路由：根据用户提问自动加载匹配的 skill =====
        if self.auto_route_skills:
            self._auto_route_skill(query)
        logger.info(f"Starting query: {query[:50]}...")

        # ===== 字数约束：从 query 解析（如 "800字" / "2000 words"）并强注入 =====
        self._length_constraint = self._extract_length_constraint(query)
        user_content = query
        if self._length_constraint:
            target, is_words = self._length_constraint
            unit = "words" if is_words else "字"
            user_content = (
                query
                + f"\n\n[长度要求] 用户明确要求约 {target} {unit}。"
                + f"最终回答必须控制在 {target} {unit} 左右（允许 ±15%，即 "
                + f"{int(target * 0.85)}–{int(target * 1.15)} {unit}），"
                + "严禁写成远超要求的长文。字数按"
                + ("英文单词数" if is_words else "汉字+标点字符数（不含空格）")
                + "统计。内容过多时宁可精简到核心要点，也不要超长。"
            )

        messages = [
            {"role": "system", "content": ""},  # 占位，每轮动态更新
            {"role": "user", "content": user_content}
        ]
        return messages, self._max_context_messages, self._tool_result_limit

    @staticmethod
    def _extract_length_constraint(query: str):
        """从用户 query 中提取字数/词数要求。

        支持：800字 / 800个字 / 2000 字 / 500 words / 800词 / 3000字符
        返回 (target, is_words) 或 None。is_words=True 表示按英文单词数统计。
        """
        m = re.search(
            r"(\d{2,6})\s*(?:个)?\s*(?:汉字|中文字|字|词|字符|words?|chars?)",
            query,
            re.IGNORECASE,
        )
        if not m:
            return None
        target = int(m.group(1))
        if target < 20:  # 过滤噪音（如版本号、编号后跟"字"）
            return None
        unit = m.group(0)
        is_words = "word" in unit.lower() or "词" in unit
        return target, is_words

    @staticmethod
    def _text_length(text: str, is_words: bool) -> int:
        """统计文本长度：英文按单词数，中文按去空格后的字符数。"""
        if is_words:
            return len(text.split())
        return len(re.sub(r"\s+", "", text))

    @staticmethod
    def _truncate_to_length(text: str, max_len: int, is_words: bool) -> str:
        """在句子/段落边界把文本截断到目标长度（兜底用，不破坏 markdown 结构）。"""
        if is_words:
            words = text.split()
            if len(words) <= max_len:
                return text
            return " ".join(words[:max_len]).rstrip("，。；、,.?! \n") + "…"
        if len(re.sub(r"\s+", "", text)) <= max_len:
            return text
        sents = re.split(r"(?<=[。！？!?；;])", text)
        acc, acc_len = "", 0
        for s in sents:
            n = acc_len + len(re.sub(r"\s+", "", s))
            if acc and n > max_len:
                break
            acc += s
            acc_len = n
        acc = acc.rstrip()
        if not acc:
            return re.sub(r"\s+", "", text)[:max_len] + "…"
        return acc + "\n\n…（已按字数要求截断）"

    def _finalize_response(self, response: str, query: str, messages: List[Dict]) -> str:
        """按用户字数要求收尾：明显超长时追加一轮压缩（一次额外 LLM 调用）。

        压缩后仍超长时用句子边界截断兜底。无字数要求时原样返回。
        """
        constraint = getattr(self, "_length_constraint", None)
        if not constraint:
            return response
        target, is_words = constraint
        unit = "words" if is_words else "字"
        cur = self._text_length(response, is_words)
        if cur <= target * 1.15:
            return response

        console.print(f"[dim]📏 回答约 {cur} {unit}，超出要求 {target} {unit}，正在压缩…[/dim]")
        # 把待压缩原文放进消息，保证模型能看到（FINAL_ANSWER 分支的回答尚未进入历史）
        if len(response) <= 8000:
            comp_msg = (
                f"用户只要求约 {target} {unit}（允许 ±15%），但你刚才的回答约 {cur} {unit}，超长了。\n"
                f"请将下面的回答压缩到 {target} {unit} 左右（{int(target * 0.85)}–{int(target * 1.15)} {unit}），"
                f"保留核心观点与必要引用，删掉冗余展开和重复表述，保持结构完整。\n\n"
                f"=== 待压缩的回答 ===\n{response}\n=== 结束 ===\n\n"
                f"直接输出压缩后的最终回答，并以 FINAL_ANSWER: 开头，不要再调用任何工具。"
            )
        else:
            comp_msg = (
                f"你刚才的回答约 {cur} {unit}，但用户只要求约 {target} {unit}（±15%）。"
                f"请把回答压缩到 {target} {unit} 左右（{int(target * 0.85)}–{int(target * 1.15)} {unit}），"
                f"保留核心观点与必要引用，删掉冗余展开和重复表述，保持结构完整。"
                f"直接输出压缩后的最终回答，并以 FINAL_ANSWER: 开头，不要再调用任何工具。"
            )
        messages.append({"role": "user", "content": comp_msg})
        try:
            final = self._call_llm(messages, temperature=0.0)
            if final.strip().startswith("FINAL_ANSWER:"):
                final = final[len("FINAL_ANSWER:"):].strip()
            if self._text_length(final, is_words) > target * 1.3:
                return self._truncate_to_length(final, int(target * 1.2), is_words)
            return final
        except Exception as e:
            logger.warning(f"Length compression failed ({e}); truncating instead")
            return self._truncate_to_length(response, int(target * 1.2), is_words)

    def _route_skill_via_llm(self, query: str):
        """
        把 skill 列表 + 用户问题交给大模型，让模型基于语义决定用哪个 skill（或不用）。

        Returns:
            (skill, explicit_none): skill 为命中的 Skill 或 None；
            explicit_none=True 表示模型明确回答 "none"（应当尊重，不再回退评分系统）；
            explicit_none=False 且 skill=None 表示模型回答无法解析或给了未知名字，
            调用方应回退到评分系统。
        传输/API 异常会向上抛出，由调用方统一兜底。
        """
        from .skills import _SKILLS
        if not _SKILLS:
            return None, False

        lines = []
        for name, skill in sorted(_SKILLS.items(), key=lambda kv: kv[0]):
            desc = (skill.description or "").replace("\n", " ").strip()
            if len(desc) > 160:
                desc = desc[:160] + "…"
            line = f"- {name}: {desc}"
            if skill.keywords:
                line += f" | keywords: {', '.join(skill.keywords[:8])}"
            lines.append(line)
        listing = "\n".join(lines)

        prompt = (
            "You are a skill router. Given the user request below and the list of available "
            "skills, decide which ONE skill should handle it. If NO skill fits, answer 'none'.\n\n"
            f"Available skills:\n{listing}\n\n"
            "Rules:\n"
            "- Choose by semantic INTENT, not by surface keywords.\n"
            "- If the user wants to reduce AI flavor / humanize a paper's writing → the "
            "humanization skill, never a coding skill.\n"
            "- 'use the appropriate ccfa skill' is a meta instruction meaning 'pick the right "
            "one' — it is NOT a request to create a skill.\n"
            "- Generic chat or simple Q&A that no skill clearly fits → 'none'.\n"
            "- Only pick from the listed skill names; never invent new ones.\n\n"
            f"User request: {query}\n\n"
            "Reply with exactly one line, nothing else:\n"
            "SKILL: <name>\n"
            "or\n"
            "SKILL: none"
        )
        logger.info("LLM routing: sending skill list to model for decision")
        resp = self._call_llm(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            reflect=False,
        )
        text = (resp or "").strip()

        m = re.search(r"(?:SKILL|skill|技能|工具)\s*[:：]\s*([A-Za-z0-9_\-\.]+)", text)
        if not m:
            logger.warning(f"LLM routing: unparseable response {text[:120]!r}; falling back to scoring")
            return None, False
        raw = m.group(1).strip().lower()
        if raw in ("none", "null", "无", "没有"):
            logger.info("LLM routing: model decided no skill matches; not routing")
            return None, True

        # 精确/去分隔符匹配 skill 名（ccf-humanization / literature_reviewer 等）
        norm = lambda s: s.lower().replace("_", "").replace("-", "").replace(".", "")
        for name, skill in _SKILLS.items():
            if norm(name) == norm(raw):
                logger.info(f"LLM routing: model picked '{name}'")
                return skill, False

        logger.warning(f"LLM routing: model picked unknown skill {raw!r}; falling back to scoring")
        return None, False

    def _auto_route_skill(self, query: str):
        """
        根据用户提问自动加载最匹配的 skill（无需用户显式提及，也无需 LLM 自觉调用 use_skill）。

        路由策略（LLM 路由为主，评分系统兜底）：
        1. 确保 CCFA 技能家族已加载（env 设置了 CCFA_SKILLS_ROOT 但尚未注册时懒加载）——
           否则路由只在内置 skill 里选，"用ccfa skills里相应的skill" 会错误路由到 coder
        2. 若 llm_route_skills 开启：把 skill 列表 + 用户问题交给模型，由模型基于语义决策：
           - 模型明确选某个 skill → 用之
           - 模型明确说 none → 不路由（尊重判断，"不匹配任何一个skill就别用"）
           - 模型回答无法解析/API 异常 → 回退到评分系统
        3. 评分系统（关键词/描述/动作动词打分）作为兜底

        返回加载的 Skill 或 None。
        """
        from .skills import match_skill

        self._ensure_ccfa_loaded()

        skill = None
        if self.llm_route_skills:
            try:
                skill, explicit_none = self._route_skill_via_llm(query)
                if explicit_none:
                    console.print("[dim]🧭 LLM router: no skill matches, not routing[/dim]")
                    logger.info("LLM router decided no skill matches; not routing")
                    return None
            except Exception as e:
                logger.warning(f"LLM routing failed ({e}); falling back to scoring system")
                skill = None

        if skill is None:
            skill = match_skill(query)
        if skill is None:
            return None

        self._loaded_skill = skill
        self._skill_tool_whitelist = skill.tools
        if skill.temperature is not None:
            self.temperature = skill.temperature
        console.print(f"[dim]🎯 AUTO-ROUTED to skill: '{skill.name}' (from query)[/dim]")
        logger.info(f"Auto-routed to skill: {skill.name}")
        return skill

    @staticmethod
    def _ensure_ccfa_loaded():
        """若设置了 CCFA_SKILLS_ROOT 且 CCFA 家族尚未注册，则懒加载。

        避免"路由发生在 load_ccfa_skills() 之前"导致的漏加载——
        此时 match_skill 只在内置 skill 里选，CCFA 场景会错误路由到 coder。
        """
        import os as _os
        from .skills import _SKILLS

        if not _os.environ.get("CCFA_SKILLS_ROOT"):
            return
        if any(name.startswith("ccf-") for name in _SKILLS):
            return
        try:
            from .ccfa_loader import load_ccfa_skills
            load_ccfa_skills()
        except Exception as e:  # 加载失败不阻断主流程
            logger.warning(f"CCFA skills 懒加载失败: {e}")



    def _force_final_answer(self, messages: List[Dict], max_iterations: int) -> str:
        """
        当超出迭代次数时，强制LLM生成最终答案（两种模式完全一致的逻辑）
        """
        logger.warning(f"Reached maximum iterations ({max_iterations})")
        messages.append({
            "role": "user",
            "content": "你已尝试多次工具调用，请根据所有已知信息，用中文给出最终答案，并以 FINAL_ANSWER: 开头。"
        })
        # 统一使用 _call_llm（自带重试），替代原生方法中直接调用 client.chat.completions.create
        final = self._call_llm(messages)
        if final.strip().startswith("FINAL_ANSWER:"):
            return final[len("FINAL_ANSWER:"):].strip()
        return final


    #========新增结束



    def run_with_tools(
        self,
        query: str,
        max_iterations: int = 10,
        tool_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:

         
       
        # ===== 替换初始化代码 =====
        messages, max_ctx, limit = self._init_run(query)


        # 使用 for 循环自动管理迭代次数
        for iteration in range(max_iterations):
            logger.info(f"Iteration {iteration + 1}/{max_iterations}")
            messages = self._compress_if_needed(messages, max_ctx)

            # ===== 动态更新 system prompt =====
            system_content = self._build_dynamic_system_prompt(mode="text")
            messages[0] = {"role": "system", "content": system_content}

            if status_callback:
                status_callback(f"Thinking (Iteration {iteration + 1})...")

            # 获取模型响应
            if stream_callback:
                chunks = []
                for token in self._call_llm_stream(messages):
                    chunks.append(token)
                    stream_callback(token)
                response = "".join(chunks)
            else:
                response = self._call_llm(messages)

            # 检测 FINAL_ANSWER
            if response.strip().startswith("FINAL_ANSWER:"):
                return self._finalize_response(
                    response[len("FINAL_ANSWER:"):].strip(), query, messages
                )

            messages.append({"role": "assistant", "content": response})

            # 解析工具调用（支持多个，模型可能一次输出多个 TOOL 块）
            tool_calls = self._parse_all_tool_calls(response)

            # 无工具调用
            if not tool_calls:
                # 启发式判断：若响应足够长且无"未完成"暗示，视为完成
                if len(response) > 100 and not any(kw in response for kw in ["需要查询", "需要搜索", "请稍等", "我会查找"]):
                    logger.info("No tool call but response seems complete, returning.")
                    return self._finalize_response(response, query, messages)
                # 否则引导
                messages.append({
                    "role": "user",
                    "content": "当前回复没有工具调用且不完整。请调用工具获取信息，或如果已足够，请以 FINAL_ANSWER: 开头给出最终回答。"
                })
                continue  # 下一轮

            # 依次执行所有工具调用
            for tool_call in tool_calls:
                # 处理 use_skill
                if tool_call["name"] == "use_skill":
                    result_str = self._use_skill_handler(**tool_call["arguments"])
                    messages.append({
                        "role": "user",
                        "content": f"工具 '{tool_call['name']}' 执行结果：{result_str}"
                    })
                    continue  # 下一个工具

                # 执行其他工具
                result_str, rejected = self._safe_execute_tool(tool_call, tool_callback, status_callback, limit)

                if rejected:
                    feedback = f"用户拒绝了工具 '{tool_call['name']}'，请建议安全的替代方案或用中文回答。"
                elif isinstance(result_str, str) and ("Error" in result_str or "Exception" in result_str):
                    feedback = f"工具 '{tool_call['name']}' 出错：{result_str}\n请解释错误并给出解决方案。"
                else:
                    feedback = f"工具 '{tool_call['name']}' 结果：{result_str}\n请继续用中文回答，完成时以 FINAL_ANSWER: 开头。"

                messages.append({"role": "user", "content": feedback})

        # 超出迭代次数，强制生成最终答案（复用 _force_final_answer，避免重复逻辑）
        return self._finalize_response(
            self._force_final_answer(messages, max_iterations), query, messages
        )




    def run_with_native_tools(
        self,
        query: str,
        max_iterations: int = 10,
        tool_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> str:

        
        # ===== 替换初始化代码 =====
        messages, max_ctx, limit = self._init_run(query)



        for iteration in range(max_iterations):
            messages = self._compress_if_needed(messages, max_ctx)

            # 动态更新 system（native 模式使用独立模板，不再要求文本 TOOL: 格式）
            system_content = self._build_dynamic_system_prompt(mode="native")
            messages[0] = {"role": "system", "content": system_content}

            if status_callback:
                status_callback(f"Thinking (Iteration {iteration + 1})...")

            # [CHANGED] 在这里动态构建 tool_schemas，基于当前过滤后的工具列表
            filtered_tools = self._get_filtered_tools()
            tool_schemas = [{
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                }
            } for t in filtered_tools]

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    tools=tool_schemas if tool_schemas else None,
                )
            except Exception as e:
                logger.error(f"Native FC LLM call failed: {e}")
                raise

            msg = response.choices[0].message

            # 检测 FINAL_ANSWER
            if msg.content and msg.content.strip().startswith("FINAL_ANSWER:"):
                return self._finalize_response(
                    msg.content[len("FINAL_ANSWER:"):].strip(), query, messages
                )

            # 无工具调用：与 text 模式保持一致，判断响应是否完整
            if not msg.tool_calls:
                content = (msg.content or "").strip()
                # 响应足够长且无"未完成"暗示 → 视为完成
                if len(content) > 100 and not any(kw in content for kw in ["需要查询", "需要搜索", "请稍等", "我会查找"]):
                    return self._finalize_response(content, query, messages)
                # 否则引导 LLM 继续（把本轮回复加入历史，避免原地打转）
                messages.append(msg)
                messages.append({
                    "role": "user",
                    "content": "当前回复没有工具调用且不完整。请调用工具获取信息，或如果已足够，请以 FINAL_ANSWER: 开头给出最终回答。"
                })
                continue

            messages.append(msg)

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = parse_json(tc.function.arguments) or {}

                
                if tool_name == "use_skill":
                    result_str = self._use_skill_handler(**arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })
                    # 注意：_loaded_skill 和 _skill_tool_whitelist 已更新，
                    # 下一轮循环会使用新的过滤列表
                    continue
                

                tool_call_info = {"name": tool_name, "arguments": arguments}
                result_str, rejected = self._safe_execute_tool(
                    tool_call_info, tool_callback, status_callback, limit
                )
                content = "Execution rejected by user. Suggest a safer alternative." if rejected else result_str
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                })


        # ===== 替换结尾的强制回答代码（现在统一使用 _call_llm） =====
        return self._finalize_response(
            self._force_final_answer(messages, max_iterations), query, messages
        )




    def run(self, query: str, max_iterations: int = 15, mode: str = "native") -> str:     #mode默认模式从text改为native，max_iterations从10改到15，.env同步改
        """
        Execute the Agent with specified tool calling mode.
        
        Args:
            query: User query text
            max_iterations: Maximum number of iterations
            mode: Tool calling mode — "text" (default, transparent parsing) 
                  or "native" (OpenAI function calling)
            
        Returns:
            Agent response text
        """
        if mode == "native":
            return self.run_with_native_tools(query, max_iterations)
        return self.run_with_tools(query, max_iterations)

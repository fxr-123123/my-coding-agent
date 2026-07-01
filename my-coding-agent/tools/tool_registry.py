from typing import Dict, Type
from tools.base_tool import BaseTool

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Type[BaseTool]] = {}

    def register(self, tool_cls: Type[BaseTool]):
        self._tools[tool_cls.name] = tool_cls

    def get_tools_schema(self) -> list:
        return [
            {
                "name": cls.name,
                "description": cls.description,
                "input_schema": cls.input_schema
            }
            for cls in self._tools.values()
        ]

    def run_tool(self, name: str, params: dict) -> str:
        if name not in self._tools:
            return f"Error: Tool {name} not found"
        return self._tools[name]().run(**params)
    
    def get_sub_tools(self) -> list:
        """返回子代理可用工具 schema —— 排除 task，防止递归生成子代理"""
        return [
            {
                "name": cls.name,
                "description": cls.description,
                "input_schema": cls.input_schema,
            }
            for cls in self._tools.values()
            if cls.name != "task"
        ]
    
registry = ToolRegistry()

import tools.bash_tool
import tools.file_tool
import tools.todo_tool
import tools.task_tool
import tools.skill_tool
import tools.compact_tool
import tools.task_crud_tools
import tools.cron_tools
import tools.team_tools
import tools.worktree_tools
import tools.mcp_tools
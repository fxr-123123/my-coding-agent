from tools.base_tool import BaseTool
from tools.tool_registry import registry
from multi_agent.plugin_mcp import connect_mcp


class ConnectMcpTool(BaseTool):
    name = "connect_mcp"
    description = "连接 MCP 服务器 (docs, deploy) 并自动注册其工具"
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "服务器名称"}},
        "required": ["name"],
    }
    def run(self, name: str) -> str:
        return connect_mcp(name)
    

registry.register(ConnectMcpTool)
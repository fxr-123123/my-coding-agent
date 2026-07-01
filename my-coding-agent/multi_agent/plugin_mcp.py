import re

_DISALLOWED_CHARS = re.compile(r'[^a-zA-Z0-9_-]')


def normalize_mcp_name(name: str) -> str:
    return _DISALLOWED_CHARS.sub('_', name)


class MCPClient:
    """MCP 工具服务器客户端"""

    def __init__(self, name: str):
        self.name = name
        self.tools: list[dict] = []

    def call_tool(self, tool_name: str, args: dict) -> str:
        """子类覆盖此方法实现实际的 MCP 调用"""
        return f"MCP error: unknown tool '{tool_name}'"


# ── Mock Servers ──

class MockDocsServer(MCPClient):
    def __init__(self):
        super().__init__("docs")
        self.tools = [
            {"name": "search", "description": "搜索文档 (readOnly)",
             "inputSchema": {"type": "object",
                             "properties": {"query": {"type": "string"}},
                             "required": ["query"]}},
            {"name": "get_version", "description": "获取 API 版本 (readOnly)",
             "inputSchema": {"type": "object", "properties": {},
                             "required": []}},
        ]

    def call_tool(self, tool_name: str, args: dict) -> str:
        if tool_name == "search":
            return f"[docs] 搜索 '{args.get('query', '')}': 找到 3 条结果"
        if tool_name == "get_version":
            return "[docs] API v2.1.0"
        return super().call_tool(tool_name, args)


class MockDeployServer(MCPClient):
    def __init__(self):
        super().__init__("deploy")
        self.tools = [
            {"name": "trigger", "description": "触发部署 (destructive)",
             "inputSchema": {"type": "object",
                             "properties": {"service": {"type": "string"}},
                             "required": ["service"]}},
            {"name": "status", "description": "查看部署状态 (readOnly)",
             "inputSchema": {"type": "object",
                             "properties": {"service": {"type": "string"}},
                             "required": ["service"]}},
        ]

    def call_tool(self, tool_name: str, args: dict) -> str:
        if tool_name == "trigger":
            return f"[deploy] 已触发部署: {args.get('service', '')}"
        if tool_name == "status":
            return f"[deploy] {args.get('service', '')}: running (v1.4.2)"
        return super().call_tool(tool_name, args)


MOCK_SERVERS = {
    "docs": MockDocsServer,
    "deploy": MockDeployServer,
}

mcp_clients: dict[str, MCPClient] = {}


def connect_mcp(name: str) -> str:
    """连接 MCP 服务器，发现工具并注册到全局工具池"""
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"

    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS.keys())
        return f"Unknown server '{name}'. Available: {available}"

    client = factory()
    mcp_clients[name] = client

    from tools.tool_registry import registry

    safe_server = normalize_mcp_name(name)
    for tool_def in client.tools:
        safe_tool = normalize_mcp_name(tool_def["name"])
        prefixed = f"mcp__{safe_server}__{safe_tool}"

        # 动态创建工具类并注册
        tool_cls = type(
            f"MCP_{safe_server}_{safe_tool}",
            (object,),
            {
                "name": prefixed,
                "description": tool_def.get("description", ""),
                "input_schema": tool_def.get("inputSchema", {}),
                "run": lambda self, c=client, t=tool_def["name"], **kw: c.call_tool(t, kw),
            },
        )
        registry.register(tool_cls)

    tool_names = [t["name"] for t in client.tools]
    print(f"  \033[31m[mcp] connected: {name} → {tool_names}\033[0m")
    return (f"Connected to MCP server '{name}'. "
            f"Discovered {len(client.tools)} tools: {', '.join(tool_names)}")
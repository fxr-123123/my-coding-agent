# My Coding Agent

从零构建的 Python Coding Agent 框架 —— 基于 Anthropic API，具备 19 个工具、四级上下文压缩、多代理协作、定时任务引擎、Git Worktree 隔离、跨会话记忆与 MCP 插件系统。

## 架构总览

```
  ┌─────────────────────────────────────────────────────┐
  │                    main.py                          │
  │   输入循环 · cron 队列消费 · 团队信箱注入              │
  └─────────────────────┬───────────────────────────────┘
                        │
  ┌─────────────────────▼───────────────────────────────┐
  │              core/agent_loop.py                     │
  │   run_one_turn() 主循环                            │
  │                                                     │
  │   ① 上下文压缩 (L1→L2→L3→L4)                        │
  │   ② 系统提示词组装 (prompt_builder)                  │
  │   ③ 记忆加载 (memory)                               │
  │   ④ API 调用 (with_retry)                           │
  │   ⑤ 工具调用执行 (tool_registry)                    │
  │   ⑥ Hook 触发 (PreToolUse/PostToolUse/Stop)         │
  └─────────────────────┬───────────────────────────────┘
                        │
        ┌───────────────┼───────────────┬──────────────┐
        ▼               ▼               ▼              ▼
  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
  │  tools/  │   │ system/  │   │  task/   │   │ multi_   │
  │ 19 工具   │   │ 加固层    │   │ 运行时    │   │ agent/   │
  └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

## 特性

### 🤖 核心引擎
- **主循环**: 上下文压缩 → 提示词组装 → API 调用 → 工具执行 → Hook 触发
- **任务规划**: `TodoPlan` 数据结构，模型通过 `todo_write` 工具声明并更新执行计划
- **子代理**: `spawn_subagent` 独立上下文执行子任务，最多 30 轮，返回文本摘要
- **编程接口**: `CodingAgent` 类，可编程调用 agent

### 🛠️ 工具系统（19 个工具）

| 类别 | 工具 | 说明 |
|------|------|------|
| 系统 | `bash` | 命令执行（subprocess，120s 超时） |
| 文件 | `read_file` `write_file` `edit_file` `glob` | 文件读写编辑 + 通配符搜索 |
| 规划 | `todo_write` | 声明与更新任务计划 |
| 代理 | `task` | 启动子代理处理复杂子任务 |
| 技能 | `load_skill` | 按名称加载技能完整内容 |
| 压缩 | `compact` | 模型主动触发对话压缩 |
| 任务 | `create_task` `list_tasks` `get_task` `claim_task` `complete_task` | 任务 CRUD + 依赖追踪 |
| 定时 | `schedule_cron` `list_crons` `cancel_cron` | 5 段 cron 定时任务管理 |
| 团队 | `spawn_teammate` `send_message` `check_inbox` `request_shutdown` `request_plan` `review_plan` | 多代理协作 |
| 隔离 | `create_worktree` `remove_worktree` `keep_worktree` | Git Worktree 环境隔离 |
| 插件 | `connect_mcp` | 连接 MCP 服务器并注册其工具 |

### 📦 四级上下文压缩

| 级别 | 触发条件 | 策略 |
|------|---------|------|
| L1 snip | 消息数 > 50 | 截断中间，保留头尾 |
| L2 micro | tool_result > 3 | 旧结果替换为占位符 |
| L3 budget | 单轮结果 > 200KB | 持久化到磁盘 |
| L4 compact | 总大小 > 50KB | LLM 摘要 + 对话存档 |
| 应急 reactive | API 报 prompt_too_long | 紧急压缩 + 保留尾部 |

### 🛡️ 安全加固

- **三级权限管道**: 硬黑名单 → 规则匹配 → 用户交互确认
- **事件 Hook 系统**: UserPromptSubmit / PreToolUse / PostToolUse / Stop
- **危险命令拦截**: `rm -rf /`、`sudo`、`shutdown` 等自动阻断

### 🔄 错误恢复

| 错误类型 | 策略 |
|---------|------|
| 429 Rate Limit | 指数退避重试（最多 10 次） |
| 529 Overloaded | 指数退避，连续 3 次切换模型 |
| max_tokens 截断 | 8K→64K 升级 → continuation 续写（最多 3 次） |
| prompt_too_long | reactive_compact 紧急压缩 |

### 👥 多代理协作

- **消息总线**: 基于文件的消息队列（`.mailboxes/xxx.jsonl`）
- **队友生命周期**: WORK 阶段（最多 10 轮） → IDLE 阶段（轮询任务板，最多 60s）
- **协议支持**: plan_approval（计划审批）、shutdown（优雅关闭）
- **自动认领**: IDLE 状态自动扫描未认领任务

### ⏰ 定时任务引擎

- 完整 5 段 cron 表达式匹配（支持 `*/step`、范围、列表）
- 每秒轮询，匹配即入队
- Daemon 线程消费队列，自动调用 `agent_loop`
- 支持 durable 持久化，重启后恢复

### 🧠 跨会话记忆

- YAML frontmatter 格式存储于 `.memory/`
- 每轮对话后自动提取新记忆
- LLM 精选 + 关键词兜底两种检索策略
- 超过阈值自动合并去重

### 🔌 MCP 插件系统

- `MCPClient` 基类：name、tools、call_tool()
- 动态创建工具类并注册到 ToolRegistry
- 工具命名规范：`mcp__{server}__{tool}`
- 内置 Mock 服务器：docs（search/get_version）、deploy（trigger/status）

### 🎯 技能系统

- YAML frontmatter + Markdown 指令格式
- `scan_skills()` 启动时自动扫描 `skills/` 目录
- `load_skill` 工具按需加载完整内容

## 快速开始

### 环境要求

- Python 3.10+
- Git（Worktree 功能需要）

### 安装

```bash
git clone <your-repo-url>
cd my-coding-agent
pip install -r requirements.txt
```

### 配置

复制环境变量模板并填入你的 API Key：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
MODEL_ID="deepseek-v4-pro"
ANTHROPIC_API_KEY="YOUR_API_KEY"
```

支持任意兼容 Anthropic Messages API 的服务（DeepSeek、Claude API 等），修改 `ANTHROPIC_BASE_URL` 和 `MODEL_ID` 即可。

### 运行

```bash
python main.py
```

交互式命令行启动后，直接输入任务即可：

```
>> 帮我写一个快速排序的 Python 实现
>> 解释 core/agent_loop.py 的代码
>> 创建一个每天 9:00 执行的任务
```

输入 `q` 或 `exit` 退出。

## 项目结构

```
my-coding-agent/
├── main.py                  # 程序入口
├── requirements.txt         # 项目依赖
├── .env.example             # 环境变量模板
│
├── core/                    # Agent 核心层
│   ├── agent_loop.py        # 主循环引擎
│   ├── todo_plan.py         # 任务规划
│   ├── sub_agent.py         # 子代理
│   ├── context_compact.py   # 上下文压缩（四级策略）
│   └── skill_loader.py      # 技能加载器
│
├── tools/                   # 工具层（19 个工具）
│   ├── base_tool.py         # BaseTool 抽象基类
│   ├── tool_registry.py     # 工具注册中心
│   ├── bash_tool.py         # Bash 命令执行
│   ├── file_tool.py         # 文件工具集（4 合 1）
│   ├── todo_tool.py         # 任务计划工具
│   ├── task_tool.py         # 子代理工具
│   ├── skill_tool.py        # 技能加载工具
│   ├── compact_tool.py      # 压缩工具
│   ├── task_crud_tools.py   # 任务管理工具（5 合 1）
│   ├── cron_tools.py        # 定时任务工具（3 合 1）
│   ├── team_tools.py        # 多代理协作工具（6 合 1）
│   ├── worktree_tools.py    # Git Worktree 工具（3 合 1）
│   └── mcp_tools.py         # MCP 连接工具
│
├── system/                  # 系统加固层
│   ├── permission.py        # 三级权限管道
│   ├── hook.py              # 事件钩子系统
│   ├── memory.py            # 跨会话记忆管理
│   ├── prompt_builder.py    # 动态提示词构建器
│   └── error_recovery.py    # 错误恢复系统
│
├── task/                    # 任务运行时层
│   ├── task_manager.py      # 持久任务管理 + 依赖追踪
│   ├── background_task.py   # 后台任务执行
│   └── cron_scheduler.py    # 定时调度引擎
│
├── multi_agent/             # 多代理协作层
│   ├── team.py              # Agent 团队核心 + 消息总线
│   ├── worktree.py          # Git 环境隔离
│   └── plugin_mcp.py        # MCP 插件系统
│
└── skills/                  # 技能库
    └── code-explainer/      # 代码解读技能
        └── SKILL.md
```

## 设计原则

- **从零构建**: 不依赖 LangChain、AutoGPT 等框架，仅依赖 `anthropic` SDK
- **纵深防御**: 黑名单、规则匹配、用户确认三级权限，危险操作多重拦截
- **优雅降级**: 四级压缩 + 错误恢复，保证长对话稳定运行
- **模块解耦**: Hook 事件系统连接各模块，核心循环与工具/权限/记忆松耦合
- **渐进增强**: 从单 Agent → 子代理 → 多 Agent 团队，能力层层叠加

## License

MIT

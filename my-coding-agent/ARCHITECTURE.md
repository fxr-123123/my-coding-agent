my-coding-agent/
├── .env                    # 密钥、模型配置（ANTHROPIC_BASE_URL, MODEL_ID）
├── requirements.txt        # 项目依赖（anthropic, python-dotenv, pyyaml）
├── main.py                 # 程序入口：交互循环 + cron 队列消费 + 团队信箱注入
│
├── core/                   # Agent 核心层
│   ├── agent_loop.py       # 主循环引擎
│   │                        #   - LoopState: 消息历史、轮次、TodoPlan、RecoveryState
│   │                        #   - run_one_turn(): 上下文压缩（L1-L4）→ API调用 → 工具执行
│   │                        #   - agent_loop(): 循环调用 run_one_turn 直到 stop_reason != tool_use
│   │                        #   - CodingAgent: 可编程调用的 Agent 封装类
│   │                        #   - 四级压缩管道：snip(L1) → micro(L2) → budget(L3) → compact(L4)
│   ├── todo_plan.py        # 任务规划
│   │                        #   - TodoItem / TodoPlan: 待办步骤数据结构
│   │                        #   - format_todo_for_prompt(): 注入系统提示让模型感知进度
│   ├── sub_agent.py        # 子代理
│   │                        #   - spawn_subagent(): 独立 messages[]，最多30轮，返回文本摘要
│   │                        #   - 使用 get_sub_tools() 排除 task 工具防止递归
│   ├── context_compact.py  # 上下文压缩（四级策略）
│   │                        #   - L1 snip_compact: 消息数 >50 时截断中间部分
│   │                        #   - L2 micro_compact: 旧 tool_result 替换为占位符，保留最近3个
│   │                        #   - L3 tool_result_budget: 大结果持久化到磁盘
│   │                        #   - L4 compact_history: LLM 摘要 + 对话存档到 .transcripts/
│   │                        #   - reactive_compact: API 报 prompt_too_long 时紧急压缩
│   └── skill_loader.py     # 技能加载器
│                            #   - scan_skills(): 扫描 skills/ 目录，解析 YAML frontmatter
│                            #   - list_skills(): 生成技能目录摘要
│                            #   - load_skill(): 按名称返回完整 SKILL.md
│
├── tools/                  # 工具层（共 13 个工具文件，19 个工具）
│   ├── base_tool.py        # BaseTool 抽象基类（name, description, input_schema, run()）
│   ├── tool_registry.py    # ToolRegistry 工具注册中心
│   │                        #   - register/get_tools_schema/run_tool/get_sub_tools
│   │                        #   - 启动时 import 所有工具模块完成自注册
│   ├── bash_tool.py        # Bash 命令执行（subprocess, 120s 超时, 50KB 上限）
│   ├── file_tool.py        # 文件工具集（4 个工具）
│   │                        #   - read_file: 读文件，支持行数限制
│   │                        #   - write_file: 写文件，自动创建父目录
│   │                        #   - edit_file: 精确文本替换（单次）
│   │                        #   - glob: 通配符搜索文件
│   ├── todo_tool.py        # todo_write: 创建/更新任务计划，同步到 TodoPlan
│   ├── task_tool.py        # task: 启动子代理处理复杂子任务
│   ├── skill_tool.py       # load_skill: 按名称加载技能完整内容
│   ├── compact_tool.py     # compact: 模型主动触发对话压缩
│   ├── task_crud_tools.py  # 任务管理工具集（5 个工具）
│   │                        #   - create_task: 创建任务，支持 blockedBy 依赖
│   │                        #   - list_tasks: 列出所有任务及状态
│   │                        #   - get_task: 获取任务详情
│   │                        #   - claim_task: 认领 pending 任务 → in_progress
│   │                        #   - complete_task: 完成任务，自动解锁下游依赖
│   ├── cron_tools.py       # 定时任务工具集（3 个工具）
│   │                        #   - schedule_cron: 注册 5 段 cron 定时任务
│   │                        #   - list_crons: 列出所有定时任务
│   │                        #   - cancel_cron: 按 ID 取消定时任务
│   ├── team_tools.py       # 多代理协作工具集（6 个工具）
│   │                        #   - spawn_teammate: 后台启动队友 agent 线程
│   │                        #   - send_message: 通过 MessageBus 发消息
│   │                        #   - check_inbox: 查看 lead 信箱
│   │                        #   - request_shutdown: 请求队友优雅关闭
│   │                        #   - request_plan: 要求队友提交执行计划
│   │                        #   - review_plan: 审批队友提交的计划
│   ├── worktree_tools.py   # Git Worktree 工具集（3 个工具）
│   │                        #   - create_worktree: 创建隔离的 git worktree
│   │                        #   - remove_worktree: 删除 worktree（可强制丢弃更改）
│   │                        #   - keep_worktree: 保留 worktree 供人工审查
│   └── mcp_tools.py        # connect_mcp: 连接 MCP 服务器并自动注册其工具
│
├── system/                 # 系统加固层
│   ├── permission.py       # 三级权限管道
│   │                        #   - Gate 1: 硬黑名单（rm -rf, sudo, shutdown 等）
│   │                        #   - Gate 2: 规则匹配（工作区外写入、危险命令）
│   │                        #   - Gate 3: 用户交互确认 [y/N]
│   │                        #   - 通过 PreToolUse hook 注册到事件系统
│   ├── hook.py             # 事件钩子系统
│   │                        #   - 4 个事件点: UserPromptSubmit, PreToolUse, PostToolUse, Stop
│   │                        #   - register_hook / trigger_hooks
│   ├── memory.py           # 跨会话记忆管理
│   │                        #   - 记忆文件存储在 .memory/，YAML frontmatter 格式
│   │                        #   - write_memory / read_memory_index / list_memory_files
│   │                        #   - select_relevant_memories: LLM 精选 + 关键词兜底
│   │                        #   - extract_memories: 每轮对话后自动提取新记忆
│   │                        #   - consolidate_memories: 超过阈值 LLM 自动合并去重
│   ├── prompt_builder.py   # 动态提示词构建器
│   │                        #   - PROMPT_SECTIONS: 静态 prompt 片段
│   │                        #   - build_context: 收集各模块状态（技能、记忆、待办）
│   │                        #   - get_system_prompt: 确定性缓存，context 不变不重建
│   └── error_recovery.py   # 错误恢复系统
│                            #   - RecoveryState: 追踪升级/重试/529连续次数
│                            #   - with_retry: 429/529 指数退避重试（最多10次）
│                            #   - max_tokens 截断: 8K→64K 升级 → continuation 续写
│                            #   - is_prompt_too_long_error: 检测上下文溢出
│
├── task/                   # 任务运行时层
│   ├── task_manager.py     # 持久任务管理
│   │                        #   - Task 数据结构: id, subject, description, status, owner, blockedBy, worktree
│   │                        #   - CRUD: create_task / load_task / save_task / list_tasks
│   │                        #   - 依赖追踪: can_start() 检查 blockedBy 是否全部完成
│   │                        #   - 状态流转: pending → in_progress → completed
│   ├── background_task.py  # 后台任务执行
│   │                        #   - is_slow_operation: 启发式判断（install/build/test 等）
│   │                        #   - should_run_background: 模型显式要求 or 启发式
│   │                        #   - collect_background_results: 收集完成的后台结果
│   └── cron_scheduler.py   # 定时调度引擎
│                            #   - CronJob: id, cron表达式, prompt, recurring, durable
│                            #   - cron_matches: 完整 5 段 cron 匹配（含 */step, 范围, 列表）
│                            #   - schedule_job / cancel_job / save_durable_jobs
│                            #   - cron_scheduler_loop: 每秒轮询，匹配则入队
│                            #   - queue_processor_loop: daemon 线程消费队列，自动调用 agent_loop
│
├── multi_agent/            # 多代理协作层
│   ├── team.py             # Agent 团队核心
│   │                        #   - MessageBus: 基于文件的消息总线（.mailboxes/xxx.jsonl）
│   │                        #   - spawn_teammate_thread: 后台线程运行队友 agent
│   │                        #     WORK阶段（最多10轮）→ IDLE阶段（轮询任务板，最多60s）
│   │                        #   - ProtocolState: plan_approval / shutdown 协议
│   │                        #   - idle_poll: 自动扫描未认领任务 + 检查信箱
│   │                        #   - consume_lead_inbox: 统一入口，路由协议响应
│   ├── worktree.py         # Git 环境隔离
│   │                        #   - create_worktree: git worktree add -b wt/{name}
│   │                        #   - remove_worktree: git worktree remove --force
│   │                        #   - keep_worktree: 保留分支和目录
│   │                        #   - 事件日志记录到 .worktrees/events.jsonl
│   │                        #   - 支持 worktree 绑定到 Task
│   └── plugin_mcp.py       # MCP 插件系统
│                            #   - MCPClient 基类: name, tools, call_tool()
│                            #   - Mock 服务器: docs (search/get_version), deploy (trigger/status)
│                            #   - connect_mcp: 动态创建工具类并注册到 ToolRegistry
│                            #   - 工具命名规范: mcp__{server}__{tool}
│
└── skills/                 # 技能库
    └── code-explainer/     # 代码解读技能
        └── SKILL.md        # YAML frontmatter + Markdown 指令


═══════════════════════════════════════════════════════════════
架构总览
═══════════════════════════════════════════════════════════════

  ┌─────────────────────────────────────────────────────┐
  │                    main.py                          │
  │   输入循环 · cron队列消费 · 团队信箱注入              │
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
  │          │   │          │   │          │   │ 协作层    │
  └──────────┘   └──────────┘   └──────────┘   └──────────┘

═══════════════════════════════════════════════════════════════
关键数据流
═══════════════════════════════════════════════════════════════

  用户输入 → main.py → agent_loop()
    → run_one_turn() 循环:
      1. 从各模块收集 context（技能/记忆/待办进度）
      2. get_system_prompt(context) 组装提示词（带缓存）
      3. 四级压缩管道处理消息历史
      4. API 调用（带 429/529 重试 + max_tokens 恢复）
      5. response.stop_reason == "tool_use":
         → execute_tool_calls() → registry.run_tool()
         → PreToolUse hook（权限检查）→ 执行 → PostToolUse hook
         → 后台任务：异步执行，结果注入
         → 返回 tool_result 给模型
      6. response.stop_reason != "tool_use":
         → 提取记忆 → 整理记忆 → Stop hook → 结束

═══════════════════════════════════════════════════════════════
上下文压缩策略
═══════════════════════════════════════════════════════════════

  L1 (snip):     消息数 > 50 → 截断中间，保留头尾
  L2 (micro):    tool_result > 3 → 旧结果替换为占位符
  L3 (budget):   单轮 tool_result 总字节 > 200KB → 持久化到磁盘
  L4 (compact):  总大小 > 50KB → LLM 摘要 + 对话存档
  应急 (reactive): API 报 prompt_too_long → 紧急压缩 + 保留尾部

═══════════════════════════════════════════════════════════════
错误恢复策略
═══════════════════════════════════════════════════════════════

  429 (Rate Limit) → 指数退避重试 (最多10次)
  529 (Overloaded) → 指数退避重试，连续3次切换模型
  max_tokens 截断  → 8K→64K 升级 → continuation 续写 (最多3次)
  prompt_too_long  → reactive_compact 紧急压缩

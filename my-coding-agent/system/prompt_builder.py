import json
from pathlib import Path
from tools.tool_registry import registry


WORKDIR = Path.cwd()

# ── Prompt 片段（静态部分） ──

PROMPT_SECTIONS = {
    "identity": (
        f"You are a coding agent at {WORKDIR}. "
        "Use tools to solve tasks. Act, don't explain."
    ),
    "todo_instruction": (
        "重要：收到任务后，第一轮必须调用 todo_write 工具列出执行计划。"
        "执行过程中每完成一步，再次调用 todo_write 更新进度。"
    ),
}


def assemble_system_prompt(context: dict) -> str:
    """根据实际状态选择并拼接 prompt 片段"""
    sections = []

    # 始终加载
    sections.append(PROMPT_SECTIONS["identity"])
    sections.append(PROMPT_SECTIONS["todo_instruction"])

    # 条件加载：有技能则注入
    skills = context.get("skills", "")
    if skills:
        sections.append(f"可用技能：\n{skills}\n需要时调用 load_skill 获取技能详情。")

    # 条件加载：有记忆则注入
    memories = context.get("memories", "")
    if memories:
        sections.append(f"跨会话记忆：\n{memories}")

    # 条件加载：当前待办进度
    todo = context.get("todo_progress", "")
    if todo:
        sections.append(todo)

    # 条件加载：首轮相关记忆
    relevant = context.get("relevant_memories", "")
    if relevant:
        sections.append(relevant)

    return "\n\n".join(sections)


# ── 缓存 ──
_last_context_key: str | None = None
_last_prompt: str | None = None


def get_system_prompt(context: dict) -> str:
    """确定性缓存：context 不变则不重建 prompt"""
    global _last_context_key, _last_prompt

    # json.dumps 保证确定性序列化（不含 Python hash 随机化）
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)

    if key == _last_context_key and _last_prompt:
        print("  \033[90m[cache hit] system prompt unchanged\033[0m")
        return _last_prompt

    _last_context_key = key
    _last_prompt = assemble_system_prompt(context)
    print(f"  \033[32m[assembled] prompt rebuilt\033[0m")
    return _last_prompt


# ── 上下文收集 ──

def build_context(todo_progress: str = "", relevant_memories: str = "") -> dict:
    """从各模块收集当前状态，返回上下文 dict"""
    skills = ""
    try:
        from core.skill_loader import list_skills
        skills = list_skills()
    except Exception:
        pass

    memories = ""
    try:
        from system.memory import read_memory_index
        memories = read_memory_index()
    except Exception:
        pass

    return {
        "skills": skills,
        "memories": memories,
        "todo_progress": todo_progress,
        "relevant_memories": relevant_memories,
    }
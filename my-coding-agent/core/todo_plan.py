from dataclasses import dataclass, field
from typing import List, Optional
@dataclass
class TodoItem:
    """单个待办步骤"""
    step_id: int
    content: str
    status: str = "pending" # pending / doing / done

@dataclass
class TodoPlan:
    """完整任务规划状态，挂载到LoopState"""
    
    total_steps: int = 0
    steps: List[TodoItem] = field(default_factory=list)
    current_step: int = 0
    is_completed: bool = False

def format_todo_for_prompt(todo: Optional[TodoPlan]) -> str:
    """把当前待办进度格式化成文本，注入系统提示，让模型感知进度"""
    if not todo or not todo.steps:
        return ""
    
    lines = ["\n【当前任务进度】"]
    for step in todo.steps:
        mark = "✓" if step.status == "done" else "→" if step.status == "doing" else "○"
        lines.append(f"{mark} 步骤{step.step_id}: {step.content}")
    lines.append(f"总进度: {sum(1 for s in todo.steps if s.status == 'done')}/{todo.total_steps}")
    return "\n".join(lines)

def print_todo(todo: TodoPlan) -> None:
    if not todo or not todo.steps:
        return
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    RESET = "\033[0m"

    print(f"\n{CYAN}📋 任务计划{RESET}")
    for step in todo.steps:
        if step.status == "done":
            mark = f"{GREEN}✓{RESET}"
        elif step.status == "doing":
            mark = f"{YELLOW}→{RESET}"
        else:
            mark = "○"
        print(f"  {mark} {step.content}")
    done_count = sum(1 for s in todo.steps if s.status == "done")
    print(f"  ────────── {done_count}/{todo.total_steps}\n")

_todo: Optional[TodoPlan] = None

def get_todo() -> Optional[TodoPlan]:
    return _todo

def set_todo(plan: TodoPlan) -> None:
    global _todo
    _todo = plan
import os
import sys
from pathlib import Path
from dataclasses import dataclass

from .todo_plan import TodoPlan, format_todo_for_prompt, get_todo
from .skill_loader import scan_skills, list_skills
from .context_compact import (
    tool_result_budget, snip_compact, micro_compact,
    compact_history, reactive_compact, estimate_size,
    CONTEXT_LIMIT, MAX_REACTIVE_RETRIES,
)
from system.memory import load_memories, extract_memories, consolidate_memories
from system.hook import register_hook, trigger_hooks
import system.permission
from system.prompt_builder import get_system_prompt, build_context
from system.error_recovery import (
    RecoveryState, with_retry, is_prompt_too_long_error, 
    DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS,
    MAX_RECOVERY_RETRIES, CONTINUATION_PROMPT,
)
from task.background_task import (
    should_run_background, start_background_task, collect_background_results,
)

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import readline
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

from tools.tool_registry import registry

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

scan_skills()

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

@dataclass
class LoopState:
    messages: list
    turn_count: int = 1
    transition_reason: str | None = None
    todo: TodoPlan | None = None
    recovery: RecoveryState = None
    max_tokens: int = DEFAULT_MAX_TOKENS

    def __post_init__(self):
        if self.recovery is None:
            self.recovery = RecoveryState()

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def _block_to_dict(block) -> dict:
    """Convert Anthropic SDK content block or dict to a plain dict."""
    if isinstance(block, dict):
        return block
    d = {"type": block.type}
    for attr in ("text", "id", "name", "input", "thinking", "signature", "data"):
        val = getattr(block, attr, None)
        if val is not None:
            d[attr] = val
    return d

def normalize_messages(messages: list) -> list:
    cleaned = []
    for msg in messages:
        clean = {"role": msg["role"]}
        if isinstance(msg.get("content"), str):
            clean["content"] = msg["content"]
        elif isinstance(msg.get("content"), list):
            clean["content"] = [
                {k: v for k, v in _block_to_dict(block).items() if not k.startswith("_")}
                for block in msg["content"]
            ]
        else:
            clean["content"] = msg.get("content", "")
        cleaned.append(clean)

    existing_results = set()
    for msg in cleaned:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if block.get("type") == "tool_result":
                    existing_results.add(block.get("tool_use_id"))

    cancelled_msgs = []
    for msg in cleaned:
        if msg["role"] != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if block.get("type") != "tool_use":
                continue
            if block.get("id") in existing_results:
                continue
            cancelled_msgs.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": block["id"], "content": "(cancelled)"}
            ]})
    cleaned.extend(cancelled_msgs)

    if not cleaned:
        return cleaned
    merged = [cleaned[0]]
    for msg in cleaned[1:]:
        if msg["role"] == merged[-1]["role"]:
            prev = merged[-1]
            prev_c = prev["content"] if isinstance(prev["content"], list) else [{"type": "text", "text": str(prev["content"])}]
            curr_c = msg["content"] if isinstance(msg["content"], list) else [{"type": "text", "text": str(msg["content"])}]
            prev["content"] = prev_c + curr_c
        else:
            merged.append(msg)
    return merged

def extract_text(content) -> str:
    if not isinstance(content, list):
        return ""
    texts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()

def execute_tool_calls(response_content) -> list[dict]:
    results = []
    CONCURRENCY_SAFE = {"read_file"}
    for block in response_content:
        if block.type != "tool_use":
            continue
        tool_name = block.name
        tool_params = block.input

        blocked = trigger_hooks("PreToolUse", block)
        if blocked:
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(blocked),
            })
            continue

        if should_run_background(tool_name, tool_params):
            def _execute(name, params):
                return registry.run_tool(name, params)
            bg_id = start_background_task(tool_name, tool_params, _execute)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": (
                    f"[Background task {bg_id} started] "
                    f"Command: {tool_params.get('command', '')}. "
                    f"Result will be injected when complete."
                ),
            })
            continue                              

        print(f"\033[33m🔧 执行工具: {tool_name}\033[0m")
        output = registry.run_tool(tool_name, tool_params)

        trigger_hooks("PostToolUse", block, output)

        print(output[:300])
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": output,
        })

    return results

def run_one_turn(state: LoopState) -> bool:
    TOOLS = registry.get_tools_schema()

    todo_progress = format_todo_for_prompt(get_todo())
    relevant = ""
    if state.turn_count == 1:
        relevant = load_memories(state.messages)
    context = build_context(todo_progress=todo_progress, relevant_memories=relevant)
    system_prompt = get_system_prompt(context)

    state.messages[:] = tool_result_budget(state.messages)   # L3
    state.messages[:] = snip_compact(state.messages)         # L1
    state.messages[:] = micro_compact(state.messages)        # L2
    if estimate_size(state.messages) > CONTEXT_LIMIT:        # L4
        print("[auto compact]")
        state.messages[:] = compact_history(state.messages)

    try:
        response = with_retry(
            lambda: client.messages.create(
                model=MODEL,
                system=system_prompt,
                messages=normalize_messages(state.messages),
                tools=TOOLS,
                max_tokens=state.max_tokens,
            ),
            state.recovery,
        )
    except Exception as e:
        if is_prompt_too_long_error(e):
            if not state.recovery.has_attempted_reactive_compact:
                print("[reactive compact]")
                state.messages[:] = reactive_compact(state.messages)
                state.recovery.has_attempted_reactive_compact = True
                # 重试
                response = client.messages.create(
                    model=MODEL, system=system_prompt,
                    messages=normalize_messages(state.messages),
                    tools=TOOLS, max_tokens=state.max_tokens,
                )
            else:
                print("  \033[31m[unrecoverable] still too long\033[0m")
                return False
        else:
            print(f"  \033[31m[unrecoverable] {e}\033[0m")
            return False

    if response.stop_reason == "max_tokens":
        if not state.recovery.has_escalated:
            state.max_tokens = ESCALATED_MAX_TOKENS
            state.recovery.has_escalated = True
            print(f"  \033[33m[max_tokens] escalate 8K → 64K\033[0m")
            return True  # 不追加截断输出，下轮重试
        # 已升级仍截断 → continuation
        state.messages.append({"role": "assistant", "content": response.content})
        if state.recovery.recovery_count < MAX_RECOVERY_RETRIES:
            state.messages.append({"role": "user", "content": CONTINUATION_PROMPT})
            state.recovery.recovery_count += 1
            print(f"  \033[33m[max_tokens] continue {state.recovery.recovery_count}/{MAX_RECOVERY_RETRIES}\033[0m")
            return True
        print("  \033[31m[max_tokens] recovery limit\033[0m")
        return False

    state.messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason != "tool_use":
        state.transition_reason = None
        return False

    # 先检查有没有 compact，单独处理
    for block in response.content:
        if block.type == "tool_use" and block.name == "compact":
            print(f"\033[33m🔧 执行工具: compact\033[0m")
            state.messages[:] = compact_history(state.messages)
            state.messages.append({"role": "user",
                "content": "Context compacted successfully."})
            state.turn_count += 1
            state.transition_reason = "compact"
            return True
                
    results = execute_tool_calls(response.content)
    if not results:
        state.transition_reason = None
        return False
    
    user_content = list(results)
    bg_notifications = collect_background_results()
    if bg_notifications:
        for notif in bg_notifications:
            user_content.append({"type": "text", "text": notif})
        print(f"  \033[32m[inject] {len(bg_notifications)} background notification(s)\033[0m")

    state.messages.append({"role": "user", "content": user_content})
    state.turn_count += 1
    state.transition_reason = "tool_result"
    return True

def agent_loop(state: LoopState) -> None:
    while run_one_turn(state):
        pass
    trigger_hooks("Stop", state.messages)
    extract_memories(state.messages)
    consolidate_memories()

class CodingAgent:
    def __init__(self):
        self.history=[]
    
    def run(self, user_query: str) -> str:
        self.history.append({"role": "user", "content": user_query})
        state = LoopState(messages=self.history)
        agent_loop(state)
        final_text = extract_text(self.history[-1]["content"])
        return final_text if final_text else ""
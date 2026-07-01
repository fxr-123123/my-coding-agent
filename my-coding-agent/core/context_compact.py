import json
import time
from pathlib import Path

WORKDIR = Path.cwd()
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

CONTEXT_LIMIT = 50000        # 触发L4自动摘要的阈值
KEEP_RECENT = 3              # L2保留最近N个完整tool_result
PERSIST_THRESHOLD = 30000    # L3持久化阈值
MAX_MESSAGES = 50            # L1消息数上限
MAX_REACTIVE_RETRIES = 1

def estimate_size(msgs) -> int:
    return len(str(msgs))

def _block_type(block):
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)

def _message_has_tool_use(msg) -> bool:
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(_block_type(b) == "tool_use" for b in content)

def _is_tool_result_message(msg) -> bool:
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


# ── L1: 截断中间消息 ──

def snip_compact(messages: list) -> list:
    """消息数超过MAX_MESSAGES时，截掉中间部分，用占位消息替代"""
    if len(messages) <= MAX_MESSAGES:
        return messages
    keep_head, keep_tail = 3, MAX_MESSAGES - 3
    head_end = keep_head
    tail_start = len(messages) - keep_tail

    # 保证不截断 tool_use/tool_result 配对
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and _is_tool_result_message(messages[head_end]):
            head_end += 1
    if tail_start > 0 and tail_start < len(messages):
        lookback = tail_start - 1
        while lookback >= 0 and _is_tool_result_message(messages[lookback]):
            lookback -= 1
        if lookback >= 0 and _message_has_tool_use(messages[lookback]):
            tail_start = lookback

    if head_end >= tail_start:
        return messages
    
    snipped = tail_start - head_end
    return messages[:head_end] + [
        {"role": "user", "content": f"[snipped {snipped} messages]"}
    ] + messages[tail_start:]


# ── L2: 旧结果占位化 ──

def _collect_tool_results(messages: list) -> list:
    """收集所有tool_result块的位置"""
    blocks = []
    for mi, msg in enumerate(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for bi, block in enumerate(msg["content"]):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                blocks.append((mi, bi, block))
    return blocks

def micro_compact(messages: list) -> list:
    """保留最近KEEP_RECENT个tool_result，其余替换为占位符"""
    tool_results = _collect_tool_results(messages)
    if len(tool_results) <= KEEP_RECENT:
        return messages
    for _, _, block in tool_results[:-KEEP_RECENT]:
        if len(block.get("content", "")) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages


# ── L3: 大结果持久化 ──

def _persist_large_output(tool_use_id: str, output: str) -> str:
    """大文件结果写入磁盘，返回摘要"""
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(output, encoding="utf-8")
    return (
        f"<persisted-output>\nFull output: {path}\n"
        f"Preview:\n{output[:2000]}\n</persisted-output>"
    )

def _persist_large_output(tool_use_id: str, output: str) -> str:
    """大文件结果写入磁盘，返回摘要"""
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(output, encoding="utf-8")
    return (
        f"<persisted-output>\nFull output: {path}\n"
        f"Preview:\n{output[:2000]}\n</persisted-output>"
    )


def tool_result_budget(messages: list, max_bytes: int = 200_000) -> list:
    """最新一条消息中tool_result总字节超限时，把最大的结果持久化"""
    if not messages:
        return messages
    last = messages[-1]
    if (last.get("role") != "user"
            or not isinstance(last.get("content"), list)):
        return messages

    blocks = [(i, b) for i, b in enumerate(last["content"])
              if isinstance(b, dict) and b.get("type") == "tool_result"]
    total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    if total <= max_bytes:
        return messages

    ranked = sorted(blocks, key=lambda p: len(str(p[1].get("content", ""))), reverse=True)
    for _, block in ranked:
        if total <= max_bytes:
            break
        content = str(block.get("content", ""))
        if len(content) <= PERSIST_THRESHOLD:
            continue
        tid = block.get("tool_use_id", "unknown")
        block["content"] = _persist_large_output(tid, content)
        total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    return messages


# ── L4: LLM摘要压缩 ──

def _write_transcript(messages: list) -> Path:
    """备份完整对话到磁盘"""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.json"
    with path.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path

def _summarize_history(messages: list) -> str:
    """掉一次API让LLM压缩历史"""
    from anthropic import Anthropic
    import os
    client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

    conversation = json.dumps(messages, default=str)[:80000]
    prompt = (
        "Summarize this coding-agent conversation so work can continue.\n"
        "Preserve: 1. current goal, 2. key findings/decisions, "
        "3. files read/changed, 4. remaining work, 5. user constraints.\n"
        "Be compact but concrete.\n\n" + conversation
    )
    response = client.messages.create(
        model=os.environ["MODEL_ID"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    texts = []
    for block in response.content:
        t = getattr(block, "text", None)
        if t:
            texts.append(t)
    return "\n".join(texts).strip() or "(empty summary)"

def compact_history(messages: list) -> list:
    """L4: 保存完整对话到磁盘，用LLM摘要替代全部历史"""
    transcript_path = _write_transcript(messages)
    print(f"[transcript saved: {transcript_path}]")
    summary = _summarize_history(messages)
    return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]


# ── 应急压缩 ──

def reactive_compact(messages: list) -> list:
    """API返回prompt_too_long时紧急压缩"""
    _write_transcript(messages)
    summary = _summarize_history(messages)
    tail_start = max(0, len(messages) - 5)
    if tail_start > 0 and tail_start < len(messages):
        lookback = tail_start - 1
        while lookback >= 0 and _is_tool_result_message(messages[lookback]):
            lookback -= 1
        if lookback >= 0 and _message_has_tool_use(messages[lookback]):
            tail_start = lookback
    return [
        {"role": "user", "content": f"[Reactive compact]\n\n{summary}"},
        *messages[tail_start:],
    ]
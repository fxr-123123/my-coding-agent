import os
from anthropic import Anthropic

SUB_SYSTEM = (
    f"You are a coding sub-agent at {os.getcwd()}. "
    "Complete the task you were given, then return a concise summary. "
    "Do not delegate further."
)

MAX_SUB_TURNS = 30


def spawn_subagent(prompt: str) -> str:
    """启动子代理，独立 messages[]，只返回最终文本摘要"""
    from tools.tool_registry import registry
    from core.agent_loop import extract_text

    print(f"\n\033[35m🤖 [子代理启动]\033[0m")

    messages = [{"role": "user", "content": prompt}] 

    sub_tools = registry.get_sub_tools() 
    client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

    for _ in range(MAX_SUB_TURNS):
        response = client.messages.create(
            model=os.environ["MODEL_ID"],
            system=SUB_SYSTEM,
            messages=messages,
            tools=sub_tools,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"  \033[90m[sub] 🔧 {block.name}\033[0m")
            output = registry.run_tool(block.name, block.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })

        if not results:
            break
        messages.append({"role": "user", "content": results})

    # 提取最终文本（兜底：如果最后一条是 tool_result，往前找 assistant 文本）
    result = extract_text(messages[-1]["content"])
    if not result:
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                result = extract_text(msg["content"])
                if result:
                    break
        if not result:
            result = f"子代理在 {MAX_SUB_TURNS} 轮后未产出最终回答。"

    print(f"\033[35m✅ [子代理完成]\033[0m")
    return result

import sys
import os
import threading
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.agent_loop import LoopState, agent_loop, extract_text
from system.hook import trigger_hooks
from task.cron_scheduler import agent_lock, queue_processor_loop, consume_cron_queue
from multi_agent.team import BUS, consume_lead_inbox

def _make_state():
    return LoopState(messages=[])

threading.Thread(target=queue_processor_loop, args=(_make_state,), daemon=True).start()

if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36m>> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query == "" :
            continue
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        with agent_lock:
            history.append({"role": "user", "content": query})
            state = LoopState(messages=history)
            agent_loop(state)
        final_text = extract_text(history[-1]["content"])
        if final_text:
            print(final_text)

        inbox = consume_lead_inbox(route_protocol=True)
        if inbox:
            inbox_text = "\n".join(
                f"From {m['from']}: {m['content'][:200]}" for m in inbox
            )
            history.append({"role": "user",
                            "content": f"[Inbox]\n{inbox_text}"})
            print(f"\n\033[33m[Inbox: {len(inbox)} messages injected]\033[0m")
            
        print()
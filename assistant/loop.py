from assistant.model import call_model
from assistant.tools.registry import _TOOL_INDEX, dispatch
from assistant.tools.describe_tool import DESCRIBE_TOOL, build_system_prompt
from assistant.tools.errors import ToolError
import json

def run_agent(user_request, max_turns: int = 10):

    messages = [{"role": "user", "content": user_request}]

    active_tools = [DESCRIBE_TOOL] # Initial tool present in the context
    loaded_tools = set()

    for turn in range(max_turns):
        print(f"--- Turn {turn + 1} (tools in request: {len(active_tools)}) ---")

        response = call_model(messages, active_tools, system=build_system_prompt())
        messages.append({"role": "assistant", "content": response.content})

        # Checks if the returned answer is anyother tjing than tool_use and stops when it is not.
        if response.stop_reason != "tool_use":
            for block in response.content:
                if block.type == "text":
                    print(f"\nASSISTANT: {block.text}")
            break
        
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input

                if tool_name == "describe_tool":
                    requested_tool = tool_input["tool_name"]
                    print(f"🔍 describe_tool({requested_tool})")

                    if requested_tool in _TOOL_INDEX:
                        if requested_tool not in loaded_tools:
                            tool_def = {**_TOOL_INDEX[requested_tool], "defer_loading": True}
                            active_tools.append(tool_def)
                            loaded_tools.add(requested_tool)
                            print(f"   ✓ Added {requested_tool} to tools (defer_loading=True)")

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": [
                                {"type": "tool_reference", "tool_name": requested_tool}
                            ],
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Tool {requested_tool} is not available",
                        })

                else:
                    # Execute discovered tool
                    print(f"🔧 {tool_name}({json.dumps(tool_input)})")
                    try:
                        result = dispatch(tool_name, tool_input)
                        print(f"   → {result}")
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})
                    except ToolError as e:
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(e), "is_error": True})

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

        

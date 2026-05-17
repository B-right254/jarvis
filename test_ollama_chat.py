
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain.ollama_client import chat
from brain.prompt_builder import build_system_prompt, get_pruned_schemas

messages = [
    {"role": "system", "content": build_system_prompt()},
    {"role": "user", "content": "open notepad"}
]

tools = get_pruned_schemas([])
print("Tools being passed:", [t["function"]["name"] for t in tools])
print("Calling chat...")
result = chat(messages=messages, tools=tools, temperature=0.2)
print("Result:", result)

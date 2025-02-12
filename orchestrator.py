#!/usr/bin/env python3
"""
child_repo/orchestrator.py

Pinned to openai==0.28.* so the pipeline can do self-healing:
 - reads fail_logs.txt from the last failing test
 - calls GPT with logs + the entire "app.py" + tests
 - attempts to fix "app.py"
"""

import os
import openai
import re

def main():
    openai.api_key = os.getenv("OPENAI_API_KEY_DECLAN", "")
    if not openai.api_key:
        print("[child orchestrator] No OPENAI_API_KEY_DECLAN, cannot do self-healing.")
        return

    LOG_FILE = "fail_logs.txt"
    if not os.path.exists(LOG_FILE):
        print(f"[child orchestrator] {LOG_FILE} not found, nothing to fix.")
        return

    with open(LOG_FILE, "r") as f:
        logs = f.read()

    system_msg = "You fix Python code. Return the entire new app.py in triple-backticks if you can fix it."
    user_msg = f"""
The following text includes fail logs, plus code for app.py (and any tests). 
Return an updated 'app.py' in triple-backtick python code blocks if you see a fix:
--------------------------------
{logs}
"""

    # GPT call
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.3
        )
        suggestions = resp["choices"][0]["message"]["content"]
        print("[child orchestrator] GPT suggestions:\n", suggestions)
    except Exception as e:
        print(f"[child orchestrator] GPT call failed: {e}")
        return

    # Attempt to parse triple-backtick code
    code_match = re.search(r"```python\s*(.*?)```", suggestions, re.DOTALL)
    if code_match:
        new_code = code_match.group(1).strip()
        with open("app.py", "w", encoding="utf-8") as f:
            f.write(new_code)
        print("[child orchestrator] Overwrote app.py from GPT fix.")
    else:
        print("[child orchestrator] No triple-backtick code block found or no fix identified. No changes made.")

if __name__ == "__main__":
    main()

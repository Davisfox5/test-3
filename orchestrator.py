#!/usr/bin/env python3
"""
orchestrator.py — GPT-based self-healing pipeline.

Reads fail_logs.txt (populated by CI on test failure), sends context to GPT-4,
and applies suggested fixes to the va_name_change package source files.
"""

import os
import re
import openai


TARGET_DIRS = ["va_name_change", "tests"]


def _collect_source_files():
    """Collect all Python source files from target directories."""
    files = {}
    for d in TARGET_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _, filenames in os.walk(d):
            for fn in filenames:
                if fn.endswith(".py"):
                    path = os.path.join(root, fn)
                    with open(path, "r", encoding="utf-8") as f:
                        files[path] = f.read()
    return files


def main():
    openai.api_key = os.getenv("OPENAI_API_KEY_DECLAN", "")
    if not openai.api_key:
        print("[orchestrator] No OPENAI_API_KEY_DECLAN, cannot do self-healing.")
        return

    log_file = "fail_logs.txt"
    if not os.path.exists(log_file):
        print(f"[orchestrator] {log_file} not found, nothing to fix.")
        return

    with open(log_file, "r") as f:
        logs = f.read()

    system_msg = (
        "You are a Python debugging assistant. You will receive pytest failure logs "
        "and source code for a Virginia name-change agent application. "
        "Identify the root cause and return ONLY the fixed file(s). "
        "For each file, use the format:\n"
        "--- FILE: path/to/file.py ---\n"
        "```python\n<entire corrected file>\n```\n"
        "Only include files that need changes."
    )

    user_msg = f"Fix the following test failures:\n\n{logs}"

    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
        )
        suggestions = resp["choices"][0]["message"]["content"]
        print("[orchestrator] GPT suggestions:\n", suggestions)
    except Exception as e:
        print(f"[orchestrator] GPT call failed: {e}")
        return

    # Parse --- FILE: path --- blocks with triple-backtick code
    file_pattern = re.compile(
        r"---\s*FILE:\s*([\w/._-]+)\s*---\s*```python\s*(.*?)```",
        re.DOTALL,
    )
    matches = file_pattern.findall(suggestions)

    if matches:
        for filepath, code in matches:
            filepath = filepath.strip()
            code = code.strip()
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)
            print(f"[orchestrator] Wrote fix to {filepath}")
    else:
        print("[orchestrator] No file blocks found in GPT response. No changes made.")


if __name__ == "__main__":
    main()

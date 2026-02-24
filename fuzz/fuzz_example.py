#!/usr/bin/env python3
"""
Example atheris fuzz harness.
Copy this file, rename it, and replace the call to `target_function`
with the function you want to fuzz.

Register it in fuzz/targets.txt:
  src/your_module.py    fuzz/fuzz_example.py
"""

import sys

import atheris

# Import the function under test
# from src.your_module import target_function


def TestOneInput(data: bytes) -> None:
    """
    Called by atheris for each generated input.
    Raise an exception (or let an uncaught one propagate) to signal a crash.
    Do NOT catch all exceptions — that defeats the purpose.
    """
    fdp = atheris.FuzzedDataProvider(data)

    # --- Shape the input for your function ---
    # Example: test a string parser
    text = fdp.ConsumeUnicodeNoSurrogates(128)  # noqa: F841 — template placeholder

    # --- Call the function under test ---
    # Uncomment and adapt:
    # target_function(text)

    # --- Example: ensure sort is stable and complete ---
    items = [fdp.ConsumeInt(4) for _ in range(fdp.ConsumeIntInRange(0, 50))]
    sorted_items = sorted(items)
    assert len(sorted_items) == len(items), "Sort changed length"
    assert all(sorted_items[i] <= sorted_items[i + 1] for i in range(len(sorted_items) - 1)), (
        "Sort result not ordered"
    )


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()

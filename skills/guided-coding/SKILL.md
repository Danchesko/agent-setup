---
name: guided-coding
description: Detailed coding guidance for tasks where the user wants more explicit implementation direction, including work with lighter models. Covers pragmatic FP, DRY, YAGNI, configuration boundaries, and proportionate checks.
disable-model-invocation: true
---

# Guided Coding

Write the simplest clear implementation that fully meets the current requirement. These are design preferences; project contracts, correctness, and the user's specific instructions take priority.

## Design

- Prefer small functions with explicit inputs and outputs. Separate calculations from configuration, I/O, and orchestration. Use classes when required state, resource management, or a library contract makes them useful.
- Protect caller-owned data from mutation. Copy where needed at that boundary; local intermediate values do not need repeated defensive copies.
- Apply YAGNI: add options, abstractions, fallback modes, and artifacts for a current need. An extra case does not automatically require redesigning the existing solution.
- Apply DRY to actual shared behavior and configuration. Reuse existing code before adding helpers. Similar syntax alone does not justify a shared abstraction.
- Keep meaningful intermediate variables and readable control flow. Reducing code volume must not make the calculation harder to follow.

## Configuration and errors

Load environment settings at startup or in configuration code, then pass required values or clients to functions. Prefer library defaults when sufficient. Validate external inputs and domain invariants where needed; avoid repeating validation across layers. Catch errors for recovery or useful context, preserving the cause.

For example, when the project already uses SQLAlchemy:

```python
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def get_engine(uri: str | None) -> Engine:
    if not uri:
        raise ValueError("No database connection URI provided")
    return create_engine(uri)
```

Startup code supplies `config.CH_DB_CONN_URI`. The helper's responsibility is connection creation. Use the project's existing client library; this example does not require adopting SQLAlchemy.

## Readability and notebooks

Use names that describe roles, explicit imports, and short docstrings. Comments explain non-obvious reasons or constraints. Describe the current code without conversation history or decorative separators.

For notebooks, preserve the question and existing comparison when adding evidence. Keep one-off analysis visible; share repeated operations according to project conventions. Display computed settings and results from code so reruns stay accurate. Create additional notebooks or artifacts when the work needs them.

## Verification

Check affected behavior using existing tests or a focused smoke run. Add behavior or regression tests where useful; avoid tests that merely reproduce a trivial wrapper. Preserve behavior during refactoring and report what was actually verified. Do not run full training just to check imports.

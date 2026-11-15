---
name: clarify
description: Expand a request into its underlying goal, missing context, hidden assumptions, and a stronger scope before any execution. Use only when the user explicitly invokes $clarify or asks to pause and clarify or decompress a request before acting; present the interpretation or minimal high-value questions, then wait for explicit approval.
disable-model-invocation: true
---

# Clarify

## Purpose

Decompress the user's words into the outcome they are actually trying to achieve. Improve the brief rather than merely repeating it, while matching the depth of clarification to the complexity of the request.

## Clarify the Request

1. **Find the real goal.** Infer why the user is asking, what successful output would enable, and what would make the result feel exactly right.
2. **Improve the scope.** Identify useful connected work the user omitted and what a senior practitioner would add. Flag it as a recommendation rather than silently expanding the task.
3. **Fill consequential gaps.** Use conversation history and available context first. Surface assumptions only when they could materially change the result.
4. **Correct the direction when needed.** Say directly when the surface request appears to solve the wrong problem, and explain the better framing.
5. **Reflect the expanded understanding.** State the intended outcome, relevant constraints, proposed scope, and any important exclusions in natural language.

## Match the Depth

- For a mostly clear, simple request, use two or three sentences: the interpretation plus one valuable addition.
- For a complex request, separate the major threads and show how they connect.
- For the wrong question, name the underlying question directly.
- For vague or emotionally charged wording, translate the feeling into a concrete need without dismissing it.
- For a technical request with hidden complexity, surface only the complexity that affects scope, risk, or approach.

Ask questions only when different answers would materially change the work. Ask the smallest number of questions that removes the most uncertainty; never ask for information already available or safely inferable.

## Approval Gate

- Do not execute the underlying task while this skill is active.
- After presenting a confident interpretation, end with: **Does this match what you want?**
- If material ambiguity remains, end with the specific questions instead. Do not also ask whether the interpretation matches.
- When the user answers a question, incorporate the answer and restate the updated understanding. Stop again and wait for explicit approval.
- Treat only an unambiguous instruction such as “yes,” “go,” “do it,” or “proceed” as permission to execute. Do not treat an answer to a clarification question as approval.

Interpret charitably, stay proportional, and be honest about uncertainty. Let the response shape follow the request rather than forcing a template.

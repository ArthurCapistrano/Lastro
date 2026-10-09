# Coding Guidelines

## 1. Think Before Coding

**Make relevant assumptions explicit. Surface ambiguity and tradeoffs.**

Before implementing:
- Investigate uncertainties using the codebase first.
- Ask when unresolved ambiguity materially affects scope, behavior, or risk.
  Otherwise, state relevant assumptions and proceed.
- When plausible interpretations lead to materially different outcomes, present
  them before choosing.
- If a simpler approach meets the requirements, explain it. Push back when warranted.

## 2. Simplicity First

**Choose the simplest correct implementation. Build for the current requirements.**

- Implement only the requested behavior.
- Introduce abstractions only when they simplify the current implementation,
  clarify domain behavior, or enable meaningful testing.
- Add flexibility or configurability only when required by the task.
- Handle failures at external boundaries and where required by the behavior.
  Rely on established internal invariants rather than adding speculative
  defensive checks.
- Remove unnecessary complexity while preserving readability and required behavior.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Keep changes within scope. Clean up what your changes leave behind.**

When editing existing code:
- Keep unrelated code, comments, and formatting unchanged.
- Refactor only when requested or necessary for the requested change.
  Keep unrelated cleanup separate.
- Match the existing style.
- If you notice unrelated dead code, mention it and leave it unchanged unless
  its removal was requested.

Remove imports, variables, and functions made unused by your changes.

The test: Every changed line should support the user's request, including tests
and necessary supporting changes.

## 4. Goal-Driven Execution

**Define success criteria. Verify the requested outcome.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass."
- "Fix the bug" → "Write a test that reproduces it, then make it pass."
- "Refactor X" → "Establish the baseline, preserve observable behavior, and run
  relevant checks before and after. Add coverage where existing tests do not
  protect the changed behavior."

For multi-step tasks, state a brief plan:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Report checks performed and their results. If verification is blocked, state the
blocker and remaining uncertainty. Keep fixes within the requested scope;
report unrelated failures separately.

Strong success criteria let you work independently. Weak criteria ("make it work") 
require clarification.

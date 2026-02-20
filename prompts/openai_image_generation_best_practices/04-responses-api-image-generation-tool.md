# Method 4: Responses API `image_generation` tool

Use this for multi-turn workflows and unified orchestration with other tools.

## When to use

- Interactive iterative refinement in chat-like loops.
- Mixed workflows (text reasoning + image generation in one run).
- Cases where you want tool traces and revised prompt inspection.

## Best practices

- Default to `action: "auto"` unless you need to force `generate` or `edit`.
- Use `action: "edit"` when a source image is already in context.
- Track and inspect `revised_prompt` for debugging and prompt tuning.
- Chain iterations using `previous_response_id` for continuity.
- Keep each turn focused: one major visual change per iteration.

## Common pitfalls

- Sending broad multi-objective edits in one turn.
- Ignoring revised prompt drift between turns.
- Mixing unrelated stylistic direction in adjacent iterations.

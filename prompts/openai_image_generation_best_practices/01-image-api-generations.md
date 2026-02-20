# Method 1: Image API `generations`

Use this when you generate a new image from text only.

## When to use

- First concept exploration.
- Batch ideation from a single prompt.
- Cases where no source image must be preserved.

## Best practices

- Start with `gpt-image-1` for general-purpose quality.
- Begin with square output and default/medium quality to iterate quickly.
- Use `n > 1` only for ideation; for final run keep `n=1` for cost control.
- Keep prompt structure explicit: subject, scene, framing, lighting, style, constraints.
- Include negative constraints to reduce common artifacts.
- Persist prompt, model, size, quality, and returned metadata for reproducibility.

## Common pitfalls

- Overspecifying many conflicting actions in one prompt.
- Jumping to max quality too early.
- Not versioning prompt changes between iterations.

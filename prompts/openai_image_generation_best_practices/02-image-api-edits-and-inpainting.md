# Method 2: Image API `edits` (image edits + inpainting)

Use this when you must preserve and modify an existing image.

## When to use

- Character identity preservation across iterations.
- Local replacement (inpainting) of specific regions.
- Controlled restyling of an existing composition.

## Best practices

- Keep source image and mask dimensions aligned.
- For GPT Image API uploads, keep files within documented size limits.
- For masked edits, use alpha-channel mask and clearly isolate editable regions.
- Prefer focused edit instructions (what changes, what stays fixed).
- If identity/logo/text fidelity matters, use high input fidelity mode.
- If multiple reference images are provided, put the most important identity reference first.

## Common pitfalls

- Broad edit prompts that unintentionally rewrite the whole frame.
- Weak masks (ambiguous edges) causing bleed into protected regions.
- Skipping close-up framing when tiny text/interface details matter.

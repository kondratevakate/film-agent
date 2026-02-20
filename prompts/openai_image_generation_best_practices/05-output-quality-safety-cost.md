# Output, Quality, Safety, and Cost Best Practices

Applies across methods.

## Output settings

- Use PNG/WebP for transparency workflows.
- Use JPEG/WebP with compression when bandwidth is a priority.
- Use explicit size/aspect choices aligned with target channel and storyboard.
- Start with moderate quality; raise quality only for shortlisted outputs.

## Streaming / partial images

- Use partial image streaming for interactive UX and quick visual feedback.
- Keep partial steps low unless user experience clearly benefits.
- Account for token/cost overhead from partial-image responses.

## Safety / moderation

- Keep moderation in default mode unless policy and risk review require otherwise.
- Validate prompts for policy-sensitive content before batch runs.
- Keep logs for rejected prompts and policy-related retries.
- Note: organization verification may be required for some image models.

## Cost / latency controls

- Generate broad candidates cheaply, then upscale/refine selected finalists.
- Keep `n` small in production.
- Avoid repeated high-fidelity edits on low-value candidates.
- Profile latency/cost by method and keep per-stage budgets.

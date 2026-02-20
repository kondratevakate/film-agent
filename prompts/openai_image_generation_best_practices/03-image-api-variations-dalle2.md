# Method 3: Image API `variations` (DALL·E 2)

Use only for legacy flows that still depend on DALL·E 2 variations.

## When to use

- Fast stylistic branching from one seed image in legacy pipelines.

## Best practices

- Treat this as migration-phase functionality.
- Keep variation experiments separated from production runs.
- Plan replacement with `gpt-image-1` generation/edit flows.
- Validate all downstream assumptions (sizes, formats, quality behavior) during migration.

## Important notes

- OpenAI docs mark DALL·E 2 generations/edits/variations as deprecated.
- Deprecation timeline in docs indicates support end on May 12, 2026.

## Common pitfalls

- Building new long-term workflows on deprecated endpoints.
- Assuming parity with GPT Image behavior and parameters.

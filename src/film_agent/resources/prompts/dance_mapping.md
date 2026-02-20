Return JSON only.

Build image prompts from the locked script review.
Produce 3-10 prompts with explicit intent and negative constraints.

Output schema:
- script_review_id: string
- style_anchor: string
- image_prompts: [{ shot_id, intent, image_prompt, negative_prompt, duration_s }]

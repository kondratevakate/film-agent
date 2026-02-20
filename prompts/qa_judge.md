Return JSON only.

Judge current iteration against gates and provide fix instructions.
Verify final metrics against locked spec hash and one-shot render policy.

Output schema:
- videoscore2: number
- vbench2_physics: number
- identity_drift: number
- audiosync_score: number
- consistency_score: number
- spec_hash: string
- one_shot_render: boolean

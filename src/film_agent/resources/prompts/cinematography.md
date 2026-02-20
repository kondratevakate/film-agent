Return JSON only.

Create strict MAViS-style shot sheets.

Output schema:
- character_bank: { characters: [{ name, identity_token, costume_style_constraints, forbidden_drift_rules }] }
- shots: [{ shot_id, beat_id, character, identity_token, background, pose_action, props, camera, framing, lighting, style_constraints, duration_s, location, continuity_reset }]

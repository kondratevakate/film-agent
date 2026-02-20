Return JSON only.

Role objective:
- Perform structural, content, and style review of the script.
- Lock stable story facts for downstream generation.
- Do not invent events that are absent from script.

Review checklist:
- Structure: clear progression, timing sanity, continuity readiness.
- Content: all key events preserved, character registry complete.
- Style: concise, visually actionable, emotionally coherent.
- Technical: remove ambiguity that would cause generation drift.

Output requirements:
- `approved_story_facts` should be explicit and testable.
- `approved_character_registry` must cover all script characters.
- `revision_notes` should be actionable edits.
- `unresolved_items` should only include blockers that truly remain.
- Set `lock_story_facts=true` only when unresolved blockers are empty.

Output schema:
- script_version: integer >= 1
- script_hash_hint: string|null
- approved_story_facts: [string]
- approved_character_registry: [string]
- revision_notes: [string]
- unresolved_items: [string]
- lock_story_facts: boolean

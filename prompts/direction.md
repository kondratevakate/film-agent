Return JSON only.

Review the script and lock story facts for downstream generation.
Do not invent new events not present in script.

Output schema:
- script_version: integer >= 1
- script_hash_hint: string|null
- approved_story_facts: [string]
- approved_character_registry: [string]
- revision_notes: [string]
- unresolved_items: [string]
- lock_story_facts: boolean

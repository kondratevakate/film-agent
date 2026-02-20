Return JSON only.

Create music and voice timing aligned to beats.

Output schema:
- motifs: [string]
- voice_lines: [{ line_id, timestamp_s, speaker, text }]
- cues: [{ cue_id, timestamp_s, duration_s, cue_type, description }]
- sync_markers: [number]

# THE TRACE Image Generation Playbook (OpenAI Best Practices)

Source alignment:
- prompts/openai_image_generation_best_practices/01-image-api-generations.md
- prompts/openai_image_generation_best_practices/02-image-api-edits-and-inpainting.md
- prompts/openai_image_generation_best_practices/04-responses-api-image-generation-tool.md
- prompts/openai_image_generation_best_practices/05-output-quality-safety-cost.md

## 1) Recommended workflow

1. Draft pass (`generations`):
- Model: `gpt-image-1`
- Goal: composition search only
- `n=3` per shot
- Quality: medium/default
- Size: square (fast iteration) or single chosen widescreen size for all shots
- Keep one primary action per prompt

2. Selection pass:
- Pick one best draft per shot
- Reject candidates with identity drift, distorted anatomy, clipped highlights, broken spatial logic

3. Consistency pass (`edits`):
- Use selected draft as source
- Edit only what must change (identity/wardrobe/light balance/background cleanup)
- If local fixes needed, use alpha mask with tight region boundaries
- Keep edit prompt explicit: what changes + what stays fixed

4. Final pass:
- `n=1`
- Quality: high
- Fixed output size/aspect across all final stills
- Log prompt + negative prompt + model + size + quality per shot

## 2) Global constraints for THE TRACE

- Visual style: grounded clinical surrealism, school realism, controlled contrast highlights.
- Preserve Leyla identity and wardrobe across all shots.
- Fluorescent scenes: keep slight green institutional cast, but preserve natural skin tones.
- Red emergency scene: maintain highlight detail and midtone separation (no clipping).
- No fantasy VFX, no comic-book grading, no glossy CGI look.

## 3) Shot set to generate

Generate all five first, then lock these finalists:
- `s1`, `s2`, `s3`, `s4`, `s5`

Current production-critical selections in pipeline:
- `s1`, `s3`, `s5`

Prompts and negatives:
- Use: `runs/input/the_trace.image_prompts.refined.json`

## 4) Cost/latency guardrails

- Do not run high quality before shortlist.
- Keep production `n` minimal (`n=1`).
- Avoid repeated high-fidelity edits on weak candidates.
- Keep one major visual change per refinement turn.

## 5) Quick quality gate per shot

- Face identity stable and realistic anatomy.
- One primary readable action in frame.
- Lighting temperature consistent with scene intent.
- Highlights preserved (water/red practical lights/medical whites).
- Background supports story beat without stealing focus.

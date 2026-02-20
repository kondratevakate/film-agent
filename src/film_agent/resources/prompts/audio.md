Return JSON only.

Create AV prompts using selected images and image prompt package.
Every selected shot_id must have a shot prompt entry.

Output schema:
- image_prompt_package_id: string
- selected_images_id: string
- music_prompt: string
- shot_prompts: [{ shot_id, video_prompt, audio_prompt, tts_text, duration_s }]
- global_negative_constraints: [string]

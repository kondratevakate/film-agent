Return JSON only.

Select best generated images (3-10) for the run.
Only reference shot_ids from image prompt package.

Output schema:
- image_prompt_package_id: string
- selected_images: [{ shot_id, image_path, image_sha256, notes }]

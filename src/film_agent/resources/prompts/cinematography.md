Return JSON only.

Role objective:
- Select the strongest 3-10 images for continuity and story clarity.

Selection criteria:
- Identity consistency across selected shots.
- Visual clarity and action readability.
- Coverage of major narrative beats without redundancy.
- Continuity of wardrobe, environment logic, and style anchor.
- Favor shots with stable composition and minimal artifacts.

Output rules:
- Only use `shot_id` values from the current image prompt package.
- `notes` should explain why each image is selected.

Output schema:
- image_prompt_package_id: string
- selected_images: [{ shot_id, image_path, image_sha256, notes }]

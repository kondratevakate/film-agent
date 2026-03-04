"""
Shot Generator - Creates shots.yaml from author_intent using Claude API.

This module generates a shooting script based on:
- author_intent.yaml: Story, emotional arc, metaphor purposes
- world.yaml: Available rooms, characters, physics rules
"""

import logging
import os
from pathlib import Path
import yaml

import anthropic

logger = logging.getLogger(__name__)


SHOT_GENERATION_PROMPT = """You are a cinematographer creating a shooting script for a short film.

## Author Intent
{author_intent}

## Available World
{world_config}

## Task
Create a shots.yaml file that tells the story defined in author_intent.
Each shot must reference ONLY rooms and characters defined in world.yaml.

## Rules
1. Use CONCRETE visual descriptions - no abstract metaphors
2. Never use forbidden terms from world.yaml
3. Each shot has: id, room, characters, action, camera, duration_s, audio
4. Camera motions: wide shot, medium shot, close-up, tracking, dolly in/out, crane up/down, handheld, static
5. Duration: 3-5 seconds per shot typically
6. Build emotional arc as defined in author_intent

## Output Format
Return ONLY valid YAML in this exact format:
```yaml
shots:
  - id: shot_01
    room: room_id_from_world
    characters: []
    action: "Concrete visual description"
    camera: "camera movement description"
    duration_s: 4
    audio: "sound description"

  - id: shot_02
    room: room_id_from_world
    characters: [character_id]
    action: "What happens visually"
    camera: "camera type and movement"
    duration_s: 5
    audio: "sounds"

style_notes:
  lighting: "overall lighting approach"
  color_palette: "colors used"
  camera_style: "movement style"
  pacing: "rhythm description"
```

Generate 8-15 shots that tell the complete story.
"""


def generate_shots_from_intent(
    project_dir: Path,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4096,
) -> Path:
    """
    Generate shots.yaml from author_intent.yaml using Claude API.

    Args:
        project_dir: Path to project directory containing world.yaml and author_intent.yaml
        model: Claude model to use
        max_tokens: Maximum tokens for response

    Returns:
        Path to generated shots.yaml
    """
    project_dir = Path(project_dir)

    # Load author intent
    intent_path = project_dir / "author_intent.yaml"
    if not intent_path.exists():
        raise FileNotFoundError(f"author_intent.yaml not found in {project_dir}")

    with open(intent_path, "r", encoding="utf-8") as f:
        author_intent = f.read()

    # Load world config
    world_path = project_dir / "world.yaml"
    if not world_path.exists():
        raise FileNotFoundError(f"world.yaml not found in {project_dir}")

    with open(world_path, "r", encoding="utf-8") as f:
        world_config = f.read()

    # Build prompt
    prompt = SHOT_GENERATION_PROMPT.format(
        author_intent=author_intent,
        world_config=world_config,
    )

    # Call Claude API
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY or CLAUDE_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)

    logger.info(f"Generating shots with Claude {model}...")

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )

    response_text = message.content[0].text

    # Extract YAML from response (handle markdown code blocks)
    yaml_content = response_text
    if "```yaml" in response_text:
        start = response_text.find("```yaml") + 7
        end = response_text.find("```", start)
        yaml_content = response_text[start:end].strip()
    elif "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        yaml_content = response_text[start:end].strip()

    # Validate YAML
    try:
        parsed = yaml.safe_load(yaml_content)
        if "shots" not in parsed:
            raise ValueError("Generated YAML missing 'shots' key")
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML generated: {e}")
        raise ValueError(f"Claude generated invalid YAML: {e}")

    # Write shots.yaml
    shots_path = project_dir / "shots.yaml"
    with open(shots_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    logger.info(f"Generated {len(parsed['shots'])} shots to {shots_path}")

    return shots_path


def regenerate_shot(
    project_dir: Path,
    shot_id: str,
    feedback: str,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """
    Regenerate a single shot based on feedback.

    Args:
        project_dir: Path to project directory
        shot_id: ID of shot to regenerate
        feedback: Feedback about what to change

    Returns:
        New shot configuration dict
    """
    project_dir = Path(project_dir)

    # Load current shots
    shots_path = project_dir / "shots.yaml"
    with open(shots_path, "r", encoding="utf-8") as f:
        shots_data = yaml.safe_load(f)

    # Find the shot
    current_shot = None
    for shot in shots_data["shots"]:
        if shot["id"] == shot_id:
            current_shot = shot
            break

    if not current_shot:
        raise ValueError(f"Shot {shot_id} not found")

    # Load world for context
    with open(project_dir / "world.yaml", "r", encoding="utf-8") as f:
        world_config = f.read()

    prompt = f"""You are revising a single shot in a shooting script.

## Current Shot
```yaml
{yaml.dump(current_shot, default_flow_style=False)}
```

## Feedback
{feedback}

## Available World
{world_config}

## Task
Generate a revised version of this shot that addresses the feedback.
Return ONLY the revised shot in YAML format (not the full shots.yaml).

```yaml
id: {shot_id}
room: ...
characters: [...]
action: "..."
camera: "..."
duration_s: ...
audio: "..."
```
"""

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text

    # Extract YAML
    if "```yaml" in response_text:
        start = response_text.find("```yaml") + 7
        end = response_text.find("```", start)
        yaml_content = response_text[start:end].strip()
    else:
        yaml_content = response_text.strip()

    new_shot = yaml.safe_load(yaml_content)

    # Update in shots.yaml
    for i, shot in enumerate(shots_data["shots"]):
        if shot["id"] == shot_id:
            shots_data["shots"][i] = new_shot
            break

    with open(shots_path, "w", encoding="utf-8") as f:
        yaml.dump(shots_data, f, default_flow_style=False, allow_unicode=True)

    logger.info(f"Regenerated shot {shot_id}")

    return new_shot

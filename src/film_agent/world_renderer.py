"""
WorldRenderer - Renders shots using pre-defined world anchors.

This implements the World Model First architecture:
1. Load locked room and character anchors
2. Build prompts from shots.yaml
3. Generate video with anchored references
4. Validate output against author intent
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml

from .core import (
    AuthorIntent,
    MetaphorTranslator,
    StyleEnforcer,
    NarrativeContext,
    PhysicsEngine,
    CharacterAnchors,
    ValidationLoop,
)
from .higgsfield_client import HiggsFieldClient, GenerationResult


logger = logging.getLogger(__name__)


@dataclass
class ShotConfig:
    """Configuration for a single shot."""

    id: str
    room: str
    characters: list[str]
    action: str
    camera: str
    duration_s: int
    audio: str = ""
    arc_beat: Optional[str] = None


@dataclass
class WorldConfig:
    """Loaded world configuration."""

    castle_name: str
    castle_style: str
    rooms: dict
    characters: dict
    metaphor_visuals: dict
    forbidden_terms: list
    physics: dict

    @classmethod
    def from_yaml(cls, path: str | Path) -> "WorldConfig":
        """Load world configuration from YAML."""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        castle = data.get("castle", {})
        return cls(
            castle_name=castle.get("name", ""),
            castle_style=castle.get("style", ""),
            rooms=data.get("rooms", {}),
            characters=data.get("characters", {}),
            metaphor_visuals=data.get("metaphor_visuals", {}),
            forbidden_terms=data.get("forbidden_terms", []),
            physics=data.get("physics", {}),
        )


@dataclass
class RoomAnchors:
    """
    Room anchor images with HYBRID architecture support.

    Supports layered lookup:
    - Base anchors from project-level (configs/project/anchors/rooms_hq/)
    - Run-level overrides (runs/{run_id}/iter-N/anchors/rooms_hq/)
    - Run-level takes precedence over project-level
    """

    anchors: dict[str, Path] = field(default_factory=dict)

    # Base directory for anchors (project-level)
    base_dir: Optional[Path] = None

    # Run directory for overrides
    run_dir: Optional[Path] = None

    @classmethod
    def _load_from_dir(cls, anchors_dir: Path, existing: dict[str, Path] | None = None) -> dict[str, Path]:
        """Load room anchors from a single directory."""
        anchors = existing.copy() if existing else {}

        if not anchors_dir.exists():
            return anchors

        for file in anchors_dir.glob("*.png"):
            # Parse room ID from filename
            # Expected: 01_tatami_hall.png -> tatami_hall
            name = file.stem
            parts = name.split("_", 1)
            if len(parts) == 2:
                room_id = parts[1]
            else:
                room_id = name
            anchors[room_id] = file

        return anchors

    @classmethod
    def from_dir(cls, anchors_dir: str | Path) -> "RoomAnchors":
        """Load room anchors from directory."""
        anchors_dir = Path(anchors_dir)
        anchors = cls._load_from_dir(anchors_dir)
        return cls(anchors=anchors, base_dir=anchors_dir)

    @classmethod
    def from_layered_dirs(
        cls,
        base_dir: str | Path,
        run_dir: str | Path | None = None
    ) -> "RoomAnchors":
        """
        Load room anchors with run-level overrides.

        HYBRID architecture:
        1. Load base anchors from project-level
        2. Override with run-level anchors (if they exist)

        Args:
            base_dir: Project-level anchors (always loaded)
            run_dir: Run-level anchors (overrides base if exists)

        Returns:
            RoomAnchors with merged references (run takes precedence)
        """
        base_dir = Path(base_dir)
        run_dir = Path(run_dir) if run_dir else None

        # Load base anchors
        anchors = cls._load_from_dir(base_dir)

        # Override with run-level anchors
        if run_dir and run_dir.exists():
            anchors = cls._load_from_dir(run_dir, existing=anchors)

        return cls(
            anchors=anchors,
            base_dir=base_dir,
            run_dir=run_dir
        )

    def get(self, room_id: str) -> Optional[Path]:
        """Get anchor path for a room."""
        return self.anchors.get(room_id)

    def get_source(self, room_id: str) -> Optional[str]:
        """Get source of anchor (base or run)."""
        path = self.anchors.get(room_id)
        if not path:
            return None
        if self.run_dir and path.is_relative_to(self.run_dir):
            return "run"
        return "base"


@dataclass
class WorldRenderer:
    """
    Renders shots in a pre-defined world using locked anchors.

    This ensures consistency across all shots by:
    1. Using room anchors for environment
    2. Using character anchors for identity
    3. Applying physics rules per room
    4. Validating against author intent

    Example:
        renderer = WorldRenderer.from_project("configs/contrast-infinity-castle")

        for shot in shots:
            video = await renderer.render_shot(shot)
            save_video(video, f"outputs/{shot.id}.mp4")
    """

    # Configuration
    world: WorldConfig
    room_anchors: RoomAnchors
    character_anchors: CharacterAnchors

    # Validators
    validation_loop: ValidationLoop

    # API client
    client: HiggsFieldClient

    # Project paths
    project_dir: Path
    outputs_dir: Path

    # Optional run directory for hybrid architecture
    run_dir: Optional[Path] = None

    # World directory (for from_cwd architecture)
    world_dir: Optional[Path] = None

    @classmethod
    def from_project(
        cls,
        project_dir: str | Path,
        run_dir: str | Path | None = None
    ) -> "WorldRenderer":
        """
        Initialize renderer from project directory.

        HYBRID architecture:
        - Base anchors from project_dir/anchors/
        - Run-level overrides from run_dir/anchors/ (if provided)
        - Run-level takes precedence over project-level

        Expected structure:
            project_dir/
                world.yaml
                shots.yaml
                author_intent.yaml
                anchors/
                    rooms_hq/
                        01_tatami_hall.png
                        ...
                    characters/
                        intruder_turnaround.png
                        ...

            run_dir/ (optional, for per-run overrides)
                anchors/
                    rooms_hq/
                        01_tatami_hall.png  # overrides base
                    characters/
                        intruder_turnaround.png  # overrides base
        """
        project_dir = Path(project_dir)
        run_dir = Path(run_dir) if run_dir else None

        # Load world config
        world = WorldConfig.from_yaml(project_dir / "world.yaml")

        # Load anchors with hybrid support
        base_rooms_dir = project_dir / "anchors" / "rooms_hq"
        base_chars_dir = project_dir / "anchors" / "characters"
        run_rooms_dir = run_dir / "anchors" / "rooms_hq" if run_dir else None
        run_chars_dir = run_dir / "anchors" / "characters" if run_dir else None

        room_anchors = RoomAnchors.from_layered_dirs(base_rooms_dir, run_rooms_dir)
        character_anchors = CharacterAnchors.from_layered_dirs(base_chars_dir, run_chars_dir)

        # Initialize validation loop
        validation_loop = ValidationLoop.from_project(project_dir)

        # Initialize API client
        client = HiggsFieldClient.from_env()

        # Setup output directory (in run_dir if provided, else project_dir)
        outputs_dir = (run_dir or project_dir) / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            world=world,
            room_anchors=room_anchors,
            character_anchors=character_anchors,
            validation_loop=validation_loop,
            client=client,
            project_dir=project_dir,
            outputs_dir=outputs_dir,
            run_dir=run_dir,
        )

    @classmethod
    def from_cwd(cls, run_id: str | None = None) -> "WorldRenderer":
        """
        Initialize renderer from current working directory.

        Clean architecture:
        - Project root = cwd (contains world.yaml, author_intent.yaml)
        - world/ = shared world anchors (rooms/, characters/)
        - run-XXX/ = individual scenario runs

        Expected structure:
            ./
                world.yaml          ← world definition (text only)
                author_intent.yaml  ← author intent (text only)
                world/              ← shared world anchors
                    rooms/
                        tatami_hall.png
                        ...
                    characters/
                        intruder_turnaround.png
                        ...
                run-001/            ← scenario run (optional)
                    shots.yaml
                    anchors/        ← run-level overrides
                    outputs/

        Args:
            run_id: Optional run directory name (e.g., "run-001")
                    If provided, shots.yaml is loaded from run dir
                    and outputs go to run dir.
        """
        project_dir = Path.cwd()
        world_dir = project_dir / "world"
        run_dir = project_dir / run_id if run_id else None

        # Load world config from project root
        world = WorldConfig.from_yaml(project_dir / "world.yaml")

        # Load anchors: world/ (base) + run/anchors/ (overrides)
        base_rooms_dir = world_dir / "rooms"
        base_chars_dir = world_dir / "characters"
        run_rooms_dir = run_dir / "anchors" / "rooms" if run_dir else None
        run_chars_dir = run_dir / "anchors" / "characters" if run_dir else None

        room_anchors = RoomAnchors.from_layered_dirs(base_rooms_dir, run_rooms_dir)
        character_anchors = CharacterAnchors.from_layered_dirs(base_chars_dir, run_chars_dir)

        # Initialize validation loop
        validation_loop = ValidationLoop.from_project(project_dir)

        # Initialize API client
        client = HiggsFieldClient.from_env()

        # Setup output directory
        outputs_dir = (run_dir or project_dir) / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            world=world,
            room_anchors=room_anchors,
            character_anchors=character_anchors,
            validation_loop=validation_loop,
            client=client,
            project_dir=project_dir,
            outputs_dir=outputs_dir,
            run_dir=run_dir,
            world_dir=world_dir,
        )

    def load_shots(self, from_run: bool = True) -> list[ShotConfig]:
        """
        Load shots from shots.yaml.

        Args:
            from_run: If True and run_dir exists, load from run_dir/shots.yaml
                      Otherwise load from project_dir/shots.yaml
        """
        if from_run and self.run_dir:
            shots_path = self.run_dir / "shots.yaml"
        else:
            shots_path = self.project_dir / "shots.yaml"

        with open(shots_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        shots = []
        for shot_data in data.get("shots", []):
            shots.append(
                ShotConfig(
                    id=shot_data["id"],
                    room=shot_data["room"],
                    characters=shot_data.get("characters", []),
                    action=shot_data["action"],
                    camera=shot_data["camera"],
                    duration_s=shot_data.get("duration_s", 5),
                    audio=shot_data.get("audio", ""),
                )
            )
        return shots

    def build_prompt(self, shot: ShotConfig) -> str:
        """
        Build full prompt for a shot.

        Combines:
        - Room description from world.yaml
        - Character appearance
        - Shot action
        - Camera instructions
        - Room mood
        """
        room_data = self.world.rooms.get(shot.room, {})
        room_desc = room_data.get("description", "")
        room_mood = room_data.get("mood", "")

        # Build character descriptions
        char_descs = []
        for char_id in shot.characters:
            char_data = self.world.characters.get(char_id, {})
            if char_data:
                appearance = char_data.get("appearance", "")
                char_descs.append(appearance)

        # Combine into prompt
        parts = []

        # Action first (what's happening)
        parts.append(shot.action)

        # Character descriptions
        if char_descs:
            parts.append("Characters: " + "; ".join(char_descs))

        # Environment
        parts.append(f"Setting: {room_desc}")

        # Camera
        parts.append(f"Camera: {shot.camera}")

        # Mood
        if room_mood:
            parts.append(f"Mood: {room_mood}")

        prompt = ". ".join(parts) + "."
        return prompt

    def render_shot(self, shot: ShotConfig, shot_index: int = 0, total_shots: int = 1) -> GenerationResult:
        """
        Render a single shot.

        1. Build prompt from shot config
        2. Process through validation loop
        3. Load anchors
        4. Generate video
        5. Save result
        """
        logger.info(f"Rendering shot: {shot.id}")

        # 1. Build prompt
        raw_prompt = self.build_prompt(shot)
        logger.debug(f"Raw prompt: {raw_prompt}")

        # 2. Process through validation loop
        processed_prompt = self.validation_loop.process_prompt(
            prompt=raw_prompt,
            shot_id=shot.id,
            shot_index=shot_index,
            total_shots=total_shots,
            room_id=shot.room,
        )
        logger.debug(f"Processed prompt: {processed_prompt}")

        # 3. Load room anchor
        room_anchor_path = self.room_anchors.get(shot.room)
        input_image = None
        if room_anchor_path and room_anchor_path.exists():
            input_image = self.client.load_image_as_base64(room_anchor_path)
            logger.info(f"Using room anchor: {room_anchor_path.name}")

        # 4. Get camera motion from shot
        camera_motion = shot.camera

        # 5. Generate video
        result = self.client.generate_video(
            prompt=processed_prompt,
            input_image=input_image,
            duration=shot.duration_s,
            camera_motion=camera_motion,
            negative_prompt="anime, cartoon, illustration, cel-shaded, manga",
        )

        # 6. Download if successful
        if result.status == "completed" and result.output_url:
            output_path = self.outputs_dir / f"{shot.id}.mp4"
            self.client.download_result(result.output_url, output_path)
            logger.info(f"Saved: {output_path}")

        return result

    def render_all_shots(self) -> list[GenerationResult]:
        """Render all shots in sequence."""
        shots = self.load_shots()
        results = []

        for idx, shot in enumerate(shots):
            result = self.render_shot(shot, idx, len(shots))
            results.append(result)

            # Log progress
            logger.info(f"Progress: {idx + 1}/{len(shots)} shots completed")

        return results

    def generate_room_anchor(self, room_id: str, save_to_run: bool = False) -> GenerationResult:
        """
        Generate a room anchor image.

        Args:
            room_id: Room ID from world.yaml
            save_to_run: If True and run_dir exists, save to run-level anchors

        Use this to create initial environment anchors.
        """
        room_data = self.world.rooms.get(room_id, {})
        room_desc = room_data.get("description", "")
        room_mood = room_data.get("mood", "")

        prompt = f"{room_desc}. {self.world.castle_style}. Mood: {room_mood}."
        prompt += " Photorealistic, 8K, shot on ARRI Alexa."
        prompt += " NOT anime, NOT cartoon, NOT illustration."

        result = self.client.generate_image(
            prompt=prompt,
            aspect_ratio="16:9",
            resolution="1080p",
            negative_prompt="anime, cartoon, illustration, cel-shaded",
        )

        # Download if successful
        if result.status == "completed" and result.output_url:
            # Choose output directory based on architecture and save_to_run flag
            if save_to_run and self.run_dir:
                # Save to run-level overrides
                output_path = self.run_dir / "anchors" / "rooms" / f"{room_id}.png"
            elif self.world_dir:
                # from_cwd architecture: save to world/rooms/
                output_path = self.world_dir / "rooms" / f"{room_id}.png"
            else:
                # Legacy: save to project/anchors/rooms_hq/
                output_path = self.project_dir / "anchors" / "rooms_hq" / f"{room_id}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_result(result.output_url, output_path)
            logger.info(f"Saved room anchor to: {output_path}")

        return result

    def generate_character_anchor(
        self, character_id: str, view: str = "turnaround", save_to_run: bool = False
    ) -> GenerationResult:
        """
        Generate a character anchor image.

        Args:
            character_id: Character ID from world.yaml
            view: "front", "profile", "back", or "turnaround"
            save_to_run: If True and run_dir exists, save to run-level anchors
        """
        char_data = self.world.characters.get(character_id, {})
        appearance = char_data.get("appearance", "")

        if view == "turnaround":
            prompt = f"Character turnaround sheet showing front view, profile view, and back view. {appearance}. {self.world.castle_style}."
        else:
            prompt = f"{view.capitalize()} view of {appearance}. {self.world.castle_style}."

        prompt += " Photorealistic, full body, neutral pose."
        prompt += " NOT anime, NOT cartoon, NOT illustration."

        result = self.client.generate_image(
            prompt=prompt,
            aspect_ratio="16:9",
            resolution="1080p",
            negative_prompt="anime, cartoon, illustration, cel-shaded",
        )

        # Download if successful
        if result.status == "completed" and result.output_url:
            # Choose output directory based on architecture and save_to_run flag
            if save_to_run and self.run_dir:
                # Save to run-level overrides
                output_path = self.run_dir / "anchors" / "characters" / f"{character_id}_{view}.png"
            elif self.world_dir:
                # from_cwd architecture: save to world/characters/
                output_path = self.world_dir / "characters" / f"{character_id}_{view}.png"
            else:
                # Legacy: save to project/anchors/characters/
                output_path = self.project_dir / "anchors" / "characters" / f"{character_id}_{view}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_result(result.output_url, output_path)
            logger.info(f"Saved character anchor to: {output_path}")

        return result

    def validate_world(self) -> tuple[bool, list[str], dict]:
        """
        Validate that the world is ready for rendering.

        Checks:
        - All rooms have anchors
        - All characters have anchors
        - Physics rules are defined

        Returns:
            (is_valid, issues, anchor_sources)
            anchor_sources: {"rooms": {room_id: "base"|"run"}, "characters": {char_id: "base"|"run"}}
        """
        issues = []
        anchor_sources = {"rooms": {}, "characters": {}}

        # Check room anchors
        for room_id in self.world.rooms:
            anchor_path = self.room_anchors.get(room_id)
            if not anchor_path:
                issues.append(f"Missing room anchor: {room_id}")
            else:
                source = self.room_anchors.get_source(room_id)
                anchor_sources["rooms"][room_id] = source

        # Check character anchors
        for char_id in self.world.characters:
            if not self.character_anchors.has_character(char_id):
                issues.append(f"Missing character anchor: {char_id}")
            else:
                source = self.character_anchors.get_source(char_id)
                anchor_sources["characters"][char_id] = source or "base"

        # Check physics
        physics_rooms = self.world.physics.get("rooms", {})
        for room_id in self.world.rooms:
            if room_id not in physics_rooms:
                issues.append(f"Missing physics for room: {room_id}")

        is_valid = len(issues) == 0
        return is_valid, issues, anchor_sources

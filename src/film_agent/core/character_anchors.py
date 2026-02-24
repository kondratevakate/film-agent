"""
CharacterAnchors - Locked reference images for character consistency.

Ensures characters look the same across all shots by using
pre-generated turnaround sheets as references.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import base64


@dataclass
class CharacterReference:
    """Reference images for a single character."""

    character_id: str
    front_path: Optional[Path] = None
    profile_path: Optional[Path] = None
    back_path: Optional[Path] = None
    turnaround_path: Optional[Path] = None

    def get_best_reference(self, camera_angle: str) -> Optional[Path]:
        """
        Select the best reference image based on camera angle.

        Args:
            camera_angle: Description of camera angle (e.g., "front", "profile", "3/4")

        Returns:
            Path to the most appropriate reference image
        """
        angle_lower = camera_angle.lower()

        # Direct matches
        if "front" in angle_lower or "face" in angle_lower:
            return self.front_path or self.turnaround_path
        if "profile" in angle_lower or "side" in angle_lower:
            return self.profile_path or self.turnaround_path
        if "back" in angle_lower or "behind" in angle_lower:
            return self.back_path or self.turnaround_path

        # Default to turnaround or front
        return self.turnaround_path or self.front_path

    def exists(self) -> bool:
        """Check if any reference images exist."""
        paths = [self.front_path, self.profile_path, self.back_path, self.turnaround_path]
        return any(p and p.exists() for p in paths)


@dataclass
class CharacterAnchors:
    """
    Manages locked reference images for character consistency.

    Characters must look the same across all shots. This class
    loads pre-generated turnaround sheets and provides the
    appropriate reference for each shot based on camera angle.

    Supports HYBRID architecture:
    - Base anchors from project-level (configs/project/anchors/characters/)
    - Run-level overrides (runs/{run_id}/iter-N/anchors/characters/)
    - Run-level takes precedence over project-level

    Example:
        # Base anchors only
        anchors = CharacterAnchors.from_anchors_dir(
            Path("configs/contrast-infinity-castle/anchors/characters")
        )

        # Hybrid: run overrides base
        anchors = CharacterAnchors.from_layered_dirs(
            base_dir=Path("configs/contrast-infinity-castle/anchors/characters"),
            run_dir=Path("runs/run_001/iter-2/anchors/characters")
        )

        ref = anchors.get_reference("intruder", "profile shot")
        # Returns run-level if exists, else base-level
    """

    # Character references by ID
    characters: dict[str, CharacterReference] = field(default_factory=dict)

    # Base directory for anchors (project-level)
    anchors_dir: Optional[Path] = None

    # Run directory for overrides
    run_anchors_dir: Optional[Path] = None

    @classmethod
    def _load_from_dir(cls, anchors_dir: Path, existing: dict[str, CharacterReference] | None = None) -> dict[str, CharacterReference]:
        """Load character references from a single directory."""
        characters = existing.copy() if existing else {}

        if not anchors_dir.exists():
            return characters

        for file in anchors_dir.glob("*.png"):
            name = file.stem

            # Parse character ID and view type
            parts = name.rsplit("_", 1)
            if len(parts) == 2:
                char_id, view_type = parts
            else:
                char_id = parts[0]
                view_type = "turnaround"

            # Create or update character reference
            if char_id not in characters:
                characters[char_id] = CharacterReference(character_id=char_id)

            ref = characters[char_id]

            if view_type == "front":
                ref.front_path = file
            elif view_type == "profile":
                ref.profile_path = file
            elif view_type == "back":
                ref.back_path = file
            elif view_type == "turnaround":
                ref.turnaround_path = file

        return characters

    @classmethod
    def from_anchors_dir(cls, anchors_dir: str | Path) -> "CharacterAnchors":
        """
        Load character anchors from directory.

        Expected structure:
            anchors/characters/
                intruder_front.png
                intruder_profile.png
                intruder_back.png
                intruder_turnaround.png (combined sheet)
                geisha_turnaround.png
        """
        anchors_dir = Path(anchors_dir)
        characters = cls._load_from_dir(anchors_dir)
        return cls(characters=characters, anchors_dir=anchors_dir)

    @classmethod
    def from_layered_dirs(
        cls,
        base_dir: str | Path,
        run_dir: str | Path | None = None
    ) -> "CharacterAnchors":
        """
        Load character anchors with run-level overrides.

        HYBRID architecture:
        1. Load base anchors from project-level
        2. Override with run-level anchors (if they exist)

        Args:
            base_dir: Project-level anchors (always loaded)
            run_dir: Run-level anchors (overrides base if exists)

        Returns:
            CharacterAnchors with merged references (run takes precedence)
        """
        base_dir = Path(base_dir)
        run_dir = Path(run_dir) if run_dir else None

        # Load base anchors
        characters = cls._load_from_dir(base_dir)

        # Override with run-level anchors
        if run_dir and run_dir.exists():
            characters = cls._load_from_dir(run_dir, existing=characters)

        return cls(
            characters=characters,
            anchors_dir=base_dir,
            run_anchors_dir=run_dir
        )

    def get_reference(self, character_id: str, camera_angle: str = "") -> Optional[Path]:
        """
        Get the best reference image for a character.

        Args:
            character_id: ID of the character
            camera_angle: Description of camera angle

        Returns:
            Path to reference image, or None if not found
        """
        ref = self.characters.get(character_id)
        if not ref:
            return None

        return ref.get_best_reference(camera_angle)

    def get_all_references(self, character_id: str) -> list[Path]:
        """Get all available reference images for a character."""
        ref = self.characters.get(character_id)
        if not ref:
            return []

        paths = [ref.front_path, ref.profile_path, ref.back_path, ref.turnaround_path]
        return [p for p in paths if p and p.exists()]

    def load_as_base64(self, path: Path) -> Optional[str]:
        """Load an image and return as base64 string."""
        if not path or not path.exists():
            return None

        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def validate_consistency(self) -> tuple[bool, Optional[str]]:
        """
        Validate that all required characters have references.

        Returns:
            (is_valid, error_message or None)
        """
        if not self.characters:
            return False, "No character anchors loaded"

        for char_id, ref in self.characters.items():
            if not ref.exists():
                return False, f"No reference images found for character: {char_id}"

        return True, None

    def get_character_ids(self) -> list[str]:
        """Get list of all character IDs with anchors."""
        return list(self.characters.keys())

    def has_character(self, character_id: str) -> bool:
        """Check if a character has anchors loaded."""
        ref = self.characters.get(character_id)
        return ref is not None and ref.exists()

    def get_source(self, character_id: str) -> Optional[str]:
        """
        Get source of character anchor (base or run).

        Returns:
            "base", "run", or None if character not found
        """
        ref = self.characters.get(character_id)
        if not ref or not ref.exists():
            return None

        # Check if any anchor path is in run_anchors_dir
        any_path = ref.turnaround_path or ref.front_path or ref.profile_path or ref.back_path
        if any_path and self.run_anchors_dir:
            try:
                if any_path.is_relative_to(self.run_anchors_dir):
                    return "run"
            except ValueError:
                pass
        return "base"

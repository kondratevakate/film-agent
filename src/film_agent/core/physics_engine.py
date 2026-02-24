"""
PhysicsEngine - Per-room motion rules and physics behavior.

Ensures consistent physics within each room type and proper
transitions between rooms with different physics.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class PhysicsConfig:
    """Physics configuration for a room."""

    motion_style: str
    movement_speed: float
    camera_style: str
    environment_effects: str
    physics_metaphor: str = ""


@dataclass
class TransitionConfig:
    """Configuration for transitioning between rooms."""

    door_effect: str
    lighting_shift: str
    sound_cue: str
    physics_shift: str = ""


@dataclass
class PhysicsEngine:
    """
    Manages physics rules per room and transitions between rooms.

    Each room in the castle has different physics behavior:
    - Water chamber: slow, floating movements (0.3x speed)
    - Sumo ring: heavy impacts, ground shake (0.7x speed)
    - Tai chi room: fluid continuous motion (0.5x speed)
    - Corridor: disorienting, perspective shifts (1.0x speed but unstable)

    Example:
        engine = PhysicsEngine.from_world_config(world_path)
        physics = engine.get_room_physics("glass_water_chamber")
        prompt = engine.apply_physics(prompt, physics)
    """

    # Room physics configurations
    room_physics: dict[str, PhysicsConfig] = field(default_factory=dict)

    # Global physics effects
    global_effects: dict[str, str] = field(default_factory=dict)

    # Transition configurations
    transitions: dict[str, TransitionConfig] = field(default_factory=dict)

    @classmethod
    def from_world_config(cls, world_path: str | Path) -> "PhysicsEngine":
        """Load physics from world.yaml config."""
        path = Path(world_path)
        if not path.exists():
            raise FileNotFoundError(f"World config not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            world = yaml.safe_load(f)

        physics_data = world.get("physics", {})

        # Parse room physics
        room_physics = {}
        for room_id, room_data in physics_data.get("rooms", {}).items():
            room_physics[room_id] = PhysicsConfig(
                motion_style=room_data.get("motion_style", "normal"),
                movement_speed=room_data.get("movement_speed", 1.0),
                camera_style=room_data.get("camera", "steady"),
                environment_effects=room_data.get("environment", ""),
                physics_metaphor=room_data.get("physics_metaphor", ""),
            )

        # Parse transitions
        transitions = {}
        for trans_name, trans_data in physics_data.get("transitions", {}).items():
            transitions[trans_name] = TransitionConfig(
                door_effect=trans_data.get("motion", ""),
                lighting_shift=trans_data.get("effect", ""),
                sound_cue=trans_data.get("sound", ""),
                physics_shift=trans_data.get("physics_metaphor", ""),
            )

        return cls(
            room_physics=room_physics,
            global_effects=physics_data.get("global", {}),
            transitions=transitions,
        )

    def get_room_physics(self, room_id: str) -> Optional[PhysicsConfig]:
        """Get physics configuration for a room."""
        return self.room_physics.get(room_id)

    def get_transition(self, from_room: str, to_room: str) -> Optional[TransitionConfig]:
        """Get transition configuration between two rooms."""
        # Try specific transition first
        key = f"{from_room}_to_{to_room}"
        if key in self.transitions:
            return self.transitions[key]

        # Fall back to generic transitions
        return self.transitions.get("room_to_room")

    def apply_physics(self, prompt: str, physics: PhysicsConfig) -> str:
        """
        Apply physics rules to a prompt.

        Args:
            prompt: Original prompt
            physics: Physics configuration for the room

        Returns:
            Prompt enhanced with physics directives
        """
        physics_parts = []

        # Add motion style
        if physics.motion_style:
            physics_parts.append(f"Motion: {physics.motion_style}")

        # Add speed modifier
        if physics.movement_speed != 1.0:
            if physics.movement_speed < 1.0:
                speed_desc = f"slow motion ({int(physics.movement_speed * 100)}% speed)"
            else:
                speed_desc = f"fast motion ({int(physics.movement_speed * 100)}% speed)"
            physics_parts.append(speed_desc)

        # Add camera style
        if physics.camera_style:
            physics_parts.append(f"Camera: {physics.camera_style}")

        # Add environment effects
        if physics.environment_effects:
            physics_parts.append(f"Environment: {physics.environment_effects}")

        if physics_parts:
            physics_suffix = ". ".join(physics_parts)
            return f"{prompt.rstrip('.')}. {physics_suffix}."

        return prompt

    def apply_transition(self, prompt: str, transition: TransitionConfig) -> str:
        """
        Apply transition effects to a prompt.

        Args:
            prompt: Original prompt
            transition: Transition configuration

        Returns:
            Prompt enhanced with transition directives
        """
        trans_parts = []

        if transition.door_effect:
            trans_parts.append(f"Door: {transition.door_effect}")

        if transition.lighting_shift:
            trans_parts.append(f"Lighting: {transition.lighting_shift}")

        if transition.sound_cue:
            trans_parts.append(f"Sound: {transition.sound_cue}")

        if trans_parts:
            trans_suffix = ". ".join(trans_parts)
            return f"{prompt.rstrip('.')}. {trans_suffix}."

        return prompt

    def get_global_effect(self, effect_name: str) -> Optional[str]:
        """Get a global physics effect by name."""
        return self.global_effects.get(effect_name)

    def validate_physics_consistency(
        self, shots: list[dict]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that physics are consistent within each room.

        Returns:
            (is_valid, error_message or None)
        """
        current_room = None

        for shot in shots:
            room = shot.get("room")
            if not room:
                continue

            if room != current_room:
                # Room change - check for transition
                if current_room is not None:
                    transition = self.get_transition(current_room, room)
                    if transition is None:
                        return False, f"No transition defined from {current_room} to {room}"

                current_room = room

        return True, None

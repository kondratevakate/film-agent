"""
NarrativeContext - Tracks emotional arc and narrative flow.

Ensures each shot knows its position in the story and transitions
make narrative sense.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ShotContext:
    """Context for a single shot in the narrative."""

    shot_id: str
    shot_index: int
    total_shots: int
    current_beat: str
    previous_mood: Optional[str] = None
    next_transition: Optional[str] = None
    arc_position: float = 0.0  # 0.0 = beginning, 1.0 = end


@dataclass
class NarrativeContext:
    """
    Tracks narrative flow and emotional arc across shots.

    This ensures that transitions between shots serve the story
    and don't just happen randomly.

    Example:
        context = NarrativeContext(emotional_arc=["disorientation", "discovery", "confrontation", "resolution"])
        shot_ctx = context.get_shot_context("shot_05", 4, 12)
        print(shot_ctx.current_beat)  # "disorientation" or "discovery"
        print(shot_ctx.arc_position)  # 0.33
    """

    # Emotional arc through the film
    emotional_arc: list[str] = field(
        default_factory=lambda: ["disorientation", "discovery", "confrontation", "resolution"]
    )

    # Mood mappings for each arc beat
    beat_moods: dict[str, str] = field(
        default_factory=lambda: {
            "disorientation": "confusion, unease, searching",
            "discovery": "curiosity, revelation, building tension",
            "confrontation": "determination, intensity, conflict",
            "resolution": "clarity, triumph, release",
        }
    )

    # Transition types between beats
    beat_transitions: dict[str, str] = field(
        default_factory=lambda: {
            "disorientation_to_discovery": "slow realization, light grows",
            "discovery_to_confrontation": "tension builds, pace quickens",
            "confrontation_to_resolution": "climactic moment, release",
        }
    )

    def get_shot_context(
        self, shot_id: str, shot_index: int, total_shots: int, previous_mood: Optional[str] = None
    ) -> ShotContext:
        """
        Get the narrative context for a specific shot.

        Args:
            shot_id: Identifier for the shot
            shot_index: 0-based index of shot
            total_shots: Total number of shots
            previous_mood: Mood of previous shot (for transitions)

        Returns:
            ShotContext with all relevant narrative information
        """
        arc_position = shot_index / max(total_shots - 1, 1)

        # Determine current beat
        beat_index = int(arc_position * len(self.emotional_arc))
        beat_index = min(beat_index, len(self.emotional_arc) - 1)
        current_beat = self.emotional_arc[beat_index]

        # Determine next transition
        next_transition = None
        if beat_index < len(self.emotional_arc) - 1:
            next_beat = self.emotional_arc[beat_index + 1]
            transition_key = f"{current_beat}_to_{next_beat}"
            next_transition = self.beat_transitions.get(transition_key)

        return ShotContext(
            shot_id=shot_id,
            shot_index=shot_index,
            total_shots=total_shots,
            current_beat=current_beat,
            previous_mood=previous_mood,
            next_transition=next_transition,
            arc_position=arc_position,
        )

    def get_mood_for_beat(self, beat: str) -> str:
        """Get the mood description for a given arc beat."""
        return self.beat_moods.get(beat, "neutral")

    def inject_context(self, prompt: str, shot_context: ShotContext) -> str:
        """
        Inject narrative context into a prompt.

        Args:
            prompt: Original prompt
            shot_context: Context for this shot

        Returns:
            Prompt enhanced with narrative context
        """
        mood = self.get_mood_for_beat(shot_context.current_beat)

        # Build context suffix
        context_parts = [f"Mood: {mood}"]

        # Add arc position awareness
        if shot_context.arc_position < 0.25:
            context_parts.append("Beginning of story - establish atmosphere")
        elif shot_context.arc_position < 0.5:
            context_parts.append("Building tension - discovery phase")
        elif shot_context.arc_position < 0.75:
            context_parts.append("Peak conflict - confrontation")
        else:
            context_parts.append("Resolution - climax and release")

        # Add transition hint if applicable
        if shot_context.next_transition:
            context_parts.append(f"Transition hint: {shot_context.next_transition}")

        context_suffix = ". ".join(context_parts)

        return f"{prompt.rstrip('.')}. {context_suffix}."

    def validate_narrative_flow(
        self, shots: list[dict], required_beats: Optional[list[str]] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that a sequence of shots covers the narrative arc.

        Returns:
            (is_valid, error_message or None)
        """
        if not shots:
            return False, "No shots provided"

        # Check that we have shots for each beat
        required = required_beats or self.emotional_arc

        for beat in required:
            beat_shots = [s for s in shots if s.get("arc_beat") == beat]
            if not beat_shots:
                return False, f"No shots found for narrative beat: {beat}"

        return True, None

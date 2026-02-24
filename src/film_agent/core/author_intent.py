"""
AuthorIntent - Immutable singleton that persists through entire pipeline.

This ensures that the author's original narrative intent is never lost
during generation, and all gates can validate against it.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


@dataclass(frozen=True)
class AuthorIntent:
    """
    Immutable container for author's narrative intent.

    This is loaded once at the start of generation and passed through
    ALL gates in the pipeline. Each gate validates its output against
    this intent.

    Example:
        intent = AuthorIntent.from_yaml("configs/contrast-infinity-castle/author_intent.yaml")
        if not intent.serves_narrative(generated_prompt):
            raise ValidationError("Output doesn't serve author's story")
    """

    # Core narrative - what story is being told
    core_narrative: str

    # Why each metaphor exists (not what it looks like)
    metaphor_purposes: dict = field(default_factory=dict)

    # Emotional arc through the film
    emotional_arc: tuple = field(default_factory=tuple)

    # Target audience understanding
    audience_takeaway: str = ""

    # Project identifier
    project_id: str = ""

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AuthorIntent":
        """Load author intent from YAML config file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Author intent config not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls(
            core_narrative=data.get("core_narrative", ""),
            metaphor_purposes=data.get("metaphor_purposes", {}),
            emotional_arc=tuple(data.get("emotional_arc", [])),
            audience_takeaway=data.get("audience_takeaway", ""),
            project_id=data.get("project_id", path.parent.name),
        )

    def get_context_prompt(self) -> str:
        """
        Generate context string to prepend to LLM prompts.

        This ensures the model always remembers why we're doing this.
        """
        metaphor_lines = "\n".join(
            f"  - {k}: {v}" for k, v in self.metaphor_purposes.items()
        )
        arc_str = " → ".join(self.emotional_arc)

        return f"""## Author Intent (DO NOT DEVIATE)
Core Story: {self.core_narrative}
Emotional Arc: {arc_str}
Audience Should Feel: {self.audience_takeaway}

Metaphor Purposes (why they exist, not what they look like):
{metaphor_lines}

IMPORTANT: Every output must serve this narrative. If it doesn't, regenerate.
"""

    def validate_serves_narrative(self, text: str) -> tuple[bool, Optional[str]]:
        """
        Check if generated text serves the narrative intent.

        Returns:
            (is_valid, error_message or None)
        """
        # Check for forbidden literal interpretations
        literal_metaphors = [
            "hydrogen atom",
            "H2O molecule",
            "MRI machine",
            "scanner bore",
            "gadolinium injection",
            "T1 relaxation",
            "T2 decay",
        ]

        text_lower = text.lower()
        for literal in literal_metaphors:
            if literal.lower() in text_lower:
                return False, f"Literal metaphor interpretation found: '{literal}'"

        return True, None

    def get_arc_position(self, shot_index: int, total_shots: int) -> str:
        """Get the emotional beat for a given shot position."""
        if not self.emotional_arc:
            return "neutral"

        arc_len = len(self.emotional_arc)
        position = int((shot_index / total_shots) * arc_len)
        position = min(position, arc_len - 1)

        return self.emotional_arc[position]


# Singleton instance for current session
_current_intent: Optional[AuthorIntent] = None


def get_current_intent() -> Optional[AuthorIntent]:
    """Get the current session's author intent."""
    return _current_intent


def set_current_intent(intent: AuthorIntent) -> None:
    """Set the current session's author intent."""
    global _current_intent
    _current_intent = intent

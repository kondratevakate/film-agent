"""
MetaphorTranslator - Translates metaphors to visual descriptions.

This prevents the video generator from literally interpreting
metaphors like "hydrogen" as actual atoms.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


class MetaphorTranslationError(Exception):
    """Raised when a forbidden term is found in output."""

    pass


@dataclass
class MetaphorTranslator:
    """
    Translates metaphor terms to concrete visual descriptions.

    CRITICAL: This is the first line of defense against literal
    interpretation of metaphors. Every prompt MUST pass through
    this translator before being sent to the video generator.

    Example:
        translator = MetaphorTranslator.from_world_config(world)
        clean_prompt = translator.translate("The hydrogen crowd gathers around the bone pillar")
        # Returns: "The crowd in white robes swaying in synchronized waves gathers around the tall pale wooden column"
    """

    # Terms that must NEVER appear in final prompts
    forbidden_terms: list[str] = field(default_factory=list)

    # Metaphor → Visual description mappings
    translations: dict[str, str] = field(default_factory=dict)

    # Style terms to always add
    required_style: str = "photorealistic Japanese castle interior, warm amber lighting"

    # Anti-style terms to add
    forbidden_styles: list[str] = field(default_factory=list)

    @classmethod
    def from_world_config(cls, world_path: str | Path) -> "MetaphorTranslator":
        """Load translator from world.yaml config."""
        path = Path(world_path)
        if not path.exists():
            raise FileNotFoundError(f"World config not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            world = yaml.safe_load(f)

        return cls(
            forbidden_terms=world.get("forbidden_terms", []),
            translations=world.get("metaphor_visuals", {}),
            forbidden_styles=["anime", "cartoon", "illustration", "cel-shaded", "manga"],
        )

    def translate(self, text: str) -> str:
        """
        Translate metaphors to visual descriptions.

        Args:
            text: Input prompt potentially containing metaphors

        Returns:
            Cleaned prompt with metaphors replaced by visual descriptions

        Raises:
            MetaphorTranslationError: If forbidden terms remain after translation
        """
        result = text

        # Apply translations (case-insensitive)
        for metaphor, visual in self.translations.items():
            # Match whole words only
            pattern = rf"\b{re.escape(metaphor)}\b"
            result = re.sub(pattern, visual, result, flags=re.IGNORECASE)

        # Check for forbidden terms
        self._check_forbidden_terms(result)

        return result

    def _check_forbidden_terms(self, text: str) -> None:
        """Raise error if any forbidden terms remain."""
        text_lower = text.lower()
        for term in self.forbidden_terms:
            if term.lower() in text_lower:
                raise MetaphorTranslationError(
                    f"Forbidden term '{term}' found in prompt. "
                    f"This term should be translated to a visual description. "
                    f"Check metaphor_visuals in world.yaml."
                )

    def validate(self, text: str) -> tuple[bool, Optional[str]]:
        """
        Validate text without raising exception.

        Returns:
            (is_valid, error_message or None)
        """
        text_lower = text.lower()

        # Check forbidden terms
        for term in self.forbidden_terms:
            if term.lower() in text_lower:
                return False, f"Forbidden term '{term}' found in prompt"

        # Check forbidden styles
        for style in self.forbidden_styles:
            if style.lower() in text_lower:
                return False, f"Forbidden style '{style}' found in prompt"

        return True, None

    def ensure_style(self, text: str) -> str:
        """
        Ensure required style is present and forbidden styles are excluded.

        Args:
            text: Input prompt

        Returns:
            Prompt with style requirements appended
        """
        # Check if style already present
        if self.required_style.lower() not in text.lower():
            text = f"{text}. Style: {self.required_style}"

        # Add anti-style guidance
        anti_styles = ", ".join(self.forbidden_styles)
        if "NOT" not in text.upper():
            text = f"{text}. NOT {anti_styles}."

        return text

    def full_process(self, text: str) -> str:
        """
        Full translation pipeline: translate + ensure style.

        This is the main entry point for prompt processing.
        """
        # First translate metaphors
        translated = self.translate(text)

        # Then ensure style
        styled = self.ensure_style(translated)

        return styled

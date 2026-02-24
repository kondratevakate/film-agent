"""
StyleEnforcer - Validates and enforces photorealistic style requirements.

Prevents anime/cartoon outputs by explicitly requiring photorealism
in every prompt.
"""

from dataclasses import dataclass, field
from typing import Optional


class StyleValidationError(Exception):
    """Raised when a forbidden style is detected."""

    pass


@dataclass
class StyleEnforcer:
    """
    Enforces consistent visual style across all generated content.

    CRITICAL: This ensures we never get anime or cartoon outputs
    when we need photorealistic content.

    Example:
        enforcer = StyleEnforcer()
        clean_prompt = enforcer.enforce("Young woman in castle")
        # Returns: "Young woman in castle. Photorealistic Japanese castle interior,
        #           warm amber lantern lighting. NOT anime, NOT cartoon, NOT illustration."
    """

    # Required style elements
    required_style: str = "photorealistic Japanese castle interior, warm amber lantern lighting"

    # Forbidden style terms
    forbidden_styles: list[str] = field(
        default_factory=lambda: [
            "anime",
            "cartoon",
            "illustration",
            "cel-shaded",
            "manga",
            "comic",
            "drawn",
            "2D",
            "stylized",
        ]
    )

    # Required negative prompts
    negative_prompt: str = "anime, cartoon, illustration, cel-shaded, manga, comic book, drawn, 2D, stylized, unrealistic"

    def enforce(self, prompt: str) -> str:
        """
        Add style requirements to prompt.

        Args:
            prompt: Input prompt

        Returns:
            Prompt with style requirements appended
        """
        # Check for forbidden styles first
        is_valid, error = self.validate(prompt)
        if not is_valid:
            raise StyleValidationError(error)

        # Build enhanced prompt
        parts = [prompt.rstrip(".")]

        # Add required style if not present
        if "photorealistic" not in prompt.lower():
            parts.append(self.required_style)

        # Add explicit negative guidance
        parts.append(f"NOT {self.negative_prompt}")

        return ". ".join(parts) + "."

    def validate(self, prompt: str) -> tuple[bool, Optional[str]]:
        """
        Check if prompt contains forbidden styles.

        Returns:
            (is_valid, error_message or None)
        """
        prompt_lower = prompt.lower()

        for style in self.forbidden_styles:
            # Check if style is used positively (not after "NOT" or "no")
            if style.lower() in prompt_lower:
                # Check if it's in a negative context
                idx = prompt_lower.find(style.lower())
                prefix = prompt_lower[max(0, idx - 10) : idx]
                if "not " not in prefix and "no " not in prefix:
                    return False, f"Forbidden style '{style}' found in prompt"

        return True, None

    def get_negative_prompt(self) -> str:
        """Get the negative prompt string for video generators that support it."""
        return self.negative_prompt

    def enhance_for_photorealism(self, prompt: str) -> str:
        """
        Add specific photorealism enhancers.

        Use this for hero frames and important shots.
        """
        enhancers = [
            "shot on ARRI Alexa",
            "35mm film grain",
            "natural lighting",
            "shallow depth of field",
            "8K resolution",
        ]

        enhanced = prompt.rstrip(".")
        enhanced += f". {', '.join(enhancers)}."
        enhanced += f" NOT {self.negative_prompt}."

        return enhanced

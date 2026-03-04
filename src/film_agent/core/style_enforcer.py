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
        Check if prompt contains forbidden styles in positive context.

        Returns:
            (is_valid, error_message or None)
        """
        prompt_lower = prompt.lower()

        # Find all "NOT" or "not" sections (negative contexts)
        # These sections start with NOT/not and continue to the next period or end
        import re
        negative_sections = []
        for match in re.finditer(r'\bnot\b[^.]*', prompt_lower):
            negative_sections.append((match.start(), match.end()))

        def is_in_negative_context(idx: int) -> bool:
            """Check if position is within a negative context."""
            for start, end in negative_sections:
                if start <= idx <= end:
                    return True
            return False

        for style in self.forbidden_styles:
            style_lower = style.lower()
            # Find all occurrences
            start = 0
            while True:
                idx = prompt_lower.find(style_lower, start)
                if idx == -1:
                    break
                # Check if this occurrence is in a negative context
                if not is_in_negative_context(idx):
                    return False, f"Forbidden style '{style}' found in prompt"
                start = idx + 1

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

"""
Core validation and context modules for Film Agent.

This module implements the feedback loop architecture:
- AuthorIntent: Immutable context that persists through pipeline
- MetaphorTranslator: Translates metaphors to visual descriptions
- StyleEnforcer: Validates photorealistic style requirements
- NarrativeContext: Tracks arc position per shot
- PhysicsEngine: Per-room motion rules
- CharacterAnchors: Locked reference images for consistency
- ValidationLoop: Orchestrates all validators
"""

from .author_intent import AuthorIntent
from .metaphor_translator import MetaphorTranslator
from .style_enforcer import StyleEnforcer
from .narrative_context import NarrativeContext
from .physics_engine import PhysicsEngine
from .character_anchors import CharacterAnchors
from .validation_loop import ValidationLoop

__all__ = [
    "AuthorIntent",
    "MetaphorTranslator",
    "StyleEnforcer",
    "NarrativeContext",
    "PhysicsEngine",
    "CharacterAnchors",
    "ValidationLoop",
]

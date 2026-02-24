"""
ValidationLoop - Orchestrates all validators for the feedback loop.

This is the central coordinator that runs all validation checks
and handles regeneration when validation fails.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any
import logging
from datetime import datetime

from .author_intent import AuthorIntent
from .metaphor_translator import MetaphorTranslator, MetaphorTranslationError
from .style_enforcer import StyleEnforcer, StyleValidationError
from .narrative_context import NarrativeContext, ShotContext
from .physics_engine import PhysicsEngine, PhysicsConfig


logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validation check."""

    is_valid: bool
    validator_name: str
    error_message: Optional[str] = None
    fix_suggestion: Optional[str] = None


@dataclass
class QCFeedback:
    """Feedback entry for QC log."""

    timestamp: str
    shot_id: str
    issue_type: str
    description: str
    action_taken: str
    resolved: bool = False


@dataclass
class ValidationLoop:
    """
    Orchestrates all validators and manages the feedback loop.

    This is the main entry point for validating prompts before
    sending them to the video generator. If validation fails,
    it logs the issue and can trigger regeneration.

    Example:
        loop = ValidationLoop.from_project("configs/contrast-infinity-castle")

        # Validate and process a prompt
        result = loop.validate_and_process(
            prompt="The hydrogen crowd gathers",
            shot_id="shot_01",
            room_id="tatami_hall"
        )

        if result.is_valid:
            send_to_generator(result.processed_prompt)
        else:
            handle_validation_failure(result)
    """

    # Core validators
    author_intent: Optional[AuthorIntent] = None
    metaphor_translator: Optional[MetaphorTranslator] = None
    style_enforcer: Optional[StyleEnforcer] = None
    narrative_context: Optional[NarrativeContext] = None
    physics_engine: Optional[PhysicsEngine] = None

    # QC feedback log
    feedback_log: list[QCFeedback] = field(default_factory=list)

    # Configuration
    max_retries: int = 3
    auto_fix: bool = True

    @classmethod
    def from_project(cls, project_dir: str | Path) -> "ValidationLoop":
        """
        Load all validators from project configuration.

        Args:
            project_dir: Path to project config directory

        Returns:
            Configured ValidationLoop
        """
        project_dir = Path(project_dir)

        # Load author intent
        author_intent = None
        author_intent_path = project_dir / "author_intent.yaml"
        if author_intent_path.exists():
            author_intent = AuthorIntent.from_yaml(author_intent_path)

        # Load world config for metaphor translator and physics
        world_path = project_dir / "world.yaml"
        metaphor_translator = None
        physics_engine = None

        if world_path.exists():
            metaphor_translator = MetaphorTranslator.from_world_config(world_path)
            physics_engine = PhysicsEngine.from_world_config(world_path)

        # Create style enforcer with defaults
        style_enforcer = StyleEnforcer()

        # Create narrative context from author intent
        narrative_context = None
        if author_intent and author_intent.emotional_arc:
            narrative_context = NarrativeContext(
                emotional_arc=list(author_intent.emotional_arc)
            )

        return cls(
            author_intent=author_intent,
            metaphor_translator=metaphor_translator,
            style_enforcer=style_enforcer,
            narrative_context=narrative_context,
            physics_engine=physics_engine,
        )

    def validate_all(self, prompt: str, shot_id: str = "") -> list[ValidationResult]:
        """
        Run all validators on a prompt.

        Returns:
            List of validation results
        """
        results = []

        # 1. Metaphor translation check
        if self.metaphor_translator:
            is_valid, error = self.metaphor_translator.validate(prompt)
            results.append(
                ValidationResult(
                    is_valid=is_valid,
                    validator_name="metaphor_translator",
                    error_message=error,
                    fix_suggestion="Use metaphor_translator.translate() to fix" if not is_valid else None,
                )
            )

        # 2. Style check
        if self.style_enforcer:
            is_valid, error = self.style_enforcer.validate(prompt)
            results.append(
                ValidationResult(
                    is_valid=is_valid,
                    validator_name="style_enforcer",
                    error_message=error,
                    fix_suggestion="Use style_enforcer.enforce() to fix" if not is_valid else None,
                )
            )

        # 3. Author intent check
        if self.author_intent:
            is_valid, error = self.author_intent.validate_serves_narrative(prompt)
            results.append(
                ValidationResult(
                    is_valid=is_valid,
                    validator_name="author_intent",
                    error_message=error,
                    fix_suggestion="Rewrite to serve narrative intent" if not is_valid else None,
                )
            )

        return results

    def process_prompt(
        self,
        prompt: str,
        shot_id: str,
        shot_index: int = 0,
        total_shots: int = 1,
        room_id: Optional[str] = None,
    ) -> str:
        """
        Full processing pipeline for a prompt.

        1. Translate metaphors
        2. Enforce style
        3. Inject narrative context
        4. Apply physics
        5. Validate result

        Returns:
            Processed prompt ready for video generation
        """
        processed = prompt

        # 1. Translate metaphors
        if self.metaphor_translator:
            processed = self.metaphor_translator.full_process(processed)

        # 2. Enforce style
        if self.style_enforcer:
            processed = self.style_enforcer.enforce(processed)

        # 3. Inject narrative context
        if self.narrative_context:
            shot_ctx = self.narrative_context.get_shot_context(
                shot_id, shot_index, total_shots
            )
            processed = self.narrative_context.inject_context(processed, shot_ctx)

        # 4. Apply physics
        if self.physics_engine and room_id:
            physics = self.physics_engine.get_room_physics(room_id)
            if physics:
                processed = self.physics_engine.apply_physics(processed, physics)

        # 5. Final validation
        results = self.validate_all(processed, shot_id)
        failures = [r for r in results if not r.is_valid]

        if failures:
            self._log_failures(shot_id, failures)
            # For now, just log - in production this would trigger regeneration

        return processed

    def _log_failures(self, shot_id: str, failures: list[ValidationResult]) -> None:
        """Log validation failures for QC review."""
        for failure in failures:
            feedback = QCFeedback(
                timestamp=datetime.now().isoformat(),
                shot_id=shot_id,
                issue_type=failure.validator_name,
                description=failure.error_message or "Unknown error",
                action_taken="logged for review",
            )
            self.feedback_log.append(feedback)
            logger.warning(
                f"Validation failed for {shot_id}: [{failure.validator_name}] {failure.error_message}"
            )

    def get_feedback_summary(self) -> dict:
        """Get summary of QC feedback."""
        if not self.feedback_log:
            return {"total_issues": 0, "by_type": {}, "unresolved": 0}

        by_type = {}
        unresolved = 0

        for fb in self.feedback_log:
            by_type[fb.issue_type] = by_type.get(fb.issue_type, 0) + 1
            if not fb.resolved:
                unresolved += 1

        return {
            "total_issues": len(self.feedback_log),
            "by_type": by_type,
            "unresolved": unresolved,
        }

    def apply_feedback(self, feedback_file: str | Path) -> None:
        """
        Apply QC feedback to update validation rules.

        This is how the system learns from author corrections.
        """
        import yaml

        path = Path(feedback_file)
        if not path.exists():
            return

        with open(path, "r", encoding="utf-8") as f:
            feedback_data = yaml.safe_load(f)

        # Add new forbidden terms
        if self.metaphor_translator and "new_forbidden_terms" in feedback_data:
            self.metaphor_translator.forbidden_terms.extend(
                feedback_data["new_forbidden_terms"]
            )

        # Add new translations
        if self.metaphor_translator and "new_translations" in feedback_data:
            self.metaphor_translator.translations.update(
                feedback_data["new_translations"]
            )

        logger.info(f"Applied feedback from {path}")

    def prepend_author_context(self, prompt: str) -> str:
        """
        Prepend author intent context to a prompt.

        Use this for LLM calls that need to understand the narrative.
        """
        if not self.author_intent:
            return prompt

        context = self.author_intent.get_context_prompt()
        return f"{context}\n\n{prompt}"

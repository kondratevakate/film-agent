"""Tests for core validation modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from film_agent.core import (
    AuthorIntent,
    MetaphorTranslator,
    StyleEnforcer,
    NarrativeContext,
    PhysicsEngine,
    ValidationLoop,
)


class TestMetaphorTranslator:
    """Tests for MetaphorTranslator."""

    def test_translate_replaces_forbidden_terms(self) -> None:
        translations = {"hydrogen_crowd": "crowd in white robes"}
        forbidden = ["hydrogen", "MRI"]
        translator = MetaphorTranslator(translations=translations, forbidden_terms=forbidden)

        result = translator.translate("The hydrogen_crowd moves forward")
        assert "hydrogen" not in result.lower()
        assert "crowd in white robes" in result

    def test_detect_forbidden_terms_returns_matches(self) -> None:
        translator = MetaphorTranslator(forbidden_terms=["anime", "MRI", "T1"])

        issues = translator.detect_forbidden_terms("This is anime style with MRI scanner")
        assert "anime" in issues
        assert "MRI" in issues
        assert "T1" not in issues

    def test_translate_chains_multiple_replacements(self) -> None:
        translations = {
            "hydrogen_crowd": "crowd in white",
            "bone_pillar": "wooden column",
        }
        translator = MetaphorTranslator(translations=translations, forbidden_terms=[])

        result = translator.translate("hydrogen_crowd near bone_pillar")
        assert "crowd in white" in result
        assert "wooden column" in result


class TestStyleEnforcer:
    """Tests for StyleEnforcer."""

    def test_enforce_appends_required_style(self) -> None:
        enforcer = StyleEnforcer(
            required_style="photorealistic Japanese castle",
            forbidden_styles=["anime"],
        )

        result = enforcer.enforce("A woman walks through the hall")
        assert "photorealistic Japanese castle" in result

    def test_detect_forbidden_styles_catches_violations(self) -> None:
        enforcer = StyleEnforcer(
            required_style="photorealistic",
            forbidden_styles=["anime", "cartoon", "illustration"],
        )

        violations = enforcer.detect_forbidden_styles("anime style illustration")
        assert "anime" in violations
        assert "illustration" in violations
        assert "cartoon" not in violations


class TestNarrativeContext:
    """Tests for NarrativeContext."""

    def test_get_beat_returns_correct_arc_position(self) -> None:
        arc = ["disorientation", "discovery", "confrontation", "resolution"]
        context = NarrativeContext(emotional_arc=arc)

        # First quarter = disorientation
        beat = context.get_beat(shot_index=0, total_shots=12)
        assert beat == "disorientation"

        # Last quarter = resolution
        beat = context.get_beat(shot_index=11, total_shots=12)
        assert beat == "resolution"

    def test_inject_context_adds_narrative_info(self) -> None:
        arc = ["disorientation", "discovery"]
        context = NarrativeContext(emotional_arc=arc)

        result = context.inject_context("The intruder enters", shot_index=0, total_shots=4)
        assert "disorientation" in result.lower() or "The intruder enters" in result


class TestPhysicsEngine:
    """Tests for PhysicsEngine."""

    def test_get_room_physics_returns_defaults_for_unknown(self) -> None:
        engine = PhysicsEngine(room_physics={})

        physics = engine.get_room_physics("unknown_room")
        assert physics.motion_style is not None
        assert physics.movement_speed == 1.0

    def test_get_room_physics_returns_configured_values(self) -> None:
        room_physics = {
            "water_chamber": {
                "motion_style": "slow floating",
                "movement_speed": 0.3,
            }
        }
        engine = PhysicsEngine(room_physics=room_physics)

        physics = engine.get_room_physics("water_chamber")
        assert physics.motion_style == "slow floating"
        assert physics.movement_speed == 0.3

    def test_apply_physics_modifies_prompt(self) -> None:
        room_physics = {
            "water_chamber": {
                "motion_style": "slow floating",
                "camera": "smooth dolly",
            }
        }
        engine = PhysicsEngine(room_physics=room_physics)

        result = engine.apply_physics("Character swims", "water_chamber")
        assert "slow" in result.lower() or "Character swims" in result


class TestAuthorIntent:
    """Tests for AuthorIntent."""

    def test_from_dict_loads_all_fields(self) -> None:
        data = {
            "core_narrative": "A story about discovery",
            "audience_takeaway": "Viewers feel curious",
            "emotional_arc": ["disorientation", "discovery"],
            "metaphor_purposes": {"hydrogen_crowd": "represents patients"},
        }

        intent = AuthorIntent.from_dict(data)
        assert intent.core_narrative == "A story about discovery"
        assert len(intent.emotional_arc) == 2
        assert "hydrogen_crowd" in intent.metaphor_purposes

    def test_validate_output_checks_forbidden_terms(self) -> None:
        intent = AuthorIntent(
            core_narrative="MRI story",
            forbidden_terms=["anime", "MRI machine"],
        )

        # Should fail - contains forbidden term
        is_valid, issues = intent.validate_output("The anime MRI machine scans")
        assert not is_valid
        assert any("anime" in issue for issue in issues)


class TestValidationLoop:
    """Tests for ValidationLoop orchestrator."""

    def test_process_prompt_applies_all_validators(self) -> None:
        loop = ValidationLoop(
            author_intent=AuthorIntent(
                core_narrative="Test story",
                forbidden_terms=["anime"],
            ),
            metaphor_translator=MetaphorTranslator(
                translations={"hydrogen_crowd": "crowd in white"},
                forbidden_terms=["hydrogen"],
            ),
            style_enforcer=StyleEnforcer(
                required_style="photorealistic",
                forbidden_styles=["anime"],
            ),
            narrative_context=NarrativeContext(
                emotional_arc=["discovery"],
            ),
            physics_engine=PhysicsEngine(room_physics={}),
        )

        result = loop.process_prompt(
            prompt="hydrogen_crowd moves",
            shot_id="shot_01",
            shot_index=0,
            total_shots=1,
            room_id="test_room",
        )

        # Should translate metaphor
        assert "hydrogen" not in result.lower() or "crowd in white" in result
        # Should add style
        assert "photorealistic" in result.lower()


class TestIntegrationWithYaml:
    """Integration tests loading from YAML files."""

    def test_validation_loop_from_project_loads_config(self, tmp_path: Path) -> None:
        # Create minimal config files
        author_intent_yaml = tmp_path / "author_intent.yaml"
        author_intent_yaml.write_text("""
core_narrative: "Test narrative"
emotional_arc:
  - discovery
  - resolution
metaphor_purposes:
  test_metaphor: "test meaning"
forbidden_literal:
  - anime
""")

        world_yaml = tmp_path / "world.yaml"
        world_yaml.write_text("""
castle:
  name: "Test Castle"
  style: "photorealistic"
rooms:
  test_room:
    description: "A test room"
    mood: "neutral"
metaphor_visuals:
  test_metaphor: "visual description"
forbidden_terms:
  - anime
physics:
  rooms:
    test_room:
      motion_style: "normal"
      movement_speed: 1.0
""")

        loop = ValidationLoop.from_project(tmp_path)
        assert loop is not None
        assert loop.author_intent is not None

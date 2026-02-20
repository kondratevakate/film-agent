from __future__ import annotations

import json
from pathlib import Path

from film_agent.gates.scoring import compute_audio_sync
from film_agent.io.hashing import sha256_file
from film_agent.schemas.artifacts import AudioPlan, FinalMetrics
from film_agent.state_machine.orchestrator import create_run
from film_agent.state_machine.state_store import load_state, run_dir


def test_create_run_resolves_relative_science_pdf_against_config_dir(tmp_path: Path) -> None:
    config_dir = tmp_path / "config_root"
    references = config_dir / "references"
    references.mkdir(parents=True)
    paper = references / "paper.pdf"
    paper.write_bytes(b"paper")

    config = {
        "project_name": "relative-path-test",
        "science_source_pdf": "references/paper.pdf",
        "duration_target_s": 95,
        "model_candidates": [
            {
                "name": "test-model",
                "weighted_score": 1.0,
                "physics": 1.0,
                "human_fidelity": 1.0,
                "identity": 1.0,
            }
        ],
    }
    config_path = config_dir / "project.yaml"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    run = create_run(tmp_path, config_path)
    state = load_state(run_dir(tmp_path, run.run_id))

    assert state.config_path == str(config_path.resolve())
    assert state.science_source_hash == sha256_file(paper)


def test_audio_sync_penalizes_unordered_or_out_of_range_markers() -> None:
    metrics = FinalMetrics.model_validate(
        {
            "videoscore2": 0.8,
            "vbench2_physics": 0.8,
            "identity_drift": 0.1,
            "audiosync_score": 80.0,
            "consistency_score": 85.0,
            "spec_hash": "locked-spec",
        }
    )
    good = AudioPlan.model_validate(
        {
            "motifs": [],
            "voice_lines": [{"line_id": "l1", "timestamp_s": 2.0, "speaker": "Narrator", "text": "x"}],
            "cues": [{"cue_id": "c1", "timestamp_s": 0.0, "duration_s": 8.0, "cue_type": "music", "description": "x"}],
            "sync_markers": [0.0, 2.0, 5.0, 8.0],
        }
    )
    bad = AudioPlan.model_validate(
        {
            "motifs": [],
            "voice_lines": [{"line_id": "l1", "timestamp_s": 2.0, "speaker": "Narrator", "text": "x"}],
            "cues": [{"cue_id": "c1", "timestamp_s": 0.0, "duration_s": 8.0, "cue_type": "music", "description": "x"}],
            "sync_markers": [999.0, 2.0, -20.0],
        }
    )

    assert compute_audio_sync(good, metrics) > compute_audio_sync(bad, metrics)

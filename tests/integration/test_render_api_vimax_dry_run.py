from __future__ import annotations

from pathlib import Path

from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.render_api import render_run_via_api
from film_agent.state_machine.orchestrator import create_run, submit_agent
from film_agent.state_machine.state_store import load_state, run_dir, save_state
from tests.helpers import write_config


def test_render_api_uses_vimax_lines_in_dry_run(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    created = create_run(tmp_path, config)
    run_id = created.run_id
    run_path = run_dir(tmp_path, run_id)

    state = load_state(run_path)
    state.current_state = "FINAL_RENDER"
    save_state(run_path, state)

    render_package_file = tmp_path / "render_package.json"
    dump_canonical_json(
        render_package_file,
        {
            "video_provider": "veo_yunwu",
            "model_version": "veo3.1-fast",
            "seed": 42,
            "resolution": "1920x1080",
            "fps": 24,
            "sampler_settings": {},
            "prompt_template_versions": {},
        },
    )
    submit_agent(tmp_path, run_id, "render_package", render_package_file)

    lines_path = tmp_path / "vimax_lines.json"
    dump_canonical_json(
        lines_path,
        {
            "lines": [
                {
                    "shot_id": "s1",
                    "duration_s": 4.0,
                    "video_prompt": "Camera push in.",
                    "negative_prompt": "blur",
                    "reference_image_path": "missing.png",
                },
                {
                    "shot_id": "s2",
                    "duration_s": 5.0,
                    "video_prompt": "Cut to close-up.",
                    "negative_prompt": "",
                    "reference_image_path": "missing2.png",
                },
            ]
        },
    )

    result = render_run_via_api(
        tmp_path,
        run_id,
        api_key="",
        dry_run=True,
        lines_path=lines_path,
    )
    manifest = load_json(result.manifest_path)
    assert manifest["source"]["type"] == "vimax_lines"
    assert len(manifest["shots"]) == 2
    assert all(item["status"] == "dry_run" for item in manifest["shots"])

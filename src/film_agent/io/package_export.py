"""Iteration export bundle builder."""

from __future__ import annotations

import shutil
from pathlib import Path

from film_agent.io.hashing import sha256_file
from film_agent.io.json_io import dump_canonical_json
from film_agent.state_machine.state_store import iteration_key, load_state, run_dir


def package_iteration(base_dir: Path, run_id: str, iteration: int | None = None) -> Path:
    run_path = run_dir(base_dir, run_id)
    state = load_state(run_path)
    target_iter = iteration or state.current_iteration
    iter_key = iteration_key(target_iter)

    src_artifacts = run_path / "iterations" / iter_key / "artifacts"
    if not src_artifacts.exists():
        raise ValueError(f"Iteration artifacts not found: {src_artifacts}")

    export_dir = run_path / "exports" / iter_key
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    artifacts_out = export_dir / "artifacts"
    shutil.copytree(src_artifacts, artifacts_out)

    scripts_out = export_dir / "scripts"
    scripts_out.mkdir(parents=True, exist_ok=True)
    script_map = _write_generation_scripts(scripts_out, run_id, target_iter)

    _write_runbook(export_dir)
    _write_env_example(export_dir)
    _write_readable_index(export_dir)
    _write_all_scripts(export_dir, script_map)
    _write_hash_manifest(export_dir)
    return export_dir


def _write_generation_scripts(scripts_out: Path, run_id: str, iteration: int) -> dict[str, str]:
    scripts = {
        "generate_audio_elevenlabs.py": _audio_script(run_id, iteration),
        "generate_images_openai_nanobanana.py": _image_script(run_id, iteration),
        "generate_video_openai.py": _video_openai_script(run_id, iteration),
        "generate_video_hugsfield.py": _video_hugsfield_script(run_id, iteration),
        "assemble_timeline.py": _timeline_script(run_id, iteration),
    }

    for name, content in scripts.items():
        (scripts_out / name).write_text(content, encoding="utf-8")
    return scripts


def _write_runbook(export_dir: Path) -> None:
    runbook = """# RUNBOOK

1. Fill `.env.example` into `.env` with API keys and provider-specific settings.
2. Review `artifacts/*.json` and confirm this iteration is the one you want to generate from.
3. Generate voice/audio first:
   `python scripts/generate_audio_elevenlabs.py`
4. Generate key images:
   `python scripts/generate_images_openai_nanobanana.py`
5. Run dry-run video with primary provider:
   `python scripts/generate_video_openai.py`
6. If primary provider blocks/fails quality, run fallback:
   `python scripts/generate_video_hugsfield.py`
7. Assemble timeline references:
   `python scripts/assemble_timeline.py`
8. Submit produced metrics/artifacts back to the pipeline with `film-agent submit`.
"""
    (export_dir / "RUNBOOK.md").write_text(runbook, encoding="utf-8")


def _write_env_example(export_dir: Path) -> None:
    payload = """OPENAI_API_KEY=
ELEVENLABS_API_KEY=
NANOBANANA_API_KEY=
HUGSFIELD_API_KEY=

# Optional endpoints
NANOBANANA_BASE_URL=
HUGSFIELD_BASE_URL=
"""
    (export_dir / ".env.example").write_text(payload, encoding="utf-8")


def _write_readable_index(export_dir: Path) -> None:
    lines = ["# Readable Index", ""]
    for path in sorted(export_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(export_dir)
        lines.append(f"- `{rel}`")
    (export_dir / "readable_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_all_scripts(export_dir: Path, scripts: dict[str, str]) -> None:
    lines = ["# All Scripts", ""]
    for name, content in scripts.items():
        lines.append(f"## {name}")
        lines.append("```python")
        lines.append(content.rstrip())
        lines.append("```")
        lines.append("")
    (export_dir / "all_scripts.md").write_text("\n".join(lines), encoding="utf-8")


def _write_hash_manifest(export_dir: Path) -> None:
    manifest: dict[str, str] = {}
    for path in sorted(export_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = str(path.relative_to(export_dir)).replace("\\", "/")
        if rel == "hash_manifest.json":
            continue
        manifest[rel] = sha256_file(path)
    dump_canonical_json(export_dir / "hash_manifest.json", manifest)


def _audio_script(run_id: str, iteration: int) -> str:
    return f'''#!/usr/bin/env python
import json
import os
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "audio_plan.json"
OUT = ROOT / "outputs" / "audio"
OUT.mkdir(parents=True, exist_ok=True)

api_key = os.environ.get("ELEVENLABS_API_KEY")
if not api_key:
    raise SystemExit("ELEVENLABS_API_KEY is required.")

plan = json.loads(ART.read_text(encoding="utf-8"))
voice_lines = plan.get("voice_lines", [])
if not voice_lines:
    print("No voice_lines found in audio_plan.json")
    raise SystemExit(0)

voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")
if not voice_id:
    raise SystemExit("Set ELEVENLABS_VOICE_ID to render voiceover lines.")

for item in voice_lines:
    line_id = item["line_id"]
    text = item["text"]
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{{voice_id}}"
    payload = {{
        "text": text,
        "model_id": "eleven_multilingual_v2",
    }}
    headers = {{
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }}
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    out_path = OUT / f"{{line_id}}.mp3"
    out_path.write_bytes(response.content)
    print("saved", out_path)
'''


def _image_script(run_id: str, iteration: int) -> str:
    return f'''#!/usr/bin/env python
import json
import os
from pathlib import Path
from openai import OpenAI
import requests

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "shot_design_sheets.json"
OUT = ROOT / "outputs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
if not os.environ.get("OPENAI_API_KEY"):
    raise SystemExit("OPENAI_API_KEY is required.")

package = json.loads(ART.read_text(encoding="utf-8"))
shots = package.get("shots", [])

for shot in shots:
    prompt = (
        f"Shot {{shot['shot_id']}}; "
        f"character={{shot['character']}}, action={{shot['pose_action']}}, "
        f"camera={{shot['camera']}}, lighting={{shot['lighting']}}, "
        f"background={{shot['background']}}, style={{'; '.join(shot.get('style_constraints', []))}}"
    )
    # Update model argument for your account/region.
    response = client.images.generate(model="gpt-image-1", prompt=prompt, size="1024x1024")
    b64 = response.data[0].b64_json
    png_bytes = __import__("base64").b64decode(b64)
    img_path = OUT / f"{{shot['shot_id']}}_openai.png"
    img_path.write_bytes(png_bytes)
    print("saved", img_path)

    # Optional NanoBanana pass
    nb_url = os.environ.get("NANOBANANA_BASE_URL")
    nb_key = os.environ.get("NANOBANANA_API_KEY")
    if nb_url and nb_key:
        payload = {{"prompt": prompt}}
        headers = {{"Authorization": f"Bearer {{nb_key}}", "Content-Type": "application/json"}}
        nb_resp = requests.post(nb_url.rstrip("/") + "/generate", headers=headers, json=payload, timeout=120)
        nb_resp.raise_for_status()
        nb_out = OUT / f"{{shot['shot_id']}}_nanobanana.json"
        nb_out.write_text(nb_resp.text, encoding="utf-8")
        print("saved", nb_out)
'''


def _video_openai_script(run_id: str, iteration: int) -> str:
    return f'''#!/usr/bin/env python
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "render_package.json"
OUT = ROOT / "outputs" / "video_openai"
OUT.mkdir(parents=True, exist_ok=True)

if not os.environ.get("OPENAI_API_KEY"):
    raise SystemExit("OPENAI_API_KEY is required.")

if not ART.exists():
    raise SystemExit("render_package.json is missing. Submit/render package artifact first.")

render = json.loads(ART.read_text(encoding="utf-8"))
payload = {{
    "provider": "openai_video",
    "note": "Fill concrete OpenAI video endpoint/model for your account.",
    "render_package": render,
    "run_id": "{run_id}",
    "iteration": {iteration},
}}

out = OUT / "openai_video_request.json"
out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print("prepared request payload", out)
print("Use your OpenAI video API call and save generated clip metadata to outputs/video_openai/")
'''


def _video_hugsfield_script(run_id: str, iteration: int) -> str:
    return f'''#!/usr/bin/env python
import json
import os
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "render_package.json"
OUT = ROOT / "outputs" / "video_hugsfield"
OUT.mkdir(parents=True, exist_ok=True)

base_url = os.environ.get("HUGSFIELD_BASE_URL")
api_key = os.environ.get("HUGSFIELD_API_KEY")
if not base_url or not api_key:
    raise SystemExit("Set HUGSFIELD_BASE_URL and HUGSFIELD_API_KEY.")
if not ART.exists():
    raise SystemExit("render_package.json is missing.")

render = json.loads(ART.read_text(encoding="utf-8"))
payload = {{
    "run_id": "{run_id}",
    "iteration": {iteration},
    "render_package": render,
}}
headers = {{"Authorization": f"Bearer {{api_key}}", "Content-Type": "application/json"}}
resp = requests.post(base_url.rstrip("/") + "/generate", headers=headers, json=payload, timeout=300)
resp.raise_for_status()
out = OUT / "hugsfield_response.json"
out.write_text(resp.text, encoding="utf-8")
print("saved", out)
'''


def _timeline_script(run_id: str, iteration: int) -> str:
    return f'''#!/usr/bin/env python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts" / "editorial_timeline.json"
OUT = ROOT / "outputs" / "timeline"
OUT.mkdir(parents=True, exist_ok=True)

if not ART.exists():
    raise SystemExit("editorial_timeline.json is missing.")

timeline = json.loads(ART.read_text(encoding="utf-8"))
entries = timeline.get("entries", [])
lines = ["# ffmpeg concat input", ""]
for item in entries:
    shot_id = item["shot_id"]
    lines.append(f"# shot {{shot_id}} duration={{item['duration_s']}}")
    lines.append(f"file 'video/{{shot_id}}.mp4'")
    lines.append(f"duration {{item['duration_s']}}")

out = OUT / "concat.txt"
out.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
print("saved", out)
print("Then run: ffmpeg -f concat -safe 0 -i concat.txt -c copy final.mp4")
'''

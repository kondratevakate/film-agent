#!/usr/bin/env python3
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from film_agent.providers.video_veo_yunwu import YunwuVeoClient, build_veo_yunwu_video_payload

# Load env
for line in (Path(__file__).parent.parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

client = YunwuVeoClient(api_key=os.environ["YUNWU_API_KEY"])
output = Path(__file__).parent.parent / "runs/the-trace-010/iterations/iter-03/render_outputs/yunwu_direct/02_G2.mp4"

# Different prompt - swimmer at pool
prompt = """Cinematic medium shot of an athletic woman in red swimsuit standing by indoor swimming pool.
She has wet dark hair and stands confidently at the pool edge. Blue pool water, lane markers visible.
Warm practical lighting, 1980s American sports film aesthetic like Flashdance.
High quality, detailed, professional cinematography."""

print("Creating task...")
payload = build_veo_yunwu_video_payload(prompt, [], model="veo3.1-fast", aspect_ratio="16:9")
task_id = client.create_task(payload)
print(f"Task: {task_id}")

result = client.wait_for_completion(task_id, poll_interval_s=5.0, timeout_s=600.0)
print("Downloading...")
client.download_video(result.video_url, output)
print(f"Done! {output}")

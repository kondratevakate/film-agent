# Cost-Optimized Runbook (Contrast Infinity Castle)

## Why this profile is cheaper
- Fewer retries: `retry_limits` are set to `1/1/1`.
- Shorter max duration: `duration_max_s: 120` instead of `150`.
- Lower render resolution for draft loops: `1280x720`.
- Simpler concept lock (`contrast`, `rhythm`) to reduce Gate1 fail loops.

Config file:
- `configs/project.contrast-infinity-castle.cost-optimized.yaml`

## Fast low-cost loop (recommended)
1. Create run:
```powershell
$created = film-agent new-run --config configs/project.contrast-infinity-castle.cost-optimized.yaml | ConvertFrom-Json
$runId = $created.run_id
$runId
```

2. Keep auto-iteration cheap:
```powershell
film-agent auto-run --run-id $runId --model gpt-4.1 --until gate2 --self-eval-rounds 0 --max-cycles 8
```

3. Push approved local inputs directly:
```powershell
film-agent replay-inputs --run-id $runId --inputs-dir configs/contrast-infinity-castle/inputs
```

4. Build packets and inspect before paid generation:
```powershell
film-agent packet build-all --run-id $runId
```

## Image generation key separation
`prepare-vimax` supports explicit key override via `--api-key`, so you can use a second key for images:
```powershell
$env:OPENAI_API_KEY_IMAGE2 = "your_second_key_here"
film-agent prepare-vimax --run-id $runId --api-key $env:OPENAI_API_KEY_IMAGE2 --dry-run
```

Then run paid image generation:
```powershell
film-agent prepare-vimax --run-id $runId --api-key $env:OPENAI_API_KEY_IMAGE2
```

## Render spend controls
Always preflight first:
```powershell
film-agent render-api --run-id $runId --provider veo_yunwu --dry-run
```

Then run paid render with conservative retries:
```powershell
film-agent render-api --run-id $runId --provider veo_yunwu --shot-retry-limit 1 --fail-fast
```

## Important note about NanoBanana
Current codebase does **not** wire NanoBanana into `prepare-vimax` image generation path.
- `prepare-vimax` currently uses OpenAI Images API (`src/film_agent/vimax_bridge.py`).
- `image_nanobanana.py` currently provides only payload helper, not an integrated client path.

So today, the practical optimization is:
- use a second OpenAI key for image calls, and
- keep the low-cost run profile above.

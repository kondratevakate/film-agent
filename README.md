# film-agent

Manual, file-based multi-agent pipeline for a 90-105s dance film workflow.

## What This Implements

- 5-agent manual orchestration (you run each agent in Codex, then submit JSON outputs).
- State machine with strict stage order:
  `INIT -> GATE0 -> COLLECT_SHOWRUNNER -> COLLECT_DIRECTION -> COLLECT_DANCE_MAPPING -> COLLECT_CINEMATOGRAPHY -> COLLECT_AUDIO -> LOCK_PREPROD -> GATE1 -> GATE2 -> DRYRUN -> GATE3 -> FINAL_RENDER -> GATE4`.
- Direction-first dance mapping:
  `UserDirectionPack` is required each iteration and `DanceMappingSpec.direction_pack_id` must reference it.
- Gate scoring and fail routing with retry limits.
- Iteration export package with copy-ready scripts:
  `artifacts/`, `scripts/`, `RUNBOOK.md`, `.env.example`, `hash_manifest.json`, `readable_index.md`, `all_scripts.md`.

## Install

```bash
pip install -e .
```

## Quick Start

```bash
film-agent new-run --config configs/project.example.yaml
film-agent gate0 --run-id <RUN_ID>
```

Submit artifacts (JSON):

```bash
film-agent submit --run-id <RUN_ID> --agent showrunner --file path/to/beat_bible.json
film-agent submit --run-id <RUN_ID> --agent direction --file path/to/user_direction_pack.json
film-agent submit --run-id <RUN_ID> --agent dance_mapping --file path/to/dance_mapping_spec.json
film-agent submit --run-id <RUN_ID> --agent cinematography --file path/to/shot_design_sheets.json
film-agent submit --run-id <RUN_ID> --agent audio --file path/to/audio_plan.json
```

Validate gates:

```bash
film-agent validate --run-id <RUN_ID> --gate 1
film-agent validate --run-id <RUN_ID> --gate 2
film-agent submit --run-id <RUN_ID> --agent dryrun_metrics --file path/to/dryrun_metrics.json
film-agent validate --run-id <RUN_ID> --gate 3
film-agent submit --run-id <RUN_ID> --agent final_metrics --file path/to/final_metrics.json
film-agent validate --run-id <RUN_ID> --gate 4
```

Export iteration package:

```bash
film-agent package-iteration --run-id <RUN_ID> --iter 1
```

Generate final report:

```bash
film-agent final-report --run-id <RUN_ID>
```

## Core JSON Contracts

- `showrunner` -> `BeatBible`
- `direction` -> `UserDirectionPack`
- `dance_mapping` -> `DanceMappingSpec` (must contain matching `direction_pack_id`)
- `cinematography` -> `CinematographyPackage`
- `audio` -> `AudioPlan`
- `dryrun_metrics` -> `DryRunMetrics`
- `final_metrics` -> `FinalMetrics`

## Provider Stack

- Audio: ElevenLabs
- Images: OpenAI Images + NanoBanana
- Video: OpenAI primary, Hugsfield fallback (triggered on Gate3 blocking failure)

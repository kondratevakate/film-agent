# film-agent

Multi-role film pipeline with strict JSON artifacts, gate validation, and SDK-driven prompt iteration.

## Core Flow

- State machine:
  `INIT -> GATE0 -> COLLECT_SHOWRUNNER -> COLLECT_DIRECTION -> COLLECT_DANCE_MAPPING -> COLLECT_CINEMATOGRAPHY -> COLLECT_AUDIO -> LOCK_PREPROD -> GATE1 -> GATE2 -> DRYRUN -> GATE3 -> FINAL_RENDER -> GATE4`
- Roles are explicit role packs under `roles/`.
- Artifacts are strict JSON and validated on submit.

## Install

```bash
pip install -e .
```

Optional legacy provider runtime (deprecated scripts only):

```bash
pip install -e .[providers]
```

## Main Commands

```bash
film-agent new-run --config configs/project.example.yaml
film-agent gate0 --run-id <RUN_ID>
film-agent submit --run-id <RUN_ID> --agent showrunner --file beat_bible.json
film-agent validate --run-id <RUN_ID> --gate 1
film-agent package-iteration --run-id <RUN_ID> --iter 1
film-agent final-report --run-id <RUN_ID>
```

## Auto SDK Iteration

Auto-run role prompts via OpenAI SDK until target stage:

```bash
film-agent auto-run --run-id <RUN_ID> --model gpt-4.1 --until gate2
```

Environment variable for SDK:

```bash
OPENAI_API_KEY=...
# or
OPENAI_SDK=...
```

## Roles (explicit agent profiles)

- `showrunner`
- `direction`
- `dance_mapping`
- `cinematography`
- `audio`
- `qa_judge`

Commands:

```bash
film-agent role list
film-agent role show --role showrunner
```

Role packs live in:

- `roles/showrunner/`
- `roles/direction/`
- `roles/dance_mapping/`
- `roles/cinematography/`
- `roles/audio/`
- `roles/qa_judge/`

Each role pack includes:

- `system.md`
- `task.md`
- `output_contract.md`
- `handoff.md`
- `schema.json`

## Prompt Packets

Build packet for one role:

```bash
film-agent packet build --run-id <RUN_ID> --role showrunner
```

Build all possible packets for current iteration:

```bash
film-agent packet build-all --run-id <RUN_ID>
```

Backward-compatible prompt command:

```bash
film-agent show-prompt --agent showrunner
```

## Export Package (prompt-first default)

`film-agent package-iteration` now exports:

- `artifacts/`
- `prompt_packets/`
- `submission_templates/`
- `scripts/` (copy-ready sheets: plan, image prompts, sora prompts, elevenlabs lines)
- `legacy_optional_scripts/` (deprecated API-run scripts area)
- `RUNBOOK.md`
- `readable_index.md`
- `hash_manifest.json`

## Canonical JSON Artifacts

- `showrunner` -> `BeatBible`
- `direction` -> `UserDirectionPack`
- `dance_mapping` -> `DanceMappingSpec`
- `cinematography` -> `CinematographyPackage`
- `audio` -> `AudioPlan`
- `dryrun_metrics` -> `DryRunMetrics`
- `final_metrics` -> `FinalMetrics`

## Prompt Stack

- Main overlay for principal scriptwriter: `prompts/main_agent_overlay.md`
- Showrunner addendum: `prompts/showrunner.md`
- Other role prompts: `prompts/*.md`

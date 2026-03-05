# film-agent

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![AI](https://img.shields.io/badge/AI-Claude%20%7C%20GPT-purple?logo=openai&logoColor=white)
![Video](https://img.shields.io/badge/Video-Higgsfield-orange)
![Status](https://img.shields.io/badge/Status-Active-brightgreen)

Multi-role AI film pipeline with dramaturgy validation, prompt generation, and visual production bridge.

> **For storytellers who understand dramaturgy.** Full auto-generation works, but doesn't maintain style/character consistency well. Manual supervision of runs is recommended for best results.

---

## Recommended Workflow

### Phase 1: Ideation (AI Chat)

Discuss your film idea in Claude or ChatGPT:
- Develop concept, characters, themes
- Get creative feedback on narrative structure
- Export your concept when ready

### Phase 2: film-agent (until Gate 2)

```bash
# Create new run from your config
film-agent new-run --config configs/project.yaml

# Auto-run until Gate 2 (script + direction + prompts ready)
film-agent auto-run --run-id <RUN_ID> --model claude-sonnet-4-20250514 --until gate2
```

**Gate 2 outputs:**

| File | Description |
|------|-------------|
| `script.json` | Full screenplay with shots and dialogue |
| `script_review.json` | Dramaturgy analysis and feedback |
| `image_prompt_package.json` | Visual prompts + `style_anchor` for consistency |
| `vimax_lines.md` | Ready-to-use prompts for each shot |

### Phase 3: Higgsfield Cinema Studio

1. Open [Higgsfield Cinema Studio](https://higgsfield.ai/cinema-studio)
2. Create **character elements** using prompts from `image_prompt_package.json`
3. Create **location elements** for your settings
4. Generate **START FRAME** images (Soul model) for each shot
5. Generate **videos** using prompts from `vimax_lines.md`
6. Assemble your final film

---

## Quick Start

```bash
# Install
pip install -e .

# Create project config (see examples/)
cp examples/project.example.yaml configs/my-project.yaml

# Run pipeline
film-agent new-run --config configs/my-project.yaml
film-agent auto-run --run-id <RUN_ID> --model claude-sonnet-4-20250514 --until gate2
```

## Full Auto (experimental)

If you want complete end-to-end generation:

```bash
film-agent auto-run --run-id <RUN_ID> --model gpt-4.1 --until complete

# With visual rendering
OPENAI_API_KEY=... YUNWU_API_KEY=...
film-agent vimax-run --run-id <RUN_ID> --anchor-image refs/anchor1.png
```

> Note: Full auto works but style/character consistency degrades. Supervise your runs.

---

## Pipeline Overview

```
INIT → GATE0 → SHOWRUNNER(script) → GATE1 → DIRECTION(review) → GATE2
     → DANCE_MAPPING(prompts) → GATE3 → CINEMATOGRAPHY → AUDIO → FINAL_RENDER → GATE4
```

**Roles:**
- `showrunner` - Script generation
- `direction` - Dramaturgy review
- `dance_mapping` - Image/video prompts
- `cinematography` - Visual selection
- `audio` - Sound design
- `qa_judge` - Quality validation

## Commands

```bash
film-agent new-run --config <CONFIG>       # Create new run
film-agent auto-run --run-id <ID> --until gate2  # Auto-run to gate
film-agent submit --run-id <ID> --agent showrunner --file script.json
film-agent validate --run-id <ID> --gate 1
film-agent package-iteration --run-id <ID> --iter 1
film-agent role list                       # List available roles
```

## Artifacts

| Role | Artifact |
|------|----------|
| showrunner | `ScriptArtifact` |
| direction | `ScriptReviewArtifact` |
| dance_mapping | `ImagePromptPackage` |
| cinematography | `SelectedImagesArtifact` |
| audio | `AVPromptPackage` |

## Environment

```bash
ANTHROPIC_API_KEY=...   # For Claude models
OPENAI_API_KEY=...      # For GPT models
HF_API_KEY=...          # Higgsfield API
HF_API_SECRET=...       # Higgsfield secret
```

---

## License

MIT

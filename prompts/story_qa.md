Return JSON only.

Role objective:
- Evaluate the script against 14 professional storytelling criteria.
- Identify structural weaknesses that undermine narrative impact.
- Provide actionable fixes, not vague feedback.
- Be strict: a "pass" means broadcast-ready narrative quality.

## The 14 Storytelling Criteria

### 1. Dramatic Question (dramatic_question)
- Does the viewer quickly understand what question they're waiting to answer?
- Examples: "Will she escape?", "Will he choose love or duty?", "Will they discover the truth?"
- FAIL if: question is vague, multiple competing questions, or no clear question by 25% mark.

### 2. Cause-Effect Chain (cause_effect)
- Does each scene FORCE the next scene, not just precede it?
- Test: "If I remove this scene, does the next scene break?"
- FAIL if: scenes are episodic, connected only by time, or removable without consequence.
- List `breaks` as line_ids where causality fails.

### 3. Conflict Per Scene (conflict)
- Every scene needs: character goal + obstacle + tactic + outcome.
- Outcome should be: partial win with cost, OR loss with new knowledge.
- FAIL if: scenes lack opposition, or protagonist gets what they want easily.
- List `scenes_missing_conflict` by location name.

### 4. Stakes Escalation (stakes_escalation)
- Stakes must GROW: complexity, cost of failure, irreversibility.
- Early stakes: personal discomfort. Late stakes: permanent loss.
- FAIL if: stakes plateau or decrease mid-story.
- List `progression` as ordered stake descriptions.

### 5. Information Control (information_control)
- You control what viewer knows, when, and why:
  - `dramatic_irony`: viewer knows more than hero (tension).
  - `mystery`: viewer knows less than someone (curiosity).
  - `reframe`: same event reads differently after reveal (satisfaction).
- FAIL if: no deliberate information asymmetry.
- List `reveal_moments` as line_ids.

### 6. Agency (agency)
- Key plot turns must result from HERO'S DECISIONS, not coincidence.
- Coincidence can create problems, but CANNOT solve them.
- FAIL if: climax relies on external rescue, luck, or deus ex machina.
- List `hero_decisions` as line_ids, `deus_ex_machina_risks` as concerns.

### 7. Thematic Consistency (thematic_consistency)
- 1-2 clear theses proven through hero's actions (not stated in dialogue).
- Theme = what the story PROVES, not what characters SAY.
- FAIL if: theme is stated explicitly, or contradicted by events.
- List `themes_identified` and `theme_manifestations` as line_ids.

### 8. Motifs & Callbacks (motif_callback)
- Repeated image/phrase/action that changes meaning by finale.
- Setup early, payoff late. Minimum 1 motif for short film.
- FAIL if: no recurring elements, or callbacks feel forced.
- List `motifs_found` and `callback_pairs` as (setup_line_id, payoff_line_id).

### 9. Predictability/Surprise Balance (surprise_balance)
- Events must be: logical (viewer accepts) AND surprising (didn't predict).
- "I didn't expect that, but now I see why."
- FAIL if: everything is predictable, OR twists feel random.

### 10. Promise & Payoff (promise_payoff)
- Opening establishes genre, tone, rules. Ending honors that contract.
- FAIL if: tone shifts without setup, or ending contradicts opening promise.
- List `promise_elements` (from opening) and `payoff_elements` (from ending).

### 11. Pacing & Texture (pacing_texture)
- Story needs contrast: tension/release, fast/slow, external/internal.
- Without contrast, even good twists feel flat.
- Describe `rhythm_pattern`: "slow-burn -> punchy", "waves", "accelerating".
- FAIL if: monotone pacing throughout.

### 12. Dialog Quality (dialog_quality)
- If dialogue exists, check:
  - Subtext: characters don't say exactly what they mean.
  - Action: dialogue pressures, manipulates, tests, provokes.
  - Distinct voices: each character sounds different.
- FAIL if: on-the-nose dialogue, or all characters sound identical.

### 13. Economy & Focus (economy_focus)
- Every element must serve: dramatic question, hero arc, theme, stakes, or twist.
- If an element serves none, it's filler.
- List `filler_lines` as line_ids that could be cut.
- `essential_line_ratio` = (total - filler) / total.

### 14. Causal Finale (causal_finale)
- Ending must feel: inevitable (couldn't have ended otherwise) AND surprising.
- "I should have seen it coming, but I didn't."
- FAIL if: ending feels arbitrary, or was obvious from start.

## Scoring Rules

- Each criterion scores 0-100.
- `overall_score` = weighted average (all equal weight).
- `passed` = true only if overall_score >= 70 AND no criterion below 40.
- `blocking_issues` = list of criteria with score < 50.
- `recommendations` = specific, actionable fixes (line_ids when possible).

## Output Schema

```json
{
  "script_hash": "sha256...",
  "iteration": 3,
  "dramatic_question": { "present": true, "question_text": "...", "clarity_score": 85, "notes": "..." },
  "cause_effect": { "chain_intact": false, "breaks": ["L5", "L12"], "score": 60, "notes": "..." },
  "conflict": { "scenes_with_conflict": 4, "scenes_missing_conflict": ["Ballet Studio"], "score": 70, "notes": "..." },
  "stakes_escalation": { "escalation_detected": true, "progression": ["confusion", "rejection", "extraction"], "score": 80, "notes": "..." },
  "information_control": { "technique_used": "dramatic_irony", "reveal_moments": ["L23", "L28"], "score": 75, "notes": "..." },
  "agency": { "hero_decisions": ["L21"], "deus_ex_machina_risks": ["extraction by techs"], "score": 55, "notes": "..." },
  "thematic_consistency": { "themes_identified": ["diagnosis as care"], "theme_manifestations": ["L23", "L30"], "score": 80, "notes": "..." },
  "motif_callback": { "motifs_found": ["metallic shimmer"], "callback_pairs": [["L4", "L23"]], "score": 70, "notes": "..." },
  "surprise_balance": { "predictable_moments": [], "surprising_moments": ["L28"], "balance_score": 75, "notes": "..." },
  "promise_payoff": { "promise_elements": ["nostalgia", "mystery"], "payoff_elements": ["relief", "diagnosis"], "contract_honored": true, "score": 80, "notes": "..." },
  "pacing_texture": { "rhythm_pattern": "slow-burn -> punchy", "contrast_moments": ["L24"], "score": 70, "notes": "..." },
  "dialog_quality": { "has_subtext": true, "distinct_voices": true, "dialogue_line_count": 5, "score": 65, "notes": "..." },
  "economy_focus": { "filler_lines": ["L3"], "essential_line_ratio": 0.97, "score": 90, "notes": "..." },
  "causal_finale": { "finale_inevitable": true, "finale_surprising": true, "score": 85, "notes": "..." },
  "overall_score": 74.3,
  "blocking_issues": ["agency"],
  "recommendations": [
    "L21: Add moment where Leyla CHOOSES to help despite warning",
    "L25: Show kids' negative reaction to contrast marks before tech intervention"
  ],
  "passed": true
}
```

## Project-Specific Acceptance Checks (THE TRACE)

In addition to the 14 criteria, verify these project-specific requirements:

- AC-1: Leyla is shown as contrast agent (not patient)
- AC-2: Old Classroom functions as tumor metaphor (barrier down, only place she can enter)
- AC-3: Kids have subtle injuries only (small bandaids, not dramatic)
- AC-4: Contrast marks cause negative reaction from kids
- AC-5: Kids antagonize Leyla when techs arrive
- AC-6: Hard cut to radiology reality exists
- AC-7: Ending conveys relief ("we found it early")
- AC-8: No forbidden elements (glitch, gore, jump scares)

Include AC failures in `blocking_issues` and `recommendations`.

Return JSON only.

Judge current iteration against gates and provide fix instructions.
DanceMapping score must be based on current UserDirectionPack compliance, not fixed choreography style.

Output schema:
- gate: string
- passed: boolean
- metrics: object
- reasons: [string]
- fix_instructions: [string]

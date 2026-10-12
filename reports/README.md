# reports/

Outputs written by the agents during the demo, for example:

| File | Written by |
|---|---|
| `STORY-123-requirements-analysis.md` | QE Orchestrator (Requirements Analyst's report) |
| `STORY-123-approved-criteria.md` | QE Orchestrator, after the human approval gate |
| `STORY-123-traceability.md` | Test Runner |
| `STORY-123-ado-test-cases.md` | Test Runner (preview when no Azure DevOps MCP tools are available) |
| `RCA-*.md` | Defect Analyst (when asked to save the analysis) |
| `MIGRATION-*.md` | Framework Migrator |

Generated reports are untracked so `git status` shows what the agents produced;
`python scripts/reset_demo.py` removes them.

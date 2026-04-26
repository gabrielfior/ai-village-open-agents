# AI agent instructions

Orchestration, workflows, triggers, and the full skill index for 0G development live in:

**`.0g-skills/AGENTS.md`**

Supporting references (also under `.0g-skills/`):

- `patterns/NETWORK_CONFIG.md` — RPC, chain IDs, env template
- `patterns/STORAGE.md`, `COMPUTE.md`, `CHAIN.md`, `SECURITY.md`, `TESTING.md`

## Skill discovery (OpenCode / Claude-compatible paths)

- **OpenCode:** `.opencode/skills/*/SKILL.md` (YAML frontmatter + full upstream body)
- **Claude-compatible:** `.claude/skills/*` → symlinks to `.opencode/skills/*`
- **Agents path:** `.agents/skills/*` → same symlinks

Raw upstream layout (no frontmatter): `.0g-skills/skills/**/SKILL.md`

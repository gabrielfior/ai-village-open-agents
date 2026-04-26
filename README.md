# ai-village-open-agents

Hackathon workspace with **[0G Agent Skills](https://github.com/0gfoundation/0g-agent-skills)** vendored for local use.

## Layout

| Path | Purpose |
|------|---------|
| `.0g-skills/` | Upstream skills, `AGENTS.md`, `patterns/`, `examples/`, IDE setup guides |
| `.opencode/skills/` | OpenCode-ready `SKILL.md` files (YAML frontmatter + full content) |
| `.claude/skills/`, `.agents/skills/` | Symlinks into `.opencode/skills/` for compatible runners |
| `AGENTS.md` | Entry point; points at `.0g-skills/AGENTS.md` |

See `.0g-skills/README.md` for SDK install, env vars, and the skills catalog.

## Updating 0G skills

Replace `.0g-skills` from [0gfoundation/0g-agent-skills](https://github.com/0gfoundation/0g-agent-skills), note the commit in `.0g-skills/VENDOR.md`, and regenerate `.opencode/skills` (prepend frontmatter to each `skills/**/SKILL.md`).

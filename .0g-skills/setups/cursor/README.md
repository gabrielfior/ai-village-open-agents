# Cursor Setup

Use 0G Agent Skills with [Cursor](https://cursor.sh) for AI-assisted 0G development.

## Installation

### Step 1: Add Skills to Your Project

```bash
# Clone skills into your project
git clone https://github.com/0gfoundation/agent-skills-0g .0g-skills
```

### Step 2: Create .cursorrules

Create a `.cursorrules` file in your project root:

```markdown
# 0G Development Rules

You are assisting a developer building on the 0G decentralized AI operating system.

## Reference Files

For 0G development, always reference these files:

- `.0g-skills/AGENTS.md` — Orchestration rules and workflow sequences
- `.0g-skills/patterns/NETWORK_CONFIG.md` — Endpoints, chain IDs, SDK versions
- `.0g-skills/patterns/STORAGE.md` — Storage architecture reference
- `.0g-skills/patterns/COMPUTE.md` — Compute architecture reference
- `.0g-skills/patterns/CHAIN.md` — Chain/EVM patterns reference

## Critical Rules

1. ALWAYS call processResponse() after every compute inference
2. processResponse() param order: (providerAddress, chatID, usageData)
3. ALWAYS extract ChatID from ZG-Res-Key header first, body as fallback
4. ALWAYS use evmVersion: "cancun" for 0G Chain contracts
5. ALWAYS use ethers v6 (NOT v5)
6. ALWAYS close ZgFile handles with file.close() in finally blocks
7. NEVER hardcode private keys — use .env

## Skills

When the user asks about:

- Storage: Reference `.0g-skills/skills/storage/*/SKILL.md`
- Compute/AI: Reference `.0g-skills/skills/compute/*/SKILL.md`
- Smart contracts: Reference `.0g-skills/skills/chain/*/SKILL.md`
- Cross-layer apps: Reference `.0g-skills/skills/cross-layer/*/SKILL.md`
```

### Step 3: Add to Cursor Context

In Cursor settings, add the `.0g-skills` directory to your project context so the AI can reference
all skill files.

## Verification

Open your project in Cursor and try:

```
Help me upload a file to 0G Storage
```

The AI should generate code following the patterns in the storage upload skill.

## Tips

- The `.cursorrules` file is automatically loaded by Cursor
- Reference specific skill files in your prompts for more precise help
- Use `@file` to reference specific skill files inline

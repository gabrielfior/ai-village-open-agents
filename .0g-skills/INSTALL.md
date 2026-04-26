# Installation Guide

Add 0G Agent Skills to your AI coding assistant in under 2 minutes.

## Quick Install

### Claude Code

```bash
# Clone into your project
git clone https://github.com/0gfoundation/agent-skills-0g .0g-skills

# Or copy CLAUDE.md to your project root
cp .0g-skills/CLAUDE.md ./CLAUDE.md
```

Claude Code auto-loads `CLAUDE.md` from your project root. Done.

See [setups/claude-code/README.md](setups/claude-code/README.md) for advanced options.

### Cursor

```bash
git clone https://github.com/0gfoundation/agent-skills-0g .0g-skills
```

Then create a `.cursorrules` file — see [setups/cursor/README.md](setups/cursor/README.md).

### GitHub Copilot

```bash
git clone https://github.com/0gfoundation/agent-skills-0g .0g-skills
```

Then create `.github/copilot-instructions.md` — see
[setups/copilot/README.md](setups/copilot/README.md).

## Project Setup

After installing skills, set up your 0G development environment:

### 1. Install SDKs

```bash
# Storage
npm install @0glabs/0g-ts-sdk ethers dotenv

# Compute
npm install @0glabs/0g-serving-broker ethers dotenv

# Both
npm install @0glabs/0g-ts-sdk @0glabs/0g-serving-broker ethers dotenv
```

### 2. Create .env

```bash
# .env — NEVER commit this file
PRIVATE_KEY=your_private_key_here
RPC_URL=https://evmrpc-testnet.0g.ai
STORAGE_INDEXER=https://indexer-storage-testnet-turbo.0g.ai
PROVIDER_ADDRESS=your_compute_provider_address
```

### 3. Add .env to .gitignore

```bash
echo ".env" >> .gitignore
```

### 4. Verify

Ask your AI assistant:

> "Help me upload a file to 0G Storage"

It should generate correct code using `@0glabs/0g-ts-sdk` with proper Merkle tree handling and file
cleanup.

## Updating

```bash
cd .0g-skills && git pull
```

## Uninstalling

```bash
rm -rf .0g-skills
# Remove any references from .cursorrules or CLAUDE.md
```

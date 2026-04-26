# 0G Agent Skills — Orchestration Guide

Master orchestration file for AI coding assistants. Defines activation triggers, workflow sequences,
critical rules, and common mistakes for all 14 skills across 4 categories.

## Skill Index

### Storage Skills

| Skill               | Path                                          | Triggers                                                              |
| ------------------- | --------------------------------------------- | --------------------------------------------------------------------- |
| Upload File         | `skills/storage/upload-file/SKILL.md`         | "upload file", "store on 0G", "ZgFile", "save to storage"             |
| Download File       | `skills/storage/download-file/SKILL.md`       | "download file", "retrieve from 0G", "get file", "fetch from storage" |
| Merkle Verification | `skills/storage/merkle-verification/SKILL.md` | "verify file", "merkle proof", "data integrity", "root hash"          |

### Compute Skills

| Skill              | Path                                         | Triggers                                                         |
| ------------------ | -------------------------------------------- | ---------------------------------------------------------------- |
| Provider Discovery | `skills/compute/provider-discovery/SKILL.md` | "list providers", "find provider", "verify provider", "TEE"      |
| Account Management | `skills/compute/account-management/SKILL.md` | "deposit", "transfer funds", "refund", "check balance"           |
| Streaming Chat     | `skills/compute/streaming-chat/SKILL.md`     | "chatbot", "inference", "LLM", "DeepSeek", "AI chat"             |
| Text to Image      | `skills/compute/text-to-image/SKILL.md`      | "generate image", "text-to-image", "Flux", "create image"        |
| Speech to Text     | `skills/compute/speech-to-text/SKILL.md`     | "transcribe", "speech-to-text", "Whisper", "audio transcription" |
| Fine-Tuning        | `skills/compute/fine-tuning/SKILL.md`        | "fine-tune", "train model", "custom model", "model training"     |

### Chain Skills

| Skill             | Path                                      | Triggers                                                       |
| ----------------- | ----------------------------------------- | -------------------------------------------------------------- |
| Scaffold Project  | `skills/chain/scaffold-project/SKILL.md`  | "new project", "scaffold", "initialize", "create 0G app"       |
| Deploy Contract   | `skills/chain/deploy-contract/SKILL.md`   | "deploy contract", "Solidity", "0G Chain"                      |
| Interact Contract | `skills/chain/interact-contract/SKILL.md` | "call contract", "read contract", "interact", "write contract" |

### Cross-Layer Skills

| Skill             | Path                                               | Triggers                                               |
| ----------------- | -------------------------------------------------- | ------------------------------------------------------ |
| Storage + Chain   | `skills/cross-layer/storage-plus-chain/SKILL.md`   | "on-chain reference", "NFT metadata on 0G", "registry" |
| Compute + Storage | `skills/cross-layer/compute-plus-storage/SKILL.md` | "AI with storage", "generate and store", "AI pipeline" |

---

## Workflow Sequences

### 1. Create New Project

**Trigger**: "new project", "scaffold", "initialize", "setup", "create app"

```
scaffold-project
```

Load `skills/chain/scaffold-project/SKILL.md` and follow project type selection.

### 2. Upload / Store Data

**Trigger**: "upload", "store", "save to 0G"

```
upload-file → AUTO: merkle-verification
```

1. Use `upload-file` for all data storage
2. After successful upload, automatically verify using `merkle-verification`
3. Return root hash to user

### 3. Download / Retrieve Data

**Trigger**: "download", "retrieve", "get file", "fetch"

```
download-file → AUTO: merkle-verification
```

1. Use `download-file` to retrieve data by root hash
2. Use verified download (third param = `true`)
3. Optionally verify with `merkle-verification`

### 4. Run AI Inference

**Trigger**: "chatbot", "inference", "generate image", "transcribe"

```
AUTO: provider-discovery → AUTO: account-management → streaming-chat | text-to-image | speech-to-text
```

1. **Auto-activate** `provider-discovery` — find appropriate provider for service type
2. **Auto-activate** `account-management` — verify balance, fund if needed
3. Run the specific inference skill based on request:
   - Chat/LLM → `streaming-chat`
   - Image → `text-to-image`
   - Audio → `speech-to-text`

### 5. Fine-Tune Model

**Trigger**: "fine-tune", "train model", "custom model"

```
AUTO: provider-discovery → AUTO: account-management → fine-tuning
```

1. **Auto-activate** `provider-discovery` — find fine-tuning providers
2. **Auto-activate** `account-management` — fund fine-tuning sub-account
3. Run `fine-tuning` workflow (testnet only)

### 6. Deploy Contract

**Trigger**: "deploy contract", "Solidity", "smart contract"

```
deploy-contract
```

Load `skills/chain/deploy-contract/SKILL.md`. Ensure `evmVersion: "cancun"`.

### 7. Cross-Layer Application

**Trigger**: "on-chain reference", "AI with storage", "NFT metadata", "full pipeline"

```
storage-plus-chain | compute-plus-storage
```

1. Determine if pattern is storage+chain or compute+storage
2. Load appropriate cross-layer skill
3. Follow multi-step workflow in skill

### 8. Manage Funds

**Trigger**: "deposit", "transfer", "refund", "balance", "withdraw"

```
account-management
```

Load `skills/compute/account-management/SKILL.md`.

---

## Critical ALWAYS Rules

These rules must be followed in EVERY interaction. Violations cause bugs, data loss, or financial
errors.

### Compute — processResponse()

```
ALWAYS call processResponse() after EVERY inference request.
ALWAYS use correct parameter order: processResponse(providerAddress, chatID, usageData)
ALWAYS extract ChatID from ZG-Res-Key header FIRST, body (data.id) as fallback (chatbot only).
```

Param order reminder:

```typescript
await broker.inference.processResponse(
  providerAddress, // 1st: provider address
  chatID, // 2nd: response identifier
  usageData, // 3rd: JSON-stringified usage (optional for images)
);
```

### Compute — Provider Setup

```
ALWAYS acknowledge provider before first use (acknowledgeProviderSigner).
ALWAYS check balance before making inference requests.
ALWAYS verify TEE status for security-sensitive workloads.
```

### Storage — File Handles

```
ALWAYS generate Merkle tree BEFORE uploading.
ALWAYS close file handles after operations (file.close()).
ALWAYS use try/finally to ensure handles are closed.
ALWAYS store root hashes — they are the ONLY way to retrieve files.
```

### Chain — Compilation

```
ALWAYS use evmVersion: "cancun" for ALL 0G Chain contract compilation.
ALWAYS use ethers v6 syntax (NOT v5).
ALWAYS wait for transaction confirmation (tx.wait()).
```

### Security

```
ALWAYS load private keys from .env files.
ALWAYS add .env to .gitignore.
ALWAYS use verified downloads in production (third param = true).
```

---

## Critical NEVER Rules

### Compute

```
NEVER skip processResponse() — causes fee settlement failure and potential fund lock.
NEVER reverse processResponse() parameter order.
NEVER skip provider acknowledgment — requests will fail.
NEVER use ethers v5 syntax (ethers.providers, ethers.utils, BigNumber).
```

### Storage

```
NEVER forget to close ZgFile handles — causes memory leaks.
NEVER lose root hashes — data becomes irretrievable.
NEVER upload without generating Merkle tree first.
```

### Chain

```
NEVER use evmVersion other than "cancun" for 0G Chain — causes invalid opcode errors.
NEVER use ethers v5 patterns — they won't work with v6.
```

### Security

```
NEVER hardcode private keys in source code.
NEVER commit .env files to version control.
NEVER use unverified downloads for production data.
```

---

## Common Mistakes & Fixes

### #1: Missing processResponse()

**Symptom**: Funds locked, fee settlement fails

```typescript
// WRONG
const data = await response.json();
return data.choices[0].message.content;

// RIGHT
const data = await response.json();
let chatID = response.headers.get('ZG-Res-Key') || response.headers.get('zg-res-key');
if (!chatID) chatID = data.id;
await broker.inference.processResponse(providerAddress, chatID, JSON.stringify(data.usage));
return data.choices[0].message.content;
```

### #2: Wrong processResponse() Parameter Order

**Symptom**: Fee verification fails silently

```typescript
// WRONG
await broker.inference.processResponse(chatID, providerAddress, usage);

// RIGHT — providerAddress FIRST
await broker.inference.processResponse(providerAddress, chatID, usage);
```

### #3: ChatID from Wrong Source

**Symptom**: Verification mismatch

```typescript
// WRONG — using body without checking header
const chatID = data.id;

// RIGHT — header first, body fallback (chatbot only)
let chatID = response.headers.get('ZG-Res-Key') || response.headers.get('zg-res-key');
if (!chatID) chatID = data.id; // Fallback for chatbot only
```

### #4: Wrong evmVersion

**Symptom**: `invalid opcode` error on deployment

```typescript
// WRONG
solidity: { version: "0.8.24" }

// RIGHT
solidity: {
  version: "0.8.24",
  settings: { evmVersion: "cancun" }
}
```

### #5: ethers v5 Syntax

**Symptom**: Import errors, undefined methods

```typescript
// WRONG (v5)
const provider = new ethers.providers.JsonRpcProvider(url);
const amount = ethers.utils.parseEther('1');

// RIGHT (v6)
const provider = new ethers.JsonRpcProvider(url);
const amount = ethers.parseEther('1');
```

### #6: Unclosed File Handles

**Symptom**: Memory leaks, file locks

```typescript
// WRONG
const file = await ZgFile.fromFilePath(path);
const [tree] = await file.merkleTree();
await indexer.upload(file, process.env.RPC_URL!, wallet);
// file.close() never called!

// RIGHT
const file = await ZgFile.fromFilePath(path);
try {
  const [tree, err] = await file.merkleTree();
  if (err) throw err;
  const [tx, uploadErr] = await indexer.upload(file, process.env.RPC_URL!, wallet);
  if (uploadErr) throw new Error(`Upload failed: ${uploadErr.message}`);
} finally {
  await file.close();
}
```

### #7: Hardcoded Private Key

**Symptom**: Security vulnerability

```typescript
// WRONG
const wallet = new ethers.Wallet('0xabc123...', provider);

// RIGHT
const wallet = new ethers.Wallet(process.env.PRIVATE_KEY!, provider);
```

---

## Pattern Documents

For deep architectural context, reference these pattern documents:

| Pattern        | Path                         | When to Reference                   |
| -------------- | ---------------------------- | ----------------------------------- |
| Network Config | `patterns/NETWORK_CONFIG.md` | Setting up any 0G connection        |
| Storage        | `patterns/STORAGE.md`        | Any storage operation               |
| Compute        | `patterns/COMPUTE.md`        | Any compute/inference operation     |
| Chain          | `patterns/CHAIN.md`          | Any smart contract operation        |
| Security       | `patterns/SECURITY.md`       | Key management, TEE, data integrity |
| Testing        | `patterns/TESTING.md`        | Writing tests for 0G apps           |

---

## SDK Quick Reference

| SDK     | Import                                                                     | Version |
| ------- | -------------------------------------------------------------------------- | ------- |
| Storage | `import { ZgFile, Indexer } from '@0glabs/0g-ts-sdk'`                      | ^0.3.3  |
| Compute | `import { createZGComputeNetworkBroker } from '@0glabs/0g-serving-broker'` | ^0.6.5  |
| Chain   | `import { ethers } from 'ethers'`                                          | ^6.13.0 |

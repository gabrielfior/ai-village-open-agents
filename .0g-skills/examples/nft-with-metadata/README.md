# 0G NFT with Metadata

Deploy a registry contract on 0G Chain, upload metadata to 0G Storage, and register root hashes on-chain.

## Architecture

```
┌──────────────────────┐     ┌──────────────────────┐
│    0G Chain           │     │    0G Storage         │
│                       │     │                       │
│  Registry Contract    │────>│  Files (root hashes)  │
│  - rootHash (bytes32) │     │  - Data chunks        │
│  - uploader (address) │     │  - Merkle proofs      │
│  - metadata (string)  │     │                       │
└──────────────────────┘     └──────────────────────┘
       On-chain                    Off-chain
     (small refs)               (large data)
```

## Setup

```bash
npm install
cp .env.example .env
# Edit .env with your private key (fund via https://faucet.0g.ai)
```

## Usage

### Step 1: Deploy the registry contract

```bash
npx tsx src/deploy.ts
# Output: Registry deployed at: 0x1234...
# Copy the address to REGISTRY_ADDRESS in .env
```

### Step 2: Upload metadata and register on-chain

```bash
npx tsx src/register.ts <file-path> "description of the file"
# Example: npx tsx src/register.ts ./my-nft-image.png "My first NFT on 0G"
```

### Step 3: Retrieve from chain + storage

```bash
npx tsx src/retrieve.ts <file-id> [output-path]
# Example: npx tsx src/retrieve.ts 0 ./retrieved-file.png
```

### Optional: Compile contract from source

A pre-compiled artifact is included. To recompile from the Solidity source:

```bash
npx tsx src/compile.ts
```

## Key Concepts

- **On-chain references**: Only the root hash (32 bytes) is stored on-chain — the actual data lives on 0G Storage.
- **evmVersion: "cancun"**: Required for all 0G Chain contract compilation.
- **Upload before register**: Always upload to storage first, then register the root hash on-chain.
- **Verified downloads**: Always use verified mode to ensure data integrity on retrieval.

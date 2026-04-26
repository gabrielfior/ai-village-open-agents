# 0G File Vault

Upload, download, and verify files on 0G decentralized storage.

## Setup

```bash
npm install
cp .env.example .env
# Edit .env with your private key (fund via https://faucet.0g.ai)
```

## Usage

### Upload a file

```bash
npx tsx src/upload.ts <file-path>
# Example: npx tsx src/upload.ts README.md
# Output: Root hash: 0x1234abcd...
```

### Download a file

```bash
npx tsx src/download.ts <root-hash> [output-path]
# Example: npx tsx src/download.ts 0x1234abcd... ./downloaded.md
```

### Verify a file

Compute the Merkle root hash of a local file (useful for comparing against a known root hash):

```bash
npx tsx src/verify.ts <file-path>
# Example: npx tsx src/verify.ts ./downloaded.md
# Output: Root hash: 0x1234abcd...
```

## How It Works

1. **Upload** — Files are split into chunks, organized as a Merkle tree, and distributed across 0G Storage nodes. You get back a root hash.
2. **Download** — Provide a root hash to retrieve and verify the file via Merkle proofs.
3. **Verify** — Compute the Merkle root hash of any local file to confirm integrity.

## Key Concepts

- **Root Hash**: The Merkle root of the file — your only way to retrieve it later. Store it safely.
- **Verified Downloads**: Always use verified mode (`true` flag) to ensure data integrity.
- **ZgFile**: Must be closed after use (`file.close()`) to prevent memory leaks.

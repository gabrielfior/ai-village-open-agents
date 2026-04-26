# 0G AI Chatbot

Discover providers, fund your account, and chat with AI on the 0G Compute Network.

## Setup

```bash
npm install
cp .env.example .env
# Edit .env with your private key (fund via https://faucet.0g.ai)
```

## Usage

### Step 1: Discover providers

Find available chatbot providers and save to `providers.json`:

```bash
npx tsx src/discover.ts
```

### Step 2: Fund your account

Deposit funds and set up a provider sub-account:

```bash
npx tsx src/setup.ts <provider-address>
```

### Step 3: Chat

```bash
npx tsx src/chat.ts <provider-address> "What is 0G?"
```

## How It Works

1. **Discover** — Lists all chatbot providers on the 0G network. Filters by service type, shows models and TEE verification status.
2. **Setup** — Deposits funds to your main account, transfers to a provider sub-account, and acknowledges the provider's signer.
3. **Chat** — Sends a prompt to the AI, gets a response, and calls `processResponse()` for fee settlement.

## Key Concepts

- **processResponse()**: Must be called after EVERY inference request. Parameter order: `(providerAddress, chatID, usageData)`.
- **ChatID**: Extracted from the `ZG-Res-Key` response header first, with `data.id` as fallback.
- **Service Tuples**: `listService()` returns tuple arrays — use `s[0]` for address, `s[1]` for type, `s[6]` for model.
- **Dual Accounts**: Main Account (deposit) → Provider Sub-Account (transfer) → Usage (auto-deducted).

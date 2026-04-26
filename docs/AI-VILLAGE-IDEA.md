# AI Village — idea

**Sprint window:** April 27–30, 2026 · **Team size:** 1 · Registration handled manually (no public signup flow required for this doc).

---

## What

**AI Village** is a small simulation where **autonomous software citizens** (each with a role—mayor, butcher, teacher, and so on) live in a shared economy. A **townhall** can announce rules and run **monetary policy** (taxes, gifts, subsidies). Citizens **earn** wages by role, then—after policy is applied—**negotiate bilateral trades** over an encrypted peer-to-peer mesh. A single **orchestrator** keeps one canonical **ledger** of balances and writes **round snapshots** so outcomes are reproducible.

The main observable outcome is **inequality over time**: after **every round**, we record a **Gini coefficient** (and optionally a second reading right after townhall, before trades) so we can plot how **policy** and **voluntary exchange** move the distribution of wealth.

Scope for this build: on the order of **four to six** citizens—not a large population—enough to tell a clear story in a short demo.

---

## Why

It is hard to reason about how a **public policy** will affect people in the real world: feedback loops, incentives, and social interaction are messy. AI Village is a **deliberately simplified testbed**: agents have **money**, **jobs**, and **communication**, so you can run a **counterfactual** (“what if we tax wealth and add a universal grant?”) and see a **quantitative trace** (Gini vs round) instead of only a narrative.

The goal is not to predict real economies; it is to make **policy → behavior → distribution** legible in a way that is **auditable** (stored history) and **decentralized in the right places** (inference, storage, messaging) as described below.

---

## How

### Round loop (policy first, then trades)

Each round, in order:

1. **Load** the current world snapshot (balances, roles, policy parameters).
2. **Earn:** apply deterministic **income rules** by role (wages, simple revenue).
3. **Townhall:** broadcast policy text over the mesh; apply **wealth-based tax**, then **transfers** (e.g. UBI or targeted subsidies) so balances reflect **post-policy** wealth **before** anyone trades.
4. **Citizen phase:** each citizen (with LLM-backed reasoning where useful) **chats** and sends **structured trade offers** peer-to-peer; peers may **accept** or **reject** under a small fixed schema.
5. **Settlement:** the orchestrator matches **OFFER** + **ACCEPT**, checks balances, moves money **once**, and appends to an **event log**.
6. **Snapshot:** write the next state; compute **`gini_end`** from final balances **every round**; optionally store **`gini_after_townhall`** for the same round to separate “policy only” from “policy + market.”

The LLM proposes **language and intents**; the orchestrator **never** trusts free-form text for amounts—only **structured** messages when settling trades.

### Partners — how we use each stack

#### 0G

- **0G Compute:** runs **per-citizen inference**—turning what a citizen “sees” (broadcasts, balances, messages) into **AXL messages** and **trade intents** consistent with the schema.
- **0G Storage:** holds the **source of truth** for the economy: **round snapshots**, **append-only event log**, and the **Gini time series** (and optional integrity roots). Durable history is what makes the run **replayable** and the inequality curve **grounded in data**.
- **0G Chain (minimal / optional):** not required to execute every tax or transfer on-chain for the toy model. If useful, a **thin anchor** (e.g. committing a hash of a policy round or storage root) can tie a run to an EVM deployment without turning the whole simulation into smart-contract accounting.

#### Gensyn (AXL — Agent eXchange Layer)

- **Townhall → citizens:** the mayor (or townhall process) uses **AXL** to reach each citizen by **fan-out** (one encrypted send per known peer identity)—there is no separate “broadcast API”; broadcast is an **application pattern** on top of point-to-point messaging.
- **Citizen ↔ citizen:** **trade offers, acceptances, and social messages** go over **AXL** between **separate nodes** (separate processes or machines), so coordination is **peer-to-peer** rather than mediated by a central chat or message broker.
- **Design rule:** the **ledger** is not duplicated from AXL payloads alone; AXL carries **intent**. Settlement and balances live in **Storage** so there is a single place to audit **who owns what** after each round.

Together, **0G** grounds **intelligence and persistent state**; **AXL** grounds **who said what to whom** in a decentralized mesh—aligned with a village where **information and deals** spread through **peers**, not through a single server.

---

## Summary

| Layer        | Role in AI Village |
|-------------|---------------------|
| Orchestrator | Deterministic earn, tax, transfers, trade settlement, Gini, snapshot writes |
| 0G Compute  | Citizen “thinking” and message/intent generation |
| 0G Storage  | Balances, logs, Gini series, replay |
| 0G Chain    | Optional anchor for a run or policy commitment |
| AXL         | Townhall fan-out + bilateral trade and chat transport across nodes |

This document describes the **product idea** only. Implementation details, repo layout, and sprint checklists live alongside the codebase and planning artifacts.

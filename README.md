# MemoDesk — support-ticket triage with Meko shared memory

**ContextCon hackathon entry (HackerEarth × YugabyteDB / Meko)**
Theme: **Support agents** (with **auditability** as the second thread).
Deadline: 17 Jan 2027. Solo entry, built 19 Nov 2026.

## What it is

A support agent for a fictional store (Northwind Outfitters). A ticket
comes in; the agent first **recalls** shared context from Meko — customer
memories, the support knowledge base, past conversations — then classifies
the ticket and drafts a reply **grounded only in what Meko returned**,
quoting each snippet with its source and score. Resolving a ticket stores
the outcome back into Meko as shared memory, so the *next* ticket from the
same customer recalls it. Every Meko call is logged in an audit trail, and
every triage turn is stored as a replayable Meko conversation.

The demo moment: TKT-1001 (Acme Corp, charged twice) is triaged and
resolved as a $149 store-credit refund — because Meko remembers Acme
prefers store credit, never cash. The follow-up ticket TKT-1002 then gets
a reply that *confirms the earlier refund*, citing the stored resolution.

## Honest labels (read this before judging)

- **The triage agent is rule-based, not an LLM.** Keyword classification
  + template replies composed from retrieved snippets. The UI says so.
  Retrieval is the real product here, and it is real Meko.
- **No cloud account was used.** Meko runs locally (see below); Cloud is
  *not linked*. The same code works against Meko Cloud by pointing
  `MEKO_MCP_URL` at `https://mcp.mekodata.ai/mcp` with a user API key —
  that path was verified from the official docs but NOT exercised here,
  because no account was created for this build.
- **No mocks.** Every number in the UI comes from a live MCP call.
  The test suite asserts the cross-session recall against live Meko.
- Demo data is fictional (Northwind Outfitters, Acme Corp, …).

## How Meko is used (the context layer)

- **Endpoint (local):** `http://127.0.0.1:7777/mcp` — Streamable HTTP MCP,
  served by the local Meko server (`meko start`). Auth is a
  locally-generated token obtained at runtime via `meko token`; it lives
  in process memory only and is never written to disk, logs, or responses
  (the test suite asserts this).
- **MCP tools used:** `datapack_create/search/delete`, `conversation_create`,
  `conversation_add_message`, `conversation_list`, `context_search`,
  `memory_add`, `memory_search`, `memory_get_all`,
  `knowledgebase_upload_file`, `knowledgebase_search`.
  `tools/list` reports 40 tools on local Meko 1.20261116.0.
- **Datapack:** `MemoDesk Support` (created via MCP; re-created on Reset).
- **Seeded shared context:** 3 memories (Acme store-credit preference,
  Citra VIP + $200 escalation, Dana password/email preference) and one
  knowledge-base document, `kb/support-policy.md` (refund policy, duplicate
  charge, 15-minute reset links, carrier delay, address change, escalation).
- **Token savings:** Meko reports them per `context_search` (e.g. 5,400
  tokens saved on the TKT-1001 triage); shown in the API response.

## Run it

Prerequisites: Linux x64 (or Apple Silicon Mac), Python 3.10+, Node not
required. Meko itself is a single binary (Apache-2.0, `yugabyte/meko`).

```bash
# 1. Install Meko (no account, no sign-in; checksum-verified download)
curl -fsSL https://mekodata.ai/install.sh | sh -s -- --non-interactive --no-service
export PATH="$HOME/.local/bin:$PATH"

# 2. Start local Meko (context engine ready in seconds; Cloud NOT linked)
meko start

# 3. Start MemoDesk
python3 memodesk.py
# UI: http://127.0.0.1:8899/
```

Then in the UI: **Reset demo** (fresh datapack + seed) → pick a ticket →
**Run triage** → **Resolve & remember** → triage the follow-up ticket
from the same customer and watch it recall the resolution.

## Files

| File | What it is |
|---|---|
| `memodesk.py` | Backend (stdlib `http.server`, :8899) + rule-based triage engine |
| `meko_client.py` | Minimal MCP client (stdlib only; SSE + plain-JSON responses) |
| `index.html` | Single-page UI (no dependencies) |
| `kb/support-policy.md` | Seeded knowledge-base document |
| `test_memodesk.py` | End-to-end tests vs live Meko — **32/32 pass** |
| `record_demo.py` | Playwright script that records the demo in a real browser |
| `build_video.py` | Assembles `memodesk-demo.mp4` (title + recording + end card + captions) |
| `memodesk-demo.mp4` | **Demo video, 21 s** (limit: < 5 min) |
| `shots/` | Screenshots of each demo step |
| `probe_meko_mcp.py`, `dump_schemas.py` | Verification probes used during development |
| `audit.jsonl` | Append-only log of every MCP call this session (no secrets) |

Runtime state (`state.json`, `tickets.json`, `server.pid`, logs) is
git-ignored; delete it to start clean.

## Verification (19 Nov 2026, this VM)

- `meko --version`: **1.20261116.0** (commit afa0dc6), installed from the
  official installer, checksum verified, no account.
- `meko status`: context engine ready, **Cloud not linked**.
- MCP probe: `initialize` OK, **40 tools**; `memory_add` →
  `memory_search` round-trip returned the exact marker text
  (score 0.781); `context_search` returned it in the memory bucket with
  token-savings accounting.
- `python3 test_memodesk.py`: **32 passed, 0 failed** — including the
  cross-session recall test (TKT-1002 retrieves the TKT-1001 resolution),
  KB retrieval (duplicate-charge + 15-minute rules), priority logic, audit
  completeness, and no-secret-leak checks.
- Demo video: recorded in a real Chromium via Playwright (unedited
  browser footage + title/end cards + step captions); frames spot-checked.
- Note: one leftover probe memory (`ZEBRA-QUOTA-7741…`) sits in the local
  *default* datapack from the early MCP probe; the app uses its own
  datapack and is unaffected.

## What is NOT done (needs Adi / the user)

- **HackerEarth registration** for ContextCon (name/email/company/LinkedIn/GitHub).
- **Public GitHub repo** — the repo is local-only (`git init`, no remote).
  Push it from an account Adi controls.
- **Video upload** — `memodesk-demo.mp4` is local; upload to YouTube (unlisted)
  or the host HackerEarth asks for, and paste that link into the submission.
- **Meko Cloud datapack** (optional): with an Adi-owned free Meko Cloud
  account + API key, the same app can run against
  `https://mcp.mekodata.ai/mcp` instead of localhost — one env var,
  no code change. Not required for the entry: local Meko *is* Meko.

# SUBMISSION.md — ContextCon (HackerEarth × YugabyteDB / Meko)

Copy-paste-ready submission text. Placeholders marked **[TO BE ADDED BY ADI]**
are the two things this build could not do without Adi's accounts:
the public GitHub repo and the hosted demo video.

---

## Title

**MemoDesk — a support agent that remembers every customer, across every session, with Meko**

## Tagline

Support triage where the memory is shared: every ticket recalls what Meko
knows, and every resolution becomes memory for the next ticket.

## Theme

**Support agents** (primary) + **auditability** (every agent action is
logged and every triage turn is stored as a replayable Meko conversation).

## Description

MemoDesk is a support-ticket triage agent for a fictional store. When a
ticket arrives, the agent does not guess — it asks Meko first. One
`context_search` recalls customer memories, the support knowledge base,
and past conversations in parallel; an explicit `knowledgebase_search`
pulls the exact policy section. The agent then classifies the ticket
(billing / technical / shipping / account) and its priority, and drafts a
reply composed only from the retrieved snippets, quoted with their source
and Meko score.

The proof is the follow-up: Acme Corp is charged twice (TKT-1001). Meko
remembers Acme prefers refunds in store credit, never cash, so the refund
is issued as store credit and the outcome is stored as shared memory.
When Acme writes again (TKT-1002), the agent replies by *confirming the
earlier refund* — it recalled the resolution from Meko instead of treating
the customer as a stranger. That is shared memory working across sessions
and across tickets, with no customer data re-entered.

Everything is auditable: the UI shows every MCP call (tool, latency,
result), and each triage turn is saved in Meko as a conversation that any
later agent can replay with `conversation_get`.

Honest note: the triage logic itself is rule-based, not an LLM — the
retrieval is the product, and it is real Meko. The demo data is fictional.

## How Meko is used

- **Context layer:** Meko is the *only* memory/knowledge store. The app
  keeps no customer facts of its own — tickets live in a JSON file, but
  every preference, policy, and past resolution comes from Meko.
- **Endpoint:** local Meko MCP server, Streamable HTTP,
  `http://127.0.0.1:7777/mcp` (Meko 1.20261116.0, installed from the
  official installer, no cloud account; Cloud not linked). The same code
  also targets Meko Cloud (`https://mcp.mekodata.ai/mcp`) via one env var.
- **MCP tools used:** `datapack_create/search/delete`,
  `conversation_create`, `conversation_add_message`, `conversation_list`,
  `context_search`, `memory_add`, `memory_search`, `memory_get_all`,
  `knowledgebase_upload_file`, `knowledgebase_search` (40 tools listed).
- **Datapack:** `MemoDesk Support`, seeded with 3 customer memories and
  one knowledge-base policy document (`support-policy.md`).
- **Token efficiency (Meko's own accounting):** `context_search` reports
  token savings per call — e.g. 5,400 tokens saved on the TKT-1001 triage.
- **Shared memory, proven:** automated test asserts that triaging the
  follow-up ticket retrieves the earlier ticket's resolution memory.

## How to run

```bash
curl -fsSL https://mekodata.ai/install.sh | sh -s -- --non-interactive --no-service
export PATH="$HOME/.local/bin:$PATH"
meko start
python3 memodesk.py
# open http://127.0.0.1:8899/ — Reset demo, triage TKT-1001, resolve it, triage TKT-1002
```

Prerequisites: Linux x64 / Apple Silicon Mac, Python 3.10+. No API keys,
no paid services, no cloud account.

## Verification

- 32/32 automated end-to-end checks pass (`test_memodesk.py`, run against
  live local Meko — no mocks), including cross-session recall, KB
  retrieval, priority logic, audit completeness, and a check that the
  local Meko token never appears in any response or log file.
- Demo video is an unedited Playwright browser recording of the real app
  talking to real Meko (title/end cards + step captions added).

## Links

- **Demo video (< 5 min, 21 s):** https://www.youtube.com/watch?v=xSuy7sWmIK8 (Unlisted)
- **Public GitHub repo:** https://github.com/Gemmahadi/memodesk
- Meko docs: https://docs.mekodata.ai/reference/mcp-server/
- Meko (open source, Apache-2.0): https://github.com/yugabyte/meko

## What remains before submitting (for Adi)

1. Register on HackerEarth for ContextCon (name/email/company/LinkedIn/GitHub) — in progress, waiting on Adi's Google sign-in.
2. ~~Push this folder to a public GitHub repo.~~ DONE — https://github.com/Gemmahadi/memodesk
3. ~~Upload `memodesk-demo.mp4` and paste the link above.~~ DONE — https://www.youtube.com/watch?v=xSuy7sWmIK8 (Unlisted)
4. Submit before **Sun 17 Jan 2027, 11:59 PM PT**.

---
*Built 19 Nov 2026. No accounts were created for this build; no tokens or
passwords are stored anywhere in the repo. Local Meko auth token is
obtained at runtime only and never persisted.*

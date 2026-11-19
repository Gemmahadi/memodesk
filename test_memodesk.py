#!/usr/bin/env python3
"""End-to-end tests for MemoDesk against the live local Meko server.

Run:  python3 test_memodesk.py   (expects memodesk.py on :8899 and `meko start`)
Exits non-zero on any failure. Prints PASS/FAIL per check.
Checks (all against REAL Meko MCP calls — no mocks):
  1. health: 40 MCP tools, cloud not linked
  2. reset+seed: fresh datapack, KB uploaded, 3 seed memories
  3. KB indexed: knowledgebase_search finds the Duplicate-charge section
  4. triage TKT-1001: billing/normal, store-credit memory retrieved, draft cites it
  5. resolve TKT-1001: resolution stored as shared memory
  6. CROSS-SESSION RECALL: triage TKT-1002 (same customer, new ticket)
     retrieves the TKT-1001 resolution memory
  7. triage TKT-1003: technical + "15 minutes" KB rule; TKT-1005: high priority
  8. audit trail lists every MCP tool used; no secret (local Meko token)
     appears in any API response or in audit.jsonl
"""
import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8899"
passed = []
failed = []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail else ""))


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read())


def main():
    # 1. health
    h = req("GET", "/api/health")
    check("health: 40 MCP tools", h.get("meko_tools") == 40, str(h.get("meko_tools")))
    check("health: cloud not linked", h.get("cloud_linked") is False)
    check("health: agent labelled rule-based (no LLM)",
          h.get("agent") == "rule-based triage (no LLM)")

    # 2. reset + seed (fresh datapack)
    r = req("POST", "/api/reset")
    check("reset+seed: datapack created", bool(r.get("datapack_id")))
    check("reset+seed: 3 seed memories", len(r.get("memory_ids", [])) == 3,
          str(r.get("memory_ids")))
    check("reset+seed: KB upload accepted",
          isinstance(r.get("kb_upload"), dict) and
          r["kb_upload"].get("filename") == "support-policy.md")

    # 3. wait for KB indexing, then triage 1001
    deadline = time.time() + 180
    t1 = None
    while time.time() < deadline:
        t1 = req("POST", "/api/triage", {"ticket_id": "TKT-1001"})
        kb = t1["retrieved"]["knowledge_base"]
        if any("Duplicate charge" in x["text"] for x in kb):
            break
        time.sleep(10)
        t1 = None
    check("KB indexed: Duplicate-charge section retrievable", t1 is not None)
    assert t1, "KB never indexed"
    check("triage 1001: category billing", t1["category"] == "billing")
    check("triage 1001: priority normal (no false VIP)",
          t1["priority"] == "normal", t1["priority"])
    mem_texts = [x["text"] for x in t1["retrieved"]["memory"]]
    check("triage 1001: Acme store-credit memory retrieved",
          any("store credit" in t and "Acme" in t for t in mem_texts))
    check("triage 1001: draft cites store credit (grounded reply)",
          "store credit" in t1["draft_reply"])
    check("triage 1001: draft does NOT cite another customer's VIP memory",
          "Citra is a VIP" not in t1["draft_reply"])
    check("triage 1001: Meko token savings reported",
          isinstance(t1.get("token_savings"), dict) and
          t1["token_savings"].get("tokens_saved", 0) > 0,
          str(t1.get("token_savings")))
    check("triage 1001: stored as replayable Meko conversation",
          bool(t1.get("conversation_id")))

    # 5. resolve 1001
    res = req("POST", "/api/resolve",
              {"ticket_id": "TKT-1001",
               "resolution": "Duplicate $149 refunded as store credit."})
    check("resolve 1001: ticket resolved", res["ticket"]["status"] == "resolved")

    # 6. cross-session recall on the follow-up ticket
    t2 = req("POST", "/api/triage", {"ticket_id": "TKT-1002"})
    mem2 = [x["text"] for x in t2["retrieved"]["memory"]]
    check("RECALL: follow-up ticket retrieves TKT-1001 resolution memory",
          any("Resolved TKT-1001" in t and "store credit" in t for t in mem2),
          str(mem2[:2]))
    check("recall: draft mentions the earlier refund",
          "store credit" in t2["draft_reply"].lower())

    # 7. other tickets
    t3 = req("POST", "/api/triage", {"ticket_id": "TKT-1003"})
    check("triage 1003: category technical", t3["category"] == "technical")
    kb3 = " ".join(x["text"] for x in t3["retrieved"]["knowledge_base"])
    check("triage 1003: KB 15-minute reset rule retrieved", "15 minutes" in kb3)
    t5 = req("POST", "/api/triage", {"ticket_id": "TKT-1005"})
    check("triage 1005: category billing", t5["category"] == "billing")
    check("triage 1005: priority high ($320 + VIP)",
          t5["priority"] == "high", t5["priority"])

    # 8. audit + no-secret leak
    a = req("GET", "/api/audit")
    tools = {c["tool"] for c in a["calls"]}
    for needed in ("context_search", "knowledgebase_search",
                   "conversation_create", "conversation_add_message",
                   "memory_add", "datapack_create",
                   "knowledgebase_upload_file"):
        check(f"audit: {needed} logged", needed in tools)
    check("audit: all calls ok", all(c["ok"] for c in a["calls"]),
          str([c for c in a["calls"] if not c["ok"]][:1]))
    token = subprocess.run(["meko", "token"], capture_output=True,
                           text=True, timeout=30).stdout.strip()
    audit_raw = open("audit.jsonl").read()
    check("no secret: local Meko token absent from audit.jsonl",
          token not in audit_raw)
    blob = json.dumps([h, r, t1, t2, t3, t5, a])
    check("no secret: local Meko token absent from API responses",
          token not in blob)
    mems = req("GET", "/api/memories")
    all_mem = [m.get("data", "") for m in mems.get("memories", [])]
    check("memories endpoint: seed + resolution memories present",
          any("Acme Corp" in m for m in all_mem) and
          any("Resolved TKT-1001" in m for m in all_mem),
          f"total={mems.get('total')}")

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()

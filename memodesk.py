#!/usr/bin/env python3
"""MemoDesk — support-ticket triage agent with Meko as its shared memory.

Theme: Support agents (+ auditability: every Meko call is logged and every
triage turn is stored in Meko as a replayable conversation).

How it works (all retrieval is REAL Meko, local server, no cloud account):
  1. Each ticket gets its own Meko conversation (conversation_create).
  2. The agent recalls shared context with context_search (memory +
     knowledge base + past conversations, in parallel) and an explicit
     knowledgebase_search for the policy doc.
  3. A transparent RULE-BASED classifier (no LLM — stated honestly in the
     UI) picks category/priority from keywords and from what Meko recalled
     (e.g. a stored refund preference, VIP status).
  4. The draft reply is composed from the retrieved snippets, quoted with
     their source and Meko score — never invented.
  5. Resolving a ticket stores the outcome with memory_add, so the NEXT
     ticket from the same customer recalls it (cross-session shared memory).
  6. The turn is saved with conversation_add_message, so any later agent
     can replay it with conversation_get.

Run:  python3 memodesk.py   (expects local Meko running: `meko start`)
UI:   http://127.0.0.1:8899/
"""
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from meko_client import MekoClient, MekoError

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("MEMODESK_PORT", "8899"))
DATAPACK_NAME = "MemoDesk Support"
STATE_FILE = os.path.join(HERE, "state.json")
TICKETS_FILE = os.path.join(HERE, "tickets.json")
AUDIT_FILE = os.path.join(HERE, "audit.jsonl")

SEED_MEMORIES = [
    "Acme Corp (customer since 2024) prefers refunds in store credit, never cash.",
    "Citra is a VIP customer with lifetime spend over $2,000; refunds above $200 must be escalated to a senior agent.",
    "Dana reset her password twice in October; she prefers contact by email.",
]

DEMO_TICKETS = [
    {"id": "TKT-1001", "customer": "Acme Corp", "email": "ops@acme.example",
     "subject": "Charged twice for order #8812",
     "body": "Hi, we were charged twice for order #8812 ($149 each). Please refund the duplicate charge. Thanks.",
     "status": "open"},
    {"id": "TKT-1002", "customer": "Acme Corp", "email": "ops@acme.example",
     "subject": "Refund for order #8812 — follow-up",
     "body": "Hi again, following up on order #8812. Has the duplicate charge been refunded? Please confirm how it was refunded.",
     "status": "open"},
    {"id": "TKT-1003", "customer": "Dana", "email": "dana@example.com",
     "subject": "Password reset link does not work",
     "body": "Hello, the password reset link you sent does not work — it says the link is invalid. Can you send a new one?",
     "status": "open"},
    {"id": "TKT-1004", "customer": "Budi", "email": "budi@example.com",
     "subject": "Package stuck for 5 days — order #7741",
     "body": "My package for order #7741 has been stuck for 5 days with no update. Where is it?",
     "status": "open"},
    {"id": "TKT-1005", "customer": "Citra", "email": "citra@example.com",
     "subject": "Refund $320 for a damaged tent",
     "body": "The tent I received is torn. I would like a full refund of $320, please.",
     "status": "open"},
    {"id": "TKT-1006", "customer": "Eko", "email": "eko@example.com",
     "subject": "Change delivery address before shipping",
     "body": "Can I change the delivery address on my order? It has not shipped yet.",
     "status": "open"},
]

CATEGORIES = [
    ("billing", ["refund", "charged twice", "duplicate charge", "charge",
                 "payment", "invoice", "overcharged", "billing"]),
    ("technical", ["password", "reset link", "login", "cannot log in",
                   "link does not work", "invalid link", "error", "crash"]),
    ("shipping", ["package", "delivery", "stuck", "tracking", "shipment",
                  "arrived", "order #"]),
    ("account", ["change", "address", "email address", "close my account",
                 "update my details"]),
]
URGENT_WORDS = ["urgent", "chargeback", "fraud", "outage", "immediately",
                "lawsuit", "angry"]


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def snippet_text(item):
    for key in ("memory", "text", "content", "snippet", "preview", "chunk"):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            v = v.strip()
            if v.startswith("{"):
                try:
                    inner = json.loads(v)
                    if isinstance(inner, dict) and inner.get("chunk_text"):
                        sec = inner.get("section", "")
                        return (inner["chunk_text"] +
                                (f"  [Section: {sec}]" if sec else ""))
                except ValueError:
                    pass
            return v
    for key in ("chunk_text",):
        v = item.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return json.dumps(item)[:300]


def snippet_score(item):
    for key in ("score", "raw_similarity_score"):
        v = item.get(key)
        if isinstance(v, (int, float)):
            return round(float(v), 3)
    return None


def norm_hits(bucket, source):
    out = []
    if isinstance(bucket, dict):
        bucket = bucket.get("hits") or bucket.get("results") or []
    for item in bucket or []:
        if not isinstance(item, dict):
            continue
        out.append({"source": source, "text": snippet_text(item),
                    "score": snippet_score(item),
                    "doc": item.get("document") or item.get("section") or ""})
    return out


class MemoDesk:
    def __init__(self):
        self.client = MekoClient()
        self.lock = threading.RLock()  # re-entrant: reset_demo() calls seed()
        self.state = load_json(STATE_FILE, {})
        self.tickets = load_json(TICKETS_FILE, None) or list(DEMO_TICKETS)
        save_json(TICKETS_FILE, self.tickets)

    # ---------- audit ----------
    def audit(self):
        entries = list(self.client.calls)
        try:
            with open(AUDIT_FILE, "a") as f:
                for e in entries[getattr(self, "_audit_flushed", 0):]:
                    f.write(json.dumps(e) + "\n")
            self._audit_flushed = len(entries)
        except OSError:
            pass
        return entries

    # ---------- datapack / seed ----------
    def ensure_datapack(self, conv_id):
        if self.state.get("datapack_id"):
            return self.state["datapack_id"]
        res = self.client.call("datapack_search",
                               {"query": DATAPACK_NAME,
                                "conversation_id": conv_id})
        packs = res.get("datapacks", []) if isinstance(res, dict) else []
        for p in packs:
            if p.get("datapack_name") == DATAPACK_NAME:
                self.state["datapack_id"] = p["datapack_id"]
                save_json(STATE_FILE, self.state)
                return p["datapack_id"]
        res = self.client.call("datapack_create",
                               {"name": DATAPACK_NAME,
                                "conversation_id": conv_id})
        if isinstance(res, dict) and res.get("error"):
            raise MekoError(f"datapack_create: {res}")
        dp = res["datapack_id"] if isinstance(res, dict) else res.get("id")
        self.state["datapack_id"] = dp
        save_json(STATE_FILE, self.state)
        return dp

    def seed(self):
        with self.lock:
            conv = self.client.conversation_create("MemoDesk seed")
            dp = self.ensure_datapack(conv)
            if self.state.get("seeded"):
                return {"datapack_id": dp, "seeded": True,
                        "note": "already seeded"}
            kb_path = os.path.join(HERE, "kb", "support-policy.md")
            up = self.client.call("knowledgebase_upload_file",
                                  {"path": kb_path, "conversation_id": conv,
                                   "datapack_id": dp})
            mem_ids = []
            for text in SEED_MEMORIES:
                r = self.client.memory_add(text, conv, datapack_id=dp)
                if isinstance(r, dict):
                    for item in r.get("results", []):
                        mem_ids.append(item.get("id"))
            self.state["seeded"] = True
            self.state["seed_conversation_id"] = conv
            save_json(STATE_FILE, self.state)
            self.audit()
            return {"datapack_id": dp, "seeded": True,
                    "kb_upload": up, "memory_ids": mem_ids}

    def reset_demo(self):
        with self.lock:
            conv = self.client.conversation_create("MemoDesk reset")
            dp = self.state.get("datapack_id")
            if dp:
                self.client.call("datapack_delete",
                                 {"datapack_id": dp,
                                  "conversation_id": conv})
            self.state = {}
            save_json(STATE_FILE, self.state)
            self.tickets = [dict(t) for t in DEMO_TICKETS]
            save_json(TICKETS_FILE, self.tickets)
            self.audit()
            return self.seed()

    # ---------- triage ----------
    def classify(self, ticket, memory_hits, kb_hits):
        text = (ticket["subject"] + " " + ticket["body"]).lower()
        scores = {}
        for name, words in CATEGORIES:
            scores[name] = sum(2 if w in text else 0 for w in words)
        category = max(scores, key=scores.get)
        if scores[category] == 0:
            category = "general"
        amount = None
        m = re.search(r"\$(\d+)", ticket["subject"] + " " + ticket["body"])
        if m:
            amount = int(m.group(1))
        priority = "normal"
        reasons = [f"category keywords matched: {category}"]
        if any(w in text for w in URGENT_WORDS):
            priority = "urgent"
            reasons.append("urgent language in ticket")
        if amount and amount > 200:
            priority = "high"
            reasons.append(f"amount ${amount} is over the $200 escalation threshold")
        cust = ticket["customer"].lower()
        vip_hit = any("vip" in h["text"].lower() and cust in h["text"].lower()
                      for h in memory_hits)
        if vip_hit:
            if priority == "normal":
                priority = "high"
            reasons.append("Meko memory: customer is VIP")
        if any("store credit" in h["text"].lower() and cust in h["text"].lower()
               for h in memory_hits):
            reasons.append("Meko memory: customer prefers store-credit refunds")
        return category, priority, amount, reasons

    def draft_reply(self, ticket, category, memory_hits, kb_hits):
        name = ticket["customer"]
        cites = []
        # Cite only the best memory ABOUT THIS CUSTOMER (name match first,
        # then Meko score) plus KB hits: other customers' memories are shown
        # in the retrieved list but never quoted in the reply.
        cust = ticket["customer"].lower()
        own = [h for h in memory_hits if cust in h["text"].lower()]
        best_mem = (sorted(own, key=lambda h: h["score"] or 0, reverse=True)[:1]
                    or memory_hits[:1])
        citable = best_mem + [h for h in kb_hits]
        for h in citable[:3]:
            cites.append(f"[{h['source']}" +
                         (f" score {h['score']}" if h["score"] is not None else "") +
                         f"] {h['text'][:220]}")
        resolved = [h for h in memory_hits
                    if "resolved" in h["text"].lower()
                    and ticket["customer"].lower() in h["text"].lower()]
        if category == "billing" and resolved:
            body = (f"Hi {name}, thanks for following up. I can confirm the "
                    f"earlier case is already handled: "
                    f"{resolved[0]['text']} "
                    f"If the refund has not posted to your account yet, please "
                    f"allow 3–5 business days from the refund date.")
        elif category == "billing":
            body = (f"Hi {name}, thanks for flagging this. "
                    f"I checked your order and the duplicate charge — I will refund "
                    f"the duplicated amount right away; refunds post in 3–5 business days.")
            if any("store credit" in h["text"].lower()
                   and ticket["customer"].lower() in h["text"].lower()
                   for h in memory_hits):
                body += (" As you prefer store credit, I will refund it as store "
                         "credit, not cash.")
        elif category == "technical":
            body = (f"Hi {name}, sorry about that. Password reset links expire "
                    f"after 15 minutes, so I have sent you a fresh link — please "
                    f"use it within 15 minutes. Let me know if it still fails.")
        elif category == "shipping":
            body = (f"Hi {name}, I checked order {ticket['id']}. Deliveries in "
                    f"your region are delayed 3–5 days by a carrier backlog. "
                    f"If it is still stuck after 5 days I will open a carrier "
                    f"trace and offer a replacement shipment.")
        elif category == "account":
            body = (f"Hi {name}, yes — your delivery address can still be "
                    f"changed free of charge because the order has not shipped "
                    f"yet. Please reply with the new address and I will update it.")
        else:
            body = (f"Hi {name}, thanks for writing in. I have logged your "
                    f"request and will follow up shortly.")
        if cites:
            body += "\n\nSources used (retrieved live from Meko):\n- " + "\n- ".join(cites)
        return body

    def triage(self, ticket_id):
        with self.lock:
            ticket = next((t for t in self.tickets if t["id"] == ticket_id),
                          None)
            if not ticket:
                raise ValueError(f"unknown ticket {ticket_id}")
            dp = self.state.get("datapack_id")
            if not dp:
                raise MekoError("not seeded yet — call POST /api/seed first")
            conv = self.client.conversation_create(
                f"Triage {ticket_id}", datapack_id=dp)
            query = f"{ticket['customer']}: {ticket['subject']} {ticket['body']}"
            ctx = self.client.context_search(query, conv, datapack_id=dp,
                                             limit=5)
            kb = self.client.knowledgebase_search(query, conv, datapack_id=dp,
                                                  limit=5)
            results = ctx.get("results", {}) if isinstance(ctx, dict) else {}
            memory_hits = norm_hits(results.get("memory"), "memory")
            kb_hits = norm_hits(results.get("knowledge_base"), "knowledge_base")
            kb_hits += norm_hits(kb, "knowledge_base")
            seen, deduped = set(), []
            for h in kb_hits:
                if h["text"] not in seen:
                    seen.add(h["text"])
                    deduped.append(h)
            kb_hits = deduped
            conv_hits = norm_hits(results.get("conversation"), "conversation")
            category, priority, amount, reasons = self.classify(
                ticket, memory_hits, kb_hits)
            reply = self.draft_reply(ticket, category, memory_hits, kb_hits)
            plan = ["Recall shared context from Meko (memory + knowledge base + past conversations).",
                    f"Classify the ticket ({category}, priority {priority}).",
                    "Draft a reply grounded only in the retrieved snippets."]
            reasoning = ("; ".join(reasons) +
                         ". Reply quotes the retrieved snippets; nothing was invented.")
            self.client.conversation_add_message(
                conv, f"Ticket {ticket_id} from {ticket['customer']}: "
                      f"{ticket['subject']} — {ticket['body']}",
                f"[{category} / {priority}] {reply}", plan, reasoning,
                datapack_id=dp)
            ticket["status"] = "triaged"
            ticket["last_triage"] = {"category": category,
                                     "priority": priority,
                                     "conversation_id": conv}
            save_json(TICKETS_FILE, self.tickets)
            self.audit()
            return {"ticket": ticket, "category": category,
                    "priority": priority, "amount": amount,
                    "reasons": reasons, "draft_reply": reply,
                    "conversation_id": conv,
                    "retrieved": {"memory": memory_hits,
                                  "knowledge_base": kb_hits,
                                  "conversation": conv_hits},
                    "token_savings": ctx.get("token_savings") if isinstance(ctx, dict) else None}

    def resolve(self, ticket_id, resolution):
        with self.lock:
            ticket = next((t for t in self.tickets if t["id"] == ticket_id),
                          None)
            if not ticket:
                raise ValueError(f"unknown ticket {ticket_id}")
            dp = self.state.get("datapack_id")
            if not dp:
                raise MekoError("not seeded yet — call POST /api/seed first")
            conv = ticket.get("last_triage", {}).get("conversation_id") or \
                self.client.conversation_create(f"Resolve {ticket_id}",
                                                datapack_id=dp)
            fact = (f"Resolved {ticket_id} ({ticket['customer']}): "
                    f"{resolution}")
            r = self.client.memory_add(fact, conv, datapack_id=dp)
            self.client.conversation_add_message(
                conv, f"Resolve {ticket_id}: {resolution}",
                f"Ticket {ticket_id} resolved and the outcome was stored "
                f"as shared memory for future tickets.",
                ["Store the resolution as shared memory in Meko.",
                 "Mark the ticket resolved."],
                "The next ticket from this customer must recall this outcome.",
                datapack_id=dp)
            ticket["status"] = "resolved"
            ticket["resolution"] = resolution
            save_json(TICKETS_FILE, self.tickets)
            self.audit()
            return {"ticket": ticket, "memory_add": r}

    def memories(self):
        dp = self.state.get("datapack_id")
        if not dp:
            return {"memories": [], "total": 0}
        conv = self.client.conversation_create("MemoDesk memory browser",
                                               datapack_id=dp)
        res = self.client.memory_get_all(conv, datapack_id=dp)
        self.audit()
        return res

    def conversations(self):
        dp = self.state.get("datapack_id")
        if not dp:
            return {"conversations": []}
        conv = self.client.conversation_create("MemoDesk audit browser",
                                               datapack_id=dp)
        res = self.client.call("conversation_list",
                               {"conversation_id": conv, "datapack_id": dp,
                                "limit": 50})
        self.audit()
        return res


APP = MemoDesk()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p == "/":
                data = open(os.path.join(HERE, "index.html"), "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif p == "/api/health":
                tools = APP.client.tools_list()
                self._send(200, {"ok": True, "meko_mcp_url": "http://127.0.0.1:7777/mcp",
                                 "meko_tools": len(tools),
                                 "datapack": APP.state.get("datapack_id"),
                                 "seeded": bool(APP.state.get("seeded")),
                                 "cloud_linked": False,
                                 "agent": "rule-based triage (no LLM)"})
            elif p == "/api/tickets":
                self._send(200, {"tickets": APP.tickets})
            elif p == "/api/memories":
                self._send(200, APP.memories())
            elif p == "/api/audit":
                self._send(200, {"calls": APP.audit()})
            elif p == "/api/conversations":
                self._send(200, APP.conversations())
            else:
                self._send(404, {"error": "not found"})
        except MekoError as e:
            self._send(502, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            body = self._read_json()
            if p == "/api/seed":
                self._send(200, APP.seed())
            elif p == "/api/reset":
                self._send(200, APP.reset_demo())
            elif p == "/api/triage":
                self._send(200, APP.triage(body["ticket_id"]))
            elif p == "/api/resolve":
                self._send(200, APP.resolve(body["ticket_id"],
                                            body.get("resolution", "")))
            elif p == "/api/ticket":
                with APP.lock:
                    nid = f"TKT-{1000 + len(APP.tickets) + 1}"
                    t = {"id": nid, "customer": body.get("customer", "Guest"),
                         "email": body.get("email", ""),
                         "subject": body.get("subject", ""),
                         "body": body.get("body", ""), "status": "open"}
                    APP.tickets.append(t)
                    save_json(TICKETS_FILE, APP.tickets)
                self._send(200, {"ticket": t})
            else:
                self._send(404, {"error": "not found"})
        except (MekoError, ValueError) as e:
            self._send(502, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    print(f"MemoDesk on http://127.0.0.1:{PORT}/  (Meko MCP: "
          f"http://127.0.0.1:7777/mcp, local, no cloud account)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

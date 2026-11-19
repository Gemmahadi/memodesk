#!/usr/bin/env python3
"""Minimal MCP client for LOCAL Meko (Streamable HTTP), stdlib only.

- Endpoint: http://127.0.0.1:7777/mcp (local Meko server, no cloud account)
- Auth: a locally-generated token obtained at RUNTIME via `meko token`
  (or the MEKO_TOKEN env var). The token is kept in memory only and is
  NEVER written to any file, log, or API response.
- Transport: one JSON-RPC POST per call; the server answers either plain
  JSON or an SSE stream, so both shapes are parsed.
"""
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

MCP_URL = os.environ.get("MEKO_MCP_URL", "http://127.0.0.1:7777/mcp")
AGENT_ID = "memodesk:web"


def obtain_token():
    """Local Meko token, obtained at runtime. Never persisted."""
    env = os.environ.get("MEKO_TOKEN")
    if env:
        return env.strip()
    meko = shutil.which("meko") or os.path.expanduser("~/.local/bin/meko")
    out = subprocess.run([meko, "token"], capture_output=True, text=True,
                         timeout=30, check=True)
    return out.stdout.strip()


def _parse_body(body: bytes):
    text = body.decode("utf-8", "replace")
    msgs = []
    for chunk in text.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data:"):
                try:
                    msgs.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
    if not msgs and text.strip():
        try:
            msgs = [json.loads(text)]
        except json.JSONDecodeError:
            pass
    return msgs


class MekoError(Exception):
    pass


class MekoClient:
    def __init__(self):
        self.token = obtain_token()
        self._next_id = 1
        self._initialized = False
        self.calls = []  # audit trail of MCP calls (no token, no secrets)

    def _post(self, payload):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            MCP_URL, data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream",
                     "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return _parse_body(resp.read())
        except urllib.error.HTTPError as e:
            raise MekoError(f"HTTP {e.code}: {e.read().decode()[:300]}")
        except urllib.error.URLError as e:
            raise MekoError(f"Cannot reach local Meko at {MCP_URL}: {e}")

    def initialize(self):
        if self._initialized:
            return
        msgs = self._post({"jsonrpc": "2.0", "id": self._next_id,
                           "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18",
                                      "capabilities": {},
                                      "clientInfo": {"name": "memodesk",
                                                     "version": "1.0.0"}}})
        self._next_id += 1
        if not msgs or "result" not in msgs[0]:
            raise MekoError(f"MCP initialize failed: {msgs!r}")
        try:  # best-effort notification; server answers 202/empty
            self._post({"jsonrpc": "2.0",
                        "method": "notifications/initialized"})
        except MekoError:
            pass
        self._initialized = True

    def tools_list(self):
        self.initialize()
        msgs = self._post({"jsonrpc": "2.0", "id": self._next_id,
                           "method": "tools/list", "params": {}})
        self._next_id += 1
        return msgs[0]["result"]["tools"]

    def call(self, tool, arguments):
        """Call one MCP tool. Returns the parsed result object.

        Raises MekoError on transport failure. A tool-level error is
        returned as a dict with an "error" key (never faked as success).
        The call is appended to self.calls for the audit trail.
        """
        self.initialize()
        started = time.time()
        args = dict(arguments)
        args.setdefault("agent_id", AGENT_ID)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "tool": tool,
                 "args": {k: (str(v)[:120]) for k, v in args.items()},
                 "ms": 0, "ok": False, "summary": ""}
        try:
            msgs = self._post({"jsonrpc": "2.0", "id": self._next_id,
                               "method": "tools/call",
                               "params": {"name": tool, "arguments": args}})
            self._next_id += 1
            entry["ms"] = int((time.time() - started) * 1000)
            if not msgs or "result" not in msgs[0]:
                entry["summary"] = f"no result: {str(msgs)[:200]}"
                self.calls.append(entry)
                raise MekoError(f"{tool}: no result in MCP response")
            result = msgs[0]["result"]
            text = ""
            for item in result.get("content", []):
                if item.get("type") == "text":
                    text += item.get("text", "")
            parsed = None
            if text.strip():
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = {"raw_text": text}
            if isinstance(parsed, dict) and parsed.get("error"):
                entry["ok"] = False
                entry["summary"] = f"error={parsed.get('error')}"
                self.calls.append(entry)
                return parsed
            entry["ok"] = True
            if isinstance(parsed, dict):
                n = len(parsed.get("results", [])) if isinstance(
                    parsed.get("results"), list) else None
                entry["summary"] = ("results=%s" % n if n is not None
                                    else str(parsed)[:140])
            elif isinstance(parsed, list):
                entry["summary"] = f"items={len(parsed)}"
            else:
                entry["summary"] = str(parsed)[:140]
            self.calls.append(entry)
            return parsed if parsed is not None else result
        except Exception:
            entry["ms"] = int((time.time() - started) * 1000)
            if entry not in self.calls:
                self.calls.append(entry)
            raise

    # ---- convenience wrappers (all go through call(), hence audited) ----
    def conversation_create(self, title, datapack_id=None):
        args = {"title": title}
        if datapack_id:
            args["datapack_id"] = datapack_id
        res = self.call("conversation_create", args)
        if isinstance(res, dict) and res.get("error"):
            raise MekoError(f"conversation_create: {res}")
        return res["id"]

    def context_search(self, query, conversation_id, datapack_id=None, limit=5):
        args = {"query": query, "conversation_id": conversation_id,
                "limit": limit}
        if datapack_id:
            args["datapack_id"] = datapack_id
        res = self.call("context_search", args)
        if isinstance(res, dict) and res.get("error"):
            raise MekoError(f"context_search: {res}")
        return res if isinstance(res, dict) else {}

    def memory_search(self, query, conversation_id, datapack_id=None, limit=5):
        args = {"query": query, "conversation_id": conversation_id,
                "limit": limit}
        if datapack_id:
            args["datapack_id"] = datapack_id
        res = self.call("memory_search", args)
        if isinstance(res, dict) and res.get("error"):
            raise MekoError(f"memory_search: {res}")
        return res.get("results", []) if isinstance(res, dict) else []

    def memory_add(self, text, conversation_id, datapack_id=None):
        args = {"text": text, "conversation_id": conversation_id}
        if datapack_id:
            args["datapack_id"] = datapack_id
        res = self.call("memory_add", args)
        if isinstance(res, dict) and res.get("error"):
            raise MekoError(f"memory_add: {res}")
        return res

    def memory_get_all(self, conversation_id, datapack_id=None, page=1):
        args = {"conversation_id": conversation_id, "page": page,
                "page_size": 50}
        if datapack_id:
            args["datapack_id"] = datapack_id
        res = self.call("memory_get_all", args)
        if isinstance(res, dict) and res.get("error"):
            raise MekoError(f"memory_get_all: {res}")
        return res

    def knowledgebase_search(self, query, conversation_id, datapack_id=None,
                             limit=5):
        args = {"query": query, "conversation_id": conversation_id,
                "limit": limit}
        if datapack_id:
            args["datapack_id"] = datapack_id
        res = self.call("knowledgebase_search", args)
        if isinstance(res, dict) and res.get("error"):
            raise MekoError(f"knowledgebase_search: {res}")
        return res.get("results", []) if isinstance(res, dict) else []

    def conversation_add_message(self, conversation_id, user_text,
                                 assistant_text, plan, reasoning,
                                 datapack_id=None):
        args = {"conversation_id": conversation_id, "input": user_text,
                "output": assistant_text, "plan": plan,
                "reasoning": reasoning}
        if datapack_id:
            args["datapack_id"] = datapack_id
        res = self.call("conversation_add_message", args)
        if isinstance(res, dict) and res.get("error"):
            raise MekoError(f"conversation_add_message: {res}")
        return res

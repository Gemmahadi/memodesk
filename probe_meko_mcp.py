#!/usr/bin/env python3
"""Probe local Meko MCP (Streamable HTTP) — token obtained at runtime via `meko token`, never stored."""
import json, os, subprocess, sys, urllib.request

MCP_URL = "http://127.0.0.1:7777/mcp"

def token():
    return subprocess.run(["meko", "token"], capture_output=True, text=True, check=True).stdout.strip()

def sse_parse(body: bytes):
    """Parse SSE stream into list of JSON payloads."""
    out = []
    for chunk in body.decode("utf-8", "replace").split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data:"):
                try:
                    out.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass
    return out

def call(tok, method, params=None, req_id=1):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "Authorization": f"Bearer {tok}"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    msgs = sse_parse(body)
    if not msgs and body.strip():
        try:
            msgs = [json.loads(body)]
        except json.JSONDecodeError:
            pass
    return msgs

def main():
    tok = token()
    print("token obtained at runtime, len", len(tok))
    msgs = call(tok, "initialize", {"protocolVersion": "2025-06-18",
        "capabilities": {}, "clientInfo": {"name": "meko-probe", "version": "0.1"}})
    print("INIT:", json.dumps(msgs, indent=1)[:800])
    # notification initialized (no id)
    payload = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                 "Authorization": f"Bearer {tok}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except Exception as e:
        print("initialized-notif status:", e)
    msgs = call(tok, "tools/list", {}, req_id=2)
    tools = msgs[0]["result"]["tools"] if msgs and "result" in msgs[0] else []
    print("TOOLS COUNT:", len(tools))
    print("TOOL NAMES:", [t["name"] for t in tools])
    # create a conversation first: most tools require its id
    msgs = call(tok, "tools/call", {"name": "conversation_create",
        "arguments": {"agent_id": "probe-agent", "title": "probe"}}, req_id=3)
    print("CONV_CREATE:", json.dumps(msgs, indent=1)[:600])
    import json as _j
    conv = _j.loads(msgs[0]["result"]["content"][0]["text"])
    CID = conv.get("conversation_id") or conv.get("id")
    print("CID:", CID)
    # datapack list
    msgs = call(tok, "tools/call", {"name": "datapack_list", "arguments": {"conversation_id": CID}}, req_id=3)
    print("DATAPACK_LIST:", json.dumps(msgs, indent=1)[:1200])
    # memory add + search round-trip (unique marker so retrieval is provable)
    marker = "ZEBRA-QUOTA-7741"
    msgs = call(tok, "tools/call", {"name": "memory_add",
        "arguments": {"text": f"PROBE MARKER {marker}: customer Acme Corp prefers refunds in store credit, never cash.",
                      "agent_id": "probe-agent", "conversation_id": CID}}, req_id=4)
    print("MEMORY_ADD:", json.dumps(msgs, indent=1)[:600])
    msgs = call(tok, "tools/call", {"name": "memory_search",
        "arguments": {"query": f"Acme Corp refund preference {marker}", "agent_id": "probe-agent", "limit": 5, "conversation_id": CID}}, req_id=5)
    print("MEMORY_SEARCH:", json.dumps(msgs, indent=1)[:1500])
    msgs = call(tok, "tools/call", {"name": "context_search",
        "arguments": {"query": f"Acme Corp refund preference {marker}", "agent_id": "probe-agent", "limit": 5, "conversation_id": CID}}, req_id=6)
    print("CONTEXT_SEARCH:", json.dumps(msgs, indent=1)[:1500])

if __name__ == "__main__":
    main()

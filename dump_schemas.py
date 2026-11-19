import json, subprocess, urllib.request
MCP_URL="http://127.0.0.1:7777/mcp"
tok=subprocess.run(["meko","token"],capture_output=True,text=True,check=True).stdout.strip()
def call(method,params=None,req_id=1):
    p={"jsonrpc":"2.0","id":req_id,"method":method,"params":params or {}}
    r=urllib.request.Request(MCP_URL,data=json.dumps(p).encode(),headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream","Authorization":f"Bearer {tok}"},method="POST")
    with urllib.request.urlopen(r,timeout=60) as resp: body=resp.read().decode()
    out=[]
    for chunk in body.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data:"):
                try: out.append(json.loads(line[5:]))
                except json.JSONDecodeError: pass
    if not out and body.strip():
        try: out=[json.loads(body)]
        except json.JSONDecodeError: pass
    return out
call("initialize",{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"d","version":"0.1"}})
import urllib.request as _u, json as _j
_p={"jsonrpc":"2.0","method":"notifications/initialized"}
_r=_u.Request(MCP_URL,data=_j.dumps(_p).encode(),headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream","Authorization":f"Bearer {tok}"},method="POST")
try:
    with _u.urlopen(_r,timeout=30) as resp: resp.read()
except Exception as e: print("notif:",e)
tools=call("tools/list",{},2)[0]["result"]["tools"]
want={"datapack_create","datapack_search","memory_add","memory_get_all","knowledgebase_upload_file","knowledgebase_search","knowledgebase_document_status","memory_promote"}
for t in tools:
    if t["name"] in want:
        print("="*20, t["name"]); print(json.dumps(t.get("inputSchema",{}),indent=1)[:1500])

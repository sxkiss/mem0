"""mem0 MCP Server - 所有 AI 工具共享记忆"""
import json, sys, os, httpx

API = "http://localhost:8000"
AGENT_ID = sys.argv[1] if len(sys.argv) > 1 else "default"

def handle(req):
    m = req.get("method")
    p = req.get("params", {})
    rid = req.get("id")

    if m == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mem0-memory", "version": "1.0.0"}
        }}
    elif m == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": "mem0_add", "description": "添加记忆到当前 agent",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string", "description": "要记住的内容"},
                 "metadata": {"type": "object"}
             }, "required": ["text"]}},
            {"name": "mem0_search", "description": "搜索当前 agent 的记忆",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"},
                 "limit": {"type": "integer", "default": 5}
             }, "required": ["query"]}},
            {"name": "mem0_search_all", "description": "跨域搜索所有 agent 的记忆",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"},
                 "limit": {"type": "integer", "default": 5}
             }, "required": ["query"]}},
            {"name": "mem0_list", "description": "列出当前 agent 的所有记忆",
             "inputSchema": {"type": "object", "properties": {}}}
        ]}}
    elif m == "tools/call":
        name = p.get("name"); args = p.get("arguments", {})
        try:
            if name == "mem0_add":
                r = httpx.post(f"{API}/memories", json={"messages":[{"role":"user","content":args["text"]}],"agent_id":AGENT_ID,"metadata":args.get("metadata",{})})
                res = r.json()
            elif name == "mem0_search":
                r = httpx.post(f"{API}/search", json={"query":args["query"],"filters":{"agent_id":AGENT_ID},"top_k":args.get("limit",5)})
                res = r.json()
            elif name == "mem0_search_all":
                r = httpx.post(f"{API}/search", json={"query":args["query"],"top_k":args.get("limit",5)})
                res = r.json()
            elif name == "mem0_list":
                r = httpx.get(f"{API}/memories?agent_id={AGENT_ID}")
                res = r.json()
            else:
                res = {"error": f"Unknown tool: {name}"}
        except Exception as e:
            res = {"error": str(e)}
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}]}}
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Not found"}}

for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
        print(json.dumps(handle(json.loads(line))), flush=True)
    except Exception as e:
        print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}), flush=True)

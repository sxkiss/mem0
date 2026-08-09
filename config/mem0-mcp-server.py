"""mem0 MCP Server - 让所有 AI 工具都能读写记忆"""
import json
import sys
import httpx

MEM0_API = "http://localhost:8000"
AGENT_ID = sys.argv[1] if len(sys.argv) > 1 else "default"

def handle_request(request):
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mem0-memory", "version": "1.0.0"}
        }}
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
            {"name": "mem0_add", "description": "添加记忆",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string", "description": "要记住的内容"},
                 "metadata": {"type": "object", "description": "可选元数据"}
             }, "required": ["text"]}},
            {"name": "mem0_search", "description": "搜索记忆",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string", "description": "搜索关键词"},
                 "limit": {"type": "integer", "description": "返回数量", "default": 5}
             }, "required": ["query"]}},
            {"name": "mem0_search_all", "description": "跨域搜索所有工具的记忆",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string", "description": "搜索关键词"},
                 "limit": {"type": "integer", "default": 5}
             }, "required": ["query"]}},
            {"name": "mem0_list", "description": "列出所有记忆",
             "inputSchema": {"type": "object", "properties": {}}}
        ]}}
    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})
        try:
            if tool_name == "mem0_add":
                r = httpx.post(f"{MEM0_API}/memories", json={
                    "messages": [{"role": "user", "content": args["text"]}],
                    "agent_id": AGENT_ID,
                    "metadata": args.get("metadata", {})
                })
                result = r.json()
            elif tool_name == "mem0_search":
                r = httpx.post(f"{MEM0_API}/search", json={
                    "query": args["query"],
                    "filters": {"agent_id": AGENT_ID},
                    "top_k": args.get("limit", 5)
                })
                result = r.json()
            elif tool_name == "mem0_search_all":
                r = httpx.post(f"{MEM0_API}/search", json={
                    "query": args["query"],
                    "top_k": args.get("limit", 5)
                })
                result = r.json()
            elif tool_name == "mem0_list":
                r = httpx.get(f"{MEM0_API}/memories", params={"agent_id": AGENT_ID})
                result = r.json()
            else:
                result = {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            result = {"error": str(e)}
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
        }}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Not found"}}

# stdio 模式
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        request = json.loads(line)
        response = handle_request(request)
        print(json.dumps(response), flush=True)
    except Exception as e:
        print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}), flush=True)

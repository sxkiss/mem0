"""mem0 统一记忆配置 - 所有工具共享"""

MEM0_API = "http://localhost:8000"

# 每个工具的 agent_id（独立记忆空间）
AGENTS = {
    "claude": "claude-code",
    "openclaw": "openclaw",
    "hermes": "hermes-agent",
    "codex": "codex-cli",
}

def get_headers(agent_id: str) -> dict:
    """获取带 agent_id 的请求头"""
    return {"Content-Type": "application/json"}

def add_memory(agent_id: str, text: str, metadata: dict = None):
    """添加记忆"""
    import httpx
    payload = {
        "messages": [{"role": "user", "content": text}],
        "agent_id": agent_id,
        "metadata": metadata or {},
    }
    r = httpx.post(f"{MEM0_API}/memories", json=payload)
    return r.json()

def search_memory(agent_id: str, query: str, limit: int = 5):
    """搜索本 agent 的记忆"""
    import httpx
    payload = {
        "query": query,
        "filters": {"agent_id": agent_id},
        "top_k": limit,
    }
    r = httpx.post(f"{MEM0_API}/search", json=payload)
    return r.json()

def search_all(query: str, limit: int = 5):
    """跨域搜索所有 agent 的记忆"""
    import httpx
    payload = {"query": query, "top_k": limit}
    r = httpx.post(f"{MEM0_API}/search", json=payload)
    return r.json()

def cross_search(query: str, from_agent: str, to_agents: list = None):
    """从一个 agent 搜索另一个 agent 的记忆"""
    import httpx
    if to_agents is None:
        to_agents = [a for a in AGENTS.values() if a != from_agent]
    results = {}
    for agent in to_agents:
        payload = {
            "query": query,
            "filters": {"agent_id": agent},
            "top_k": 3,
        }
        r = httpx.post(f"{MEM0_API}/search", json=payload)
        results[agent] = r.json()
    return results

"""mem0 Memory Server - 轻量级，pgvector 存储，无需外部 LLM"""
import os, json, hashlib, re
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text

app = FastAPI(title="mem0 Memory API")

PG_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "postgres")
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")

engine = create_engine(
    f"postgresql+psycopg://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}",
    pool_pre_ping=True
)

with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS memories (
            id SERIAL PRIMARY KEY,
            memory_id VARCHAR(64) UNIQUE NOT NULL,
            data TEXT NOT NULL,
            user_id VARCHAR(255),
            agent_id VARCHAR(255),
            run_id VARCHAR(255),
            hash VARCHAR(64) NOT NULL,
            metadata JSONB DEFAULT '{}',
            embedding vector(384),
            keywords TEXT[] DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            expiration_date DATE
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_memories_keywords ON memories USING GIN(keywords)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_memories_data_fts ON memories USING GIN(to_tsvector('simple', data))
    """))
    conn.commit()

def text_to_embedding(text_str: str, dim: int = 384) -> list:
    """简单 hash-based embedding（无需 LLM）"""
    vec = [0.0] * dim
    words = re.findall(r'\w+', text_str.lower())
    for word in words:
        h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
        for i in range(dim):
            vec[i] += ((h >> (i % 32)) & 1) * 0.5 - 0.25
    # normalize
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec

def extract_keywords(text: str) -> List[str]:
    """提取关键词（简单分词）"""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    stop = {"the","and","for","are","but","not","you","all","can","had","her","was","one","our","out","has","have","been","from","this","that","with","they","will","what","when","where","who","which","their","about","would","could","should"}
    return list(set(w for w in words if w not in stop))[:20]

class MemoryAdd(BaseModel):
    messages: List[Dict[str, str]]
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class MemorySearch(BaseModel):
    query: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    top_k: int = 10
    threshold: float = 0.3

@app.get("/")
def root():
    return {"status": "ok", "service": "mem0-memory", "engine": "pgvector"}

@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

@app.get("/configure")
def get_config():
    return {
        "version": "v1.1",
        "vector_store": {"provider": "pgvector", "host": PG_HOST, "port": PG_PORT, "db": PG_DB},
        "llm": {"provider": "none", "model": "local"},
        "embedder": {"provider": "local", "model": "hash-384"}
    }

@app.post("/memories")
async def add_memory(req: MemoryAdd):
    full_text = " ".join(m.get("content", "") for m in req.messages)
    data = full_text[:2000]
    h = hashlib.sha256(data.encode()).hexdigest()
    mem_id = hashlib.md5((data + str(req.agent_id)).encode()).hexdigest()[:16]
    embedding = text_to_embedding(data)
    keywords = extract_keywords(data)
    
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO memories (memory_id, data, user_id, agent_id, run_id, hash, metadata, embedding, keywords)
            VALUES (:id, :data, :uid, :aid, :rid, :hash, :meta, :emb, :kw)
            ON CONFLICT (memory_id) DO UPDATE SET
                data = EXCLUDED.data,
                metadata = EXCLUDED.metadata,
                keywords = EXCLUDED.keywords,
                embedding = EXCLUDED.embedding,
                updated_at = NOW()
        """), {
            "id": mem_id, "data": data,
            "uid": req.user_id, "aid": req.agent_id, "rid": req.run_id,
            "hash": h, "meta": json.dumps(req.metadata or {}),
            "emb": str(embedding), "kw": keywords
        })
        conn.commit()
    return {"results": [{"memory_id": mem_id, "memory": data}]}

@app.post("/search")
async def search_memory(req: MemorySearch):
    """混合搜索：关键词 + 向量"""
    query_emb = text_to_embedding(req.query)
    query_keywords = extract_keywords(req.query)
    
    filters = []
    params = {"emb": str(query_emb), "top_k": req.top_k * 2}
    
    if req.agent_id:
        filters.append("agent_id = :aid")
        params["aid"] = req.agent_id
    if req.user_id:
        filters.append("user_id = :uid")
        params["uid"] = req.user_id
    
    where = " AND ".join(filters) if filters else "1=1"
    
    with engine.connect() as conn:
        # 向量搜索
        vec_rows = conn.execute(text(f"""
            SELECT memory_id, data, user_id, agent_id,
                   1 - (embedding <=> :emb::vector) as score
            FROM memories
            WHERE {where}
            ORDER BY embedding <=> :emb::vector
            LIMIT :top_k
        """), params).fetchall()
        
        # 关键词搜索
        kw_filter = " AND ".join(f"keywords @> ARRAY[:kw{i}]" for i in range(len(query_keywords)))
        kw_params = {f"kw{i}": kw for i, kw in enumerate(query_keywords)}
        kw_params["top_k"] = req.top_k * 2
        
        kw_rows = []
        if query_keywords:
            kw_rows = conn.execute(text(f"""
                SELECT memory_id, data, user_id, agent_id, 0.8 as score
                FROM memories
                WHERE {where} AND {kw_filter}
                ORDER BY created_at DESC
                LIMIT :top_k
            """), {**params, **kw_params}).fetchall()
    
    # 合并去重
    seen = {}
    for row in vec_rows + kw_rows:
        if row.memory_id not in seen:
            seen[row.memory_id] = {"id": row.memory_id, "memory": row.data,
                                    "user_id": row.user_id, "agent_id": row.agent_id,
                                    "score": round(float(row.score), 4)}
    
    results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:req.top_k]
    return {"results": results}

@app.get("/memories")
def list_memories(agent_id: str = Query(None), user_id: str = Query(None)):
    filters = []
    params = {}
    if agent_id:
        filters.append("agent_id = :aid")
        params["aid"] = agent_id
    if user_id:
        filters.append("user_id = :uid")
        params["uid"] = user_id
    where = " AND ".join(filters) if filters else "1=1"
    
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT memory_id, data, user_id, agent_id, created_at FROM memories
            WHERE {where} ORDER BY created_at DESC LIMIT 1000
        """), params).fetchall()
    
    return {"results": [
        {"id": r.memory_id, "memory": r.data, "user_id": r.user_id,
         "agent_id": r.agent_id, "created_at": str(r.created_at)}
        for r in rows
    ]}

@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM memories WHERE memory_id = :id"), {"id": memory_id})
        conn.commit()
    return {"status": "deleted"}

@app.get("/memories/{memory_id}/history")
def get_history(memory_id: str):
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT data, updated_at FROM memories WHERE memory_id = :id"
        ), {"id": memory_id}).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    return {"memory": row.data, "updated_at": str(row.updated_at)}

@app.post("/reset")
def reset():
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE memories RESTART IDENTITY"))
        conn.commit()
    return {"message": "All memories reset"}

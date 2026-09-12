"""轻量级记忆服务 - pgvector + BAAI/bge-m3 语义嵌入"""
import os, json, hashlib, re, time, logging
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import psycopg

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mem0")

app = FastAPI(title="mem0 Memory")

EMBED_DIM = 1024

PG_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "postgres")
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "postgres")

def get_conn():
    return psycopg.connect(f"host={PG_HOST} port={PG_PORT} dbname={PG_DB} user={PG_USER} password={PG_PASS}")

log.info("Loading BAAI/bge-m3 model...")
t0 = time.time()
from sentence_transformers import SentenceTransformer
_model = SentenceTransformer("BAAI/bge-m3")
log.info(f"bge-m3 loaded in {time.time()-t0:.1f}s")

def embed(text: str) -> list:
    return _model.encode(text, normalize_embeddings=True).tolist()

def kws(t: str) -> List[str]:
    stop = {"the","and","for","are","but","not","you","all","can","had","her","was","one","our","out","has","have","been","from","this","that","with","they","will","what","when","where","who","which","their","about","would","could","should"}
    return list(set(w for w in re.findall(r'\b[a-zA-Z]{3,}\b', t.lower()) if w not in stop))[:20]

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[Dict]:
    """文档分块：按字符数切分，支持重叠"""
    chunks = []
    text = text.strip()
    if len(text) <= chunk_size:
        return [{"id": hashlib.md5(text.encode()).hexdigest()[:12], "text": text, "index": 0}]
    
    # 尝试按段落/句子边界切分
    sentences = re.split(r'(?<=[。！？；\n])', text)
    chunks_data = []
    current_chunk = ""
    chunk_idx = 0
    
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(current_chunk) + len(sent) > chunk_size and current_chunk:
            chunks_data.append({"id": hashlib.md5(current_chunk.encode()).hexdigest()[:12], 
                              "text": current_chunk, "index": chunk_idx})
            chunk_idx += 1
            # 保留末尾重叠部分
            current_chunk = current_chunk[-overlap:] + sent
        else:
            current_chunk += (sent if current_chunk.endswith('\n') else '\n') + sent
    
    if current_chunk.strip():
        chunks_data.append({"id": hashlib.md5(current_chunk.encode()).hexdigest()[:12],
                          "text": current_chunk.strip(), "index": chunk_idx})
    
    return chunks_data

with get_conn() as conn:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cols = conn.execute("""
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_name='memories' AND column_name='embedding'
    """).fetchone()
    if cols and 'dim' in cols[1]:
        cur_dim = int(re.search(r'\d+', cols[1]).group())
        if cur_dim != EMBED_DIM:
            log.info(f"Migrating embedding dimension {cur_dim} -> {EMBED_DIM}")
            conn.execute("DROP TABLE IF NOT EXISTS memories CASCADE")
            conn.commit()
            cols = None
    if not cols:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS memories (
            id SERIAL PRIMARY KEY, memory_id VARCHAR(64) UNIQUE NOT NULL,
            data TEXT NOT NULL, user_id VARCHAR(255), agent_id VARCHAR(255),
            run_id VARCHAR(255), hash VARCHAR(64) NOT NULL,
            metadata JSONB DEFAULT '{{}}', embedding vector({EMBED_DIM}),
            keywords TEXT[] DEFAULT '{{}}',
            created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_user ON memories(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_kw ON memories USING GIN(keywords)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_emb ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
        conn.commit()
    log.info("Database ready")

class MAdd(BaseModel):
    messages: List[Dict[str, str]]
    user_id: Optional[str] = None; agent_id: Optional[str] = None
    run_id: Optional[str] = None; metadata: Optional[Dict] = None

class MUpdate(BaseModel):
    data: Optional[str] = None
    metadata: Optional[Dict] = None
    keywords: Optional[List[str]] = None

class MSearch(BaseModel):
    query: str; user_id: Optional[str] = None; agent_id: Optional[str] = None
    top_k: int = 10; threshold: float = 0.3; include_metadata: bool = False

class MImport(BaseModel):
    texts: List[str]
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict] = None
    chunk_size: int = 500
    chunk_overlap: int = 50

@app.get("/")
def root(): return {"status": "ok", "engine": "pgvector", "embedder": "bge-m3", "dim": EMBED_DIM}

@app.get("/configure")
def cfg(): return {"version": "v2.1", "vector_store": {"provider": "pgvector"}, "embedder": {"provider": "bge-m3", "dim": EMBED_DIM}}

@app.post("/memories")
async def add(req: MAdd):
    full_text = " ".join(m.get("content","") for m in req.messages)[:2000]
    mid = hashlib.md5((full_text + str(req.agent_id or "")).encode()).hexdigest()[:16]
    h = hashlib.sha256(full_text.encode()).hexdigest()
    kw = kws(full_text)
    emb = embed(full_text)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO memories (memory_id,data,user_id,agent_id,run_id,hash,metadata,embedding,keywords)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)
            ON CONFLICT (memory_id) DO UPDATE SET data=EXCLUDED.data, metadata=EXCLUDED.metadata,
            keywords=EXCLUDED.keywords, embedding=EXCLUDED.embedding, updated_at=NOW()""",
            (mid, full_text, req.user_id, req.agent_id, req.run_id, h,
             json.dumps(req.metadata or {}), str(emb), kw))
        conn.commit()
    return {"results": [{"memory_id": mid, "memory": full_text}]}

@app.put("/memories/{mid}")
async def update(mid: str, req: MUpdate):
    """更新记忆内容（按 ID）"""
    with get_conn() as conn:
        old = conn.execute("SELECT data FROM memories WHERE memory_id=%s", (mid,)).fetchone()
        if not old:
            raise HTTPException(404, "Memory not found")
        
        new_data = req.data or old[0]
        new_hash = hashlib.sha256(new_data.encode()).hexdigest()
        new_kw = kws(new_data)
        new_emb = embed(new_data)
        new_meta = req.metadata or json.loads(old[0].get("metadata", "{}") if hasattr(old[0], 'get') else "{}")
        if req.metadata:
            new_meta.update(req.metadata)
        
        conn.execute("""
            UPDATE memories SET 
                data=%s, hash=%s, keywords=%s, embedding=%s::vector, 
                metadata=%s::jsonb, updated_at=NOW()
            WHERE memory_id=%s
        """, (new_data, new_hash, new_kw, str(new_emb), json.dumps(new_meta), mid))
        conn.commit()
    
    return {"status": "updated", "memory_id": mid}

@app.post("/search")
async def search(req: MSearch):
    qe = embed(req.query); qk = kws(req.query)
    emb_str = str(qe)
    conditions = []
    params = [emb_str]
    if req.agent_id:
        conditions.append("agent_id = %s")
        params.append(req.agent_id)
    if req.user_id:
        conditions.append("user_id = %s")
        params.append(req.user_id)
    wc = " AND ".join(conditions) if conditions else "1=1"
    
    with get_conn() as conn:
        # 向量检索
        vr = conn.execute(
            f"SELECT memory_id,data,user_id,agent_id,metadata,1-(embedding <=> %s::vector) as score FROM memories WHERE {wc} ORDER BY embedding <=> %s::vector LIMIT %s",
            params + [emb_str, req.top_k*2]
        ).fetchall()
        
        # 关键词检索
        kr = []
        if qk:
            kw_conds = " OR ".join(["keywords @> %s"] * len(qk))
            kr = conn.execute(
                f"SELECT memory_id,data,user_id,agent_id,metadata,0.8 as score FROM memories WHERE {wc} AND ({kw_conds}) LIMIT %s",
                params + [list(k for k in qk)] * len(qk) + [req.top_k*2]
            ).fetchall()
    
    # 合并去重，精排（取加权平均分）
    seen = {}
    for r in vr + kr:
        mid = r[0]
        if mid not in seen:
            seen[mid] = {"id": mid, "data": r[1], "user_id": r[2], "agent_id": r[3], 
                        "metadata": r[4] if req.include_metadata else {}, "score": 0, "count": 0}
        seen[mid]["score"] += float(r[5])
        seen[mid]["count"] += 1
    
    results = []
    for item in seen.values():
        avg_score = item["score"] / item["count"]
        if avg_score >= req.threshold:
            results.append({
                "id": item["id"],
                "memory": item["data"],
                "user_id": item["user_id"],
                "agent_id": item["agent_id"],
                "score": round(avg_score, 4)
            })
    
    return {"results": sorted(results, key=lambda x: x["score"], reverse=True)[:req.top_k]}

@app.get("/memories")
def lst(agent_id: str=Query(None), user_id: str=Query(None), limit: int = Query(50)):
    wc, params = [], []
    if agent_id: wc.append("agent_id = %s"); params.append(agent_id)
    if user_id: wc.append("user_id = %s"); params.append(user_id)
    ws = " AND ".join(wc) if wc else "1=1"
    with get_conn() as conn:
        rows = conn.execute(f"SELECT memory_id,data,user_id,agent_id,metadata,created_at FROM memories WHERE {ws} ORDER BY created_at DESC LIMIT %s", 
                          params + [limit]).fetchall()
    return {"results":[{"id":r[0],"memory":r[1],"user_id":r[2],"agent_id":r[3],
              "metadata":r[4] if r[4] else {}, "created_at":str(r[5])} for r in rows]}

@app.delete("/memories/{mid}")
def rm(mid: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM memories WHERE memory_id = %s", (mid,)); conn.commit()
    return {"status":"deleted"}

@app.get("/memories/{mid}/history")
def hist(mid: str):
    with get_conn() as conn:
        r = conn.execute("SELECT data,updated_at FROM memories WHERE memory_id=%s", (mid,)).fetchone()
    if not r: raise HTTPException(404)
    return {"memory":r[0],"updated_at":str(r[1])}

@app.post("/import")
async def batch_import(req: MImport):
    """批量导入（自动分块）"""
    imported = 0
    for text in req.texts:
        chunks = chunk_text(text, chunk_size=req.chunk_size, overlap=req.chunk_overlap)
        for chunk in chunks:
            meta = {"source": "import", "chunk_index": chunk["index"], 
                   "total_chunks": len(chunks), **(req.metadata or {})}
            payload = {"messages": [{"role": "user", "content": chunk["text"]}]}
            if req.agent_id: payload["agent_id"] = req.agent_id
            if req.user_id: payload["user_id"] = req.user_id
            payload["metadata"] = meta
            await add(MAdd(**payload))
            imported += 1
    return {"status": "ok", "imported": imported, "chunks": imported}

@app.post("/reset")
def rst():
    with get_conn() as conn:
        conn.execute("TRUNCATE TABLE memories RESTART IDENTITY"); conn.commit()
    return {"message":"All memories reset"}

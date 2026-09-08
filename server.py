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
            conn.execute("DROP TABLE IF EXISTS memories CASCADE")
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

class MSearch(BaseModel):
    query: str; user_id: Optional[str] = None; agent_id: Optional[str] = None
    top_k: int = 10; threshold: float = 0.3

@app.get("/")
def root(): return {"status": "ok", "engine": "pgvector", "embedder": "bge-m3", "dim": EMBED_DIM}

@app.get("/configure")
def cfg(): return {"version": "v2.0", "vector_store": {"provider": "pgvector"}, "llm": {"provider": "none"}, "embedder": {"provider": "bge-m3", "dim": EMBED_DIM}}

@app.post("/memories")
async def add(req: MAdd):
    full_text = " ".join(m.get("content","") for m in req.messages)[:2000]
    mid = hashlib.md5((full_text + str(req.agent_id)).encode()).hexdigest()[:16]
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
        vr = conn.execute(
            f"SELECT memory_id,data,user_id,agent_id,1-(embedding <=> %s::vector) as score FROM memories WHERE {wc} ORDER BY embedding <=> %s::vector LIMIT %s",
            params + [emb_str, req.top_k*2]
        ).fetchall()
        kr = []
        if qk:
            kw_conds = " OR ".join(["keywords @> %s"] * len(qk))
            kr = conn.execute(
                f"SELECT memory_id,data,user_id,agent_id,0.8 as score FROM memories WHERE {wc} AND ({kw_conds}) LIMIT %s",
                params + [list(k for k in qk)] * len(qk) + [req.top_k*2]
            ).fetchall()
    seen = {}
    for r in vr+kr:
        if r[0] not in seen:
            seen[r[0]] = {"id":r[0],"memory":r[1],"user_id":r[2],"agent_id":r[3],"score":round(float(r[4]),4)}
    return {"results": sorted(seen.values(), key=lambda x:x["score"], reverse=True)[:req.top_k]}

@app.get("/memories")
def lst(agent_id: str=Query(None), user_id: str=Query(None)):
    wc, params = [], []
    if agent_id: wc.append("agent_id = %s"); params.append(agent_id)
    if user_id: wc.append("user_id = %s"); params.append(user_id)
    ws = " AND ".join(wc) if wc else "1=1"
    with get_conn() as conn:
        rows = conn.execute(f"SELECT memory_id,data,user_id,agent_id,created_at FROM memories WHERE {ws} ORDER BY created_at DESC LIMIT 1000", params).fetchall()
    return {"results":[{"id":r[0],"memory":r[1],"user_id":r[2],"agent_id":r[3],"created_at":str(r[4])} for r in rows]}

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

@app.post("/reset")
def rst():
    with get_conn() as conn:
        conn.execute("TRUNCATE TABLE memories RESTART IDENTITY"); conn.commit()
    return {"message":"All memories reset"}

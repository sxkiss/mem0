"""轻量级记忆服务 - pgvector 存储，无需外部 LLM"""
import os, json, hashlib, re
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import create_engine, text

app = FastAPI(title="mem0 Memory")

PG = {k: os.getenv(k, d) for k, d in [
    ("POSTGRES_HOST", "127.0.0.1"),
    ("POSTGRES_PORT", "5432"),
    ("POSTGRES_DB", "postgres"),
    ("POSTGRES_USER", "postgres"),
    ("POSTGRES_PASSWORD", "postgres"),
]}

engine = create_engine(
    f"postgresql+psycopg://{PG['POSTGRES_USER']}:{PG['POSTGRES_PASSWORD']}@{PG['POSTGRES_HOST']}:{PG['POSTGRES_PORT']}/{PG['POSTGRES_DB']}",
    pool_pre_ping=True
)

with engine.connect() as c:
    c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    c.execute(text("""CREATE TABLE IF NOT EXISTS memories (
        id SERIAL PRIMARY KEY, memory_id VARCHAR(64) UNIQUE NOT NULL,
        data TEXT NOT NULL, user_id VARCHAR(255), agent_id VARCHAR(255),
        run_id VARCHAR(255), hash VARCHAR(64) NOT NULL,
        metadata JSONB DEFAULT '{}', embedding vector(384),
        keywords TEXT[] DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
    )"""))
    c.execute(text("CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id)"))
    c.execute(text("CREATE INDEX IF NOT EXISTS idx_mem_user ON memories(user_id)"))
    c.execute(text("CREATE INDEX IF NOT EXISTS idx_mem_kw ON memories USING GIN(keywords)"))
    c.execute(text("CREATE INDEX IF NOT EXISTS idx_mem_emb ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"))
    c.commit()

def embed(t: str, dim=384) -> list:
    v = [0.0]*dim
    for w in re.findall(r'\w+', t.lower()):
        h = int(hashlib.sha256(w.encode()).hexdigest(), 16)
        for i in range(dim): v[i] += ((h >> (i%32)) & 1)*0.5 - 0.25
    n = sum(x*x for x in v)**0.5
    return [x/n for x in v] if n > 0 else v

def kws(t: str) -> List[str]:
    stop = {"the","and","for","are","but","not","you","all","can","had","her","was","one","our","out","has","have","been","from","this","that","with","they","will","what","when","where","who","which","their","about","would","could","should"}
    return list(set(w for w in re.findall(r'\b[a-zA-Z]{3,}\b', t.lower()) if w not in stop))[:20]

class MAdd(BaseModel):
    messages: List[Dict[str, str]]
    user_id: Optional[str] = None; agent_id: Optional[str] = None
    run_id: Optional[str] = None; metadata: Optional[Dict] = None

class MSearch(BaseModel):
    query: str; user_id: Optional[str] = None; agent_id: Optional[str] = None
    top_k: int = 10; threshold: float = 0.3

@app.get("/")
def root(): return {"status": "ok", "engine": "pgvector"}

@app.get("/configure")
def cfg(): return {"version": "v1.1", "vector_store": {"provider": "pgvector"}, "llm": {"provider": "none"}, "embedder": {"provider": "local"}}

@app.post("/memories")
async def add(req: MAdd):
    full_text = " ".join(m.get("content","") for m in req.messages)[:2000]
    text_content = full_text
    mid = hashlib.md5((text + str(req.agent_id)).encode()).hexdigest()[:16]
    h = hashlib.sha256(text.encode()).hexdigest()
    kw = kws(text)
    emb = embed(text)
    with engine.connect() as c:
        c.execute(text("""INSERT INTO memories (memory_id,data,user_id,agent_id,run_id,hash,metadata,embedding,keywords)
            VALUES (:id,:d,:u,:a,:r,:h,:m,:e,:k)
            ON CONFLICT (memory_id) DO UPDATE SET data=EXCLUDED.data, metadata=EXCLUDED.metadata,
            keywords=EXCLUDED.keywords, embedding=EXCLUDED.embedding, updated_at=NOW()"""),
            {"id":mid,"d":text_content,"u":req.user_id,"a":req.agent_id,"r":req.run_id,"h":h,
             "m":json.dumps(req.metadata or {}),"e":str(emb),"k":kw})
        c.commit()
    return {"results": [{"memory_id": mid, "memory": text}]}

@app.post("/search")
async def search(req: MSearch):
    qe = embed(req.query); qk = kws(req.query)
    fl, p = [], {"emb": str(qe), "top_k": req.top_k*2}
    if req.agent_id: fl.append("agent_id=:a"); p["a"]=req.agent_id
    if req.user_id: fl.append("user_id=:u"); p["u"]=req.user_id
    w = " AND ".join(fl) if fl else "1=1"
    with engine.connect() as c:
        vr = c.execute(text(f"SELECT memory_id,data,user_id,agent_id,1-(embedding<=>:emb::vector) score FROM memories WHERE {w} ORDER BY embedding<=>:emb::vector LIMIT :top_k"), p).fetchall()
        kr = []
        if qk:
            kf = " AND ".join(f"keywords @> ARRAY[:k{i}]" for i in range(len(qk)))
            kp = {f"k{i}":k for i,k in enumerate(qk)}; kp.update(p)
            kr = c.execute(text(f"SELECT memory_id,data,user_id,agent_id,0.8 score FROM memories WHERE {w} AND {kf} LIMIT :top_k"), kp).fetchall()
    seen = {}
    for r in vr+kr:
        if r.memory_id not in seen: seen[r.memory_id] = {"id":r.memory_id,"memory":r.data,"user_id":r.user_id,"agent_id":r.agent_id,"score":round(float(r.score),4)}
    return {"results": sorted(seen.values(), key=lambda x:x["score"], reverse=True)[:req.top_k]}

@app.get("/memories")
def lst(agent_id: str=Query(None), user_id: str=Query(None)):
    fl,p = [],[]
    if agent_id: fl.append("agent_id=:a"); p["a"]=agent_id
    if user_id: fl.append("user_id=:u"); p["u"]=user_id
    w = " AND ".join(fl) if fl else "1=1"
    with engine.connect() as c:
        rows = c.execute(text(f"SELECT memory_id,data,user_id,agent_id,created_at FROM memories WHERE {w} ORDER BY created_at DESC LIMIT 1000"), p).fetchall()
    return {"results":[{"id":r.memory_id,"memory":r.data,"user_id":r.user_id,"agent_id":r.agent_id,"created_at":str(r.created_at)} for r in rows]}

@app.delete("/memories/{mid}")
def rm(mid: str):
    with engine.connect() as c:
        c.execute(text("DELETE FROM memories WHERE memory_id=:id"),{"id":mid}); c.commit()
    return {"status":"deleted"}

@app.get("/memories/{mid}/history")
def hist(mid: str):
    with engine.connect() as c:
        r = c.execute(text("SELECT data,updated_at FROM memories WHERE memory_id=:id"),{"id":mid}).fetchone()
    if not r: raise HTTPException(404)
    return {"memory":r.data,"updated_at":str(r.updated_at)}

@app.post("/reset")
def rst():
    with engine.connect() as c:
        c.execute(text("TRUNCATE TABLE memories RESTART IDENTITY")); c.commit()
    return {"message":"All memories reset"}

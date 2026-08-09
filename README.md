# mem0 Memory Service

轻量级 AI 记忆服务，基于 pgvector 向量存储，无需外部 LLM，支持跨工具共享记忆。

## 功能特性

- ✅ **pgvector 向量存储** - 本地持久化，无需外部向量数据库
- ✅ **混合搜索** - 向量相似度 + 关键词匹配
- ✅ **跨工具共享** - Claude Code、Codex、Hermes、OpenClaw 统一记忆
- ✅ **独立命名空间** - 每个 agent 有独立记忆空间
- ✅ **Docker 一键部署** - 自动构建推送到 Docker Hub

## 快速开始

### 本地部署

```bash
# 克隆仓库
git clone https://github.com/sxkiss/mem0.git
cd mem0

# 启动服务
docker compose up -d

# 验证服务
curl http://localhost:8000/health
```

### 配置 LLM 连接（可选）

如果你需要使用 LLM 提取记忆，配置环境变量：

```bash
# 在 docker-compose.yml 中添加
environment:
  - OPENAI_API_KEY=your-api-key
  - OPENAI_BASE_URL=http://your-llm-proxy/v1
  - MEM0_DEFAULT_LLM_MODEL=your-model
```

## API 接口

### 根路径
```http
GET /
```
响应：
```json
{
  "status": "ok",
  "engine": "pgvector"
}
```

### 健康检查
```http
GET /health
```

### 添加记忆
```http
POST /memories
Content-Type: application/json

{
  "messages": [
    {"role": "user", "content": "要记住的内容"}
  ],
  "agent_id": "claude-code",
  "metadata": {"source": "cli"}
}
```

### 搜索记忆
```http
POST /search
Content-Type: application/json

{
  "query": "搜索关键词",
  "agent_id": "claude-code",
  "top_k": 5
}
```

### 跨域搜索
```http
POST /search
Content-Type: application/json

{
  "query": "搜索关键词",
  "top_k": 10
}
```

### 列出记忆
```http
GET /memories?agent_id=claude-code
```

### 删除记忆
```http
DELETE /memories/{memory_id}
```

### 重置所有记忆
```http
POST /reset
```

## 集成指南

### Claude Code

1. 复制 MCP 配置到 Claude Code：
```bash
cp config/mem0-mcp.py ~/.claude/config/mcp-servers/mem0-memory.py
```

2. 在 Claude Code 设置中启用 MCP server

### Codex

1. 添加到 `~/.codex/config.toml`：
```toml
[mcp_servers.mem0-memory]
type = "stdio"
command = "python3"
args = ["/path/to/mem0-mcp.py", "codex-cli"]
```

### Hermes

1. 添加到 `~/.hermes/config.yaml`：
```yaml
mcp_servers:
  mem0-memory:
    command: python3
    args:
      - /path/to/mem0-mcp.py
      - hermes-agent
    enabled: true
```

### OpenClaw

1. 创建 skill 文件 `~/.openclaw/skills/mem0-memory/SKILL.md`

### CLI 工具

```bash
# 添加记忆
mem0-cli add "内容" claude-code

# 搜索记忆
mem0-cli search "关键词" claude-code

# 列出记忆
mem0-cli list claude-code

# 跨域搜索
mem0-cli all "关键词"
```

## 命名空间

每个工具有独立的 `agent_id`：

- `claude-code` - Claude Code
- `codex-cli` - Codex
- `hermes-agent` - Hermes
- `openclaw` - OpenClaw
- `cli` - CLI 工具

## Docker 镜像

- **官方镜像**: `sxkiss/mem0:latest`
- **本地构建**: `docker compose build`

## 开发指南

### 本地开发

```bash
# 安装依赖
pip install fastapi uvicorn psycopg pydantic

# 运行测试
python -m pytest tests/
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POSTGRES_HOST` | `127.0.0.1` | PostgreSQL 地址 |
| `POSTGRES_PORT` | `5432` | PostgreSQL 端口 |
| `POSTGRES_DB` | `postgres` | 数据库名 |
| `POSTGRES_USER` | `postgres` | 数据库用户 |
| `POSTGRES_PASSWORD` | `postgres` | 数据库密码 |
| `OPENAI_API_KEY` | - | OpenAI API Key（可选） |
| `OPENAI_BASE_URL` | - | OpenAI Base URL（可选） |
| `MEM0_DEFAULT_LLM_MODEL` | - | 默认 LLM 模型 |

## 架构

```
mem0 API Server
├── FastAPI REST API
├── pgvector 向量存储
├── PostgreSQL 持久化
└── MCP Server 集成

各工具集成
├── Claude Code (MCP)
├── Codex (MCP)
├── Hermes (MCP)
├── OpenClaw (Skill)
└── CLI (命令行)
```

## 许可证

Apache License 2.0

## 致谢

- [mem0ai/mem0](https://github.com/mem0ai/mem0) - 核心记忆系统
- [pgvector](https://github.com/pgvector/pgvector) - PostgreSQL 向量扩展

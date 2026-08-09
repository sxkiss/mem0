# mem0 Memory Service

轻量级 AI 记忆服务，基于 pgvector 向量存储，无需外部 LLM，支持跨工具共享记忆。

## 功能特性

- ✅ **pgvector 向量存储** - 本地持久化，无需外部向量数据库
- ✅ **混合搜索** - 向量相似度 + 关键词匹配
- ✅ **跨工具共享** - Claude Code、Codex、Hermes、OpenClaw、OpenCode 统一记忆
- ✅ **独立命名空间** - 每个 agent 有独立记忆空间
- ✅ **Docker 一键部署** - 自动构建推送到 Docker Hub

## 快速开始

### 1. 克隆仓库
```bash
git clone https://github.com/sxkiss/mem0.git
cd mem0
```

### 2. 配置环境变量
```bash
# 复制示例配置
cp .env.example .env

# 编辑配置文件
nano .env
```

### 3. 启动服务
```bash
# 启动 PostgreSQL 和 mem0 API
docker compose up -d

# 检查服务状态
docker compose ps

# 查看日志
docker compose logs -f mem0
```

### 4. 验证服务
```bash
# 测试 API
curl http://localhost:8000/

# 添加测试记忆
curl -X POST http://localhost:8000/memories \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"测试记忆"}],"agent_id":"test"}'

# 搜索记忆
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"测试","agent_id":"test"}'
```

## 环境变量配置

### .env 文件
```env
# PostgreSQL 配置
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# 可选：LLM 配置（用于智能提取记忆）
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=http://your-llm-proxy/v1
MEM0_DEFAULT_LLM_MODEL=your-model
```

### 环境变量说明

| 变量 | 默认值 | 必填 | 说明 |
|------|--------|------|------|
| `POSTGRES_HOST` | `127.0.0.1` | ✅ | PostgreSQL 地址 |
| `POSTGRES_PORT` | `5432` | ✅ | PostgreSQL 端口 |
| `POSTGRES_DB` | `postgres` | ✅ | 数据库名 |
| `POSTGRES_USER` | `postgres` | ✅ | 数据库用户 |
| `POSTGRES_PASSWORD` | `postgres` | ✅ | 数据库密码 |
| `OPENAI_API_KEY` | - | ❌ | OpenAI API Key（可选） |
| `OPENAI_BASE_URL` | - | ❌ | OpenAI Base URL（可选） |
| `MEM0_DEFAULT_LLM_MODEL` | - | ❌ | 默认 LLM 模型 |

## API 接口文档

### 基础信息
- **Base URL**: `http://localhost:8000`
- **Content-Type**: `application/json`
- **认证**: 无（本地开发模式）

### 1. 健康检查
```http
GET /
```

**响应示例:**
```json
{
  "status": "ok",
  "engine": "pgvector"
}
```

### 2. 添加记忆
```http
POST /memories
```

**请求体:**
```json
{
  "messages": [
    {"role": "user", "content": "要记住的内容"}
  ],
  "agent_id": "claude-code",
  "user_id": "optional-user-id",
  "run_id": "optional-run-id",
  "metadata": {
    "source": "cli",
    "importance": "high"
  }
}
```

**参数说明:**
- `messages` (必填): 消息列表，格式为 `[{"role": "user", "content": "..."}]`
- `agent_id` (必填): agent 标识，决定记忆归属
- `user_id` (可选): 用户标识，用于区分同一 agent 的不同用户
- `run_id` (可选): 运行标识，用于关联对话
- `metadata` (可选): 元数据，存储额外信息

**响应示例:**
```json
{
  "results": [
    {
      "memory_id": "a1b2c3d4e5f6",
      "memory": "要记住的内容"
    }
  ]
}
```

### 3. 搜索记忆
```http
POST /search
```

**请求体:**
```json
{
  "query": "搜索关键词",
  "agent_id": "claude-code",
  "user_id": "optional-user-id",
  "top_k": 10,
  "threshold": 0.3
}
```

**参数说明:**
- `query` (必填): 搜索关键词
- `agent_id` (可选): 指定搜索某个 agent 的记忆
- `user_id` (可选): 指定搜索某个用户的记忆
- `top_k` (可选): 返回结果数量，默认 10
- `threshold` (可选): 相似度阈值，默认 0.3

**跨域搜索:**
不传 `agent_id` 会搜索所有 agent 的记忆：
```json
{
  "query": "搜索关键词",
  "top_k": 10
}
```

**响应示例:**
```json
{
  "results": [
    {
      "id": "a1b2c3d4e5f6",
      "memory": "记忆内容",
      "user_id": null,
      "agent_id": "claude-code",
      "score": 0.85
    }
  ]
}
```

### 4. 列出记忆
```http
GET /memories?agent_id=claude-code&user_id=optional-user-id
```

**参数说明:**
- `agent_id` (可选): 指定 agent
- `user_id` (可选): 指定用户

**响应示例:**
```json
{
  "results": [
    {
      "id": "a1b2c3d4e5f6",
      "memory": "记忆内容",
      "user_id": null,
      "agent_id": "claude-code",
      "created_at": "2026-08-09 15:00:00"
    }
  ]
}
```

### 5. 删除记忆
```http
DELETE /memories/{memory_id}
```

**响应示例:**
```json
{
  "status": "deleted"
}
```

### 6. 重置所有记忆
```http
POST /reset
```

**响应示例:**
```json
{
  "message": "All memories reset"
}
```

## 集成指南

### Claude Code

#### 方法 1: MCP Server（推荐）
1. 复制 MCP 配置：
```bash
mkdir -p ~/.claude/config/mcp-servers
cp config/mem0-mcp.py ~/.claude/config/mcp-servers/mem0-memory.py
chmod +x ~/.claude/config/mcp-servers/mem0-memory.py
```

2. 在 Claude Code 设置中启用 MCP server：
```json
{
  "mcpServers": {
    "mem0-memory": {
      "type": "stdio",
      "command": "python3",
      "args": ["~/.claude/config/mcp-servers/mem0-memory.py", "claude-code"]
    }
  }
}
```

#### 方法 2: Skill 文档
创建 `~/.claude/commands/mem0.md`：
```markdown
# mem0 Memory

## 使用方法
- 添加记忆: curl -X POST http://localhost:8000/memories ...
- 搜索记忆: curl -X POST http://localhost:8000/search ...
```

### Codex

1. 添加到 `~/.codex/config.toml`：
```toml
[mcp_servers.mem0-memory]
type = "stdio"
command = "python3"
args = ["/path/to/mem0-mcp.py", "codex-cli"]
```

2. 或者使用 CLI：
```bash
codex mcp add mem0-memory -- python3 /path/to/mem0-mcp.py codex-cli
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

2. 重启 Hermes：
```bash
hermes gateway restart
```

### OpenClaw

1. 创建 skill 文件 `~/.openclaw/skills/mem0-memory/SKILL.md`

2. 或者直接使用 API：
```bash
# 添加记忆
curl -X POST http://localhost:8000/memories \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"内容"}],"agent_id":"openclaw"}'

# 搜索记忆
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"关键词","agent_id":"openclaw"}'
```

### OpenCode

1. 添加到 `~/.config/opencode/opencode.json`：
```json
{
  "mcp": {
    "mem0-memory": {
      "command": ["python3", "/path/to/mem0-mcp.py", "opencode"],
      "enabled": true,
      "type": "local"
    }
  }
}
```

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

| Agent ID | 工具 |
|----------|------|
| `claude-code` | Claude Code |
| `codex-cli` | Codex |
| `hermes-agent` | Hermes |
| `openclaw` | OpenClaw |
| `opencode` | OpenCode |
| `cli` | CLI 工具 |

## 跨域搜索

不传 `agent_id` 会搜索所有 agent 的记忆：
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"搜索关键词","top_k":10}'
```

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

### 项目结构
```
mem0/
├── Dockerfile          # Docker 镜像定义
├── docker-compose.yml  # Docker Compose 配置
├── .env                # 环境变量配置
├── server.py           # API 服务器
├── config/
│   ├── mem0-cli        # CLI 工具
│   └── mem0-mcp.py     # MCP Server
└── README.md           # 本文档
```

## 常见问题

### 1. 服务无法启动
```bash
# 检查日志
docker compose logs mem0

# 检查 PostgreSQL 是否运行
docker compose ps postgres

# 重启服务
docker compose restart
```

### 2. 记忆搜索无结果
- 检查是否添加了记忆
- 降低 `threshold` 值
- 使用更简单的关键词

### 3. 跨域搜索不工作
- 确保不传 `agent_id` 参数
- 检查各 agent 是否正确配置

### 4. PostgreSQL 连接失败
- 检查 `.env` 中的数据库配置
- 确保 PostgreSQL 容器运行中
- 检查端口是否被占用

## 许可证

Apache License 2.0

## 致谢

- [mem0ai/mem0](https://github.com/mem0ai/mem0) - 核心记忆系统
- [pgvector](https://github.com/pgvector/pgvector) - PostgreSQL 向量扩展

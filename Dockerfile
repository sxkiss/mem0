FROM python:3.11-slim

WORKDIR /app

# 华为云镜像加速 + 系统依赖（含 git 用于克隆源码）
RUN sed -i 's@deb.debian.org@repo.huaweicloud.com@g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    git \
    libpq-dev \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 拉取 mem0 源码（构建时自动获取，不依赖本地上下文）
ARG MEM0_REPO=https://github.com/mem0ai/mem0.git
ARG MEM0_REF=main
RUN git clone --depth 1 --branch ${MEM0_REF} ${MEM0_REPO} .

# 安装服务端依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r server/requirements.txt

# 持久化目录
RUN mkdir -p /app/history /app/logs && chmod 777 /app/history /app/logs

EXPOSE 8000

CMD ["sh", "-c", "cd /app/server && uvicorn main:app --host 0.0.0.0 --port 8000"]

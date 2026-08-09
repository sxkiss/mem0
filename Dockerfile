FROM python:3.11-slim

WORKDIR /app

RUN sed -i 's@deb.debian.org@repo.huaweicloud.com@g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl git libpq-dev gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ARG MEM0_REPO=https://github.com/mem0ai/mem0.git
ARG MEM0_REF=main
RUN git clone --depth 1 --branch ${MEM0_REF} ${MEM0_REPO} .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r server/requirements.txt

RUN mkdir -p /app/history /app/logs && chmod 777 /app/history /app/logs

EXPOSE 8000

CMD ["sh", "-c", "cd /app/server && uvicorn main:app --host 0.0.0.0 --port 8000"]

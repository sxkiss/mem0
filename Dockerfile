FROM python:3.11-slim

WORKDIR /app

RUN sed -i 's@deb.debian.org@repo.huaweicloud.com@g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl libpq-dev gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir fastapi uvicorn sqlalchemy psycopg pydantic

COPY server.py .

RUN mkdir -p /app/history /app/logs && chmod 777 /app/history /app/logs

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]

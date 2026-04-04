FROM python:3.12-slim AS base
WORKDIR /app
COPY pyproject.toml .
COPY app/ app/
RUN pip install --no-cache-dir .

FROM base AS production
RUN mkdir -p /data
EXPOSE 8001
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}

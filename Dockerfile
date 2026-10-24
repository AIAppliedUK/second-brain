FROM node:22-slim AS web

WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
ENV SECOND_BRAIN_FRONTEND_DIST_DIR=/app/apps/web/dist

WORKDIR /app

# Bake the models into the image so containers never download at runtime. This sits
# before the source COPY so code changes reuse the cached layer instead of re-downloading.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ARG RERANKER_MODEL=Xenova/ms-marco-MiniLM-L-12-v2
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "fastembed>=0.5,<1.0" \
    && python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}')" \
    && python -c "from fastembed.rerank.cross_encoder import TextCrossEncoder; TextCrossEncoder('${RERANKER_MODEL}')"

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY libs ./libs

RUN pip install --no-cache-dir ".[embeddings]"

COPY --from=web /web/dist ./apps/web/dist

EXPOSE 8000 8090

CMD ["python", "-m", "second_brain_mcp_server.cli"]

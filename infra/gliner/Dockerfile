FROM python:3.12-slim

WORKDIR /app

# System dependencies for PyTorch
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY validate_batch.py .

# Pre-download the model into the image layer (avoids runtime download)
# Override GLINER_MODEL_PATH at runtime to use a different model.
ARG GLINER_MODEL_PATH=urchade/gliner_large-v2.1
ENV GLINER_MODEL_PATH=${GLINER_MODEL_PATH}

# CI fix: actually pre-download the model into the image layer. The previous
# version only declared the ARG but never ran the download — so the first
# request at runtime had to fetch ~1.5 GB from HuggingFace, which on
# resource-constrained CI runners can OOM-kill uvicorn (exit code 3) or hit
# rate limits. Pre-fetching to the image (as root, before USER switch) puts
# the weights into ``/root/.cache/huggingface`` baked into the layer.
# We then copy them into appuser's cache so the runtime load is a no-op fetch.
RUN python -c "from gliner import GLiNER; GLiNER.from_pretrained('${GLINER_MODEL_PATH}')"

# Correctness gate: build FAILS if server-side batching (batch_predict_entities)
# does not produce entities identical to the per-text predict_entities path.
# This is the micro-batching cutover safety check — runs against the baked model.
RUN python validate_batch.py

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"

# Security: run as non-root (F-009)
# Pre-create the HuggingFace cache directory with correct ownership so the named
# volume inherits appuser ownership on first mount (Docker copies image dir into
# a new empty volume, preserving permissions).
RUN useradd --create-home --uid 1001 appuser && \
    mkdir -p /home/appuser/.cache/huggingface && \
    cp -r /root/.cache/huggingface/* /home/appuser/.cache/huggingface/ 2>/dev/null || true && \
    chown -R appuser:appuser /home/appuser/.cache
USER appuser

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
